import os, sys, json, time, uuid, re, subprocess, tempfile, wave, threading, hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
os.environ['HF_HUB_OFFLINE']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QColor, QPainter, QLinearGradient, QPen, QTextDocument, QFontDatabase, QIcon
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import *
from ai_summary import DEFAULT_CONFIG, is_local, check_config
from ai_ui import AISettingsDialog, SummaryWorker
ROOT=Path(__file__).resolve().parent.parent
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
    def __init__(self,path,language):
        super().__init__(); self.path=path; self.language=language; self.cancel=False
    def run(self):
        try:
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
            with tempfile.TemporaryDirectory(prefix='listenote_') as td:
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
                        text=proc.batch_decode(ids,skip_special_tokens=True)[0].strip()
                        self.segment.emit({'start':position/16000,'end':(position+len(samples))/16000,'text':text})
                        position+=len(samples)
                        self.progress.emit(int(position/total*100),f'已处理 {stamp(position/16000)} / {stamp(total/16000)}')
            self.finished_job.emit('转写完成 · 课堂摘录已生成')
        except Exception as e: self.failed.emit(str(e))
class WaveArt(QWidget):
    def __init__(self): super().__init__(); self.setMinimumHeight(95)
    def paintEvent(self,event):
        import math
        p=QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        for i in range(90):
            x=self.width()*i/90; h=8+50*abs(math.sin(i*.29))*math.exp(-((i-45)/33)**2)
            p.setPen(QPen(QColor('#a89bed' if i<48 else '#dcd6f7'),3.5,Qt.SolidLine,Qt.RoundCap)); p.drawLine(int(x),int((self.height()-h)/2),int(x),int((self.height()+h)/2))
def button(text,slot,primary=False):
    b=QPushButton(text); b.setCursor(Qt.PointingHandCursor); b.clicked.connect(slot)
    if primary:b.setObjectName('primary')
    return b
