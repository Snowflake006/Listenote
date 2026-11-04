import os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Listenote'/'app'))
os.environ['QT_QPA_PLATFORM']='offscreen'
os.environ['LISTENOTE_DISABLE_UPDATE_CHECK']='1'
os.environ['LISTENOTE_DATA']=str(ROOT/'.test-data'/'export-selection')
from PySide6.QtWidgets import QApplication,QFileDialog,QMessageBox
from main import Window,export,STYLE
from PySide6.QtGui import QTextDocument

class RecordingDocument(QTextDocument):
    last_text=''
    def setPlainText(self,text):
        RecordingDocument.last_text=text
        super().setPlainText(text)

class ExportSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(STYLE)

    def test_selected_content_is_isolated_in_every_document_format(self):
        data=dict(title='测试课堂',date='2026-11-04',summary='摘录独有内容',ai_summary='模型独有内容',transcript='原文独有内容',notes='笔记独有内容',segments=[])
        with tempfile.TemporaryDirectory(dir=ROOT/'.test-data') as folder:
            for selection,expected,excluded in [('summary','摘录独有内容','模型独有内容'),('ai_summary','模型独有内容','摘录独有内容')]:
                for ext in ['.txt','.md','.docx','.pdf']:
                    target=Path(folder)/(selection+ext)
                    with patch('main.QTextDocument',RecordingDocument):export(data,target,selection)
                    self.assertGreater(target.stat().st_size,0)
                    if ext=='.docx':
                        from docx import Document
                        text='\n'.join(p.text for p in Document(target).paragraphs)
                    elif ext=='.pdf':
                        text=RecordingDocument.last_text
                    else:text=target.read_text('utf8')
                    self.assertIn(expected,text)
                    for forbidden in [excluded,'原文独有内容','笔记独有内容']:self.assertNotIn(forbidden,text)

    def test_dropdown_actions_export_selected_content_and_empty_content_does_not_prompt_save(self):
        w=Window();w.new('导出分类测试.wav')
        w.current.update(summary='摘录独有内容',ai_summary='模型独有内容')
        with tempfile.TemporaryDirectory(dir=ROOT/'.test-data') as folder:
            for index,expected,excluded in [(0,'摘录独有内容','模型独有内容'),(1,'模型独有内容','摘录独有内容')]:
                target=Path(folder)/(str(index)+'.txt')
                with patch.object(w,'error',side_effect=AssertionError),patch.object(QFileDialog,'getSaveFileName',return_value=(str(target),'纯文本 (*.txt)')) as save:
                    w.export_menu.actions()[index].trigger()
                    self.assertNotIn('字幕 SRT',save.call_args.args[3])
                text=target.read_text('utf8');self.assertIn(expected,text);self.assertNotIn(excluded,text)
            w.current['ai_summary']=''
            with patch.object(QMessageBox,'information') as info,patch.object(QFileDialog,'getSaveFileName') as save:
                w.export_menu.actions()[1].trigger();info.assert_called_once();save.assert_not_called()
        w.close()

if __name__=='__main__':unittest.main(verbosity=2)
