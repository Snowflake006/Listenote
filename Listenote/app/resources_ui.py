from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QPushButton, QProgressBar,
                               QHBoxLayout, QComboBox, QDialogButtonBox)
from ai_summary import Cancelled
from resources import LOCAL_MODELS, prepare_ollama, prepare_speech, speech_ready


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
                prepare_speech(self.data, report, cancel)
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
    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.data, self.worker = data, None
        self.setWindowTitle('准备语音识别')
        self.setMinimumWidth(530)
        layout = QVBoxLayout(self)
        title = QLabel('更轻的程序，一次准备，离线使用')
        title.setObjectName('setupTitle')
        layout.addWidget(title)
        detail = QLabel('从国内 ModelScope 下载约 148 MB 的语音模型。\n下载后保存在本机，不会上传你的录音。支持断点续传。\n轻量模型速度更快；识别复杂术语时建议回听核对。')
        detail.setWordWrap(True)
        layout.addWidget(detail)
        self.status = QLabel('点击下方按钮即可自动准备，无需手动下载或输入命令。')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setValue(0)
        layout.addWidget(self.bar)
        buttons = QHBoxLayout()
        self.start = QPushButton('从国内源一键下载')
        self.start.setObjectName('primary')
        self.start.clicked.connect(self.begin)
        self.close_btn = QPushButton('稍后再说')
        self.close_btn.clicked.connect(self.reject)
        buttons.addWidget(self.start)
        buttons.addWidget(self.close_btn)
        layout.addLayout(buttons)

    def begin(self):
        if self.worker:
            return
        self.worker = SetupWorker('speech', self.data)
        self.worker.progress.connect(self.progress)
        self.worker.ready.connect(self.accept_ready)
        self.worker.failed.connect(self.failed)
        self.worker.cancelled.connect(lambda: self.status.setText('已暂停，再次点击可继续下载。'))
        self.worker.finished.connect(self.release)
        self.start.setEnabled(False)
        self.close_btn.setText('暂停下载')
        self.worker.start()

    def progress(self, percent, text):
        self.bar.setRange(0, 0 if percent < 0 else 100)
        if percent >= 0:
            self.bar.setValue(percent)
        self.status.setText(text)

    def accept_ready(self):
        self.status.setText('语音模型已准备好。')

    def failed(self, text):
        self.status.setText(text)

    def release(self):
        self.worker.deleteLater()
        self.worker = None
        self.start.setEnabled(True)
        self.close_btn.setText('关闭')
        if speech_ready(self.data):
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
