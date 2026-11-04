import os, sys, json, time, uuid, re, subprocess, tempfile, wave, threading, hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from runtime_support import bootstrap, transcription_available, find_legacy_root, legacy_root_available
if __name__=='__main__':bootstrap(__file__)
os.environ['HF_HUB_OFFLINE']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl, QEvent, QPoint
from PySide6.QtGui import QFont, QColor, QPainter, QLinearGradient, QPen, QTextDocument, QFontDatabase, QIcon, QDesktopServices
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import *
from ai_summary import DEFAULT_CONFIG, is_local, check_config, has_substance
from ai_ui import SummaryWorker
from resources import speech_ready, speech_folder
from local_engine import close_engine, model_ready
from text_utils import to_simplified, simplify_note
from settings_ui import SettingsPage
from ui_components import AppleComboBox as QComboBox, GlassMenu as QMenu, TitleBar, line_icon
from window_chrome import (apply_window_corners, enable_snap_layout,
                           maximize_client_rect, constrain_maximized_bounds)
from updates import UpdateWorker, VERSION_LABEL, CHECK_INTERVAL
from classroom_store import ClassroomStore, write_json, safe_name
from classroom_ui import ClassroomList, SubjectList, RecordingDialog
from motion import AnimatedStack, WindowMotion, install_motion, capture, reveal
from ui_theme import GlassBackdrop
ROOT=Path(__file__).resolve().parent.parent
if '--data-dir' in sys.argv:
    i=sys.argv.index('--data-dir')
    if i+1<len(sys.argv):os.environ['LISTENOTE_DATA']=sys.argv[i+1]
DATA=Path(os.environ.get('LISTENOTE_DATA', str(Path(os.environ.get('LOCALAPPDATA',str(ROOT)))/'Listenote')))
DATA.mkdir(parents=True,exist_ok=True)
TAB_KEYS = ['transcript', 'summary', 'ai_summary', 'notes']
def stamp(t):
    t=int(t); return f'{t//3600:02}:{t//60%60:02}:{t%60:02}'
def run(args):
    p=subprocess.run([str(x) for x in args],capture_output=True,creationflags=0x08000000)
    if p.returncode: raise RuntimeError(p.stderr.decode('utf8','replace')[-1200:])
    return p.stdout
