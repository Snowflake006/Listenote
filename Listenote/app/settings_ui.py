from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QDialogButtonBox
from updates import VERSION_LABEL, REPOSITORY_URL


class AboutDialog(QDialog):
    def __init__(self, window, parent=None):
        super().__init__(parent or window)
        self.setWindowTitle('关于听课 · 检测更新')
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.setSpacing(18)
        layout.setAlignment(Qt.AlignTop)
        title = QLabel('听课 Listenote')
        title.setObjectName('setupTitle')
        layout.addWidget(title)
        layout.addWidget(QLabel('当前版本：' + VERSION_LABEL))
        info = QLabel('本地转写 · 简体中文 · 可选 AI 总结\n'
                      '本地千问支持国内下载；远程 AI 仅在你主动确认后发送原文。\n'
                           '启动时及每小时检测正式版本，发现新版本会在软件内提示。')
        info.setWordWrap(True)
        layout.addWidget(info)
        link = QLabel(f'GitHub 仓库：<a href="{REPOSITORY_URL}">{REPOSITORY_URL}</a>')
        link.setOpenExternalLinks(True)
        link.setWordWrap(True)
        layout.addWidget(link)
        releases = QLabel(f'<a href="{REPOSITORY_URL}/releases/latest">打开 GitHub 正式版发布页 ↗</a>')
        releases.setOpenExternalLinks(True)
        layout.addWidget(releases)
        self.state = QLabel(window.update_message)
        self.state.setWordWrap(True)
        window.update_status.connect(self.state.setText)
        layout.addWidget(self.state)
        check = QPushButton('检测更新')
        check.setObjectName('primary')
        check.clicked.connect(lambda: window.check_updates(manual=True))
        layout.addWidget(check)
        help_text = QLabel('转写原文：逐段显示识别结果。\n'
                           '我的笔记：上方显示转写实时预览，下方可独立记录笔记。\n'
                           'AI 总结：基于课堂原文生成，请核对重要内容。')
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.button(QDialogButtonBox.Close).setText('关闭')
        close.rejected.connect(self.reject)
        layout.addWidget(close)


# Settings are child widgets in the main stack, never a second top-level window.
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QListWidget, QStackedWidget,
                               QScrollArea, QFrame)
from motion import AnimatedStack
from ai_ui import AISettingsDialog
from resources_ui import SpeechSetupDialog
from ui_components import line_icon, AppleComboBox
from PySide6.QtWidgets import QListWidgetItem


class InlineAISettings(AISettingsDialog):
    def __init__(self, window, data):
        super().__init__(window.ai_config, window.ai_key, window, data=data)
        self.owner = window

    def done(self, result):
        if result == QDialog.Accepted:
            self.owner.persist_ai_settings(self)
        else:
            # Revert unsaved fields by rebuilding this detail pane next visit.
            self.owner.settings_page.reset_ai = True
            self.owner.return_to_classroom()


class InlineSpeechSettings(SpeechSetupDialog):
    def done(self, result):
        if result == QDialog.Accepted:
            self.status.setText('✓ 语音模型已准备好，可以返回课堂开始转写。')
        else:
            self.parent_page.owner.return_to_classroom()


class InlineAbout(AboutDialog):
    def done(self, result):
        self.owner.return_to_classroom()


