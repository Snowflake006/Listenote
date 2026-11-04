import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Listenote'/'app'))
os.environ['QT_QPA_PLATFORM']='offscreen'
os.environ['LISTENOTE_DISABLE_UPDATE_CHECK']='1'
os.environ['LISTENOTE_DATA']=str(ROOT/'.test-data'/'navigation')

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QInputDialog
import main
from main import Window, STYLE


class NavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion');cls.app.setStyleSheet(STYLE)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'.test-data')
        self.data_patch=patch.object(main,'DATA',Path(self.temp.name));self.data_patch.start()
        self.window=Window();self.window.resize(1180,780);self.window.show()

    def tearDown(self):
        if self.window.settings_page:
            for panel in self.window.settings_page.panels.values():
                if hasattr(panel,'worker'):panel.worker=None
        self.window.close();self.app.processEvents();self.data_patch.stop();self.temp.cleanup()

    def test_settings_save_cancel_and_repeated_navigation_stay_in_main_window(self):
        w=self.window;w.new('课堂.wav');w.editor.setPlainText('保留课堂编辑内容')
        for section in [0,1,2,0,2,1,0]:
            w.settings(section);self.app.processEvents()
            self.assertIsNone(self.app.activeModalWidget())
            panel=w.settings_page.panels[section]
            self.assertFalse(panel.isWindow())
            self.assertIs(panel.window(),w)
            w.return_to_classroom()
            self.assertEqual(w.pages.currentIndex(),0)
            self.assertEqual(w.editor.toPlainText(),'保留课堂编辑内容')
        w.settings(0);panel=w.settings_page.panels[0]
        panel.provider.setCurrentIndex(panel.provider.findData('api'))
        panel.url.setText('http://127.0.0.1:9999/v1');panel.model.setEditText('test-model')
        panel.key.setText('session-only-secret');panel.accept()
        self.assertEqual(w.ai_config['model'],'test-model')
        saved=(main.DATA/'settings'/'ai.json').read_text('utf8')
        self.assertNotIn('session-only-secret',saved)
        panel.model.setEditText('discard-this');panel.reject()
        w.settings(0)
        self.assertEqual(w.settings_page.panels[0].selected_model(),'test-model')
        self.assertIsNone(self.app.activeModalWidget())

    def test_subject_filter_assignment_and_restart_preserve_original_note(self):
        w=self.window;w.new('历史课堂.wav');w.editor.setPlainText('原笔记内容');w.save()
        old_id=w.current['id']
        for subject in ['高等数学','大学物理']:
            with patch.object(QInputDialog,'getText',return_value=(subject,True)):w.add_subject()
        math_id=w.subjects[0]['id'];physics_id=w.subjects[1]['id']
        # Clicking a folder while a note exists saves first and rebuilds its list.
        w.choose_subject(w.folders.item(1))
        self.assertEqual(w.active_subject,math_id)
        w.new('数学第一讲.wav');math_note=w.current['id']
        self.assertEqual(w.current['subject'],math_id)
        self.assertEqual(w.history.count(),1)
        w.subject_picker.setCurrentIndex(w.subject_picker.findData(physics_id))
        self.assertEqual(w.history.count(),0)
        w.choose_subject(w.folders.item(2));self.assertEqual(w.history.count(),1)
        w.select(w.history.item(0));self.assertEqual(w.current['id'],math_note)
        legacy=json.loads((main.DATA/(old_id+'.json')).read_text('utf8'))
        self.assertEqual(legacy['transcript'],'原笔记内容')
        # Older notes without a subject still belong in Unclassified.
        legacy.pop('subject',None)
        (main.DATA/(old_id+'.json')).write_text(json.dumps(legacy),'utf8')
        w.choose_subject(w.folders.item(0));self.assertEqual(w.history.count(),2)
        reopened=Window()
        self.assertEqual([s['name'] for s in reopened.subjects],['高等数学','大学物理'])
        self.assertEqual(reopened.history.count(),2);reopened.close()

    def test_settings_task_cannot_be_hidden_or_closed_until_finished(self):
        w=self.window;w.settings(0);page=w.settings_page;panel=page.panels[0]
        panel.worker=object()
        page.open_section(2)
        self.assertEqual(page.section_order[page.navigation.currentRow()],0)
        w.return_to_classroom();self.assertIs(w.pages.currentWidget(),page)
        self.assertFalse(w.close());self.assertTrue(w.isVisible())
        panel.worker=None;w.return_to_classroom();self.assertEqual(w.pages.currentIndex(),0)

    def test_scaled_native_window_hit_testing_keeps_content_clickable(self):
        if sys.platform!='win32':self.skipTest('Windows chrome')
        import ctypes
        from ctypes import wintypes
        w=self.window
        def bounds(hwnd,ptr):
            rect=ctypes.cast(ptr,ctypes.POINTER(wintypes.RECT)).contents
            rect.left,rect.top,rect.right,rect.bottom=200,100,1970,1270
            return 1
        def hit(x,y):
            msg=wintypes.MSG();msg.message=0x84;msg.lParam=(y<<16)|(x&0xffff)
            return w.nativeEvent(b'windows_generic_MSG',ctypes.addressof(msg))
        with patch.object(ctypes.windll.user32,'GetWindowRect',side_effect=bounds):
            self.assertEqual(hit(201,101),(True,13))
            self.assertEqual(hit(1969,1269),(True,17))
            self.assertFalse(hit(1500,950)[0])
        self.assertTrue(w.windowFlags() & Qt.FramelessWindowHint)


if __name__=='__main__':unittest.main(verbosity=2)
