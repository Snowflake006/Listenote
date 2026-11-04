"""Desktop materials based on the ddmer admin's shared glass palette."""
from pathlib import Path
from PySide6.QtGui import QColor, QPainter, QRadialGradient
from PySide6.QtWidgets import QWidget


class GlassBackdrop(QWidget):
    """Static soft wallpaper under translucent panels, with no live blur cost."""
    def paintEvent(self, event):
        from PySide6.QtWidgets import QApplication
        dark=bool(QApplication.instance().property('darkTheme'))
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#111b2a' if dark else '#f2f5fb'))
        for x, y, radius, color in [(.05, .05, .75, '#dbe8ff'),
                                     (.95, .35, .65, '#e8ddfa'),
                                     (.40, 1., .65, '#d8eeef')]:
            gradient = QRadialGradient(self.width()*x, self.height()*y,
                                       max(self.width(), self.height())*radius)
            gradient.setColorAt(0, QColor({'#dbe8ff':'#1e3654','#e8ddfa':'#302747','#d8eeef':'#183b40'}.get(color,color) if dark else color))
            gradient.setColorAt(1, QColor(242, 245, 251, 0))
            painter.fillRect(self.rect(), gradient)


ARROW = (Path(__file__).with_name('chevron.svg')).as_posix()

def dark_style():
    import re
    colors={
        '#26334b':'#e7edfa','#f2f5fb':'#111b2a','#f5f8fe':'#202b3e',
        '#69778c':'#a3b0c7','#4a5d78':'#d0dbee','#e6edfc':'#2d405e',
        '#d0ddf6':'#425a7b','#dae3f2':'#3b4c66','#354866':'#dbe6f9',
        '#64748b':'#aab9d0','#4567a1':'#bad0ff','#eef3fe':'#2a3a53',
        '#cbdaf6':'#4a6083','#dce7fc':'#334b70','#e7ecf4':'#26334b',
        '#a0abba':'#738198','#e0e7f1':'#35435a','#8997ad':'#a1b1ca',
        '#7d8ba3':'#a7b7d1','#7d8ba1':'#a3b0c7','#6884b2':'#b1c8ef',
        '#f8faff':'#26364e','#425778':'#cfddf4','#e1eafb':'#344a70',
        '#486aa7':'#c4d8ff','#e2e9f5':'#2d3d55','#8a98ad':'#9bacc5',
        '#5478b7':'#b9d0ff','#c4cfe0':'#4c607c','#3e5579':'#d6e4fc',
        '#e1e8f4':'#354760','#7185a3':'#afc1dd','#edf3fe':'#2c3f5c',
        '#c5d7f5':'#50698e','#adc5ee':'#6e8fbb','#3d6099':'#c6daff',
        '#d8e4fc':'#3d5681'}
    style=re.sub(r'#[0-9a-fA-F]{6}\b',lambda m:colors.get(m.group().lower(),m.group()),STYLE)
    return re.sub(r'rgba\(255,255,255,(\d+)\)',r'rgba(30,39,58,\1)',style)
