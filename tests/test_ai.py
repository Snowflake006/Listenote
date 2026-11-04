import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Listenote' / 'app'))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['LISTENOTE_DATA'] = str(ROOT / '.test-data' / 'notes')
import ai_summary as ai


class Handler(BaseHTTPRequestHandler):
    calls = []
    status = 200
    truncated = False

    def log_message(self, *args):
        pass

    def do_GET(self):
        data = {'models': [{'name': 'qwen3:4b'}, {'name': 'remote:cloud'}]} if self.path == '/api/tags' else {'data': [{'id': 'test-model'}]}
        self.reply(data)

    def reply(self, data):
        self.send_response(self.status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.calls.append((self.path, payload, self.headers.get('Authorization')))
        if self.path == '/api/chat':
            self.reply({'message': {'content': '课堂总结：测试知识点。'}, 'done_reason': 'length' if self.truncated else 'stop'})
        else:
            self.reply({'choices': [{'message': {'content': '课堂总结：测试知识点。'}, 'finish_reason': 'length' if self.truncated else 'stop'}]})


class AITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        Handler.calls = []
        Handler.status = 200
        Handler.truncated = False

    def config(self, provider='ollama'):
        return dict(ai.DEFAULT_CONFIG, provider=provider, url=self.url + ('/v1' if provider == 'api' else ''), model='qwen3:4b')

    def test_native_and_compatible_protocols(self):
        for provider in ['ollama', 'api', 'deepseek']:
            config = self.config(provider)
            self.assertTrue(ai.list_models(config))
            self.assertIn('课堂总结', ai.summarize(config, 'session-secret', '课堂原文'))
            path, body, authorization = Handler.calls[-1]
            self.assertEqual(path, '/api/chat' if provider == 'ollama' else '/v1/chat/completions' if provider == 'api' else '/chat/completions')
            self.assertEqual(authorization, 'Bearer session-secret')
            self.assertEqual(body['messages'][1]['content'], '课堂原文')
            if provider == 'deepseek':
                self.assertEqual(body['thinking'], {'type': 'disabled'})
        self.assertEqual(ai.list_models(self.config()), ['qwen3:4b'])

    def test_long_lecture_preserves_tail_and_reduces(self):
        text = ('长课堂知识点\n' * 1300) + '最后一段的重要作业'
        self.assertEqual(''.join(ai.split_text(text)), text)
        ai.summarize(self.config(), '', text)
        inputs = [call[1]['messages'][1]['content'] for call in Handler.calls[:-1]]
        self.assertEqual(''.join(inputs), text)
        self.assertGreater(len(Handler.calls), 2)

    def test_cancellation_makes_no_request(self):
        with self.assertRaises(ai.Cancelled):
            ai.summarize(self.config(), '', '原文', cancel=lambda: True)
        self.assertEqual(Handler.calls, [])

    def test_bad_credentials_and_truncation(self):
        Handler.status = 401
        with self.assertRaisesRegex(RuntimeError, '401'):
            ai.summarize(self.config('api'), 'secret', '原文')
        Handler.status = 200
        Handler.truncated = True
        with self.assertRaisesRegex(RuntimeError, '长度上限'):
            ai.summarize(self.config(), '', '原文')

    def test_validate_remote_and_cloud_models(self):
        with self.assertRaises(ValueError):
            ai.check_config(dict(self.config(), url='http://example.com'))
        with self.assertRaises(ValueError):
            ai.check_config(dict(self.config(), model='large:32b-cloud'))
        with self.assertRaises(ValueError):
            ai.base_url(dict(self.config(), url='https://user:secret@example.com'))

    def test_qt_summary_save_legacy_tabs_and_export(self):
        from PySide6.QtWidgets import QApplication
        from main import Window, export, STYLE, DATA
        from ai_ui import AISettingsDialog
        app = QApplication.instance() or QApplication([])
        app.setStyleSheet(STYLE)
        window = Window()
        window.new('测试课堂.wav')
        window.editor.setPlainText('[00:00:00] 这是测试课堂原文。')
        window.ai_config = self.config('api')
        window.ai_key = 'session-secret'
        window.summarize()
        deadline = time.monotonic() + 10
        while window.job and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.01)
        self.assertIsNone(window.job)
        self.assertEqual(window.tabs.currentIndex(), 2)
        self.assertIn('课堂总结', window.editor.toPlainText())
        self.assertTrue(window.ai_btn.isEnabled())
        old_summary = window.current['ai_summary']
        Handler.status = 401
        from PySide6.QtWidgets import QMessageBox
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes), patch.object(QMessageBox, 'warning'):
            window.summarize()
            deadline = time.monotonic() + 10
            while window.job and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.01)
        self.assertIsNone(window.job)
        self.assertEqual(window.current['ai_summary'], old_summary)
        Handler.status = 200
        saved = (DATA / (window.current['id'] + '.json')).read_text('utf8')
        self.assertNotIn('session-secret', saved)
        window.tabs.setCurrentIndex(3)
        window.editor.setPlainText('独立笔记')
        window.tabs.setCurrentIndex(1)
        self.assertEqual(window.editor.toPlainText(), '')
        with tempfile.TemporaryDirectory() as folder:
            for suffix in ['.txt', '.md', '.docx', '.pdf', '.srt']:
                path = Path(folder) / ('export' + suffix)
                export(window.current, path)
                self.assertTrue(path.exists())
                if suffix in ['.txt', '.md']:
                    self.assertIn('课堂总结', path.read_text('utf8'))
                    self.assertIn('独立笔记', path.read_text('utf8'))
                if suffix == '.docx':
                    from docx import Document
                    self.assertIn('课堂总结', '\n'.join(p.text for p in Document(str(path)).paragraphs))
            window.current['transcript'] += '修改'
            path = Path(folder) / 'stale.txt'
            export(window.current, path)
            self.assertIn('原文已修改', path.read_text('utf8'))
        # Legacy note files without any AI fields remain readable.
        window.current.pop('ai_summary')
        window.current.pop('ai_metadata')
        window.tabs.setCurrentIndex(2)
        window.change_tab(2)
        self.assertEqual(window.editor.toPlainText(), '')
        dialog = AISettingsDialog(self.config(), parent=window)
        dialog.show()
        app.processEvents()
        dialog.grab().save(str(ROOT / '.test-data' / 'ai-settings.png'))
        dialog.reject()
        window.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
