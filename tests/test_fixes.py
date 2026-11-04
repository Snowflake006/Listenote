import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Listenote' / 'app'))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['LISTENOTE_DATA'] = str(ROOT / '.test-data' / 'fixes')
os.environ['LISTENOTE_DISABLE_UPDATE_CHECK']='1'

from ai_summary import DEFAULT_CONFIG, LEGACY_PROMPT, DEFAULT_PROMPT, has_substance, summarize, normalize_prompt
from text_utils import to_simplified
from updates import parse_release


class FixTests(unittest.TestCase):
    def test_original_startup_uses_complete_runtime(self):
        result = subprocess.run([str(ROOT/'Listenote/runtime/python.exe'),
                                 str(ROOT/'Listenote/app/startup.py'), '--runtime-info'],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        info = json.loads(result.stdout)
        self.assertTrue(info['faster_whisper'])
        self.assertIn('.preview', info['executable'])

    def test_simplified_preserves_english_timestamps_and_emoji(self):
        self.assertEqual(to_simplified('[00:00:25] 課堂轉寫，學習與考試。AI 😀'),
                         '[00:00:25] 课堂转写，学习与考试。AI 😀')

    def test_high_accuracy_option_survives_light_runtime(self):
        from PySide6.QtWidgets import QApplication
        from main import Window
        app=QApplication.instance() or QApplication([])
        window=Window()
        self.assertGreaterEqual(window.engine.findData('legacy'),0)
        self.assertIn('高精度识别',window.engine.itemText(window.engine.findData('legacy')))
        window.close()

    def test_heading_only_summary_is_retried_not_saved(self):
        headings = '一、课程主题与知识框架\n二、重要概念与解释\n三、老师明确提到的考试重点\n四、作业与待办\n五、需要核对的疑点'
        self.assertFalse(has_substance(headings))
        response = {'choices':[{'message':{'content':headings},'finish_reason':'stop'}]}
        config = dict(DEFAULT_CONFIG,provider='api',model='test',url='http://localhost')
        with patch('ai_summary.request_json', return_value=response) as request:
            with self.assertRaisesRegex(RuntimeError, '只返回了标题'):
                summarize(config, '', '监督学习使用带标签的数据训练。')
            self.assertEqual(request.call_count, 2)
        self.assertEqual(normalize_prompt(LEGACY_PROMPT), DEFAULT_PROMPT)

    def test_update_versions_and_source(self):
        newer = parse_release({'tag_name':'v99.0.0','body':'新增功能'})
        self.assertTrue(newer['newer'])
        self.assertEqual(newer['url'],'https://github.com/Snowflake006/Listenote/releases/tag/v99.0.0')
        self.assertFalse(parse_release({'tag_name':'v1.1.0'})['newer'])
        with self.assertRaises(ValueError):
            parse_release({'tag_name':'v1.4.0','draft':True})

    def test_notes_show_live_simplified_text_and_keep_user_edits(self):
        from PySide6.QtWidgets import QApplication, QMessageBox
        from main import Window
        app = QApplication.instance() or QApplication([])
        window = Window()
        window.new('sample.wav')
        window.tabs.setCurrentIndex(3)
        window.editor.setPlainText('我自己的笔记')
        cursor = window.editor.textCursor()
        cursor.setPosition(3)
        window.editor.setTextCursor(cursor)
        window.add_segment({'start':0,'end':25,'text':'課堂的重點是學習方法。'})
        window.add_segment({'start':25,'end':50,'text':'老師要求完成課後作業。'})
        self.assertIn('课堂的重点是学习方法',window.live_preview.toPlainText())
        self.assertIn('[00:00:25]',window.live_preview.toPlainText())
        self.assertEqual(window.editor.toPlainText(),'我自己的笔记')
        self.assertEqual(window.editor.textCursor().position(),3)
        self.assertEqual(window.current['notes'],'我自己的笔记')
        self.assertFalse(window.live_pane.isHidden())
        old = window.current['transcript']
        with patch('main.transcription_available',return_value=False), patch.object(QMessageBox,'warning'):
            window.transcribe()
        self.assertEqual(window.current['transcript'],old)
        # Future-release notification opens only once automatically and stays in app.
        with patch('main.QDesktopServices.openUrl') as open_url:
            window.update_checked(parse_release({'tag_name':'v9.0.0'}))
            self.assertIsNotNone(window.update_dialog)
            self.assertIn('v9.0.0',window.update_message)
            window.update_dialog.reject()
            open_url.assert_not_called()
        window.close()
        app.processEvents()


if __name__=='__main__':
    unittest.main(verbosity=2)
