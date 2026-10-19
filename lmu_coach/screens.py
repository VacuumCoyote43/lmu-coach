"""Pantallas: en qué monitor está la ventana de LMU, para poner el coach en el mismo."""
import ctypes as C
import ctypes.wintypes as W

_u = C.windll.user32
MONITOR_DEFAULTTONEAREST = 2


class _MONITORINFO(C.Structure):
    _fields_ = [("cbSize", W.DWORD), ("rcMonitor", W.RECT), ("rcWork", W.RECT), ("dwFlags", W.DWORD)]


def _monitor_rect(hmon) -> tuple[int, int, int, int] | None:
    mi = _MONITORINFO()
    mi.cbSize = C.sizeof(_MONITORINFO)
    if not _u.GetMonitorInfoW(hmon, C.byref(mi)):
        return None
    r = mi.rcMonitor
    return r.left, r.top, r.right, r.bottom


def game_monitor() -> tuple[int, int, int, int] | None:
    """Rectángulo del monitor donde está la ventana de Le Mans Ultimate (None si no está abierta)."""
    found = []

    @C.WINFUNCTYPE(C.c_bool, W.HWND, W.LPARAM)
    def cb(h, _):
        if _u.IsWindowVisible(h):
            buf = C.create_unicode_buffer(128)
            _u.GetWindowTextW(h, buf, 128)
            if buf.value.startswith("Le Mans Ultimate"):
                found.append(h)
                return False
        return True

    _u.EnumWindows(cb, 0)
    if not found:
        return None
    return _monitor_rect(_u.MonitorFromWindow(found[0], MONITOR_DEFAULTTONEAREST))


def monitor_at(x: int, y: int) -> tuple[int, int, int, int] | None:
    return _monitor_rect(_u.MonitorFromPoint(W.POINT(int(x), int(y)), MONITOR_DEFAULTTONEAREST))
