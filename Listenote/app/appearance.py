import json
from PySide6.QtCore import QObject, QTimer, Signal, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication
from ui_theme import STYLE, dark_style

class Appearance(QObject):
    changed=Signal()
    def __init__(self,window,data):
        super().__init__(window);self.window=window;self.path=data/'settings'/'appearance.json'
        try:self.mode=json.loads(self.path.read_text('utf8')).get('theme','system')
        except (OSError,ValueError,AttributeError):self.mode='system'
        if self.mode not in ('light','dark','system'):self.mode='system'
        self.dark=None;self.refresh()
        QApplication.styleHints().colorSchemeChanged.connect(lambda _:self.refresh())
        self.timer=QTimer(self);self.timer.timeout.connect(self.refresh);self.timer.start(2000)
    def set_mode(self,mode):
        if mode not in ('light','dark','system'):return
        self.mode=mode;self.path.parent.mkdir(parents=True,exist_ok=True)
        self.path.write_text(json.dumps({'theme':mode}),'utf8');self.refresh()
    def refresh(self):
        dark=self.mode=='dark'
        if self.mode=='system':
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
                    dark=not bool(winreg.QueryValueEx(key,'AppsUseLightTheme')[0])
            except (ImportError,OSError):dark=QApplication.styleHints().colorScheme()==Qt.ColorScheme.Dark
        if dark==self.dark:return
        self.dark=dark;app=QApplication.instance();app.setProperty('darkTheme',dark)
        style=STYLE
        if dark:style=dark_style()
        app.setStyleSheet(style)
        palette=QPalette()
        for role,color in [(QPalette.Window,'#111b2a' if dark else '#f2f5fb'),
                           (QPalette.Base,'#202b3e' if dark else '#f8faff'),
                           (QPalette.Button,'#28364e' if dark else '#f8faff'),
                           (QPalette.WindowText,'#e7edfa' if dark else '#26334b'),
                           (QPalette.Text,'#e7edfa' if dark else '#26334b'),
                           (QPalette.ButtonText,'#e7edfa' if dark else '#26334b'),
                           (QPalette.Highlight,'#3d5681' if dark else '#d8e4fc'),
                           (QPalette.HighlightedText,'#fff' if dark else '#26334b')]:palette.setColor(role,QColor(color))
        app.setPalette(palette)
        from window_chrome import set_dark_chrome
        set_dark_chrome(self.window,dark)
        self.window.centralWidget().update();self.changed.emit()