def extract(segments):
    if not segments: return ''
    out=['课堂重点摘录','以下按时间抽取原文，未经大语言模型概括；请结合录音核对。','']
    n=max(1,len(segments)//10)
    selected=set(range(0,len(segments),n))
    for i,s in enumerate(segments):
        if any(w in s['text'] for w in ['重点','考试','注意','定义','所谓','总结','作业']): selected.add(i)
    for i in sorted(selected)[:35]:
        s=segments[i]; out.append(f"[{stamp(s['start'])}] {s['text']}")
    return '\n\n'.join(out)
class Worker(QThread):
    progress=Signal(int,str); segment=Signal(dict); finished_job=Signal(str); failed=Signal(str)
    def __init__(self,path,language,engine='legacy',legacy_root=None):
        super().__init__(); self.path=path; self.language=language; self.engine=engine; self.cancel=False;self.legacy_root=legacy_root
    def run(self):
        try:
            if self.engine == 'lite':
                self.run_lite();return
            root=self.legacy_root or find_legacy_root(ROOT)
            if not root:raise RuntimeError('未找到原版高精度识别文件，请选择原版软件目录。')
            if not transcription_available('legacy') or Path(root).resolve()!=ROOT.resolve():
                self.run_legacy_external(root);return
            self.progress.emit(0,'正在加载本地模型，首次启动请稍候…')
            import torch, numpy as np
            from transformers import AutoProcessor,AutoModelForSpeechSeq2Seq
            torch.set_num_threads(max(1,min(8,(os.cpu_count() or 4)//2)))
            model_dir=ROOT/'models'/'whisper'
            if not (model_dir/'model.safetensors').exists(): raise RuntimeError('模型不完整。请解压整个软件包，不要单独移动 EXE。')
            proc=AutoProcessor.from_pretrained(str(model_dir),local_files_only=True)
            model=AutoModelForSpeechSeq2Seq.from_pretrained(str(model_dir),local_files_only=True,torch_dtype=torch.float32)
            model.generation_config.forced_decoder_ids=None
            model.eval()
            audio_temp=DATA/'temp';audio_temp.mkdir(parents=True,exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='listenote_',dir=audio_temp) as td:
                target=Path(td)/'audio.wav'
                self.progress.emit(0,'正在准备音频…')
                run([ROOT/'tools'/'ffmpeg.exe','-v','error','-y','-i',self.path,'-vn','-ac','1','-ar','16000',target])
                with wave.open(str(target),'rb') as audio:
                    total=audio.getnframes(); position=0
                    while position<total:
                        if self.cancel: self.finished_job.emit('已停止，完成的文字已保存'); return
                        raw=audio.readframes(25*16000)
                        samples=np.frombuffer(raw,dtype=np.int16).astype(np.float32)/32768
                        inputs=proc(samples,sampling_rate=16000,return_tensors='pt',return_attention_mask=True)
                        kw={'task':'transcribe','max_new_tokens':440}
                        if self.language!='auto': kw['language']=self.language
                        with torch.inference_mode(): ids=model.generate(inputs.input_features,attention_mask=inputs.attention_mask,**kw)
                        text=to_simplified(proc.batch_decode(ids,skip_special_tokens=True)[0].strip())
                        self.segment.emit({'start':position/16000,'end':(position+len(samples))/16000,'text':text})
                        position+=len(samples)
                        self.progress.emit(int(position/total*100),f'已处理 {stamp(position/16000)} / {stamp(total/16000)}')
            self.finished_job.emit('转写完成 · 课堂摘录已生成')
        except Exception as e: self.failed.emit(str(e))
    def run_legacy_external(self,root):
        self.progress.emit(0,'正在启动原版高精度识别环境…')
        temp_dir=DATA/'temp';temp_dir.mkdir(parents=True,exist_ok=True)
        env=dict(os.environ,PYTHONIOENCODING='utf-8',TMP=str(temp_dir),TEMP=str(temp_dir))
        helper=Path(__file__).with_name('legacy_transcribe.py')
        with tempfile.TemporaryDirectory(prefix='legacy_',dir=temp_dir) as ipc_dir,tempfile.TemporaryFile(dir=temp_dir) as errors:
            cancel_marker=Path(ipc_dir)/'cancel'
            process=subprocess.Popen([str(Path(root)/'runtime'/'python.exe'),'-u',str(helper),
                                      str(root),str(Path(self.path).resolve()),self.language,str(cancel_marker)],
                stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=errors,text=True,
                encoding='utf-8',errors='replace',env=env,creationflags=0x08000000)
            finished=False;reported_error=False;stop_watch=threading.Event()
            def watch_cancel():
                while not stop_watch.wait(.1):
                    if self.cancel:
                        try:cancel_marker.write_text('cancel',encoding='ascii')
                        except (OSError,ValueError):pass
                        return
            watcher=threading.Thread(target=watch_cancel,daemon=True);watcher.start()
            try:
                for line in process.stdout:
                    try:message=json.loads(line)
                    except ValueError:continue
                    kind=message.get('type');value=message.get('value')
                    if kind=='segment':self.segment.emit(value)
                    elif kind=='progress':self.progress.emit(*value)
                    elif kind=='done':finished=True;self.finished_job.emit(value)
                    elif kind=='error':reported_error=True;self.failed.emit(value)
                process.wait()
                if not finished and not reported_error:
                    self.failed.emit('原版高精度识别未正常完成，请确认原版运行环境和模型完整。')
            finally:
                stop_watch.set();watcher.join(timeout=.3)
                process.stdout.close()
                if process.poll() is None:process.terminate();process.wait(timeout=5)
    def run_lite(self):
        from faster_whisper import WhisperModel
        self.progress.emit(0,'正在加载轻量语音模型…')
        model=WhisperModel(str(speech_folder(DATA)),device='cpu',compute_type='int8',
                           cpu_threads=max(1,min(8,(os.cpu_count() or 4)//2)),local_files_only=True)
        language={'chinese':'zh','english':'en','auto':None}[self.language]
        segments,info=model.transcribe(self.path,language=language,beam_size=3,vad_filter=True)
        for segment in segments:
            if self.cancel:self.finished_job.emit('已停止，完成的文字已保存');return
            self.segment.emit({'start':segment.start,'end':segment.end,'text':to_simplified(segment.text.strip())})
            self.progress.emit(min(100,int(segment.end/max(info.duration,.01)*100)),
                               f'已处理 {stamp(segment.end)} / {stamp(info.duration)}')
        self.finished_job.emit('转写完成 · 轻量语音识别')
class WaveArt(QWidget):
    def __init__(self): super().__init__(); self.setMinimumHeight(95)
    def paintEvent(self,event):
        import math
        p=QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        for i in range(90):
            x=self.width()*i/90; h=8+50*abs(math.sin(i*.29))*math.exp(-((i-45)/33)**2)
            p.setPen(QPen(QColor('#9db5e9' if i<48 else '#dce5f6'),3.5,Qt.SolidLine,Qt.RoundCap)); p.drawLine(int(x),int((self.height()-h)/2),int(x),int((self.height()+h)/2))
def button(text,slot,primary=False):
    b=QPushButton(text); b.setCursor(Qt.PointingHandCursor); b.clicked.connect(slot)
    if primary:b.setObjectName('primary')
    return b
class Window(QMainWindow):
    update_status=Signal(str)
    def __init__(self):
        super().__init__(); QFontDatabase.addApplicationFont(str(ROOT/'app'/'fonts'/'NotoSansSC.ttf')); self.setWindowIcon(QIcon(str(ROOT/'app'/'icon.ico'))); self.job=None; self.current=None; self.rec=None; self.frames=0; self.rec_paused=False
        install_motion()
        self.motion=WindowMotion(self)
        self.ai_config=dict(DEFAULT_CONFIG);self.ai_key=''
        try:
            saved=json.loads((DATA/'settings'/'ai.json').read_text('utf8'))
            self.ai_config.update({k:saved[k] for k in DEFAULT_CONFIG if k in saved and isinstance(saved[k],str)})
        except (OSError,ValueError,TypeError):pass
        self.update_job=None;self.update_message='运行期间自动检测更新，也可以手动检查。';self.update_dialog=None
        self.legacy_root=find_legacy_root(ROOT)
        try:
            saved_root=Path(json.loads((DATA/'settings'/'speech.json').read_text('utf8'))['legacy_root'])
            if legacy_root_available(saved_root):self.legacy_root=saved_root
        except (OSError,ValueError,KeyError,TypeError):pass
        self.recording_history=[]
        try:self.recording_history=json.loads((DATA/'settings'/'recording_history.json').read_text('utf8'))
        except (OSError,ValueError):pass
        self.recording_history=[h for h in self.recording_history if isinstance(h,dict) and isinstance(h.get('name'),str)] if isinstance(self.recording_history,list) else []
        self.notified_version=''
        self.setWindowTitle('听课 Listenote · 本地课堂笔记')
        self.setWindowFlag(Qt.FramelessWindowHint)
        self.setAcceptDrops(True)
        self.subjects=[];self.active_subject=None
        try:
            subjects=json.loads((DATA/'settings'/'subjects.json').read_text('utf8'))
            self.subjects=[s for s in subjects if isinstance(s,dict) and isinstance(s.get('id'),str) and isinstance(s.get('name'),str)]
        except (OSError,ValueError,TypeError):pass
        screen=QApplication.primaryScreen().availableGeometry()
        self.setMinimumSize(min(500,screen.width()),min(360,screen.height()))
        self.resize(min(1180,int(screen.width()*.88)),min(820,int(screen.height()*.88)))
        self.move(screen.center()-self.rect().center())
        if '--local-preview' in sys.argv:self.setWindowTitle('听课 Listenote · 本地修复预览')
        if '--high-accuracy-preview' in sys.argv:self.setWindowTitle('听课 Listenote · 双模式识别预览')
        outer=GlassBackdrop();self.setCentralWidget(outer); layout=QHBoxLayout(outer);self.outer_layout=layout;layout.setContentsMargins(10,8,10,10);layout.setSpacing(0)
        side=QFrame();self.sidebar=side;self.compact_sidebar=False;side.setObjectName('sidebar');side.setFixedWidth(216); sl=QVBoxLayout(side);sl.setContentsMargins(18,24,18,20);sl.setSpacing(12)
        brand=QLabel('◉  听课');brand.setObjectName('brand');sl.addWidget(brand);sl.addWidget(QLabel('L I S T E N O T E'))
        sl.addSpacing(18);sl.addWidget(button('＋  导入课堂录音',self.import_file,True));sl.addWidget(button('●  开始录音',self.record))
        sl.addSpacing(4)
        folder_header=QHBoxLayout();folder_header.addWidget(QLabel('学科文件夹'));folder_header.addStretch()
        add_subject=button('＋',self.add_subject);add_subject.setObjectName('addSubject');add_subject.setToolTip('添加学科文件夹');add_subject.setFixedWidth(32);folder_header.addWidget(add_subject);sl.addLayout(folder_header)
        self.folders=SubjectList();self.folders.classroomDropped.connect(self.move_classroom);self.folders.setObjectName('folders');self.folders.setMaximumHeight(165)
        self.folders.itemClicked.connect(self.choose_subject)
        self.folders.itemActivated.connect(self.choose_subject)
        self.folders.setToolTip('点击查看学科课程；拖入课堂即可归类；右键可打开资料目录')
        self.folders.setContextMenuPolicy(Qt.CustomContextMenu);self.folders.customContextMenuRequested.connect(self.subject_menu)
        sl.addWidget(self.folders)
        sl.addWidget(QLabel('录音与笔记'));self.search=QLineEdit();self.search.setPlaceholderText('搜索课堂…');self.search.textChanged.connect(self.refresh);sl.addWidget(self.search)
        self.history=ClassroomList();self.history.setToolTip('拖到学科文件夹归类；双击在文件资源管理器中展开');self.history.itemDoubleClicked.connect(self.reveal_classroom);self.history.itemClicked.connect(self.select)
        self.history.setContextMenuPolicy(Qt.CustomContextMenu);self.history.customContextMenuRequested.connect(self.note_menu)
        sl.addWidget(self.history,1)
        self.settings_btn=button('设置',self.settings);sl.addWidget(self.settings_btn)
        sl.addWidget(button('打开笔记文件夹',self.open_notebook_folder));sl.addWidget(QLabel('● 转写离线 · AI 可选'))
        self.sidebar_container=QScrollArea();self.sidebar_container.setObjectName('sidebarScroll')
        self.sidebar_container.setFrameShape(QFrame.NoFrame);self.sidebar_container.setWidgetResizable(True)
        self.sidebar_container.setFixedWidth(216);side.setMinimumHeight(620)
        side.setMinimumWidth(0);side.setMaximumWidth(16777215)
        self.sidebar_container.setWidget(side);layout.addWidget(self.sidebar_container)
        right=QWidget();right_layout=QVBoxLayout(right);right_layout.setContentsMargins(0,0,0,0);right_layout.setSpacing(0)
        self.title_bar=TitleBar(self);right_layout.addWidget(self.title_bar)
        self.pages=AnimatedStack();right_layout.addWidget(self.pages,1);layout.addWidget(right,1)
        main=QWidget();self.classroom=main;main.setMinimumHeight(720);ml=QVBoxLayout(main);ml.setContentsMargins(26,8,26,18);ml.setSpacing(10);self.classroom_scroll=QScrollArea();self.classroom_scroll.setWidgetResizable(True);self.classroom_scroll.setFrameShape(QFrame.NoFrame);self.classroom_scroll.setWidget(main);self.pages.addWidget(self.classroom_scroll)
        self.settings_page=None
        top=QHBoxLayout();tag=QLabel('你的课堂，值得被好好记住。');tag.setObjectName('muted');tag.setWordWrap(True);top.addWidget(button('‹  课程列表',self.show_course_list));top.addWidget(tag);top.addStretch();badge=QLabel('  本地课堂笔记  ');badge.setObjectName('badge');top.addWidget(badge);ml.addLayout(top)
        self.title=QLineEdit('新的一课，从这里开始');self.title.setObjectName('title');self.title.editingFinished.connect(self.save)
        title_row=QHBoxLayout();self.title_row=title_row;title_row.addWidget(self.title,1)
        self.subject_picker=QComboBox();self.subject_picker.setToolTip('将当前课堂归入学科');self.subject_picker.setFixedWidth(145)
        self.subject_picker.currentIndexChanged.connect(self.assign_subject);title_row.addWidget(self.subject_picker);ml.addLayout(title_row)
        self.subtitle=QLabel('拖入录音，留住知识。支持 MP3 / M4A / WAV / MP4 等格式。');self.subtitle.setObjectName('muted');self.subtitle.setWordWrap(True);ml.addWidget(self.subtitle)
        hero=QFrame();hero.setObjectName('hero');hl=QVBoxLayout(hero);hl.setContentsMargins(20,4,20,14)
        self.wave=WaveArt();hl.addWidget(self.wave)
        row=QHBoxLayout();self.recognizer_row=row;self.source=QLabel('还没有选择录音');self.source.setWordWrap(True);hl.addWidget(self.source)
        self.lang=QComboBox();self.lang.addItems(['中文','English','自动识别']);row.addWidget(self.lang);row.addStretch()
        self.engine=QComboBox()
        if transcription_available('lite'):self.engine.addItem('轻量识别 · 国内下载','lite')
        self.engine.addItem('高精度识别 · 原版模型' if self.legacy_root else '高精度识别 · 选择原版目录','legacy')
        if '--high-accuracy-preview' in sys.argv:self.engine.setCurrentIndex(self.engine.findData('legacy'))
        if self.engine.count()==0:self.engine.addItem('需要完整轻量运行环境','lite')
        row.addWidget(self.engine)
        self.start=button('开始转写  →',self.transcribe,True);row.addWidget(self.start);hl.addLayout(row)
        self.bar=QProgressBar();self.bar.setTextVisible(False);self.bar.setFixedHeight(5);hl.addWidget(self.bar)
        self.status=QLabel('音频和文字保存在你的电脑上');self.status.setObjectName('muted');self.status.setWordWrap(True);hl.addWidget(self.status)
        controls=QHBoxLayout();self.record_controls=controls;self.stop=button('停止任务',self.cancel);self.stop.hide();controls.addWidget(self.stop)
        self.pause=button('暂停录音',self.pause_record);self.pause.hide();controls.addWidget(self.pause)
        self.mark=button('标记重点',self.mark_record);self.mark.hide();controls.addWidget(self.mark)
        controls.addStretch();controls.addWidget(button('打开原始录音',self.open_audio));hl.addLayout(controls);ml.addWidget(hero)
        airow=QHBoxLayout();self.ai_label=QLabel();self.ai_label.setObjectName('muted');self.ai_label.setWordWrap(True);airow.addWidget(self.ai_label,1)
        self.ai_btn=button('生成 AI 总结',self.summarize,True);airow.addWidget(self.ai_btn);ml.addLayout(airow);self.update_ai_label()
        tools=QHBoxLayout();self.editor_tools=tools;self.tabs=QTabBar();self.tabs.addTab('转写原文');self.tabs.addTab('课堂摘录');self.tabs.addTab('AI 总结');self.tabs.addTab('我的笔记');self.tabs.setUsesScrollButtons(True);self.tabs.setExpanding(False);self.tabs.currentChanged.connect(self.change_tab);tools.addWidget(self.tabs);tools.addStretch()
        self.export_btn=QPushButton('导出资料');self.export_btn.setObjectName('exportButton');self.export_btn.setCursor(Qt.PointingHandCursor)
        self.export_menu=QMenu(self.export_btn)
        for label,selection in [('导出课堂摘录','summary'),('导出 AI 总结','ai_summary'),('导出全部资料','all')]:
            action=self.export_menu.addAction(label)
            action.triggered.connect(lambda checked=False,selection=selection:self.export(selection))
        self.export_btn.setMenu(self.export_menu);tools.addWidget(self.export_btn);ml.addLayout(tools)
        self.splitter=QSplitter(Qt.Vertical)
        self.live_pane=QWidget();live_layout=QVBoxLayout(self.live_pane);live_layout.setContentsMargins(0,0,0,0)
        live_layout.addWidget(QLabel('转写实时预览 · 下方可独立记录你的笔记'))
        self.live_preview=QPlainTextEdit();self.live_preview.setReadOnly(True);self.live_preview.setPlaceholderText('识别出的简体中文会逐段出现在这里…');live_layout.addWidget(self.live_preview)
        self.splitter.addWidget(self.live_pane);self.live_pane.hide()
        self.editor=QPlainTextEdit();self.editor.setPlaceholderText('文字会在转写过程中逐段出现。\n\n你可以直接修改识别结果，所有修改会自动保存。');self.editor.textChanged.connect(self.schedule_save);self.splitter.addWidget(self.editor);ml.addWidget(self.splitter,1)
        foot=QHBoxLayout();self.footer=foot;self.count=QLabel('0 字');self.count.setObjectName('muted');foot.addWidget(self.count);foot.addStretch();self.saved=QLabel('自动保存 · 本地笔记');self.saved.setObjectName('muted');foot.addWidget(self.saved);ml.addLayout(foot)
        self.course_browser=QWidget();browser_layout=QVBoxLayout(self.course_browser)
        browser_layout.setContentsMargins(26,20,26,24);browser_layout.setSpacing(16)
        browser_header=QHBoxLayout();self.course_heading=QLabel('全部课堂');self.course_heading.setObjectName('settingsHeading')
        browser_header.addWidget(self.course_heading,1)
        browser_header.addWidget(button('＋ 导入录音',self.import_file,True));browser_layout.addLayout(browser_header)
        self.course_info=QLabel();self.course_info.setObjectName('muted');self.course_info.setWordWrap(True);browser_layout.addWidget(self.course_info)
        self.course_search=QLineEdit();self.course_search.setPlaceholderText('搜索本学科的课程…')
        self.course_search.textChanged.connect(self.search.setText);self.search.textChanged.connect(self.course_search.setText);browser_layout.addWidget(self.course_search)
        self.course_list=ClassroomList();self.course_list.setObjectName('courseList');self.course_list.itemClicked.connect(self.select)
        self.course_list.itemActivated.connect(self.select)
        self.course_list.setWordWrap(True)
        self.course_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.course_list.customContextMenuRequested.connect(lambda pos:self.note_menu(pos,self.course_list))
        self.course_list.setToolTip('点击打开已保存的课堂内容；右键可在资源管理器中定位')
        browser_layout.addWidget(self.course_list,1)
        self.course_empty=QLabel('这个学科还没有课堂，点击上方“导入录音”，或从左侧开始录音。')
        self.course_empty.setWordWrap(True);self.course_empty.setObjectName('muted');browser_layout.addWidget(self.course_empty)
        self.pages.addWidget(self.course_browser)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self.save)
        self.clock=QTimer(self);self.clock.timeout.connect(self.tick_record)
        self.sync_classroom_folders()
        self.refresh()
        if self.course_list.count():self.pages.setCurrentWidget(self.course_browser)
        self.update_timer=QTimer(self);self.update_timer.timeout.connect(self.check_updates)
        from appearance import Appearance
        self.appearance=Appearance(self,DATA)
        from desktop_integration import DesktopIntegration
        self.desktop=DesktopIntegration(self,DATA)
        if '--no-update-check' not in sys.argv and not os.environ.get('LISTENOTE_DISABLE_UPDATE_CHECK'):
            self.update_timer.start(CHECK_INTERVAL*1000);QTimer.singleShot(2500,self.check_updates)
    def set_pinned(self,enabled):
        if sys.platform=='win32':
            import ctypes
            from ctypes import wintypes
            ctypes.windll.user32.SetWindowPos(wintypes.HWND(int(self.winId())),wintypes.HWND(-1 if enabled else -2),0,0,0,0,0x0013)
        else:
            self.setWindowFlag(Qt.WindowStaysOnTopHint,enabled);self.show()
        self.title_bar.pin_button.setToolTip('取消窗口置顶' if enabled else '保持窗口在最前')
    def settings(self,section=0):
        self.save()
        if self.settings_page is None:
            self.settings_page=SettingsPage(self,DATA)
            self.pages.addWidget(self.settings_page)
        self.pages.setCurrentWidget(self.settings_page)
        self.settings_page.set_compact(self.width()<760)
        self.settings_page.open_section(section)
        if self.compact_sidebar:self.motion.drawer(False)
    def return_to_classroom(self):
        if self.settings_page and self.settings_page.busy():
            self.settings_page.message.setText('模型任务正在进行，请先停止或等待完成。');return
        self.pages.setCurrentIndex(0)
    def showEvent(self,event):
        super().showEvent(event)
        enable_snap_layout(self)
        apply_window_corners(self)
        self.adapt_layout()
        self.motion.show()
    def changeEvent(self,event):
        super().changeEvent(event)
        if event.type()==QEvent.WindowStateChange:
            apply_window_corners(self)
    def toggle_sidebar(self):
        if self.compact_sidebar:
            self.motion.drawer(not self.motion.drawer_open)
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'footer'):self.adapt_layout()
    def adapt_layout(self):
        compact=self.width()<980
        if compact!=self.compact_sidebar:
            self.compact_sidebar=compact
            if compact:
                self.outer_layout.removeWidget(self.sidebar_container)
                self.sidebar_container.setParent(self.centralWidget());self.sidebar_container.hide()
            else:
                self.outer_layout.insertWidget(0,self.sidebar_container);self.sidebar_container.show()
        self.title_bar.menu_button.setVisible(compact)
        if compact:
            self.sidebar_container.setGeometry(0,46,216,self.centralWidget().height()-46)
            self.sidebar_container.raise_()
        narrow=self.width()<760
        direction=QBoxLayout.TopToBottom if narrow else QBoxLayout.LeftToRight
        for row in (self.title_row,self.recognizer_row,self.record_controls,self.editor_tools,self.footer):
            row.setDirection(direction)
        self.classroom.layout().setContentsMargins(16 if narrow else 26,8,16 if narrow else 26,18)
        self.wave.setVisible(not narrow)
        self.classroom.setMinimumHeight(740 if narrow else 700)
        if self.settings_page:self.settings_page.set_compact(narrow)
    def nativeEvent(self,event_type,message):
        if sys.platform=='win32':
            import ctypes
            from ctypes import wintypes
            msg=wintypes.MSG.from_address(int(message))
            if msg.message==0x0024:  # WM_GETMINMAXINFO: includes drag-to-top Snap.
                constrain_maximized_bounds(int(msg.hWnd),msg.lParam)
                # Qt's normal minimum tracking constraints still apply.
                class MinMaxInfo(ctypes.Structure):
                    _fields_=[(name,wintypes.POINT) for name in ('reserved','max_size','max_position','min_track','max_track')]
                bounds=MinMaxInfo.from_address(msg.lParam)
                bounds.min_track.x=round(self.minimumWidth()*self.devicePixelRatioF())
                bounds.min_track.y=round(self.minimumHeight()*self.devicePixelRatioF())
                return True,0
            if msg.message==0x0083 and msg.wParam:  # WM_NCCALCSIZE
                maximize_client_rect(int(msg.hWnd),msg.lParam)
                return True,0
            if msg.message==0x0084:  # WM_NCHITTEST, physical screen coordinates
                bounds=wintypes.RECT()
                ctypes.windll.user32.GetWindowRect(wintypes.HWND(msg.hWnd),ctypes.byref(bounds))
                x=ctypes.c_short(msg.lParam & 0xffff).value-bounds.left
                y=ctypes.c_short((msg.lParam >> 16) & 0xffff).value-bounds.top
                scale=self.devicePixelRatioF();edge=round(6*scale)
                if not self.isMaximized():
                    left,right=x<edge,x>=bounds.right-bounds.left-edge
                    top,bottom=y<edge,y>=bounds.bottom-bounds.top-edge
                    hit=13 if top and left else 14 if top and right else 16 if bottom and left else 17 if bottom and right else 10 if left else 11 if right else 12 if top else 15 if bottom else 0
                    if hit:return True,hit
                if hasattr(self,'title_bar'):
                    control=self.title_bar.maximize_button;pos=control.mapTo(self,QPoint(0,0))
                    if pos.x()*scale<=x<(pos.x()+control.width())*scale and pos.y()*scale<=y<(pos.y()+control.height())*scale:
                        return True,9  # HTMAXBUTTON lets Windows show its Snap flyout.
            if hasattr(self,'title_bar'):
                bar=self.title_bar
                if msg.message==0x00A0:  # WM_NCMOUSEMOVE: let Windows handle hover.
                    bar.set_native_hover(msg.wParam==9)
                    # Qt consumes nonclient mouse moves for frameless windows.
                    # Forward to DefWindowProc so Windows can arm Snap Layouts.
                    if msg.wParam==9:
                        default=ctypes.windll.user32.DefWindowProcW
                        default.argtypes=[wintypes.HWND,wintypes.UINT,ctypes.c_size_t,ctypes.c_ssize_t]
                        default.restype=ctypes.c_ssize_t
                        return True,default(msg.hWnd,msg.message,msg.wParam,msg.lParam)
                elif msg.message==0x02A2:  # WM_NCMOUSELEAVE
                    bar.set_native_hover(False);bar.maximize_button.setDown(False);self._native_max_pressed=False
                elif msg.message==0x00A1 and msg.wParam==9:
                    bar.maximize_button.setDown(True);self._native_max_pressed=True
                    return True,0
                elif msg.message==0x00A2 and msg.wParam==9:
                    pressed=getattr(self,'_native_max_pressed',False);self._native_max_pressed=False
                    bar.maximize_button.setDown(False)
                    if pressed:bar.maximize_button.click()
                    return True,0
                elif msg.message==0x00A3 and msg.wParam==9:
                    return True,0
        return False,0
    def about(self,parent=None):
        self.settings(2)
    def check_updates(self,manual=False):
        if self.update_job:return
        self.update_message='正在连接 GitHub 检测更新…';self.update_status.emit(self.update_message)
        self.update_job=UpdateWorker(self,DATA/'settings'/'update_cache.json',manual)
        self.update_job.checked.connect(lambda release:self.update_checked(release,manual))
        self.update_job.failed.connect(self.update_failed)
        self.update_job.finished.connect(self.release_update_job);self.update_job.start()
    def update_failed(self,text):
        self.update_message=text;self.update_status.emit(text)
        self.update_timer.setInterval(300000)
    def release_update_job(self):
        self.update_job.deleteLater();self.update_job=None
    def update_checked(self,release,manual=False):
        self.update_timer.setInterval(300000 if release.get('stale') else CHECK_INTERVAL*1000)
        self.update_message=('发现新版本 '+release['tag'] if release['newer'] else '当前版本 '+VERSION_LABEL+'；GitHub 正式版 '+release['tag'])
        if release.get('stale'):self.update_message+=' · 网络暂不可用，显示上次检查结果'
        elif release.get('cached'):self.update_message+=' · 最近检查结果'
        self.update_status.emit(self.update_message)
        if release['newer'] and (manual or self.notified_version!=release['tag']):
            self.notified_version=release['tag']
            box=QMessageBox(QMessageBox.Information,'发现新版本',release['tag']+' 已发布。\n是否打开官方下载页面？',QMessageBox.Yes|QMessageBox.Cancel,self)
            box.setWindowModality(Qt.NonModal)
            box.button(QMessageBox.Yes).setText('查看新版');box.button(QMessageBox.Cancel).setText('稍后')
            box.finished.connect(lambda code:QDesktopServices.openUrl(QUrl(release['url'])) if code==QMessageBox.Yes else None)
            self.update_dialog=box;box.show()
    def speech_settings(self,parent=None):
        if self.job or self.rec:return False
        if speech_ready(DATA):return True
        self.settings(1)
        return False
    def update_ai_label(self):
        mode={'local':'本地千问 · 国内下载','ollama':'Ollama','deepseek':'国内 DeepSeek','api':'自定义 API'}.get(self.ai_config['provider'],'自定义 API')
        self.ai_label.setText('AI 总结 · '+mode+' · '+(self.ai_config.get('model') or '请在设置中选择模型'))
    def ai_settings(self,parent=None):
        if self.job or self.rec:return
        self.settings(0)
    def persist_ai_settings(self,dialog):
        config=dialog.config()
        try:
            folder=DATA/'settings';folder.mkdir(exist_ok=True)
            target=folder/'ai.json';tmp=target.with_suffix('.tmp')
            tmp.write_text(json.dumps(config,ensure_ascii=False,indent=2),'utf8');tmp.replace(target)
        except OSError as exc:
            dialog.state.setText('无法保存模型设置：'+str(exc));return
        self.ai_config=config;self.ai_key=dialog.key.text().strip();self.update_ai_label()
        dialog.state.setText('✓ 模型设置已保存，可以返回课堂使用。')
    def summarize(self):
        if self.job or self.rec:return
        if not self.current or not self.current.get('transcript','').strip():
            QMessageBox.information(self,'需要课堂原文','请先导入录音并转写，再生成 AI 总结。');return
        self.save()
        if self.ai_config['provider']=='local' and not model_ready(DATA,self.ai_config['model']):
            self.ai_settings();return
        if self.ai_config['provider']=='deepseek' and not self.ai_key:
            self.ai_settings();return
        try:check_config(self.ai_config)
        except ValueError:
            self.ai_settings();return
        if not is_local(self.ai_config):
            if QMessageBox.question(self,'发送原文到模型服务',
                '将把当前课堂转写原文发送到：\n'+self.ai_config['url']+'\n模型：'+self.ai_config['model']+
                '\n\n服务商可能收取费用。是否继续？',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return
        if self.current.get('ai_summary') and QMessageBox.question(self,'重新生成总结','成功后将替换现有 AI 总结，是否继续？',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return
        self.job=SummaryWorker(self.ai_config,self.ai_key,self.current['transcript'])
        self.job.progress.connect(self.progress);self.job.finished_job.connect(self.ai_done)
        self.job.failed.connect(self.error);self.job.cancelled.connect(lambda:self.status.setText('已取消 AI 总结，保留原有内容'))
        self.job.finished.connect(self.release_job);self.start.setEnabled(False);self.ai_btn.setEnabled(False)
        self.stop.show();self.bar.setRange(0,0);self.change_tab(self.tabs.currentIndex());self.status.setText('正在连接 AI 模型…');self.job.start()
    def ai_done(self,text):
        self.current['ai_summary']=text
        self.current['ai_metadata']={'model':self.ai_config['model'],'provider':self.ai_config['provider'],'generated_at':time.strftime('%Y-%m-%d %H:%M'),'source_sha256':hashlib.sha256(self.current['transcript'].encode('utf8')).hexdigest()}
        self.save();self.tabs.setCurrentIndex(2);self.change_tab(2);self.status.setText('AI 总结已保存 · 请结合原文核对')
    def store_subjects(self):
        self.save()
        folder=DATA/'settings';folder.mkdir(exist_ok=True)
        target=folder/'subjects.json';tmp=target.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.subjects,ensure_ascii=False,indent=2),'utf8');tmp.replace(target)
        self.sync_classroom_folders()
        self.refresh()
    def refresh_subjects(self):
        self.folders.clear()
        for name,key in [('全部课堂',None)]+[(s['name'],s['id']) for s in self.subjects]:
            item=QListWidgetItem(line_icon('all' if key is None else 'folder'),name)
            item.setData(Qt.UserRole,key);self.folders.addItem(item)
            if key==self.active_subject:self.folders.setCurrentItem(item)
        self.subject_picker.blockSignals(True);self.subject_picker.clear()
        self.subject_picker.setPlaceholderText('选择学科')
        for subject in self.subjects:self.subject_picker.addItem(subject['name'],subject['id'])
        self.subject_picker.setCurrentIndex(self.subject_picker.findData((self.current or {}).get('subject','')))
        self.subject_picker.setEnabled(bool(self.current) and not self.job and not self.rec)
        self.subject_picker.blockSignals(False)
    def add_subject(self):
        if self.job or self.rec:return
        name,ok=QInputDialog.getText(self,'添加学科','学科名称，例如：高等数学')
        if not ok or not name.strip():return
        name=name.strip()[:40]
        if any(s['name']==name for s in self.subjects):
            QMessageBox.information(self,'学科已存在','这个学科已经在左侧文件夹中。');return
        subject={'id':uuid.uuid4().hex,'name':name};self.subjects.append(subject)
        self.active_subject=subject['id'];self.store_subjects()
        self.choose_subject(self.folders.item(self.folders.count()-1))
    def choose_subject(self,item):
        if self.job or self.rec:return
        previous=capture(self.course_browser)
        key=item.data(Qt.UserRole);self.save();self.active_subject=key
        self.search.clear();self.refresh();self.pages.setCurrentWidget(self.course_browser)
        reveal(self.course_browser,previous)
        if self.compact_sidebar:self.motion.drawer(False)
    def show_course_list(self):
        if self.job or self.rec:return
        self.save();self.refresh();self.pages.setCurrentWidget(self.course_browser)
    def assign_subject(self):
        if self.current and not self.job and not self.rec:
            key=self.subject_picker.currentData()
            if key is None:return
            self.move_classroom(str(DATA/(self.current['id']+'.json')),key)
    def subject_menu(self,pos):
        item=self.folders.itemAt(pos)
        if not item or item.data(Qt.UserRole) is None:return
        key=item.data(Qt.UserRole)
        if not key:os.startfile(str(ClassroomStore(DATA,self.subjects).subject_path('')));return
        subject=next(s for s in self.subjects if s['id']==key)
        menu=QMenu(self);reveal=menu.addAction('在文件资源管理器中打开');rename=menu.addAction('重命名学科');remove=menu.addAction('移除文件夹（保留笔记）')
        action=menu.exec(self.folders.mapToGlobal(pos))
        if action==reveal:
            os.startfile(str(ClassroomStore(DATA,self.subjects).subject_path(key)))
        elif action==rename:
            name,ok=QInputDialog.getText(self,'重命名学科','学科名称',text=subject['name'])
            if ok and name.strip() and not any(s['id']!=key and s['name']==name.strip()[:40] for s in self.subjects):
                subject['name']=name.strip()[:40];self.store_subjects()
        elif action==remove:
            # Removing a grouping never removes a recording or note.
            if self.job or self.rec:return
            self.save()
            for path in DATA.glob('*.json'):
                try:
                    note=json.loads(path.read_text('utf8'))
                    if note.get('subject')==key:
                        note['subject']='';tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(note,ensure_ascii=False,indent=2),'utf8');tmp.replace(path)
                except (OSError,ValueError,TypeError):continue
            if self.current and self.current.get('subject')==key:self.current['subject']=''
            self.subjects=[s for s in self.subjects if s['id']!=key];self.active_subject=None;self.store_subjects()
    def sync_classroom_folders(self):
        store=ClassroomStore(DATA,self.subjects)
        for subject in self.subjects:store.subject_path(subject['id'])
        store.subject_path('')
        for path in DATA.glob('*.json'):
            try:
                note=json.loads(path.read_text('utf8'))
                if 'id' in note and 'title' in note:store.persist(note)
            except (OSError,ValueError,KeyError) as exc:
                self.status.setText('部分课堂资料整理未完成：'+str(exc))
        if self.current:
            updated=DATA/(self.current['id']+'.json')
            if updated.exists():self.current=json.loads(updated.read_text('utf8'))
    def move_classroom(self,path,key):
        if self.job or self.rec:return
        path=Path(path).resolve()
        if path.parent!=DATA.resolve() or path.suffix!='.json':return
        if key and not any(s['id']==key for s in self.subjects):return
        self.save()
        try:
            note=json.loads(path.read_text('utf8'));note['subject']=key
            ClassroomStore(DATA,self.subjects).persist(note)
            if self.current and self.current['id']==note['id']:self.current=note
            self.refresh();self.status.setText('课堂录音、原文、摘录、AI 总结和笔记已一起归档。')
        except (OSError,ValueError,KeyError) as exc:self.error('移动未完成：'+str(exc))
    def open_notebook_folder(self):
        path=DATA/'课堂资料';path.mkdir(exist_ok=True);os.startfile(str(path))
    def reveal_classroom(self,item):
        path=Path(item.data(Qt.UserRole));self.save()
        note=json.loads(path.read_text('utf8'))
        folder=ClassroomStore(DATA,self.subjects).persist(note)
        subprocess.Popen(['explorer.exe','/select,',str(folder/'课堂笔记.json')])
    def note_menu(self,pos,source=None):
        source=source or self.history
        item=source.itemAt(pos)
        if not item or self.job or self.rec:return
        path=item.data(Qt.UserRole)
        menu=QMenu(self);reveal=menu.addAction('在文件资源管理器中展开');menu.addSeparator()
        for name,key in [(s['name'],s['id']) for s in self.subjects]:
            action=menu.addAction('移至 · '+name);action.setData(key)
        menu.addSeparator();remove=menu.addAction('删除课堂…')
        action=menu.exec(source.mapToGlobal(pos))
        if action is None:return
        if action==remove:self.delete_classroom(path);return
        if action==reveal:
            note=json.loads(Path(path).read_text('utf8'));folder=ClassroomStore(DATA,self.subjects).persist(note)
            subprocess.Popen(['explorer.exe','/select,',str(folder/'课堂笔记.json')]);return
        self.move_classroom(path,action.data())
    def delete_classroom(self,path):
        if self.job or self.rec:return
        try:
            index=Path(path).resolve()
            if index.parent!=DATA.resolve() or index.suffix!='.json':
                raise ValueError('课堂索引不在笔记目录内')
            note=json.loads(index.read_text('utf8'))
            answer=QMessageBox.question(self,'删除课堂',
                '删除“'+note.get('title','未命名课堂')+'”？\n\n'
                '这节课堂将从列表移除，归档录音和笔记会移至本机“已删除课堂”目录。\n'
                '外部导入的原始文件保留。',QMessageBox.Yes|QMessageBox.Cancel,QMessageBox.Cancel)
            if answer!=QMessageBox.Yes or self.job or self.rec:return
            self.save()
            ClassroomStore(DATA,self.subjects).delete(index)
            if self.current and self.current['id']==note['id']:
                self.timer.stop();self.current=None
                self.title.setText('新的一课，从这里开始');self.source.setText('还没有选择录音')
                self.tabs.setCurrentIndex(0);self.change_tab(0);self.live_preview.clear();self.bar.setValue(0)
                self.saved.setText('自动保存 · 本地笔记')
                self.pages.setCurrentWidget(self.course_browser)
            self.refresh();self.status.setText('课堂已删除，归档资料保留在本机“已删除课堂”目录。')
        except (OSError,ValueError,KeyError,TypeError) as exc:
            self.error('删除未完成：'+str(exc))
    def refresh(self):
        self.refresh_subjects()
        self.history.clear();self.course_list.clear()
        for p in sorted(DATA.glob('*.json'),key=lambda x:x.stat().st_mtime,reverse=True):
            try:
                d=json.loads(p.read_text('utf8'))
                if self.search.text().lower() not in d['title'].lower():continue
                if self.active_subject is not None and d.get('subject','')!=self.active_subject:continue
                item=QListWidgetItem(d['title']+'\n'+d.get('date',''));item.setData(Qt.UserRole,str(p));self.history.addItem(item)
                ready=[label for key,label in [('transcript','转写原文'),('summary','课堂摘录'),('ai_summary','AI 总结'),('notes','我的笔记')] if d.get(key,'').strip()]
                course=QListWidgetItem(d['title']+'\n'+d.get('date','')+'  ·  '+(' / '.join(ready) or '待转写'))
                course.setData(Qt.UserRole,str(p));self.course_list.addItem(course)
            except (ValueError,OSError,KeyError):pass
        name=next((s['name'] for s in self.subjects if s['id']==self.active_subject),'全部课堂')
        self.course_heading.setText(name)
        self.course_info.setText(f'{self.course_list.count()} 节课堂 · 点击课程查看之前保存的内容')
        self.course_empty.setVisible(self.course_list.count()==0)
    def select(self,item):
        if self.job or self.rec: return
        path=item.data(Qt.UserRole)
        self.save();raw=Path(path).read_text('utf8');self.current=json.loads(raw)
        if simplify_note(self.current):
            backup=DATA/'backups';backup.mkdir(exist_ok=True);target=backup/(self.current['id']+'.before-simplified.json')
            if not target.exists():target.write_text(raw,'utf8')
            ClassroomStore(DATA,self.subjects).persist(self.current)
        self.pages.setCurrentIndex(0)
        preferred=next((index for index in (2,1,0,3) if self.current.get(TAB_KEYS[index],'').strip()),0)
        self.tabs.setCurrentIndex(preferred)
        self.title.setText(self.current['title']);self.refresh_subjects();self.source.setText(Path(self.current['audio']).name);self.change_tab(self.tabs.currentIndex());self.status.setText('已打开本地课堂笔记 · 简体中文')
        if self.compact_sidebar:self.motion.drawer(False)
        if self.current.get('ai_summary') and not has_substance(self.current['ai_summary']):self.status.setText('已有 AI 总结仅包含标题，请重新生成总结')
    def new(self,path):
        self.pages.setCurrentIndex(0)
        self.save();self.current={'id':uuid.uuid4().hex,'title':Path(path).stem,'audio':str(path),'date':time.strftime('%Y-%m-%d %H:%M'),'segments':[],'transcript':'','summary':'','notes':'','subject':self.active_subject or ''};self.title.setText(self.current['title']);self.source.setText(Path(path).name);self.tabs.setCurrentIndex(0);self.change_tab(0);self.save();self.bar.setValue(0)
    def import_file(self):
        if self.job or self.rec:return
        path,_=QFileDialog.getOpenFileName(self,'选择课堂录音','','音视频 (*.mp3 *.m4a *.wav *.mp4 *.flac *.ogg *.aac *.webm *.wma);;所有文件 (*)')
        if path:self.new(path)
    def dragEnterEvent(self,e):
        if e.mimeData().hasUrls():e.acceptProposedAction()
    def dropEvent(self,e):
        if not self.job and not self.rec:
            p=Path(e.mimeData().urls()[0].toLocalFile())
            if p.is_file():self.new(p)
    def change_tab(self,index):
        if not hasattr(self,'editor'):return
        previous=capture(self.editor)
        self.editor.blockSignals(True);self.editor.setPlainText((self.current or {}).get(TAB_KEYS[index],''));self.editor.blockSignals(False)
        self.editor.setReadOnly(bool(self.job) and index<3);self.count.setText(f'{len(self.editor.toPlainText())} 字')
        placeholders=['文字会在转写过程中逐段出现。你可以修改原文，修改会自动保存。',
                      '转写完成后显示课堂原文摘录。','点击“生成 AI 总结”，这里会显示具体的课堂要点。',
                      '在这里独立记录你的笔记；上方实时显示转写原文，笔记会自动保存。']
        self.editor.setPlaceholderText(placeholders[index])
        self.live_pane.setVisible(index==3)
        if index==3:self.live_preview.setPlainText((self.current or {}).get('transcript',''))
        reveal(self.editor,previous)
    def schedule_save(self):
        if self.current:
            self.current[TAB_KEYS[self.tabs.currentIndex()]]=self.editor.toPlainText()
            if self.tabs.currentIndex()==0 and self.current.get('ai_summary'):self.status.setText('原文已修改，已有 AI 总结可能需要重新生成')
        self.count.setText(f'{len(self.editor.toPlainText())} 字');self.timer.start(700)
    def save(self):
        if not self.current:return
        self.current['title']=self.title.text().strip() or '未命名课堂'
        ClassroomStore(DATA,self.subjects).persist(self.current);self.saved.setText('已保存到本机');self.refresh()
    def transcribe(self):
        if self.job or self.rec:return
        if not self.current:self.import_file();return
        engine=self.engine.currentData()
        if engine=='legacy' and (not self.legacy_root or not legacy_root_available(self.legacy_root)):
            folder=QFileDialog.getExistingDirectory(self,'选择原版听课.exe 所在文件夹')
            if not folder:return
            if not legacy_root_available(folder):self.error('请选择包含原版 runtime、models 和 tools 的完整软件文件夹。');return
            self.legacy_root=Path(folder)
            settings=DATA/'settings';settings.mkdir(exist_ok=True)
            (settings/'speech.json').write_text(json.dumps({'legacy_root':folder},ensure_ascii=False),'utf8')
            self.engine.setItemText(self.engine.findData('legacy'),'高精度识别 · 原版模型')
        if engine=='lite' and not transcription_available(engine):
            self.error('当前启动环境缺少转写组件。请关闭软件，从完整轻量版目录启动；不要只复制 app 文件。');return
        if not Path(self.current['audio']).is_file():
            self.error('原始录音文件不存在，请重新导入录音。');return
        if engine=='lite' and not speech_ready(DATA):
            if not self.speech_settings():return
        if self.current['transcript'] and QMessageBox.question(self,'重新转写','重新转写将替换这节课的原文、摘录并清除已有 AI 总结，是否继续？')!=QMessageBox.Yes:return
        self.current['ai_summary']='';self.current.pop('ai_metadata',None)
        self.current['segments']=[];self.current['transcript']='';self.current['summary']='';self.tabs.setCurrentIndex(0);self.change_tab(0)
        self.job=Worker(self.current['audio'],['chinese','english','auto'][self.lang.currentIndex()],engine,self.legacy_root);self.job.segment.connect(self.add_segment);self.job.progress.connect(self.progress);self.job.finished_job.connect(self.done);self.job.failed.connect(self.error);self.job.finished.connect(self.release_job);self.start.setEnabled(False);self.ai_btn.setEnabled(False);self.stop.show();self.editor.setReadOnly(True);self.bar.setRange(0,0);self.job.start()
    def add_segment(self,s):
        s=dict(s,text=to_simplified(s['text']));self.current['segments'].append(s)
        chunk='['+stamp(s['start'])+'] '+s['text']+'\n\n';self.current['transcript']+=chunk
        if self.tabs.currentIndex()==0:
            self.editor.blockSignals(True);self.editor.setPlainText(self.current['transcript']);self.editor.blockSignals(False);self.editor.verticalScrollBar().setValue(self.editor.verticalScrollBar().maximum())
            self.count.setText(f'{len(self.editor.toPlainText())} 字')
        if self.tabs.currentIndex()==3:
            self.live_preview.setPlainText(self.current['transcript']);self.live_preview.verticalScrollBar().setValue(self.live_preview.verticalScrollBar().maximum())
        self.save()
    def progress(self,n,text):
        if n:self.bar.setRange(0,100);self.bar.setValue(n)
        self.status.setText(text)
    def done(self,text):
        self.current['summary']=extract(self.current['segments']);self.save();self.status.setText(text);self.bar.setRange(0,100);self.change_tab(self.tabs.currentIndex())
    def error(self,text):self.status.setText('处理未完成，已保留现有文字');QMessageBox.warning(self,'需要检查',text)
    def release_job(self):self.job.deleteLater();self.job=None;self.start.setEnabled(True);self.ai_btn.setEnabled(True);self.stop.hide();self.editor.setReadOnly(False);self.bar.setRange(0,100);self.refresh_subjects()
    def cancel(self):
        if self.rec:self.finish_record()
        elif self.job:self.job.cancel=True;self.status.setText('将在当前请求或片段处理完成后停止，不保存新的 AI 总结…')
    def record(self):
        if self.job or self.rec:return
        dialog=RecordingDialog(self.subjects,self.active_subject,self.recording_history,self)
        if dialog.exec()!=QDialog.Accepted:dialog.deleteLater();return
        name=dialog.name.currentText().strip();subject=dialog.subject.currentData() or '';dialog.deleteLater()
        if not name:return
        try:
            import sounddevice as sd
            self.new(DATA/'temp'/(uuid.uuid4().hex+'.wav'))
            self.current['title']=name;self.current['subject']=subject;self.title.setText(name);self.save()
            p=DATA/self.current['_bundle']/(safe_name(name)+'.wav')
            self.current['audio']=str(p);self.save();self.source.setText(p.name)
            self.wav=wave.open(str(p),'wb');self.wav.setnchannels(1);self.wav.setsampwidth(2);self.wav.setframerate(16000);self.frames=0;self.rec_paused=False
            def callback(data,frames,timing,status):
                if not self.rec_paused:self.wav.writeframes(bytes(data));self.frames+=frames
            self.rec=sd.RawInputStream(samplerate=16000,channels=1,dtype='int16',callback=callback);self.rec.start()
            self.title.setEnabled(False)
            self.recording_history=[{'name':name,'subject':subject,'date':time.strftime('%Y-%m-%d %H:%M')}]+self.recording_history[:99]
            write_json(DATA/'settings'/'recording_history.json',self.recording_history)
            self.clock.start(500);self.stop.setText('结束录音');self.stop.show();self.pause.show();self.mark.show();self.start.setEnabled(False);self.ai_btn.setEnabled(False)
        except Exception as e:
            if self.rec:
                try:self.rec.close()
                except Exception:pass
            if getattr(self,'wav',None):self.wav.close()
            self.rec=None;self.title.setEnabled(True);self.error('无法开始录音，请检查麦克风连接及权限。\n'+str(e))
    def tick_record(self):self.status.setText(('已暂停  ' if self.rec_paused else '正在录音  ●  ')+stamp(self.frames/16000))
    def pause_record(self):
        if not self.rec:return
        self.rec_paused=not self.rec_paused;self.pause.setText('继续录音' if self.rec_paused else '暂停录音')
    def mark_record(self):
        self.current['notes']+='['+stamp(self.frames/16000)+'] 课堂重点\n';self.save();self.change_tab(self.tabs.currentIndex())
    def finish_record(self):
        if not self.rec:return
        self.rec.stop();self.rec.close();self.rec=None;self.title.setEnabled(True);self.wav.close();self.clock.stop();self.stop.hide();self.stop.setText('停止任务');self.pause.hide();self.mark.hide();self.start.setEnabled(True);self.ai_btn.setEnabled(True);self.status.setText('录音已保存，点击开始转写');self.save()
    def open_audio(self):
        if self.current and Path(self.current['audio']).exists():os.startfile(self.current['audio'])
    def export(self,selection='all'):
        if not self.current:
            QMessageBox.information(self,'还没有课堂','请先打开一节课堂，再选择要导出的内容。');return
        self.save()
        label={'all':'全部资料','summary':'课堂摘录','ai_summary':'AI 总结'}[selection]
        if selection!='all' and not self.current.get(selection,'').strip():
            QMessageBox.information(self,'暂无'+label,'当前课堂还没有'+label+'，请先'+('生成 AI 总结。' if selection=='ai_summary' else '完成录音转写。'));return
        name=re.sub(r'[<>:"/\\|?*]','_',self.current['title'])
        if selection!='all':name+='_'+label
        if self.current.get('_bundle'):name=str(DATA/self.current['_bundle']/name)
        formats='Word 文档 (*.docx);;PDF 文档 (*.pdf);;Markdown (*.md);;纯文本 (*.txt)'
        if selection=='all':formats+=';;字幕 SRT (*.srt)'
        path,fmt=QFileDialog.getSaveFileName(self,'导出'+label,name,formats)
        if not path:return
        suffix=re.search(r'\*([.a-z]+)',fmt).group(1)
        if not path.lower().endswith(suffix):path+=suffix
        try:export(self.current,Path(path),selection);self.status.setText('已导出'+label+'：'+Path(path).name)
        except Exception as e:self.error('导出失败：'+str(e))
    def closeEvent(self,event):
        if self.settings_page and self.settings_page.busy():
            self.settings_page.message.setText('请先停止模型任务，再关闭软件。');event.ignore();return
        if self.rec or self.job:QMessageBox.information(self,'任务进行中','请先结束录音或停止转写 / AI 总结，再关闭软件。');event.ignore();return
        if self.update_job:
            self.update_message='正在结束更新检查，请稍候…';self.update_status.emit(self.update_message);self.update_job.finished.connect(self.close);event.ignore();return
        if not self.motion.close():event.ignore();return
        self.update_timer.stop()
        self.timer.stop()
        self.save();close_engine();event.accept()
def export(data,path,selection='all'):
    if selection not in ('all','summary','ai_summary'):raise ValueError('未知的导出内容')
    if path.suffix.lower()=='.srt' and selection!='all':raise ValueError('字幕仅支持转写原文')
    ai=data.get('ai_summary','')
    metadata=data.get('ai_metadata',{})
    ai_note=('模型：'+metadata.get('model','未知')+' · '+metadata.get('generated_at','')+'\nAI 生成内容，请结合原文核对。') if ai else ''
    if ai and metadata.get('source_sha256')!=hashlib.sha256(data['transcript'].encode('utf8')).hexdigest():ai_note+='\n原文已修改，此总结可能需要重新生成。'
    sections=[('课堂摘录','summary')]+([('AI 总结','ai_summary')] if ai else [])+[('转写原文','transcript'),('我的笔记','notes')]
    if selection!='all':sections=[(title,key) for title,key in sections if key==selection]
    blocks=[data['title'],data['date']]
    for title,key in sections:
        blocks.append(title)
        if key=='ai_summary':blocks.append(ai_note)
        blocks.append(data.get(key,''))
    text='\n\n'.join(blocks)
    if path.suffix=='.docx':
        from docx import Document
        from docx.shared import Pt
        from docx.oxml.ns import qn
        doc=Document();style=doc.styles['Normal'];style.font.name='Microsoft YaHei';style._element.rPr.rFonts.set(qn('w:eastAsia'),'Microsoft YaHei');style.font.size=Pt(11);doc.add_heading(data['title'],0);doc.add_paragraph(data['date'])
        for title,key in sections:
            doc.add_heading(title,1)
            if key=='ai_summary':doc.add_paragraph(ai_note)
            for line in data[key].splitlines():doc.add_paragraph(line)
        doc.save(str(path))
    elif path.suffix=='.pdf':
        printer=QPrinter(QPrinter.HighResolution);printer.setOutputFormat(QPrinter.PdfFormat);printer.setOutputFileName(str(path));doc=QTextDocument();doc.setDefaultFont(QFont('Noto Sans SC',11));doc.setPlainText(text);doc.print_(printer)
    elif path.suffix=='.srt':
        def ts(t):return stamp(t)+f',{int(t%1*1000):03}'
        text='\n\n'.join(f"{i+1}\n{ts(s['start'])} --> {ts(s['end'])}\n{s['text']}" for i,s in enumerate(data['segments']));path.write_text(text,'utf8')
    else:path.write_text(('# '+text if path.suffix=='.md' else text),'utf8')
from ui_theme import STYLE
if __name__=='__main__':
    from desktop_integration import set_process_identity,forward_action
    set_process_identity()
    app=QApplication(sys.argv);app.setApplicationName('Listenote');app.setApplicationDisplayName('Listenote')
    app.setWindowIcon(QIcon(str(ROOT/'app'/'icon.ico')))
    task='activate'
    if '--task-action' in sys.argv:
        i=sys.argv.index('--task-action')
        if i+1<len(sys.argv):task=sys.argv[i+1]
    if forward_action(DATA,task):sys.exit(0)
    app.setStyle('Fusion');app.setStyleSheet(STYLE);w=Window();w.show()
    if task!='activate':QTimer.singleShot(400,lambda:w.desktop.dispatch(task))
    if '--preview-settings' in sys.argv:QTimer.singleShot(600,w.ai_settings)
    if '--screenshot' in sys.argv:QTimer.singleShot(1200,lambda:(w.grab().save(str(ROOT/'preview.png')),app.quit()))
    sys.exit(app.exec())
