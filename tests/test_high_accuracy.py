import os,sys,json,tempfile,hashlib,time
from pathlib import Path
import unittest
from unittest.mock import patch,Mock

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'Listenote/app'))
os.environ['QT_QPA_PLATFORM']='offscreen';os.environ['LISTENOTE_DISABLE_UPDATE_CHECK']='1'
os.environ['LISTENOTE_DATA']=str(ROOT/'.test-data/high-tests')
from PySide6.QtWidgets import QApplication
import resources as res
import main
from ai_summary import Cancelled

def install_fake(data,mode):
    folder=res.speech_folder(data,mode);folder.mkdir(parents=True,exist_ok=True)
    manifest={}
    for name in res.SPEECH_MODELS[mode]['files']:
        payload=(mode+name).encode();(folder/name).write_bytes(payload)
        manifest[name]={'size':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}
    (folder/'ready.json').write_text(json.dumps(manifest),'utf8')

class HighAccuracyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'.test-data');self.data=Path(self.temp.name)
        self.data_patch=patch.object(main,'DATA',self.data);self.data_patch.start()
    def tearDown(self):self.data_patch.stop();self.temp.cleanup()
    def drain(self,panel):
        deadline=time.monotonic()+5
        while panel.worker and time.monotonic()<deadline:
            self.app.processEvents();time.sleep(.01)
        self.assertIsNone(panel.worker)
    def test_download_uses_pinned_domestic_repo_and_verifies_each_high_file(self):
        install_fake(self.data,'lite')
        files=[{'Path':n,'Size':3,'Sha256':hashlib.sha256(b'abc').hexdigest(),'Revision':'test-revision'} for n in res.SPEECH_MODELS['high']['files']]
        response=Mock();response.json.return_value={'Data':{'Files':files}}
        def download(url,path,progress,cancel,digest,size):
            self.assertIn('mobiuslabsgmbh/faster-whisper-large-v3-turbo',url)
            self.assertIn('Revision=test-revision',url)
            self.assertEqual(digest,hashlib.sha256(b'abc').hexdigest());self.assertEqual(size,3)
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'abc')
        with patch.object(res.requests,'get',return_value=response) as get,patch.object(res,'download_file',side_effect=download) as transfer:
            res.prepare_speech(self.data,lambda *a:None,lambda:False,'high')
        self.assertEqual(transfer.call_count,5)
        self.assertEqual(get.call_args.kwargs['params']['Revision'],res.SPEECH_MODELS['high']['revision'])
        self.assertTrue(res.speech_ready(self.data,'high'));self.assertTrue(res.speech_ready(self.data,'lite'))
        self.assertNotEqual(res.speech_folder(self.data,'high'),res.speech_folder(self.data,'lite'))
        (res.speech_folder(self.data,'high')/'model.bin').write_bytes(b'broken-size')
        self.assertFalse(res.speech_ready(self.data,'high'))
    def test_missing_high_files_never_mark_configuration_ready(self):
        response=Mock();response.json.return_value={'Data':{'Files':[]}}
        with patch.object(res.requests,'get',return_value=response),patch.object(res,'download_file') as transfer:
            with self.assertRaisesRegex(RuntimeError,'完整模型'):res.prepare_speech(self.data,lambda *a:None,lambda:False,'high')
            transfer.assert_not_called()
        self.assertFalse(res.speech_ready(self.data,'high'))
    def test_download_ready_selects_high_engine_and_avoids_old_directory_picker(self):
        w=main.Window();w.show();w.new(str(self.data/'lesson.wav'))
        (self.data/'lesson.wav').write_bytes(b'placeholder')
        try:
            w.engine.setCurrentIndex(w.engine.findData('high'))
            with patch.object(main.QFileDialog,'getExistingDirectory') as old_picker:
                w.transcribe();old_picker.assert_not_called()
            panel=w.settings_page.panels[1];self.assertEqual(panel.selected_mode,'high')
            self.assertEqual(panel.high_start.text(),'配置高精度识别')
            with patch('resources_ui.prepare_speech',side_effect=lambda data,report,cancel,mode:install_fake(data,mode)):
                panel.high_start.click();self.drain(panel)
            self.assertEqual(w.engine.currentData(),'high')
            self.assertIn('本地模型',w.engine.currentText());self.assertIn('已准备好',panel.model_states['high'].text())
            w.return_to_classroom();self.assertIs(w.pages.currentWidget(),w.pages.widget(0))
        finally:w.close();self.app.processEvents()
    def test_cancel_high_download_does_not_confuse_existing_base_with_success(self):
        install_fake(self.data,'lite');w=main.Window();w.settings(1)
        try:
            panel=w.settings_page.panels[1]
            def cancel(data,report,should_cancel,mode):raise Cancelled()
            with patch('resources_ui.prepare_speech',side_effect=cancel):panel.begin('high');self.drain(panel)
            self.assertFalse(panel.completed);self.assertFalse(res.speech_ready(self.data,'high'))
            self.assertIn('已暂停',panel.status.text());self.assertTrue(panel.high_start.isEnabled())
            self.assertNotEqual(w.engine.currentData(),'high')
        finally:w.close();self.app.processEvents()
    def test_high_worker_uses_local_large_model_with_existing_runtime(self):
        worker=main.Worker('lesson.wav','chinese','high');segments=[];finished=[]
        worker.segment.connect(segments.append);worker.finished_job.connect(finished.append)
        model=Mock();model.transcribe.return_value=(iter([Mock(start=0,end=2,text='課堂內容')]),Mock(duration=2))
        with patch('faster_whisper.WhisperModel',return_value=model) as loader,patch.object(worker,'run_legacy_external') as legacy:
            worker.run();legacy.assert_not_called()
        self.assertEqual(loader.call_args.args[0],str(res.speech_folder(self.data,'high')))
        self.assertTrue(loader.call_args.kwargs['local_files_only']);self.assertEqual(loader.call_args.kwargs['compute_type'],'int8')
        self.assertEqual(model.transcribe.call_args.kwargs['beam_size'],5)
        self.assertEqual(segments[0]['text'],'课堂内容');self.assertIn('高精度',finished[0])

if __name__=='__main__':unittest.main(verbosity=2)
