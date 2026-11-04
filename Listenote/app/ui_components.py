"""Shared desktop chrome and softly styled selection controls."""
from PySide6.QtCore import Qt, QRectF, QByteArray, QObject, QEvent, QPoint
from PySide6.QtGui import QPainterPath, QRegion, QIcon, QPixmap, QPainter, QColor, QLinearGradient
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QComboBox, QListView, QWidget, QHBoxLayout, QLabel, QPushButton, QFrame, QMenu
from window_chrome import remove_popup_border, set_dark_chrome

POPUP_RADIUS = 18


def round_popup(popup):
    """Clip the actual top-level surface, including the native square corners."""
    path = QPainterPath()
    radius = min(POPUP_RADIUS, popup.height()/2, popup.width()/2)
    path.addRoundedRect(QRectF(popup.rect()), radius, radius)
    if popup.testAttribute(Qt.WA_TranslucentBackground):popup.clearMask()
    else:popup.setMask(QRegion(path.toFillPolygon().toPolygon()))
    remove_popup_border(popup)


class GlassPopupSurface(QWidget):
    def __init__(self,popup):
        super().__init__(popup);self.image=QPixmap()
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setStyleSheet('background:transparent;border:0;')
    def paintEvent(self,event):
        painter=QPainter(self)
        paint_glass(painter,self.rect(),self.image)


def paint_glass(painter,rect,image):
        from PySide6.QtWidgets import QApplication
        dark=bool(QApplication.instance().property('darkTheme'))
        painter.setRenderHint(QPainter.Antialiasing)
        path=QPainterPath();path.addRoundedRect(QRectF(rect).adjusted(.75,.75,-.75,-.75),18,18)
        painter.setClipPath(path)
        if not image.isNull():painter.drawPixmap(rect,image)
        painter.fillPath(path,QColor(30,41,61,220) if dark else QColor(248,251,255,205))
        sheen=QLinearGradient(0,0,rect.width(),rect.height())
        sheen.setColorAt(0,QColor(255,255,255,32 if dark else 100));sheen.setColorAt(1,QColor(179,204,255,12))
        painter.fillPath(path,sheen);painter.setClipping(False)
        painter.setPen(QColor(170,197,238,65) if dark else QColor(255,255,255,220))
        painter.drawPath(path)


