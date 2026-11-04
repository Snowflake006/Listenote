"""Shared, interruptible Qt motion. No delays are added to business actions."""
import os
import sys
from functools import lru_cache

from PySide6.QtCore import (QObject, QEvent, Qt, QRect, QRectF, QPoint, QEasingCurve,
                            QVariantAnimation, QPropertyAnimation, QTimer)
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QWidget, QAbstractButton, QComboBox,
                               QLineEdit, QPlainTextEdit, QAbstractItemView,
                               QTabBar, QMenu, QDialog, QStackedWidget)


@lru_cache(maxsize=1)
def reduced_motion():
    if QApplication.platformName() in ('offscreen', 'minimal'):
        return True
    if os.environ.get('LISTENOTE_REDUCED_MOTION', '').lower() in ('1', 'true', 'yes'):
        return True
    if sys.platform == 'win32':
        try:
            import ctypes
            enabled = ctypes.c_int(1)
            if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0):
                return not enabled.value
        except (AttributeError, OSError):
            pass
    return False


def tween(parent, start, end, duration, update, finished=None):
    animation = QVariantAnimation(parent)
    animation.setDuration(duration)
    animation.setStartValue(start)
    animation.setEndValue(end)
    animation.setEasingCurve(QEasingCurve.OutCubic)
    animation.valueChanged.connect(update)
    if finished:
        animation.finished.connect(finished)
    animation.finished.connect(animation.deleteLater)
    animation.start()
    return animation


class TransitionCover(QWidget):
    """Fade the old pixels over live new content, keeping text fully readable."""
    def __init__(self, target, pixmap):
        super().__init__(target)
        self.pixmap, self.progress = pixmap, 0.
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setStyleSheet('background:transparent;border:0;')
        self.setGeometry(target.rect())
        self.show()
        self.raise_()
        self.animation = tween(self, 0., 1., 220, self.advance, self.deleteLater)

    def advance(self, value):
        self.progress = value
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setOpacity(1. - self.progress)
        painter.drawPixmap(QPoint(0, 0), self.pixmap)


def capture(target):
    previous = getattr(target, '_transition_cover', None)
    if previous is not None:
        previous.animation.stop()
        previous.hide()
        previous.deleteLater()
        target._transition_cover = None
    if reduced_motion() or not target.isVisible() or target.width() < 1:
        return None
    return target.grab()


def reveal(target, pixmap):
    if pixmap is not None and target.isVisible():
        cover = TransitionCover(target, pixmap)
        target._transition_cover = cover
        # Clear the Python reference before deferred C++ destruction.
        cover.animation.finished.connect(lambda: setattr(target, '_transition_cover', None))


class AnimatedStack(QStackedWidget):
    def setCurrentIndex(self, index):
        if index == self.currentIndex() or not 0 <= index < self.count():
            return super().setCurrentIndex(index)
        pixmap = capture(self)
        super().setCurrentIndex(index)
        reveal(self, pixmap)

    def setCurrentWidget(self, widget):
        self.setCurrentIndex(self.indexOf(widget))


class InteractionGlow(QWidget):
    """A paint-only overlay: never moves controls or steals input/focus."""
    def __init__(self, target):
        super().__init__(target)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setStyleSheet('background:transparent;border:0;')
        self.hover = self.focus = self.ripple = 0.
        self.point = QPoint()
        self.highlight = QRectF()
        self.animations = {}
        self.setGeometry(target.rect())
        self.show()
        self.raise_()

    def animate(self, key, value, duration=150):
        if key not in self.animations and getattr(self, key) == value:
            return
        old = self.animations.pop(key, None)
        if old is not None:
            old.stop()
            old.deleteLater()
        def update(v):
            setattr(self, key, v)
            self.update()
        self.animations[key] = tween(self, getattr(self, key), value, duration, update)
        self.animations[key].finished.connect(lambda: self.animations.pop(key, None))

    def pulse(self, point):
        self.point = point
        self.ripple = 0.
        self.animate('ripple', 1., 360)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.highlight if not self.highlight.isEmpty() else QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setClipRect(self.rect())
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(91, 135, 235, round(22 * self.hover)))
        painter.drawRoundedRect(rect, 6, 6)
        if self.focus:
            painter.setPen(QPen(QColor(116, 151, 218, round(170 * self.focus)), 1.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect, 6, 6)
        if 0 < self.ripple < 1:
            painter.setClipRect(rect)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(116, 151, 218, round(48 * (1 - self.ripple))))
            radius = max(rect.width(), rect.height()) * self.ripple
            painter.drawEllipse(self.point, radius, radius)


