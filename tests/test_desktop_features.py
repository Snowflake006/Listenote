import os,sys,tempfile,json,wave,subprocess
from pathlib import Path
from unittest.mock import patch
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'Listenote'/'app'))
os.environ['QT_QPA_PLATFORM']='offscreen';os.environ['LISTENOTE_DISABLE_UPDATE_CHECK']='1'
os.environ['LISTENOTE_DATA']=str(ROOT/'.test-data'/'desktop-tests')
from PySide6.QtWidgets import QApplication,QDialog
from PySide6.QtNetwork import QLocalServer
from PySide6.QtTest import QTest
import main
from desktop_integration import forward_action,server_name

class DesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'.test-data');self.data=Path(self.temp.name)
        self.patch=patch.object(main,'DATA',self.data);self.patch.start()
        self.w=main.Window();self.w.show();self.app.processEvents()
    def tearDown(self):
        if self.w.rec:self.w.finish_record()
        self.w.close();self.app.processEvents();self.patch.stop();self.temp.cleanup()
    def test_theme_picker_persists_and_switches_all_surfaces(self):
        w=self.w;w.settings(3);panel=w.settings_page.panels[3]
        from ui_components import AppleComboBox
        picker=panel.findChild(AppleComboBox)
        self.assertEqual([picker.itemText(i) for i in range(3)],['亮','暗','跟随系统'])
        picker.setCurrentIndex(picker.findData('dark'));self.app.processEvents()
        self.assertTrue(self.app.property('darkTheme'))
        self.assertIn('#e7edfa',self.app.styleSheet())
        saved=json.loads((self.data/'settings'/'appearance.json').read_text());self.assertEqual(saved['theme'],'dark')
        reopened=main.Window()
        try:self.assertEqual(reopened.appearance.mode,'dark')
        finally:reopened.close()
        picker.setCurrentIndex(picker.findData('light'));self.assertFalse(self.app.property('darkTheme'))
        picker.setCurrentIndex(picker.findData('system'));self.assertEqual(w.appearance.mode,'system')
    def test_taskbar_actions_operate_real_recording_lifecycle(self):
        w=self.w
        with patch('main.RecordingDialog') as dialog,patch('sounddevice.RawInputStream') as stream:
            dialog.return_value.exec.return_value=QDialog.Accepted
            dialog.return_value.name.currentText.return_value='任务栏录音'
            dialog.return_value.subject.currentData.return_value=''
            w.desktop.dispatch('record');self.assertIsNotNone(w.rec)
            path=Path(w.current['audio']);callback=stream.call_args.kwargs['callback']
            callback(bytes(640),320,None,None);self.assertEqual(w.frames,320)
            w.desktop.dispatch('pause');self.assertTrue(w.rec_paused)
            callback(bytes(640),320,None,None);self.assertEqual(w.frames,320)
            w.desktop.dispatch('pause');self.assertTrue(w.rec_paused)
            w.pause_record();self.assertFalse(w.rec_paused)
            callback(bytes(640),320,None,None)
            w.desktop.dispatch('stop');self.assertIsNone(w.rec)
            with wave.open(str(path),'rb') as audio:self.assertEqual(audio.getnframes(),640)
            self.assertTrue((self.data/(w.current['id']+'.json')).exists())
    def test_follow_system_updates_without_overwriting_preference(self):
        appearance=self.w.appearance
        with patch('winreg.QueryValueEx',return_value=(0,4)):
            appearance.set_mode('system');self.assertTrue(appearance.dark)
        with patch('winreg.QueryValueEx',return_value=(1,4)):
            appearance.refresh();self.assertFalse(appearance.dark)
        self.assertEqual(appearance.mode,'system')
        self.assertEqual(json.loads(appearance.path.read_text())['theme'],'system')
    def test_idle_pause_stop_do_not_record_or_modify_notes(self):
        with patch.object(self.w,'pause_record') as pause,patch.object(self.w,'finish_record') as stop:
            self.w.desktop.dispatch('pause');self.w.desktop.dispatch('stop')
            pause.assert_not_called();stop.assert_not_called()
    def test_ipc_routes_to_existing_window_without_new_recording_process(self):
        desktop=self.w.desktop;desktop.server=QLocalServer(desktop)
        self.assertTrue(desktop.server.listen(server_name(self.data)))
        desktop.server.newConnection.connect(desktop.receive)
        with patch.object(desktop,'dispatch') as dispatch:
            code="import sys;sys.path.insert(0,sys.argv[1]);from PySide6.QtWidgets import QApplication;app=QApplication([]);from desktop_integration import forward_action;sys.exit(0 if forward_action(sys.argv[2],'pause') else 1)"
            sender=subprocess.Popen([sys.executable,'-c',code,str(ROOT/'Listenote'/'app'),str(self.data)])
            for _ in range(200):
                QTest.qWait(20)
                if sender.poll() is not None:break
            self.assertEqual(sender.wait(3),0)
            dispatch.assert_called_once_with('pause')
        desktop.server.close()
    def test_outer_inset_and_pin_button(self):
        margins=self.w.outer_layout.contentsMargins()
        self.assertTrue(all(6<=n<=14 for n in [margins.left(),margins.top(),margins.right(),margins.bottom()]))
        with patch.object(self.w,'set_pinned') as unused:
            self.assertFalse(self.w.title_bar.pin_button.isChecked())
        self.assertFalse(self.w.title_bar.pin_button.icon().isNull())

if __name__=='__main__':unittest.main(verbosity=2)
