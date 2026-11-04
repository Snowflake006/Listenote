"""Qt controls and background tasks for optional AI summaries."""
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLabel, QComboBox,
                               QLineEdit, QPlainTextEdit, QPushButton, QHBoxLayout,
                               QDialogButtonBox, QMessageBox, QGroupBox, QWidget, QProgressBar)
from ui_components import AppleComboBox as QComboBox
from ai_summary import (DEFAULT_CONFIG, DEFAULT_PROMPT, DEEPSEEK_URL, DEEPSEEK_MODELS,
                        base_url, check_config, list_models, summarize, Cancelled, normalize_prompt)
from resources import LOCAL_MODELS
from resources_ui import SetupWorker
from local_engine import QWEN_MODELS, model_ready, ensure_engine


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
            if self.config['provider'] == 'local':
                from pathlib import Path
                import os
                data = Path(os.environ.get('LISTENOTE_DATA', str(Path(os.environ['LOCALAPPDATA']) / 'Listenote')))
                url, key = ensure_engine(data, Path(__file__).resolve().parent.parent,
                                         self.config['model'], lambda text: self.progress.emit(0,text), lambda:self.cancel)
                self.config['url'], self.key = url, key
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
    def __init__(self, config, key='', parent=None, data=None):
        super().__init__(parent)
        self.setWindowTitle('AI 模型设置')
        from pathlib import Path
        import os
        self.data = data or Path(os.environ.get('LISTENOTE_DATA', str(Path(os.environ['LOCALAPPDATA']) / 'Listenote')))
        self.setMinimumWidth(620)
        self.worker = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 24)
        layout.setSpacing(16)
        intro = QLabel('让 AI 帮你整理课堂')
        intro.setObjectName('setupTitle')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.provider = QComboBox()
        self.provider.addItem('本地免费 · 通义千问（国内下载）', 'local')
        self.provider.addItem('国内服务 · DeepSeek', 'deepseek')
        self.provider.addItem('其他服务 · 自己接入 API', 'api')
        self.provider.addItem('已有 Ollama · 高级选项', 'ollama')
        form.addRow('使用方式', self.provider)
        self.url = QLineEdit()
        self.url_label = QLabel('服务地址')
        form.addRow(self.url_label, self.url)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText('仅本次运行保存；本地服务通常不需要')
        self.key_label = QLabel('API 密钥')
        form.addRow(self.key_label, self.key)
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.setMinimumWidth(260)
        row = QHBoxLayout()
        row.addWidget(self.model, 1)
        self.fetch = QPushButton('检查已有模型')
        self.fetch.clicked.connect(self.fetch_models)
        row.addWidget(self.fetch)
        form.addRow('选择模型', row)
        layout.addLayout(form)
        self.install = QPushButton('一键安装并准备本地模型')
        self.install.setObjectName('primary')
        self.install.setMinimumHeight(48)
        self.install.clicked.connect(self.install_model)
        layout.addWidget(self.install)
        self.help = QLabel()
        self.help.setWordWrap(True)
        self.help.setOpenExternalLinks(True)
        layout.addWidget(self.help)
        self.advanced = QGroupBox('自定义总结要求（可选）')
        self.advanced.setCheckable(True)
        self.advanced.setChecked(False)
        advanced_layout = QVBoxLayout(self.advanced)
        self.prompt = QPlainTextEdit()
        self.prompt.setMaximumHeight(125)
        self.prompt.hide()
        advanced_layout.addWidget(self.prompt)
        self.advanced.toggled.connect(self.prompt.setVisible)
        layout.addWidget(self.advanced)
        self.state = QLabel('密钥不会写入笔记、设置文件或导出资料。')
        self.state.setWordWrap(True)
        layout.addWidget(self.state)
        self.bar = QProgressBar()
        self.bar.hide()
        layout.addWidget(self.bar)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText('使用这个模型')
        self.buttons.button(QDialogButtonBox.Cancel).setText('取消')
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.provider.currentIndexChanged.connect(self.provider_changed)
        self.provider.setCurrentIndex(max(0, self.provider.findData(config['provider'])))
        self.provider_changed()
        self.url.setText(config.get('url', DEFAULT_CONFIG['url']))
        model_id = config.get('model', '')
        index = self.model.findData(model_id)
        if index >= 0:
            self.model.setCurrentIndex(index)
        elif model_id:
            if self.model.isEditable():
                self.model.setEditText(model_id)
            else:
                self.model.addItem(model_id, model_id)
                self.model.setCurrentIndex(self.model.count() - 1)
        self.key.setText(key)
        self.prompt.setPlainText(normalize_prompt(config.get('prompt', DEFAULT_PROMPT)))

    def provider_changed(self):
        native = self.provider.currentData() == 'local'
        local = self.provider.currentData() in ('ollama', 'local')
        domestic = self.provider.currentData() == 'deepseek'
        self.url.setText('http://127.0.0.1' if native else 'http://localhost:11434' if local else DEEPSEEK_URL if domestic else '')
        self.url.setVisible(not local and not domestic)
        self.url_label.setVisible(not local and not domestic)
        self.key.setVisible(not local)
        self.key_label.setVisible(not local)
        self.install.setVisible(local)
        self.install.setText('一键从国内下载千问模型' if native else '一键安装并准备 Ollama 模型')
        self.fetch.setVisible(not domestic and not native)
        self.fetch.setText('检查已有模型' if local else '获取模型列表')
        self.url.setPlaceholderText('例如 https://你的服务地址/v1（不含 /chat/completions）')
        self.model.clear()
        self.model.setEditable(not domestic)
        for label, model in QWEN_MODELS if native else LOCAL_MODELS if local else DEEPSEEK_MODELS if domestic else []:
            self.model.addItem(label, model)
        self.key.clear()
        self.help.setText(
            '直接从国内 ModelScope 下载千问模型，推理引擎已随程序提供。<br>'
            '无需安装 Ollama，无需输入命令；下载一次后可离线总结，无按次费用。'
            if native else
            '点击上方按钮，电脑会自动安装 Ollama、下载并准备所选模型。<br>'
            '首次需联网并预留数 GB 空间，准备好后可离线总结，无按次费用。无需输入命令。'
            if local else
            '国内模型服务，地址已填好，选择模型并填写密钥即可。<br>'
            '<a href="https://platform.deepseek.com/api_keys">前往 DeepSeek 获取密钥</a> · '
            '原文会发送到 DeepSeek，费用以服务商为准。无需安装本地模型。'
            if domestic else
            '填写服务商提供的 Base URL、密钥和模型名称。接口需支持 /chat/completions；'
            '获取列表使用 /models，服务不提供列表时可手动输入模型名。远程服务可能收费，原文会发送至该地址。')
        self.state.setText('本地运行，课堂文字保留在电脑上。' if local else '密钥仅在本次运行中保留，不会写入课堂笔记。')

    def selected_model(self):
        index = self.model.currentIndex()
        if index >= 0 and self.model.currentText() == self.model.itemText(index):
            return self.model.itemData(index) or self.model.currentText().strip()
        return self.model.currentText().strip()

    def config(self):
        return {'provider': self.provider.currentData(), 'url': self.url.text().strip().rstrip('/'),
                'model': self.selected_model(), 'prompt': self.prompt.toPlainText().strip() or DEFAULT_PROMPT}

    def install_model(self):
        if self.worker:
            return
        model = self.selected_model()
        native = self.provider.currentData() == 'local'
        choices = QWEN_MODELS if native else LOCAL_MODELS
        if model not in {item[1] for item in choices}:
            self.state.setText('请先从列表选择轻量或进阶模型，再点击一键准备。')
            return
        self.url.setText('http://127.0.0.1' if native else 'http://localhost:11434')
        self.worker = SetupWorker('qwen' if native else 'ollama', self.data, model)
        self.worker.progress.connect(self.setup_progress)
        self.worker.ready.connect(lambda: self.state.setText('✓ 本地模型已准备好，点击“使用这个模型”即可。'))
        self.worker.failed.connect(self.state.setText)
        self.worker.cancelled.connect(lambda: self.state.setText('已停止准备，再次点击可继续。'))
        self.worker.finished.connect(self.release_worker)
        self.set_busy(True)
        self.bar.setRange(0, 0)
        self.bar.show()
        self.worker.start()

    def setup_progress(self, percent, text):
        self.bar.setRange(0, 0 if percent < 0 else 100)
        if percent >= 0:
            self.bar.setValue(percent)
        self.state.setText(text)

    def set_busy(self, busy):
        for widget in (self.install, self.fetch, self.provider, self.url, self.key, self.model):
            widget.setEnabled(not busy)
        self.buttons.button(QDialogButtonBox.Save).setEnabled(not busy)
        self.buttons.button(QDialogButtonBox.Cancel).setText('停止准备' if busy else '取消')

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
        self.worker.failed.connect(lambda text: self.state.setText(
            '尚未找到运行中的本地模型。点击上方“一键安装并准备本地模型”即可。'
            if self.provider.currentData() == 'ollama' else text + '；也可以手动输入模型名称。'))
        self.worker.finished.connect(self.release_worker)
        self.set_busy(True)
        self.state.setText('正在连接并获取模型列表…')
        self.worker.start()

    def models_loaded(self, models):
        selected = self.selected_model()
        self.model.clear()
        for model in models:
            self.model.addItem(model, model)
        if selected:
            self.model.setEditText(selected)
        self.state.setText(f'已连接，找到 {len(models)} 个模型。' if models else '服务已连接，但没有可用模型。请先下载模型或手动输入名称。')

    def release_worker(self):
        self.worker.deleteLater()
        self.worker = None
        self.set_busy(False)
        self.bar.setRange(0, 100)

    def accept(self):
        if self.worker:
            return
        try:
            check_config(self.config())
            if self.provider.currentData() == 'local' and not model_ready(self.data, self.selected_model()):
                self.state.setText('请先点击上方按钮下载所选千问模型，再开始使用。')
                return
            if self.provider.currentData() == 'deepseek' and not self.key.text().strip():
                raise ValueError('请先填写 DeepSeek API 密钥，或选择本地免费模型。')
        except ValueError as exc:
            QMessageBox.warning(self, '检查模型配置', str(exc))
            return
        super().accept()

    def reject(self):
        if isinstance(self.worker, SetupWorker):
            self.worker.cancel = True
            self.state.setText('正在停止；若已开始安装，将在安装结束后停止。')
        elif not self.worker:
            super().reject()

    def closeEvent(self, event):
        if self.worker:
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)
