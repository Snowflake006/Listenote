"""Windows 11 compositor corners for the custom in-app title bar.

Use DWM rather than a window mask: masks prevent native rounded corners and
shadows. Older systems simply keep their normal window decorations.
https://learn.microsoft.com/windows/apps/desktop/modernize/ui/apply-rounded-corners
"""
import ctypes
import sys

from PySide6.QtGui import QGuiApplication

def set_dark_chrome(widget,dark):
    if sys.platform!='win32' or QGuiApplication.platformName()!='windows':return
    from ctypes import wintypes
    try:
        value=ctypes.c_int(bool(dark))
        ctypes.windll.dwmapi.DwmSetWindowAttribute(wintypes.HWND(int(widget.winId())),20,ctypes.byref(value),ctypes.sizeof(value))
    except (AttributeError,OSError):pass


def native_window_command(widget, command):
    """Dispatch caption actions through the Windows system-menu animation path."""
    if sys.platform != 'win32' or QGuiApplication.platformName() != 'windows':
        return False
    from ctypes import wintypes
    user = ctypes.windll.user32
    hwnd = wintypes.HWND(int(widget.winId()))
    # Qt opacity fades may leave WS_EX_LAYERED on an otherwise opaque window.
    # Return it to a regular compositor surface before caption transitions.
    widget.setWindowOpacity(1.)
    get_style = user.GetWindowLongPtrW
    get_style.argtypes = [wintypes.HWND, ctypes.c_int]
    get_style.restype = ctypes.c_ssize_t
    set_style = user.SetWindowLongPtrW
    set_style.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    set_style.restype = ctypes.c_ssize_t
    style = get_style(hwnd, -20)
    if style & 0x00080000:
        set_style(hwnd, -20, style & ~0x00080000)
        user.RedrawWindow(hwnd, None, None, 0x0485)
    enable_snap_layout(widget)
    try:
        disabled = ctypes.c_int(0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 3, ctypes.byref(disabled), ctypes.sizeof(disabled))
    except (AttributeError, OSError):
        pass
    post = user.PostMessageW
    post.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
    post.restype = wintypes.BOOL
    return bool(post(hwnd, 0x0112, command, 0))


def remove_popup_border(widget):
    if sys.platform != 'win32' or QGuiApplication.platformName() != 'windows':
        return
    from ctypes import wintypes
    try:
        color = wintypes.DWORD(0xFFFFFFFE)  # DWMWA_COLOR_NONE.
        ctypes.windll.dwmapi.DwmSetWindowAttribute(wintypes.HWND(int(widget.winId())),
                                                  34, ctypes.byref(color), ctypes.sizeof(color))
    except (AttributeError, OSError):
        pass


def enable_snap_layout(widget):
    """Keep native resize/maximize capabilities behind the drawn title bar."""
    if sys.platform != 'win32' or QGuiApplication.platformName() != 'windows':
        return False
    from ctypes import wintypes
    user = ctypes.windll.user32
    get_style = user.GetWindowLongPtrW
    get_style.argtypes = [wintypes.HWND, ctypes.c_int]
    get_style.restype = ctypes.c_ssize_t
    set_style = user.SetWindowLongPtrW
    set_style.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    set_style.restype = ctypes.c_ssize_t
    hwnd = wintypes.HWND(int(widget.winId()))
    style = get_style(hwnd, -16)
    # Retain WS_CAPTION as well as resize/system controls. WM_NCCALCSIZE
    # removes its visible frame while DWM keeps native window animations.
    wanted = style | 0x00CF0000
    if wanted != style:
        set_style(hwnd, -16, wanted)
        user.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0037)
    return True


def constrain_maximized_bounds(hwnd, address):
    """Use the target monitor's work area for button, drag-to-top and Snap."""
    from ctypes import wintypes
    class MinMaxInfo(ctypes.Structure):
        _fields_ = [(name, wintypes.POINT) for name in
                    ('reserved', 'max_size', 'max_position', 'min_track', 'max_track')]
    info = monitor_info(hwnd)
    if info is None:
        return
    bounds = MinMaxInfo.from_address(address)
    bounds.max_position.x = info.work.left - info.monitor.left
    bounds.max_position.y = info.work.top - info.monitor.top
    bounds.max_size.x = info.work.right - info.work.left
    bounds.max_size.y = info.work.bottom - info.work.top


def monitor_info(hwnd):
    from ctypes import wintypes
    class MonitorInfo(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('monitor', wintypes.RECT),
                    ('work', wintypes.RECT), ('flags', wintypes.DWORD)]
    user = ctypes.windll.user32
    user.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user.MonitorFromWindow.restype = wintypes.HANDLE
    user.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
    info = MonitorInfo(); info.size = ctypes.sizeof(info)
    monitor = user.MonitorFromWindow(wintypes.HWND(hwnd), 2)
    return info if user.GetMonitorInfoW(monitor, ctypes.byref(info)) else None


def maximize_client_rect(hwnd, rect_address):
    """Keep maximized content inside the monitor's work area, including DPI."""
    from ctypes import wintypes
    user = ctypes.windll.user32
    if not user.IsZoomed(wintypes.HWND(hwnd)):
        return
    info = monitor_info(hwnd)
    if info:
        rect = wintypes.RECT.from_address(rect_address)
        rect.left, rect.top, rect.right, rect.bottom = (
            info.work.left, info.work.top, info.work.right, info.work.bottom)


def apply_window_corners(widget, small=False):
    if (sys.platform != 'win32' or QGuiApplication.platformName() != 'windows'
            or sys.getwindowsversion().build < 22000):
        return False
    from ctypes import wintypes

    try:
        dwm = ctypes.windll.dwmapi
        set_attribute = dwm.DwmSetWindowAttribute
        set_attribute.argtypes = [wintypes.HWND, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD]
        set_attribute.restype = ctypes.c_long
        hwnd = wintypes.HWND(int(widget.winId()))
        # DWMWA_WINDOW_CORNER_PREFERENCE: 2 = round, 3 = round small.
        # Maximized/full-screen windows meet the screen edges without gaps.
        preference = ctypes.c_int(1 if widget.isMaximized() or widget.isFullScreen()
                                  else 3 if small else 2)
        result = set_attribute(hwnd, 33, ctypes.byref(preference), ctypes.sizeof(preference))
        if result != 0:
            return False
        if not small:
            # A 1px compositor frame restores the native shadow to Qt's
            # frameless window while keeping the client-drawn title bar.
            class Margins(ctypes.Structure):
                _fields_ = [(name, ctypes.c_int) for name in ('left', 'right', 'top', 'bottom')]
            extend = dwm.DwmExtendFrameIntoClientArea
            extend.argtypes = [wintypes.HWND, ctypes.POINTER(Margins)]
            extend.restype = ctypes.c_long
            # Extending glass into maximized edges can leave a light strip
            # over the taskbar after Snap. Restore it only for normal windows.
            edge = 0 if widget.isMaximized() or widget.isFullScreen() else 1
            margins = Margins(edge, edge, edge, edge)
            extend(hwnd, ctypes.byref(margins))
        return True
    except (AttributeError, OSError):
        return False