class MotionSystem(QObject):
    def __init__(self, app):
        super().__init__(app)
        app.installEventFilter(self)

    def glow(self, widget):
        glow = getattr(widget, '_motion_glow', None)
        if glow is None:
            # Creating/showing a child can synchronously send FocusIn/Enter
            # back to an editable combo's line edit. Guard before construction.
            widget._motion_creating = True
            try:
                glow = InteractionGlow(widget)
                widget._motion_glow = glow
            finally:
                widget._motion_creating = False
        return glow

    def popup_open(self, widget):
        old = getattr(widget, '_popup_fade', None)
        if old:
            old.stop()
            old.deleteLater()
        widget.setWindowOpacity(0.)
        fade = QPropertyAnimation(widget, b'windowOpacity', widget)
        widget._popup_fade = fade
        fade.setDuration(150)
        fade.setStartValue(0.)
        fade.setEndValue(1.)
        fade.start()

    def eventFilter(self, widget, event):
        if not isinstance(widget, QWidget):
            return False
        # Shape is independent of animation/accessibility preferences.
        if isinstance(widget, QMenu) and event.type() in (QEvent.Show, QEvent.Resize):
            from ui_components import round_popup
            round_popup(widget)
        if reduced_motion() or getattr(widget, '_motion_creating', False):
            return False
        kind = event.type()
        if isinstance(widget, (InteractionGlow, TransitionCover)):
            return False
        popup = widget.isWindow() and (isinstance(widget, QMenu) or
                    widget.windowType() == Qt.Popup or isinstance(widget, QDialog))
        if popup and kind == QEvent.Show:
            self.popup_open(widget)
        elif popup and kind == QEvent.Hide:
            fade = getattr(widget, '_popup_fade', None)
            if fade:
                fade.stop()
            widget.setWindowOpacity(1.)
        interactive = isinstance(widget, (QAbstractButton, QComboBox, QLineEdit, QPlainTextEdit, QTabBar))
        view = widget.parentWidget() if isinstance(widget.parentWidget(), QAbstractItemView) else None
        # Item views already paint hover/selection with their styled delegate.
        # A viewport overlay includes item margins and creates a second block
        # beneath course cards. Keep all item feedback inside the delegate.
        viewport = False
        if not interactive and not viewport:
            return False
        if kind == QEvent.Show and viewport:
            widget.setMouseTracking(True)
        if kind == QEvent.Resize:
            glow = getattr(widget, '_motion_glow', None)
            if glow:
                glow.setGeometry(widget.rect())
        elif kind in (QEvent.Enter, QEvent.FocusIn) and widget.isEnabled():
            self.glow(widget).animate('focus' if kind == QEvent.FocusIn else 'hover', 1.)
        elif kind in (QEvent.Leave, QEvent.FocusOut, QEvent.EnabledChange):
            glow = getattr(widget, '_motion_glow', None)
            if glow:
                glow.animate('focus' if kind == QEvent.FocusOut else 'hover', 0.)
        elif kind in (QEvent.MouseMove, QEvent.MouseButtonPress) and widget.isEnabled():
            glow = self.glow(widget)
            pos = event.position().toPoint()
            if viewport:
                index = view.indexAt(pos)
                glow.highlight = QRectF(view.visualRect(index)) if index.isValid() else QRectF()
                glow.animate('hover', 1. if index.isValid() else 0.)
            elif isinstance(widget, QTabBar):
                index = widget.tabAt(pos)
                glow.highlight = QRectF(widget.tabRect(index)) if index >= 0 else QRectF()
            if kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                glow.pulse(pos)
        elif kind == QEvent.KeyPress and widget.isEnabled() and event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            if isinstance(widget, (QAbstractButton, QComboBox, QTabBar)) or viewport:
                self.glow(widget).pulse(widget.rect().center())
        return False


def install_motion():
    app = QApplication.instance()
    if not hasattr(app, '_listenote_motion'):
        app._listenote_motion = MotionSystem(app)


class WindowMotion(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.animation = None
        self.closing = False
        self.opened = False
        self.restoring = False
        self.normal_rect = None
        self.drawer_animation = None
        self.drawer_open = False

    def drawer(self, visible):
        drawer = self.window.sidebar_container
        self.drawer_open = visible
        if self.drawer_animation:
            self.drawer_animation.stop()
            self.drawer_animation.deleteLater()
            self.drawer_animation = None
        if reduced_motion():
            drawer.setVisible(visible)
            return
        end = QRect(0 if visible else -drawer.width(), 46, drawer.width(),
                    self.window.centralWidget().height() - 46)
        start = drawer.geometry()
        if visible and not drawer.isVisible():
            start.moveLeft(-drawer.width())
        drawer.setGeometry(start)
        drawer.show()
        drawer.raise_()
        def finish():
            drawer.setVisible(visible)
            self.drawer_animation = None
        self.drawer_animation = tween(self, start, end, 220, drawer.setGeometry, finish)

    def stop(self):
        if self.animation:
            self.animation.stop()
            self.animation.deleteLater()
            self.animation = None

    def fade(self, start, end, duration, finished=None):
        self.stop()
        self.window.setWindowOpacity(start)
        if reduced_motion():
            self.window.setWindowOpacity(end)
            if finished:
                finished()
            return
        self.animation = tween(self, start, end, duration, self.window.setWindowOpacity, finished)
        self.animation.finished.connect(lambda: setattr(self, 'animation', None))

    def show(self):
        if not self.opened:
            self.opened = True
            self.fade(0., 1., 180)

    def minimize(self):
        if self.closing:
            return
        self.stop()
        from window_chrome import native_window_command
        if reduced_motion() or not native_window_command(self.window, 0xF020):
            self.window.setWindowOpacity(1.)
            self.window.showMinimized()

    def toggle_maximized(self):
        if self.closing:
            return
        self.stop()
        w = self.window
        from window_chrome import native_window_command
        command = 0xF120 if w.isMaximized() else 0xF030
        if reduced_motion() or not native_window_command(w, command):
            w.setWindowOpacity(1.)
            w.showNormal() if w.isMaximized() else w.showMaximized()

    def close(self):
        if self.closing:
            return True
        if reduced_motion() or not self.window.isVisible():
            return True
        self.closing = True
        self.fade(self.window.windowOpacity(), 0., 170, self.window.close)
        return False
