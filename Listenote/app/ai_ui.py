"""Qt controls and background tasks for optional AI summaries."""
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLabel, QComboBox,
                               QLineEdit, QPlainTextEdit, QPushButton, QHBoxLayout,
                               QDialogButtonBox, QMessageBox)
from ai_summary import DEFAULT_CONFIG, DEFAULT_PROMPT, base_url, check_config, list_models, summarize, Cancelled


class SummaryWorker(QThread):
    progress = Signal(int, str)
    finished_job = Signal(str)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, config, key, transcript):
        super().__init__()
        self.config, self.key, self.transcript = dict(config), key, transcript
        self.cancel = False

    def run(self):
        try:
            result = summarize(self.config, self.key, self.transcript,
                               lambda text: self.progress.emit(0, text), lambda: self.cancel)
            if self.cancel:
                raise Cancelled()
            self.finished_job.emit(result)
        except Cancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.key = ''


class ModelsWorker(QThread):
    loaded = Signal(list)
    failed = Signal(str)

    def __init__(self, config, key):
        super().__init__()
        self.config, self.key = config, key

    def run(self):
        try:
            self.loaded.emit(list_models(self.config, self.key))
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.key = ''


class AISettingsDialog(QDialog):
    def __init__(self, config, key='', parent=None):
        super().__init__(parent)
        self.setWindowTitle('AI 模型设置')
        self.setMinimumWidth(610)
        self.worker = None
        layout = QVBoxLayout(self)
        intro = QLabel('选择本地开源模型，或接入你自己的模型服务。')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        self.provider = QComboBox()
        self.provider.addItem('本地开源模型 · Ollama', 'ollama')
        self.provider.addItem('自定义 API · Chat Completions 兼容接口', 'api')
        form.addRow('运行方式', self.provider)
        self.url = QLineEdit()
        form.addRow('服务地址', self.url)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText('仅本次运行保存；本地服务通常不需要')
        form.addRow('API 密钥', self.key)
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.setMinimumWidth(260)
        row = QHBoxLayout()
        row.addWidget(self.model, 1)
        self.fetch = QPushButton('获取模型列表')
        self.fetch.clicked.connect(self.fetch_models)
        row.addWidget(self.fetch)
        form.addRow('模型名称', row)
        layout.addLayout(form)
        self.help = QLabel()
        self.help.setWordWrap(True)
        self.help.setOpenExternalLinks(True)
        layout.addWidget(self.help)
        layout.addWidget(QLabel('总结要求（可修改）'))
        self.prompt = QPlainTextEdit()
        self.prompt.setMaximumHeight(145)
        layout.addWidget(self.prompt)
        self.state = QLabel('密钥不会写入笔记、设置文件或导出资料。')
        self.state.setWordWrap(True)
        layout.addWidget(self.state)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText('保存设置')
        self.buttons.button(QDialogButtonBox.Cancel).setText('取消')
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.provider.currentIndexChanged.connect(self.provider_changed)
        self.provider.setCurrentIndex(0 if config['provider'] == 'ollama' else 1)
        self.provider_changed()
        self.url.setText(config.get('url', DEFAULT_CONFIG['url']))
        self.model.setEditText(config.get('model', ''))
        self.key.setText(key)
        self.prompt.setPlainText(config.get('prompt', DEFAULT_PROMPT))

    def provider_changed(self):
        local = self.provider.currentData() == 'ollama'
        self.url.setText('http://localhost:11434' if local else '')
        self.url.setPlaceholderText('例如 https://你的服务地址/v1（不含 /chat/completions）')
        self.model.clear()
        self.key.clear()
        self.help.setText(
            '先安装 <a href="https://ollama.com/download/windows">Ollama</a>，并在终端运行 '
            '<code>ollama pull qwen3:4b</code> 下载开源模型。下载后启动 Ollama，点击“获取模型列表”。'
            '模型需另行下载，占用额外内存和磁盘；本地模型无按次 API 费用。'
            if local else
            '填写服务商提供的 Base URL、密钥和模型名称。接口需支持 /chat/completions；'
            '获取列表使用 /models，服务不提供列表时可手动输入模型名。远程服务可能收费，原文会发送至该地址。')

    def config(self):
        return {'provider': self.provider.currentData(), 'url': self.url.text().strip().rstrip('/'),
                'model': self.model.currentText().strip(), 'prompt': self.prompt.toPlainText().strip() or DEFAULT_PROMPT}

    def fetch_models(self):
        if self.worker:
            return
        try:
            base_url(self.config())
        except ValueError as exc:
            QMessageBox.warning(self, '检查地址', str(exc))
            return
        self.worker = ModelsWorker(self.config(), self.key.text().strip())
        self.worker.loaded.connect(self.models_loaded)
        self.worker.failed.connect(lambda text: self.state.setText(text + '；也可以手动输入模型名称。'))
        self.worker.finished.connect(self.release_worker)
        self.fetch.setEnabled(False)
        self.provider.setEnabled(False)
        self.state.setText('正在连接并获取模型列表…')
        self.worker.start()

    def models_loaded(self, models):
        selected = self.model.currentText()
        self.model.clear()
        self.model.addItems(models)
        if selected:
            self.model.setEditText(selected)
        self.state.setText(f'已连接，找到 {len(models)} 个模型。' if models else '服务已连接，但没有可用模型。请先下载模型或手动输入名称。')

    def release_worker(self):
        self.worker.deleteLater()
        self.worker = None
        self.fetch.setEnabled(True)
        self.provider.setEnabled(True)

    def accept(self):
        if self.worker:
            return
        try:
            check_config(self.config())
        except ValueError as exc:
            QMessageBox.warning(self, '检查模型配置', str(exc))
            return
        super().accept()

    def reject(self):
        if not self.worker:
            super().reject()

    def closeEvent(self, event):
        if self.worker:
            event.ignore()
        else:
            super().closeEvent(event)
