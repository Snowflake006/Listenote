import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, Mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Listenote' / 'app'))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['LISTENOTE_DATA'] = str(ROOT / '.test-data' / 'setup-tests')
import resources as res
from ai_summary import Cancelled, DEFAULT_CONFIG, DEEPSEEK_URL


class DownloadHandler(BaseHTTPRequestHandler):
    payload = b'model-file-for-resume-tests' * 30000
    ranges = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        offset = int(self.headers.get('Range', 'bytes=0-').split('=')[1].split('-')[0])
        self.ranges.append(offset)
        data = self.payload[offset:]
        self.send_response(206 if offset else 200)
        if offset:
            self.send_header('Content-Range', f'bytes {offset}-{len(self.payload)-1}/{len(self.payload)}')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        assert payload['model'] == 'qwen3:0.6b'
        self.send_response(200)
        self.send_header('Content-Type', 'application/x-ndjson')
        self.end_headers()
        for item in [{'status': 'pulling', 'completed': 100, 'total': 200},
                     {'status': 'pulling', 'completed': 200, 'total': 200},
                     {'status': 'success'}]:
            self.wfile.write(json.dumps(item).encode() + b'\n')


class SetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), DownloadHandler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}/model.bin'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_atomic_download_resume_and_hash(self):
        payload = DownloadHandler.payload
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'model.bin'
            part = target.with_suffix('.bin.part')
            part.write_bytes(payload[:250000])
            res.download_file(self.url, target, lambda *args: None, lambda: False, digest, len(payload))
            self.assertEqual(target.read_bytes(), payload)
            self.assertIn(250000, DownloadHandler.ranges)
            self.assertFalse(part.exists())

    def test_cancel_preserves_partial_and_bad_hash_never_installs(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'model.bin'
            state = {'cancel': False}
            def progress(*args):
                state['cancel'] = True
            with self.assertRaises(Cancelled):
                res.download_file(self.url, target, progress, lambda: state['cancel'])
            self.assertFalse(target.exists())
            self.assertGreater(target.with_suffix('.bin.part').stat().st_size, 0)
            with self.assertRaisesRegex(RuntimeError, '校验失败'):
                res.download_file(self.url, target, lambda *args: None, lambda: False, '0'*64, len(DownloadHandler.payload))
            self.assertFalse(target.exists())

    def test_one_click_checks_signature_before_installer_and_pulls_model(self):
        with tempfile.TemporaryDirectory() as folder:
            installer = Path(folder) / 'downloads' / 'OllamaSetup.exe'
            def fake_download(url, target, *args):
                self.assertEqual(url, res.OLLAMA_INSTALLER)
                target.parent.mkdir(parents=True)
                target.write_bytes(b'test-installer')
            state = {'verified': False}
            def verify(path):
                self.assertEqual(path, installer)
                state['verified'] = True
            process = Mock(returncode=0)
            process.poll.return_value = 0
            def launch(args, **kwargs):
                self.assertTrue(state['verified'])
                self.assertIn('/VERYSILENT', args)
                return process
            with patch.object(res, 'ollama_available', side_effect=[False, True, True]), \
                 patch.object(res, 'find_ollama', side_effect=[None, Path('ollama.exe')]), \
                 patch.object(res, 'download_file', side_effect=fake_download), \
                 patch.object(res, 'verify_installer', side_effect=verify), \
                 patch.object(res.subprocess, 'Popen', side_effect=launch), \
                 patch.object(res, 'pull_model') as pull:
                res.prepare_ollama(folder, 'qwen3:0.6b', lambda *args: None, lambda: False)
                self.assertEqual(pull.call_args.args[0], 'qwen3:0.6b')

    def test_unsigned_installer_is_never_executed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'downloads' / 'OllamaSetup.exe'
            path.parent.mkdir()
            path.write_bytes(b'bad')
            with patch.object(res, 'ollama_available', return_value=False), \
                 patch.object(res, 'find_ollama', return_value=None), \
                 patch.object(res, 'verify_installer', side_effect=RuntimeError('签名未通过')), \
                 patch.object(res.subprocess, 'Popen') as launch:
                with self.assertRaisesRegex(RuntimeError, '签名'):
                    res.prepare_ollama(folder, 'qwen3:0.6b', lambda *args: None, lambda: False)
                launch.assert_not_called()
                self.assertFalse(path.exists())

    def test_model_pull_stream_reports_progress(self):
        progress = []
        with patch.object(res, 'OLLAMA_URL', self.url.rsplit('/', 1)[0]):
            res.pull_model('qwen3:0.6b', lambda n, text: progress.append(n), lambda: False)
        self.assertIn(50, progress)
        self.assertIn(100, progress)

    def test_simple_settings_domestic_preset_and_one_click_worker(self):
        from PySide6.QtWidgets import QApplication, QDialog
        from ai_ui import AISettingsDialog
        app = QApplication.instance() or QApplication([])
        dialog = AISettingsDialog(dict(DEFAULT_CONFIG), data=ROOT / '.test-data')
        self.assertEqual(dialog.selected_model(), 'qwen3-0.6b')
        self.assertTrue(dialog.url.isHidden())
        self.assertTrue(dialog.key.isHidden())
        with patch('local_engine.prepare_qwen') as prepare:
            dialog.install_model()
            deadline = time.monotonic() + 5
            while dialog.worker and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.01)
            self.assertIsNone(dialog.worker)
            prepare.assert_called_once()
            self.assertIn('已准备好', dialog.state.text())
        dialog.provider.setCurrentIndex(dialog.provider.findData('deepseek'))
        self.assertEqual(dialog.config()['url'], DEEPSEEK_URL)
        self.assertEqual(dialog.config()['model'], 'deepseek-flash')
        self.assertTrue(dialog.url.isHidden())
        self.assertFalse(dialog.key.isHidden())
        dialog.key.setText('test-key')
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.Accepted)


if __name__ == '__main__':
    unittest.main(verbosity=2)