STYLE = r'''
QWidget {font-family:"Segoe UI","Microsoft YaHei UI","Noto Sans SC";font-size:13px;color:#26334b;background:transparent;}
QMainWindow {background:#f2f5fb;}
QDialog,QMessageBox {background:#f5f8fe;}
QLabel {background:transparent;}
QScrollArea {background:transparent;border:0;}
QScrollArea#sidebarScroll {background:rgba(255,255,255,145);border:0;border-right:1px solid rgba(255,255,255,210);}
QFrame#sidebar {background:transparent;color:#69778c;}
QLabel#brand {font-size:28px;font-weight:700;color:#26334b;}
QFrame#sidebar QPushButton {background:rgba(255,255,255,150);border:1px solid rgba(255,255,255,220);border-radius:10px;color:#4a5d78;padding:10px 12px;text-align:left;}
QFrame#sidebar QPushButton#addSubject {padding:0;font-size:19px;}
QFrame#sidebar QPushButton:hover {background:#e6edfc;border-color:#d0ddf6;}
QFrame#sidebar QLineEdit {background:rgba(255,255,255,155);border:1px solid #dae3f2;color:#354866;}
QFrame#sidebar QListWidget {background:transparent;border:0;outline:0;}
QFrame#sidebar QListWidget::item {padding:10px 8px;border-radius:10px;color:#64748b;}
QFrame#sidebar QListWidget::item:hover {background:rgba(91,135,235,16);}
QFrame#sidebar QListWidget::item:selected {background:rgba(91,135,235,28);color:#4567a1;}
QFrame#sidebar QListWidget#folders::item {padding:7px 8px;}
QPushButton {background:rgba(255,255,255,190);border:1px solid rgba(255,255,255,235);border-radius:10px;padding:9px 14px;color:#4a5d78;}
QPushButton:hover {background:#eef3fe;border-color:#cbdaf6;}
QPushButton:pressed {background:#dce7fc;}
QPushButton#exportButton {padding-right:30px;}
QPushButton#exportButton::menu-indicator {image:url("__ARROW__");subcontrol-origin:padding;subcontrol-position:center right;right:10px;width:11px;height:7px;}
QPushButton#primary,QFrame#sidebar QPushButton#primary {background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #7395e8,stop:1 #847bdc);color:#fff;border:1px solid #829bea;font-weight:600;}
QPushButton#primary:hover,QFrame#sidebar QPushButton#primary:hover {background:#7892df;border-color:#91a9ed;}
QPushButton:disabled {background:#e7ecf4;color:#a0abba;border-color:#e0e7f1;}
QWidget#titleBar {background:transparent;}
QLabel#chromeLabel {font-size:11px;color:#8997ad;}
QWidget#titleBar QPushButton {border:0;background:transparent;border-radius:8px;font-size:19px;color:#7d8ba3;padding:0;}
QWidget#titleBar QPushButton[nativeHover="true"],QWidget#titleBar QPushButton:hover {background:rgba(91,135,235,24);color:#4567a1;}
QWidget#titleBar QPushButton#closeWindow:hover {background:#fce6ea;color:#cc5067;}
QWidget#titleBar QPushButton#pinWindow:checked {background:rgba(91,135,235,38);border:1px solid #adc5ee;}
QLineEdit {background:rgba(255,255,255,190);border:1px solid #dae3f2;border-radius:10px;padding:8px 10px;selection-background-color:#d8e4fc;}
QLineEdit:focus {border-color:#9db6ec;}
QLineEdit#title {font-size:25px;font-weight:700;border:0;background:transparent;padding:2px 0;color:#26334b;}
QLabel#muted {color:#7d8ba1;font-size:12px;}
QLabel#badge {color:#6884b2;font-size:10px;background:rgba(255,255,255,150);border:1px solid rgba(255,255,255,220);border-radius:8px;padding:5px 8px;}
QFrame#hero {background:rgba(255,255,255,158);border:1px solid rgba(255,255,255,225);border-radius:18px;}
QFrame#hero QLabel,QFrame#hero WaveArt {background:transparent;}
QComboBox {background:rgba(255,255,255,195);border:1px solid #dae3f2;border-radius:10px;padding:8px 28px 8px 12px;min-height:19px;}
QComboBox:hover {border-color:#b7cbee;background:#f8faff;}
QComboBox:focus {border-color:#9db6ec;}
QComboBox::drop-down {subcontrol-origin:padding;subcontrol-position:top right;width:25px;border:0;background:transparent;}
QComboBox::down-arrow {image:url("__ARROW__");width:11px;height:7px;}
QComboBox QAbstractItemView {background:#f5f8fe;color:#425778;border:0;border-radius:10px;padding:5px;outline:0;selection-background-color:#e1eafb;selection-color:#486aa7;}
QComboBox QAbstractItemView::item {min-height:29px;padding:5px 12px;border:0;border-radius:8px;}
QComboBox QAbstractItemView::item:hover,QComboBox QAbstractItemView::item:selected {background:#e1eafb;color:#486aa7;}
QProgressBar {background:#e2e9f5;border:0;border-radius:3px;}
QProgressBar::chunk {background:#8da9e6;border-radius:3px;}
QTabBar {background:transparent;}
QTabBar::tab {padding:10px 12px;color:#8a98ad;border-bottom:2px solid transparent;}
QTabBar::tab:selected {color:#5478b7;border-bottom:2px solid #8da9e6;}
QTabBar::tab:hover {color:#5478b7;}
QPlainTextEdit {background:rgba(255,255,255,200);border:1px solid rgba(255,255,255,230);border-radius:14px;padding:16px;font-size:14px;selection-background-color:#d8e4fc;}
QScrollBar:vertical {width:7px;background:transparent;margin:3px 0;}
QScrollBar::handle:vertical {background:#c4cfe0;border-radius:3px;min-height:30px;}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {height:0;}
QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical {background:transparent;}
QLabel#setupTitle {font-size:19px;font-weight:600;color:#3e5579;padding:2px 0 6px;}
QLabel#settingsHeading {font-size:27px;font-weight:700;color:#26334b;}
QListWidget#settingsNav {background:rgba(255,255,255,125);border:1px solid rgba(255,255,255,215);border-radius:16px;padding:7px;outline:0;}
QListWidget#settingsNav::item {padding:15px 8px;border-radius:10px;margin:3px 0;color:#69778c;}
QListWidget#settingsNav::item:selected {background:rgba(91,135,235,28);color:#4567a1;}
QListWidget#settingsNav::item:hover {background:rgba(91,135,235,16);}
QScrollArea#settingsScroll {background:rgba(255,255,255,185);border:1px solid rgba(255,255,255,230);border-radius:18px;}
QWidget#settingsDetail {background:transparent;}
QGroupBox {background:rgba(255,255,255,100);border:1px solid #e1e8f4;border-radius:12px;margin-top:12px;padding:14px 10px 8px;}
QGroupBox::title {subcontrol-origin:margin;left:12px;padding:0 5px;color:#7185a3;}
QMenu {background:#f5f8fe;border:0;border-radius:18px;padding:9px;}
QMenu::item {padding:9px 18px;border-radius:8px;color:#425778;}
QMenu::item:selected {background:#e1eafb;color:#486aa7;}
QSplitter::handle {background:rgba(152,174,209,60);height:4px;}
QListWidget#courseList {background:transparent;border:0;outline:0;}
QListWidget#courseList::item {background:rgba(255,255,255,185);border:1px solid rgba(255,255,255,230);border-radius:14px;margin:0 0 10px;padding:20px 18px;color:#425778;}
QListWidget#courseList::item:hover {background:#edf3fe;border-color:#c5d7f5;}
QListWidget#courseList::item:selected {background:#e1eafb;border-color:#adc5ee;color:#3d6099;}
'''.replace('__ARROW__',ARROW)
