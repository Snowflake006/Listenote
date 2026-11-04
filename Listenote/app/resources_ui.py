from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QPushButton, QProgressBar,
                               QHBoxLayout, QComboBox, QDialogButtonBox, QFrame)
from ai_summary import Cancelled
from resources import LOCAL_MODELS, prepare_ollama, prepare_speech, speech_ready, SPEECH_MODELS


class SetupWorker(QThread):
    progress = Signal(int, str)
    ready = Signal()
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, task, data, model=''):
        super().__init__()
        self.task, self.data, self.model = task, data, model
        self.cancel = False

    def run(self):
        try:
            report = lambda n, text: self.progress.emit(n, text)
            cancel = lambda: self.cancel
            if self.task == 'speech':
                prepare_speech(self.data, report, cancel, self.model or 'lite')
            elif self.task == 'qwen':
                from local_engine import prepare_qwen
                prepare_qwen(self.data, self.model, report, cancel)
            else:
                prepare_ollama(self.data, self.model, report, cancel)
            self.ready.emit()
        except Cancelled:
            self.cancelled.emit()
        except (RuntimeError, ValueError) as exc:
            self.failed.emit(str(exc))
        except Exception:
            self.failed.emit('准备未完成。请检查网络后点击重试，已下载的进度会保留。')


class SpeechSetupDialog(QDialog):
    model_ready=Signal(str)
    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.data, self.worker = data, None
        self.selected_mode='lite';self.completed=False;self.model_states={};self.model_buttons={}
        self.setWindowTitle('准备语音识别')
        self.setMinimumWidth(530)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignTop);layout.setSpacing(16)
        title = QLabel('配置本地语音识别')
        title.setObjectName('setupTitle')
        layout.addWidget(title)
        detail = QLabel('选择适合课堂的模型，从国内 ModelScope 下载到本机。\n无需安装旧版软件；准备一次，之后离线使用，不会上传录音。')
        detail.setWordWrap(True)
        layout.addWidget(detail)
        for mode,name,description,action in [
            ('lite','轻量识别 · Whisper Base',
             '约 148 MB · 下载更快，适合日常录音和快速整理。\n复杂术语和嘈杂录音请回听核对。','配置轻量识别'),
            ('high','高精度识别 · Whisper large-v3-turbo',
             '约 1.62 GB · 使用更大的 Whisper 模型，处理速度取决于电脑。\n复用软件内置引擎，无需另装 Python 或下载旧版整包。\n建议至少 8 GB 内存，准备 3 GB 以上可用磁盘空间。','配置高精度识别')]:
            card=QFrame();card.setObjectName('hero');box=QVBoxLayout(card);box.setContentsMargins(18,16,18,16);box.setSpacing(10)
            heading=QLabel(name);heading.setObjectName('setupTitle');heading.setWordWrap(True);box.addWidget(heading)
            text=QLabel(description);text.setWordWrap(True);box.addWidget(text)
            state=QLabel();state.setObjectName('muted');state.setWordWrap(True);box.addWidget(state);self.model_states[mode]=state
            control=QPushButton(action);control.setObjectName('primary');control.clicked.connect(lambda checked=False,mode=mode:self.begin(mode));box.addWidget(control)
            self.model_buttons[mode]=control;layout.addWidget(card)
        self.start=self.model_buttons['lite'];self.high_start=self.model_buttons['high']
        self.status = QLabel('支持暂停、继续下载与文件校验。高精度模型无需在 GitHub 下载。')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setValue(0)
        layout.addWidget(self.bar)
        buttons = QHBoxLayout()
        self.close_btn = QPushButton('稍后再说')
        self.close_btn.clicked.connect(self.reject)
        buttons.addStretch()
        buttons.addWidget(self.close_btn)
        layout.addLayout(buttons)
        self.refresh_models()

    def refresh_models(self):
        for mode,state in self.model_states.items():
            ready=speech_ready(self.data,mode)
            state.setText('已准备好 · 可在本机离线使用' if ready else '尚未配置 · 下载完成后即可使用')
            self.model_buttons[mode].setText(('重新校验' if ready else '配置')+SPEECH_MODELS[mode]['label'])

    def focus_model(self,model):
        if self.worker:return
        self.selected_mode=model;self.model_buttons[model].setFocus()
        self.status.setText('点击“配置'+SPEECH_MODELS[model]['label']+'”即可从国内源下载；已下载的进度会保留。')

    def begin(self,model='lite'):
        if self.worker:
            return
        self.selected_mode=model;self.completed=False
        self.worker = SetupWorker('speech', self.data,model)
        self.worker.progress.connect(self.progress)
        self.worker.ready.connect(self.accept_ready)
        self.worker.failed.connect(self.failed)
        self.worker.cancelled.connect(lambda: self.status.setText('已暂停，再次点击可继续下载。'))
        self.worker.finished.connect(self.release)
        for button in self.model_buttons.values():button.setEnabled(False)
        self.close_btn.setText('暂停下载')
        self.worker.start()

    def progress(self, percent, text):
        self.bar.setRange(0, 0 if percent < 0 else 100)
        if percent >= 0:
            self.bar.setValue(percent)
        self.status.setText(text)

    def accept_ready(self):
        self.completed=True
        self.status.setText(SPEECH_MODELS[self.selected_mode]['label']+'已准备好，可以返回课堂开始转写。')

    def failed(self, text):
        self.status.setText(text)

    def release(self):
        self.worker.deleteLater()
        self.worker = None
        for button in self.model_buttons.values():button.setEnabled(True)
        self.close_btn.setText('关闭')
        self.refresh_models()
        if self.completed and speech_ready(self.data,self.selected_mode):
            self.model_ready.emit(self.selected_mode)
            self.accept()

    def reject(self):
        if self.worker:
            self.worker.cancel = True
            self.status.setText('正在暂停，请稍候…')
        else:
            super().reject()

    def closeEvent(self, event):
        if self.worker:
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)