class Window(QMainWindow):
    def __init__(self):
        super().__init__(); QFontDatabase.addApplicationFont(str(ROOT/'app'/'fonts'/'NotoSansSC.ttf')); self.setWindowIcon(QIcon(str(ROOT/'app'/'icon.ico'))); self.job=None; self.current=None; self.rec=None; self.frames=0; self.rec_paused=False
        self.ai_config=dict(DEFAULT_CONFIG);self.ai_key=''
        try:
            saved=json.loads((DATA/'settings'/'ai.json').read_text('utf8'))
            self.ai_config.update({k:saved[k] for k in DEFAULT_CONFIG if k in saved and isinstance(saved[k],str)})
        except (OSError,ValueError,TypeError):pass
        self.setWindowTitle('听课 Listenote · 本地课堂笔记'); self.resize(1280,900); self.setMinimumSize(1080,760); self.setAcceptDrops(True)
        outer=QWidget();self.setCentralWidget(outer); layout=QHBoxLayout(outer);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
        side=QFrame();side.setObjectName('sidebar');side.setFixedWidth(242); sl=QVBoxLayout(side);sl.setContentsMargins(22,32,22,24);sl.setSpacing(16)
        brand=QLabel('◉  听课');brand.setObjectName('brand');sl.addWidget(brand);sl.addWidget(QLabel('L I S T E N O T E'))
        sl.addSpacing(18);sl.addWidget(button('＋  导入课堂录音',self.import_file,True));sl.addWidget(button('●  开始录音',self.record))
        sl.addSpacing(10);sl.addWidget(QLabel('我的课堂'));self.search=QLineEdit();self.search.setPlaceholderText('搜索课堂…');self.search.textChanged.connect(self.refresh);sl.addWidget(self.search)
        self.history=QListWidget();self.history.itemClicked.connect(self.select);sl.addWidget(self.history,1)
        self.ai_settings_btn=button('AI 模型设置',self.ai_settings);sl.addWidget(self.ai_settings_btn)
        sl.addWidget(button('打开笔记文件夹',lambda:os.startfile(str(DATA))));sl.addWidget(button('关于与使用说明',self.about));sl.addWidget(QLabel('● 转写离线 · AI 可选'))
        layout.addWidget(side)
        main=QWidget();ml=QVBoxLayout(main);ml.setContentsMargins(38,30,38,24);ml.setSpacing(15);layout.addWidget(main,1)
        top=QHBoxLayout();tag=QLabel('你的课堂，值得被好好记住。');tag.setObjectName('muted');top.addWidget(tag);top.addStretch();badge=QLabel('  LOCAL + AI  /  1.1  ');badge.setObjectName('badge');top.addWidget(badge);ml.addLayout(top)
        self.title=QLineEdit('新的一课，从这里开始');self.title.setObjectName('title');self.title.editingFinished.connect(self.save);ml.addWidget(self.title)
        self.subtitle=QLabel('拖入录音，留住知识。支持 MP3 / M4A / WAV / MP4 等格式。');self.subtitle.setObjectName('muted');ml.addWidget(self.subtitle)
        hero=QFrame();hero.setObjectName('hero');hl=QVBoxLayout(hero);hl.setContentsMargins(24,15,24,20)
        self.wave=WaveArt();hl.addWidget(self.wave)
        row=QHBoxLayout();self.source=QLabel('还没有选择录音');self.source.setWordWrap(True);row.addWidget(self.source,1)
        self.lang=QComboBox();self.lang.addItems(['中文','English','自动识别']);row.addWidget(self.lang)
        self.start=button('开始转写  →',self.transcribe,True);row.addWidget(self.start);hl.addLayout(row)
        self.bar=QProgressBar();self.bar.setTextVisible(False);self.bar.setFixedHeight(5);hl.addWidget(self.bar)
        self.status=QLabel('音频和文字保存在你的电脑上');self.status.setObjectName('muted');hl.addWidget(self.status)
        controls=QHBoxLayout();self.stop=button('停止任务',self.cancel);self.stop.hide();controls.addWidget(self.stop)
        self.pause=button('暂停录音',self.pause_record);self.pause.hide();controls.addWidget(self.pause)
        self.mark=button('标记重点',self.mark_record);self.mark.hide();controls.addWidget(self.mark)
        controls.addStretch();controls.addWidget(button('打开原始录音',self.open_audio));hl.addLayout(controls);ml.addWidget(hero)
        airow=QHBoxLayout();self.ai_label=QLabel();self.ai_label.setObjectName('muted');self.ai_label.setWordWrap(True);airow.addWidget(self.ai_label,1)
        self.ai_btn=button('生成 AI 总结',self.summarize,True);airow.addWidget(self.ai_btn);ml.addLayout(airow);self.update_ai_label()
        tools=QHBoxLayout();self.tabs=QTabBar();self.tabs.addTab('转写原文');self.tabs.addTab('课堂摘录');self.tabs.addTab('AI 总结');self.tabs.addTab('我的笔记');self.tabs.currentChanged.connect(self.change_tab);tools.addWidget(self.tabs);tools.addStretch()
        self.export_btn=button('导出资料  ↗',self.export);tools.addWidget(self.export_btn);ml.addLayout(tools)
        self.editor=QPlainTextEdit();self.editor.setPlaceholderText('文字会在转写过程中逐段出现。\n\n你可以直接修改识别结果，补充课堂笔记。所有修改会自动保存。');self.editor.textChanged.connect(self.schedule_save);ml.addWidget(self.editor,1)
        foot=QHBoxLayout();self.count=QLabel('0 字');self.count.setObjectName('muted');foot.addWidget(self.count);foot.addStretch();self.saved=QLabel('自动保存 · 本地笔记');self.saved.setObjectName('muted');foot.addWidget(self.saved);ml.addLayout(foot)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self.save)
        self.clock=QTimer(self);self.clock.timeout.connect(self.tick_record)
        self.refresh()
    def about(self):
        QMessageBox.information(self,'关于听课','听课 Listenote 1.1\n\n本地 Whisper large-v3-turbo 转写，无需账号、无需联网。\nAI 总结可选本地 Ollama 开源模型或自定义兼容 API。\n本地总结需自行安装 Ollama 并下载模型；远程 API 会发送原文，可能产生费用。\n\n课堂摘录保留原文，AI 总结单独保存；请核对 AI 输出。\n录音前请遵守课堂要求并取得必要同意。\n\n导出：TXT / Markdown / Word / PDF / SRT。')
    def update_ai_label(self):
        mode='Ollama' if self.ai_config['provider']=='ollama' else '自定义 API'
        self.ai_label.setText('AI 总结 · '+mode+' · '+(self.ai_config.get('model') or '请先在左侧选择模型'))
    def ai_settings(self):
        if self.job or self.rec:return
        dialog=AISettingsDialog(self.ai_config,self.ai_key,self)
        if dialog.exec()!=QDialog.Accepted:return
        config=dialog.config()
        try:
            folder=DATA/'settings';folder.mkdir(exist_ok=True)
            target=folder/'ai.json';tmp=target.with_suffix('.tmp')
            tmp.write_text(json.dumps(config,ensure_ascii=False,indent=2),'utf8');tmp.replace(target)
        except OSError as exc:
            QMessageBox.warning(self,'设置未保存','无法保存模型设置：'+str(exc));return
        self.ai_config=config;self.ai_key=dialog.key.text().strip();self.update_ai_label()
    def summarize(self):
        if self.job or self.rec:return
        if not self.current or not self.current.get('transcript','').strip():
            QMessageBox.information(self,'需要课堂原文','请先导入录音并转写，再生成 AI 总结。');return
        self.save()
        try:check_config(self.ai_config)
        except ValueError:
            self.ai_settings()
            try:check_config(self.ai_config)
            except ValueError:return
        if not is_local(self.ai_config):
            if QMessageBox.question(self,'发送原文到模型服务',
                '将把当前课堂转写原文发送到：\n'+self.ai_config['url']+'\n模型：'+self.ai_config['model']+
                '\n\n服务商可能收取费用。是否继续？',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return
        if self.current.get('ai_summary') and QMessageBox.question(self,'重新生成总结','成功后将替换现有 AI 总结，是否继续？',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return
        self.job=SummaryWorker(self.ai_config,self.ai_key,self.current['transcript'])
        self.job.progress.connect(self.progress);self.job.finished_job.connect(self.ai_done)
        self.job.failed.connect(self.error);self.job.cancelled.connect(lambda:self.status.setText('已取消 AI 总结，保留原有内容'))
        self.job.finished.connect(self.release_job);self.start.setEnabled(False);self.ai_btn.setEnabled(False);self.ai_settings_btn.setEnabled(False)
        self.stop.show();self.bar.setRange(0,0);self.change_tab(self.tabs.currentIndex());self.status.setText('正在连接 AI 模型…');self.job.start()
    def ai_done(self,text):
        self.current['ai_summary']=text
        self.current['ai_metadata']={'model':self.ai_config['model'],'provider':self.ai_config['provider'],'generated_at':time.strftime('%Y-%m-%d %H:%M'),'source_sha256':hashlib.sha256(self.current['transcript'].encode('utf8')).hexdigest()}
        self.save();self.tabs.setCurrentIndex(2);self.change_tab(2);self.status.setText('AI 总结已保存 · 请结合原文核对')
    def refresh(self):
        self.history.clear()
        for p in sorted(DATA.glob('*.json'),key=lambda x:x.stat().st_mtime,reverse=True):
            try:
                d=json.loads(p.read_text('utf8'))
                if self.search.text().lower() not in d['title'].lower():continue
                item=QListWidgetItem(d['title']+'\n'+d.get('date',''));item.setData(Qt.UserRole,str(p));self.history.addItem(item)
            except (ValueError,OSError,KeyError):pass
    def select(self,item):
        if self.job or self.rec: return
        path=item.data(Qt.UserRole)
        self.save();self.current=json.loads(Path(path).read_text('utf8'));self.title.setText(self.current['title']);self.source.setText(Path(self.current['audio']).name);self.change_tab(self.tabs.currentIndex());self.status.setText('已打开本地课堂笔记')
    def new(self,path):
        self.save();self.current={'id':uuid.uuid4().hex,'title':Path(path).stem,'audio':str(path),'date':time.strftime('%Y-%m-%d %H:%M'),'segments':[],'transcript':'','summary':'','notes':''};self.title.setText(self.current['title']);self.source.setText(Path(path).name);self.tabs.setCurrentIndex(0);self.change_tab(0);self.save();self.bar.setValue(0)
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
        self.editor.blockSignals(True);self.editor.setPlainText((self.current or {}).get(TAB_KEYS[index],''));self.editor.blockSignals(False)
        self.editor.setReadOnly(bool(self.job) and index<3);self.count.setText(f'{len(self.editor.toPlainText())} 字')
    def schedule_save(self):
        if self.current:
            self.current[TAB_KEYS[self.tabs.currentIndex()]]=self.editor.toPlainText()
            if self.tabs.currentIndex()==0 and self.current.get('ai_summary'):self.status.setText('原文已修改，已有 AI 总结可能需要重新生成')
        self.count.setText(f'{len(self.editor.toPlainText())} 字');self.timer.start(700)
    def save(self):
        if not self.current:return
        self.current['title']=self.title.text().strip() or '未命名课堂'
        p=DATA/(self.current['id']+'.json');tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(self.current,ensure_ascii=False,indent=2),'utf8');tmp.replace(p);self.saved.setText('已保存到本机');self.refresh()
    def transcribe(self):
        if self.job or self.rec:return
        if not self.current:self.import_file();return
        if self.current['transcript'] and QMessageBox.question(self,'重新转写','重新转写将替换这节课的原文、摘录并清除已有 AI 总结，是否继续？')!=QMessageBox.Yes:return
        self.current['ai_summary']='';self.current.pop('ai_metadata',None)
        self.current['segments']=[];self.current['transcript']='';self.current['summary']='';self.tabs.setCurrentIndex(0);self.change_tab(0)
        self.job=Worker(self.current['audio'],['chinese','english','auto'][self.lang.currentIndex()]);self.job.segment.connect(self.add_segment);self.job.progress.connect(self.progress);self.job.finished_job.connect(self.done);self.job.failed.connect(self.error);self.job.finished.connect(self.release_job);self.start.setEnabled(False);self.ai_btn.setEnabled(False);self.ai_settings_btn.setEnabled(False);self.stop.show();self.editor.setReadOnly(True);self.bar.setRange(0,0);self.job.start()
    def add_segment(self,s):
        self.current['segments'].append(s);self.current['transcript']+='['+stamp(s['start'])+'] '+s['text']+'\n\n';self.change_tab(self.tabs.currentIndex());self.save()
    def progress(self,n,text):
        if n:self.bar.setRange(0,100);self.bar.setValue(n)
        self.status.setText(text)
    def done(self,text):
        self.current['summary']=extract(self.current['segments']);self.save();self.status.setText(text);self.bar.setRange(0,100);self.change_tab(self.tabs.currentIndex())
    def error(self,text):self.status.setText('处理未完成，已保留现有文字');QMessageBox.warning(self,'需要检查',text)
    def release_job(self):self.job.deleteLater();self.job=None;self.start.setEnabled(True);self.ai_btn.setEnabled(True);self.ai_settings_btn.setEnabled(True);self.stop.hide();self.editor.setReadOnly(False);self.bar.setRange(0,100)
    def cancel(self):
        if self.rec:self.finish_record()
        elif self.job:self.job.cancel=True;self.status.setText('将在当前请求或片段处理完成后停止，不保存新的 AI 总结…')
    def record(self):
        if self.job or self.rec:return
        try:
            import sounddevice as sd
            folder=DATA/'recordings';folder.mkdir(exist_ok=True);p=folder/(time.strftime('课堂录音_%Y%m%d_%H%M%S')+'.wav');self.new(p)
            self.wav=wave.open(str(p),'wb');self.wav.setnchannels(1);self.wav.setsampwidth(2);self.wav.setframerate(16000);self.frames=0;self.rec_paused=False
            def callback(data,frames,timing,status):
                if not self.rec_paused:self.wav.writeframes(bytes(data));self.frames+=frames
            self.rec=sd.RawInputStream(samplerate=16000,channels=1,dtype='int16',callback=callback);self.rec.start();self.clock.start(500);self.stop.setText('结束录音');self.stop.show();self.pause.show();self.mark.show();self.start.setEnabled(False);self.ai_btn.setEnabled(False);self.ai_settings_btn.setEnabled(False)
        except Exception as e:
            if getattr(self,'wav',None):self.wav.close()
            self.rec=None;self.error('无法开始录音，请检查麦克风连接及权限。\n'+str(e))
    def tick_record(self):self.status.setText(('已暂停  ' if self.rec_paused else '正在录音  ●  ')+stamp(self.frames/16000))
    def pause_record(self):self.rec_paused=not self.rec_paused;self.pause.setText('继续录音' if self.rec_paused else '暂停录音')
    def mark_record(self):
        self.current['notes']+='['+stamp(self.frames/16000)+'] 课堂重点\n';self.save();self.change_tab(self.tabs.currentIndex())
    def finish_record(self):
        self.rec.stop();self.rec.close();self.rec=None;self.wav.close();self.clock.stop();self.stop.hide();self.stop.setText('停止任务');self.pause.hide();self.mark.hide();self.start.setEnabled(True);self.ai_btn.setEnabled(True);self.ai_settings_btn.setEnabled(True);self.status.setText('录音已保存，点击开始转写');self.save()
    def open_audio(self):
        if self.current and Path(self.current['audio']).exists():os.startfile(self.current['audio'])
    def export(self):
        if not self.current:return
        self.save();name=re.sub(r'[<>:"/\\|?*]','_',self.current['title']);path,fmt=QFileDialog.getSaveFileName(self,'导出课堂资料',name,'Word 文档 (*.docx);;PDF 文档 (*.pdf);;Markdown (*.md);;纯文本 (*.txt);;字幕 SRT (*.srt)')
        if not path:return
        suffix=re.search(r'\*([.a-z]+)',fmt).group(1)
        if not path.lower().endswith(suffix):path+=suffix
        try:export(self.current,Path(path));self.status.setText('已导出：'+Path(path).name)
        except Exception as e:self.error('导出失败：'+str(e))
    def closeEvent(self,event):
        if self.rec or self.job:QMessageBox.information(self,'任务进行中','请先结束录音或停止转写 / AI 总结，再关闭软件。');event.ignore();return
        self.save();event.accept()
def export(data,path):
    ai=data.get('ai_summary','')
    metadata=data.get('ai_metadata',{})
    ai_note=('模型：'+metadata.get('model','未知')+' · '+metadata.get('generated_at','')+'\nAI 生成内容，请结合原文核对。') if ai else ''
    if ai and metadata.get('source_sha256')!=hashlib.sha256(data['transcript'].encode('utf8')).hexdigest():ai_note+='\n原文已修改，此总结可能需要重新生成。'
    blocks=[data['title'],data['date'],'课堂摘录',data['summary']]
    if ai:blocks+=['AI 总结',ai_note,ai]
    blocks+=['转写原文',data['transcript'],'我的笔记',data['notes']]
    text='\n\n'.join(blocks)
    if path.suffix=='.docx':
        from docx import Document
        from docx.shared import Pt
        from docx.oxml.ns import qn
        doc=Document();style=doc.styles['Normal'];style.font.name='Microsoft YaHei';style._element.rPr.rFonts.set(qn('w:eastAsia'),'Microsoft YaHei');style.font.size=Pt(11);doc.add_heading(data['title'],0);doc.add_paragraph(data['date'])
        sections=[('课堂摘录','summary')]+([('AI 总结','ai_summary')] if ai else [])+[('转写原文','transcript'),('我的笔记','notes')]
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
STYLE='''
QWidget{font-family:"Noto Sans SC";font-size:13px;color:#272739;background:#f7f8fc;}
QFrame#sidebar,QFrame#sidebar QWidget{background:#202233;color:#b7bbd1;}
QLabel#brand{font-size:30px;font-weight:700;color:white;}
QFrame#sidebar QPushButton{border:1px solid #41445c;background:#2b2e44;color:#e5e5f3;padding:12px;border-radius:10px;text-align:left;}
QPushButton{background:white;border:1px solid #e0e1eb;border-radius:9px;padding:10px 15px;}
QPushButton:hover{background:#ece9fb;border-color:#b9acf0;}
QPushButton#primary,QFrame#sidebar QPushButton#primary{background:#7560da;color:white;border:0;font-weight:600;}
QPushButton#primary:hover{background:#6650ce;} QPushButton:disabled{color:#aaa;background:#e7e5ef;}
QListWidget{border:0;outline:0;}QListWidget::item{padding:14px 6px;border-radius:7px;}QListWidget::item:selected{background:#363951;color:white;}
QLineEdit{border:1px solid #e1e2ec;border-radius:8px;padding:9px;background:white;}
QFrame#sidebar QLineEdit{border:1px solid #404359;}
QLineEdit#title{font-size:29px;font-weight:700;border:0;background:transparent;padding:4px 0;}
QLabel#muted{color:#85869c;font-size:12px;}QLabel#badge{color:#7766bd;font-size:10px;background:#eeebfa;border-radius:8px;padding:7px;}
QFrame#hero{background:#f0edfc;border:1px solid #e4def8;border-radius:16px;}QFrame#hero QLabel,QFrame#hero WaveArt{background:transparent;}
QComboBox{padding:9px;border:1px solid #dcd5f4;border-radius:7px;}
QProgressBar{background:#e1dcf3;border:0;border-radius:2px;}QProgressBar::chunk{background:#8c77df;border-radius:2px;}
QTabBar::tab{padding:12px 17px;color:#8b8a9e;border-bottom:2px solid transparent;}QTabBar::tab:selected{color:#7360cf;border-bottom:2px solid #7360cf;}
QPlainTextEdit{background:white;border:1px solid #e6e6ef;border-radius:12px;padding:19px;font-size:15px;selection-background-color:#ddd5fa;}
QScrollBar:vertical{width:7px;background:transparent;}QScrollBar::handle:vertical{background:#ccc8de;border-radius:3px;min-height:30px;}QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}
'''
if __name__=='__main__':
    app=QApplication(sys.argv);app.setStyle('Fusion');app.setStyleSheet(STYLE);w=Window();w.show()
    if '--screenshot' in sys.argv:QTimer.singleShot(1200,lambda:(w.grab().save(str(ROOT/'preview.png')),app.quit()))
    sys.exit(app.exec())