class SettingsPage(QWidget):
    def __init__(self, window, data):
        super().__init__()
        self.owner, self.data = window, data
        self.panels = {}; self.reset_ai = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 10, 26, 20)
        header = QHBoxLayout()
        title = QLabel('设置');title.setObjectName('settingsHeading')
        header.addWidget(title);header.addStretch()
        back = QPushButton('‹  返回课堂');back.clicked.connect(window.return_to_classroom)
        header.addWidget(back);layout.addLayout(header)
        self.message = QLabel('按你的习惯，让每一堂课更有条理。')
        self.message.setObjectName('muted');layout.addWidget(self.message)
        self.section_order=(3,0,1,2)
        sections=[('all','界面设置'),('ai','AI 模型设置'),('speech','语音模型与下载'),('about','关于与使用说明')]
        self.section_picker=AppleComboBox();self.section_picker.addItems([name for _,name in sections])
        self.section_picker.currentIndexChanged.connect(self.select_row);self.section_picker.hide()
        layout.addWidget(self.section_picker)
        body = QHBoxLayout();body.setSpacing(18)
        self.navigation = QListWidget();self.navigation.setObjectName('settingsNav')
        self.navigation.setFixedWidth(176)
        for kind,name in sections:
            self.navigation.addItem(QListWidgetItem(line_icon(kind),name))
        self.navigation.currentRowChanged.connect(self.select_row)
        body.addWidget(self.navigation)
        self.details = AnimatedStack();body.addWidget(self.details,1)
        layout.addLayout(body,1)

    def set_compact(self, compact):
        self.navigation.setVisible(not compact)
        self.section_picker.setVisible(compact)
        self.layout().setContentsMargins(16 if compact else 26,10,16 if compact else 26,20)

    def busy(self):
        return any(getattr(panel,'worker',None) is not None for panel in self.panels.values())

    def select_row(self,row):
        if 0<=row<len(self.section_order):self.open_section(self.section_order[row])

    def open_section(self, index=0):
        current=self.details.currentWidget()
        if self.busy() and current.widget() is not self.panels.get(index, None):
            self.message.setText('请先停止当前模型任务，再切换设置。')
            self.navigation.blockSignals(True)
            self.navigation.setCurrentRow(self.section_order.index(next(k for k,v in self.panels.items() if v is current.widget())))
            self.navigation.blockSignals(False)
            self.section_picker.blockSignals(True);self.section_picker.setCurrentIndex(self.navigation.currentRow());self.section_picker.blockSignals(False);return
        if index==0 and self.reset_ai and not self.busy():
            old=self.panels.pop(0,None)
            if old:
                scroll=old.parentWidget().parentWidget();self.details.removeWidget(scroll);scroll.deleteLater()
            self.reset_ai=False
        if index not in self.panels:
            if index==0:panel=InlineAISettings(self.owner,self.data)
            elif index==1:
                panel=InlineSpeechSettings(self.data,self.owner);panel.parent_page=self
            elif index==3:
                panel=QWidget();box=QVBoxLayout(panel);box.setAlignment(Qt.AlignTop)
                box.addWidget(QLabel('界面设置'));box.addWidget(QLabel('主题 · 更改后立即生效'))
                picker=AppleComboBox()
                for label,key in [('亮','light'),('暗','dark'),('跟随系统','system')]:picker.addItem(label,key)
                picker.setCurrentIndex(picker.findData(self.owner.appearance.mode))
                picker.currentIndexChanged.connect(lambda _:self.owner.appearance.set_mode(picker.currentData()))
                box.addWidget(picker)
            else:
                panel=InlineAbout(self.owner);panel.owner=self.owner
            panel.setWindowFlags(Qt.Widget)
            panel.setMinimumWidth(0);panel.setObjectName('settingsDetail')
            panel.layout().setContentsMargins(20,20,20,20)
            scroll=QScrollArea();scroll.setObjectName('settingsScroll');scroll.setFrameShape(QFrame.NoFrame)
            scroll.setWidgetResizable(True);scroll.setWidget(panel)
            self.details.addWidget(scroll);self.panels[index]=panel
        panel=self.panels[index]
        if index in (0,1):panel.setEnabled(not self.owner.job and not self.owner.rec)
        scroll=panel.parentWidget().parentWidget()
        self.details.setCurrentWidget(scroll)
        row=self.section_order.index(index)
        self.navigation.blockSignals(True);self.navigation.setCurrentRow(row);self.navigation.blockSignals(False)
        self.section_picker.blockSignals(True);self.section_picker.setCurrentIndex(row);self.section_picker.blockSignals(False)
        self.message.setText('任务结束后可修改模型设置。' if (self.owner.job or self.owner.rec) and index in (0,1) else '按你的习惯，让每一堂课更有条理。')
