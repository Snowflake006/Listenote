import json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Listenote'/'app'))
os.environ['QT_QPA_PLATFORM']='offscreen'
os.environ['LISTENOTE_DISABLE_UPDATE_CHECK']='1'
os.environ['LISTENOTE_DATA']=str(ROOT/'.test-data'/'folder-tests')
from PySide6.QtWidgets import QApplication,QDialog,QMessageBox,QMenu
from PySide6.QtCore import Qt,QMimeData,QPointF
from PySide6.QtTest import QTest
from classroom_store import ClassroomStore
from classroom_ui import MIME
import main

class FolderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'.test-data');self.root=Path(self.temp.name)
        self.patch=patch.object(main,'DATA',self.root);self.patch.start()
        self.w=main.Window();self.w.subjects=[dict(id='math',name='高等数学'),dict(id='physics',name='大学物理')];self.w.store_subjects();self.w.show();self.app.processEvents()
    def tearDown(self):
        if self.w.rec:self.w.finish_record()
        self.w.close();self.patch.stop();self.temp.cleanup()
    def test_drag_moves_complete_bundle_and_keeps_external_original(self):
        source=self.root/'external.wav';source.write_bytes(b'audio-original')
        w=self.w;w.new(source);w.current.update(transcript='原文',summary='摘录',ai_summary='总结',notes='笔记',ai_metadata={'model':'test'})
        w.change_tab(0);w.save();old=self.root/w.current['_bundle'];(old/'附件.txt').write_text('附件','utf8')
        mime=QMimeData();mime.setData(MIME,str(self.root/(w.current['id']+'.json')).encode())
        event=MagicMock();event.mimeData.return_value=mime
        event.position.return_value=QPointF(w.folders.visualItemRect(w.folders.item(1)).center())
        w.folders.dropEvent(event);event.accept.assert_called_once()
        folder=self.root/w.current['_bundle']
        self.assertIn('高等数学',str(folder));self.assertFalse(old.exists())
        self.assertEqual(source.read_bytes(),b'audio-original')
        self.assertEqual(Path(w.current['audio']).read_bytes(),b'audio-original')
        for filename in ['转写原文.txt','课堂摘录.txt','AI总结.md','我的笔记.txt','附件.txt','课堂笔记.json']:self.assertTrue((folder/filename).exists(),filename)
        saved=json.loads((folder/'课堂笔记.json').read_text('utf8'));self.assertEqual(saved['ai_metadata']['model'],'test')
        w.subjects[0]['name']='数学课程';w.store_subjects()
        self.assertIn('数学课程',w.current['_bundle']);self.assertTrue(Path(w.current['audio']).exists())

    def test_delete_current_classroom_keeps_original_and_does_not_reappear(self):
        w=self.w;source=self.root/'original.wav';source.write_bytes(b'original')
        w.new(source);w.editor.setPlainText('尚未自动保存的笔记')
        key=w.current['id'];index=self.root/(key+'.json');bundle=self.root/w.current['_bundle']
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes):w.delete_classroom(index)
        self.assertIsNone(w.current);self.assertFalse(w.timer.isActive())
        self.assertFalse(index.exists());self.assertFalse(bundle.exists())
        self.assertEqual(source.read_bytes(),b'original')
        self.assertEqual(w.history.count(),0);self.assertEqual(w.course_list.count(),0)
        archived=next((self.root/'已删除课堂').iterdir())
        saved=json.loads((archived/'课堂索引.json').read_text('utf8'))
        self.assertEqual(saved['transcript'],'尚未自动保存的笔记')
        self.assertEqual((archived/'课堂资料'/'original.wav').read_bytes(),b'original')
        w.save();w.sync_classroom_folders();w.refresh()
        self.assertEqual(w.course_list.count(),0)
        reopened=main.Window()
        try:self.assertEqual(reopened.history.count(),0)
        finally:reopened.close()

    def test_delete_cancel_and_other_classroom_leave_current_content_intact(self):
        w=self.w;w.new('删除候选.wav');key=w.current['id'];index=self.root/(key+'.json')
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Cancel):w.delete_classroom(index)
        self.assertTrue(index.exists());self.assertEqual(w.current['id'],key)
        w.new('保留课堂.wav');kept=w.current['id'];w.editor.setPlainText('继续编辑的内容')
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes):w.delete_classroom(index)
        self.assertEqual(w.current['id'],kept)
        self.assertEqual(w.editor.toPlainText(),'继续编辑的内容')
        self.assertEqual(w.history.count(),1);self.assertEqual(w.course_list.count(),1)

    def test_both_context_menus_dispatch_delete_and_active_task_blocks_it(self):
        w=self.w;w.new('菜单课堂.wav');index=str(self.root/(w.current['id']+'.json'))
        class DeleteMenu(QMenu):
            def exec(self,*args):
                return next(a for a in self.actions() if a.text()=='删除课堂…')
        with patch('main.QMenu',DeleteMenu),patch.object(w,'delete_classroom') as delete:
            for view in (w.history,w.course_list):
                w.note_menu(view.visualItemRect(view.item(0)).center(),view)
            self.assertEqual(delete.call_count,2);delete.assert_called_with(index)
        w.job=object()
        try:
            with patch.object(QMessageBox,'question') as confirm:
                w.delete_classroom(index);confirm.assert_not_called()
            self.assertTrue(Path(index).exists())
        finally:w.job=None

    def test_delete_rejects_foreign_bundle_and_rolls_back_failed_index_move(self):
        w=self.w;w.new('路径检查.wav');index=self.root/(w.current['id']+'.json')
        note=json.loads(index.read_text('utf8'));bundle=self.root/note['_bundle']
        note['_bundle']='课堂资料'
        index.write_text(json.dumps(note),'utf8')
        with self.assertRaises(ValueError):ClassroomStore(self.root,w.subjects).delete(index)
        w.save()
        original_rename=Path.rename
        def fail_index(path,target):
            if path==index:raise OSError('模拟索引移动失败')
            return original_rename(path,target)
        with patch.object(Path,'rename',autospec=True,side_effect=fail_index):
            with self.assertRaises(OSError):ClassroomStore(self.root,w.subjects).delete(index)
        self.assertTrue(index.exists());self.assertTrue((bundle/'课堂笔记.json').exists())
    def test_subject_browser_reopens_saved_course_content_and_has_no_unclassified_option(self):
        w=self.w;w.active_subject='math';w.new(self.root/'数学第一讲.wav')
        w.current.update(transcript='已保存的原文',summary='已保存的摘录',ai_summary='已保存的总结正文',notes='独立笔记')
        w.change_tab(0);w.save();note_id=w.current['id']
        w.active_subject='physics';w.new(self.root/'物理第一讲.wav')
        w.choose_subject(w.folders.item(1))
        self.assertIs(w.pages.currentWidget(),w.course_browser)
        self.assertEqual(w.course_heading.text(),'高等数学');self.assertEqual(w.course_list.count(),1)
        self.assertIn('AI 总结',w.course_list.item(0).text())
        w.select(w.course_list.item(0))
        self.assertEqual(w.current['id'],note_id);self.assertEqual(w.editor.toPlainText(),'已保存的总结正文')
        for index,text in [(0,'已保存的原文'),(1,'已保存的摘录'),(3,'独立笔记')]:
            w.tabs.setCurrentIndex(index);self.assertEqual(w.editor.toPlainText(),text)
        w.show_course_list();self.assertIs(w.pages.currentWidget(),w.course_browser)
        self.assertFalse(any('未分类' in w.folders.item(i).text() for i in range(w.folders.count())))
        self.assertFalse(any('未分类' in w.subject_picker.itemText(i) for i in range(w.subject_picker.count())))
        w.choose_subject(w.folders.item(0));self.assertEqual(w.course_list.count(),2)

    def test_folder_and_course_clicks_restore_notes_and_survive_restart(self):
        w=self.w;w.active_subject='math';w.new(self.root/'仅有笔记.wav')
        w.tabs.setCurrentIndex(3);w.editor.setPlainText('之前记录的课堂笔记');w.save()
        note_id=w.current['id']
        w.active_subject='physics';w.new(self.root/'另一节课.wav')
        # Use real widget events: opening folders must stay inside the app.
        with patch('main.os.startfile') as explorer:
            QTest.mouseClick(w.folders.viewport(),Qt.LeftButton,pos=w.folders.visualItemRect(w.folders.item(1)).center())
            self.app.processEvents()
            self.assertIs(w.pages.currentWidget(),w.course_browser)
            QTest.keyClick(w.folders,Qt.Key_Return);self.app.processEvents()
            explorer.assert_not_called()
        QTest.mouseClick(w.course_list.viewport(),Qt.LeftButton,pos=w.course_list.visualItemRect(w.course_list.item(0)).center())
        self.app.processEvents()
        self.assertEqual(w.current['id'],note_id)
        self.assertEqual(w.tabs.currentIndex(),3)
        self.assertEqual(w.editor.toPlainText(),'之前记录的课堂笔记')
        w.editor.setPlainText('继续编辑并保留');w.show_course_list()
        reopened=main.Window()
        try:
            self.assertIs(reopened.pages.currentWidget(),reopened.course_browser)
            item=next(reopened.course_list.item(i) for i in range(reopened.course_list.count()) if '仅有笔记' in reopened.course_list.item(i).text())
            reopened.select(item)
            self.assertEqual(reopened.editor.toPlainText(),'继续编辑并保留')
        finally:reopened.close()

    def test_recording_requires_confirmation_and_persists_name_history(self):
        w=self.w
        with patch('main.RecordingDialog') as dialog,patch('sounddevice.RawInputStream') as stream:
            dialog.return_value.exec.return_value=QDialog.Rejected
            w.record();stream.assert_not_called()
            dialog.return_value.exec.return_value=QDialog.Accepted
            dialog.return_value.name.currentText.return_value='第三讲'
            dialog.return_value.subject.currentData.return_value='physics'
            w.record();stream.assert_called_once();self.assertEqual(w.current['title'],'第三讲')
            self.assertIn('大学物理',w.current['_bundle']);self.assertTrue(Path(w.current['audio']).exists())
            w.finish_record()
        history=json.loads((self.root/'settings'/'recording_history.json').read_text('utf8'))
        self.assertEqual(history[0]['name'],'第三讲');self.assertEqual(history[0]['subject'],'physics')
        reopened=main.Window();self.assertEqual(reopened.recording_history[0]['name'],'第三讲');reopened.close()
    def test_explorer_actions_use_real_subject_and_classroom_paths(self):
        self.w.new(self.root/'missing.wav')
        with patch('main.os.startfile') as opened:self.w.open_notebook_folder();self.assertEqual(opened.call_args.args[0],str(self.root/'课堂资料'))
        with patch('main.subprocess.Popen') as explorer:
            self.w.reveal_classroom(self.w.history.item(0))
            self.assertEqual(explorer.call_args.args[0][1],'/select,')
            self.assertTrue(Path(explorer.call_args.args[0][-1]).exists())

if __name__=='__main__':unittest.main(verbosity=2)