class GlassMenu(QMenu):
    """The same glass material for export and context menus."""
    def __init__(self,parent=None):
        super().__init__(parent);self.backdrop=QPixmap()
        self.setWindowFlag(Qt.FramelessWindowHint,True)
        self.setWindowFlag(Qt.NoDropShadowWindowHint,True)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet('QMenu {background:transparent;border:0;padding:8px;}')
    def showEvent(self,event):
        host=self.parentWidget().window() if self.parentWidget() else None
        if host:
            image=host.grab();origin=host.mapToGlobal(QPoint(0,0));area=self.geometry().translated(-origin)
            scale=image.devicePixelRatioF()
            crop=image.copy(round(area.x()*scale),round(area.y()*scale),round(area.width()*scale),round(area.height()*scale))
            if not crop.isNull():
                self.backdrop=crop.scaled(max(1,crop.width()//18),max(1,crop.height()//18),Qt.IgnoreAspectRatio,Qt.SmoothTransformation).scaled(crop.size(),Qt.IgnoreAspectRatio,Qt.SmoothTransformation)
        super().showEvent(event);round_popup(self)
    def paintEvent(self,event):
        painter=QPainter(self);paint_glass(painter,self.rect(),self.backdrop);painter.end()
        super().paintEvent(event)


class PopupShape(QObject):
    def eventFilter(self, widget, event):
        if event.type() in (QEvent.Show, QEvent.Resize):
            round_popup(widget)
            surface=getattr(widget,'glass_surface',None)
            if surface:surface.setGeometry(widget.rect());surface.lower()
        return False


def line_icon(kind, color='#8b9fbe'):
    paths = {
        'menu': '<path d="M4 6h16M4 12h16M4 18h16"/>',
        'folder': '<path d="M3 7h6l2 2h10v11H3z"/><path d="M3 7V5h7l2 2h8v2"/>',
        'all': '<rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><rect x="14" y="14" width="6" height="6" rx="1"/>',
        'ai': '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z"/>',
        'speech': '<path d="M4 10v4m4-8v12m4-15v18m4-15v12m4-8v4"/>',
        'about': '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v1"/>',
        'pin': '<path d="m8 3 8 0-2 6 4 5H6l4-5zM12 14v7"/>',
    }
    svg=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">{paths[kind]}</svg>'
    pixmap=QPixmap(48,48);pixmap.fill(Qt.transparent)
    painter=QPainter(pixmap);QSvgRenderer(QByteArray(svg.encode())).render(painter);painter.end()
    return QIcon(pixmap)


class AppleComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setView(QListView())
        self.setMaxVisibleItems(9)
        self.view().setSpacing(3)
        self.view().setTextElideMode(Qt.ElideRight)
        self.view().setFrameShape(QFrame.NoFrame)
        popup = self.view().window()
        self.popup_frame=popup
        popup.setWindowFlag(Qt.FramelessWindowHint, True)
        popup.setWindowFlag(Qt.NoDropShadowWindowHint,True)
        popup.setAttribute(Qt.WA_TranslucentBackground)
        popup.glass_surface=GlassPopupSurface(popup)
        self.popup_shape = PopupShape(popup)
        popup.installEventFilter(self.popup_shape)

    def showPopup(self):
        host=self.window();backdrop=host.grab();origin=host.mapToGlobal(QPoint(0,0))
        super().showPopup()
        popup = self.view().window()
        # Style just the outer popup; a generic QFrame selector also outlines
        # the view, viewport and scroll containers, producing nested boxes.
        popup.setObjectName('comboPopup')
        popup.setFrameShape(QFrame.NoFrame)
        popup.setContentsMargins(0,0,0,0)
        popup.setStyleSheet('''
            QFrame#comboPopup {background:transparent;border:0;}
            QFrame#comboPopup QAbstractItemView {background:transparent;border:0;outline:0;padding:8px;}
            QFrame#comboPopup QAbstractItemView QWidget {background:transparent;border:0;}
        ''')
        scale=backdrop.devicePixelRatioF()
        area=popup.geometry().translated(-origin)
        crop=backdrop.copy(round(area.x()*scale),round(area.y()*scale),round(area.width()*scale),round(area.height()*scale))
        if not crop.isNull():
            blurred=crop.scaled(max(1,crop.width()//18),max(1,crop.height()//18),Qt.IgnoreAspectRatio,Qt.SmoothTransformation)
            popup.glass_surface.image=blurred.scaled(crop.size(),Qt.IgnoreAspectRatio,Qt.SmoothTransformation)
        popup.glass_surface.setGeometry(popup.rect());popup.glass_surface.lower();popup.glass_surface.show()
        from PySide6.QtWidgets import QApplication
        set_dark_chrome(popup,bool(QApplication.instance().property('darkTheme')))
        popup.glass_surface.update()
        round_popup(popup)


class TitleBar(QWidget):
    def __init__(self, window):
        super().__init__()
        self.owner = window
        self.setObjectName('titleBar')
        self.setFixedHeight(46)
        row = QHBoxLayout(self)
        row.setContentsMargins(27, 0, 10, 0)
        label = QLabel('听课  /  让知识留下来')
        label.setObjectName('chromeLabel')
        row.addWidget(label)
        row.addStretch()
        pin=QPushButton();pin.setIcon(line_icon('pin'));pin.setObjectName('pinWindow');pin.setCheckable(True);pin.setFixedSize(40,30)
        pin.setToolTip('保持窗口在最前');pin.setAccessibleName('保持窗口在最前')
        pin.toggled.connect(window.set_pinned);row.addWidget(pin);self.pin_button=pin
        for name, text, hint, action in [
            ('minimize', '−', '最小化', window.motion.minimize),
            ('maximize', '□', '最大化 / 还原', self.toggle_maximized),
            ('closeWindow', '×', '关闭', window.close),
        ]:
            control = QPushButton(text)
            control.setObjectName(name)
            control.setAccessibleName(hint)
            control.setToolTip(hint)
            control.setFixedSize(40, 30)
            control.clicked.connect(action)
            row.addWidget(control)
            if name == 'maximize':
                self.maximize_button = control
        self.menu_button = QPushButton();self.menu_button.setIcon(line_icon('menu'))
        self.menu_button.setAccessibleName('显示或隐藏课堂侧栏')
        self.menu_button.setFixedSize(34,30)
        self.menu_button.clicked.connect(window.toggle_sidebar)
        self.menu_button.hide()
        row.insertWidget(0,self.menu_button)
        self.setCursor(Qt.ArrowCursor)

    def set_native_hover(self, hovered):
        control = self.maximize_button
        if bool(control.property('nativeHover')) != hovered:
            control.setProperty('nativeHover',hovered)
            control.style().unpolish(control);control.style().polish(control)
            control.update()

    def toggle_maximized(self):
        self.owner.motion.toggle_maximized()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.owner.windowHandle().startSystemMove()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.toggle_maximized()
