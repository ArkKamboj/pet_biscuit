"""Win32 integration: monitors, work areas, foreground window, fullscreen & idle.

All public coordinates are Qt *logical* (device-independent) pixels so they can be
used directly with QWidget.move().  Win32 reports physical pixels (Qt6 runs the
process Per-Monitor-DPI-aware), so every rect is converted through the monitor it
lives on.
"""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass

from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtGui import QGuiApplication, QScreen

try:
    import win32api
    import win32con
    import win32gui
    import win32process
    HAS_WIN32 = True
except ImportError:  # allows the pet to run (taskbar-only) without pywin32
    HAS_WIN32 = False

DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14

SHELL_CLASSES = {
    "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
    "NotifyIconOverflowWindow", "Windows.UI.Core.CoreWindow",
    "TopLevelWindowForOverflowXamlIsland", "XamlExplorerHostIslandWindow",
    "ForegroundStaging", "MultitaskingViewFrame", "TaskListThumbnailWnd",
    "#32768",  # context menus
}


@dataclass
class MonitorInfo:
    phys: tuple[int, int, int, int]       # monitor rect, physical px (l, t, r, b)
    phys_work: tuple[int, int, int, int]  # work area, physical px
    geometry: QRect                       # logical
    work: QRect                           # logical work area (excludes taskbar)
    screen: QScreen | None
    device: str

    @property
    def ratio(self) -> float:
        width = self.phys[2] - self.phys[0]
        return width / max(1, self.geometry.width())

    def contains_phys(self, x: int, y: int) -> bool:
        l, t, r, b = self.phys
        return l <= x < r and t <= y < b


@dataclass
class WindowInfo:
    hwnd: int
    rect: QRect          # logical, visible frame (without invisible resize borders)
    fullscreen: bool
    maximized: bool
    minimized: bool
    cls: str
    monitor: MonitorInfo | None


class WindowMonitor:
    def __init__(self) -> None:
        self.monitors: list[MonitorInfo] = []
        self._own_pid = os.getpid()
        self._user32 = ctypes.windll.user32 if HAS_WIN32 else None
        self._dwm = None
        if HAS_WIN32:
            try:
                self._dwm = ctypes.windll.dwmapi
            except OSError:
                self._dwm = None
        self.refresh_monitors()

    # ----------------------------------------------------------- monitors
    def refresh_monitors(self) -> None:
        screens = QGuiApplication.screens()
        result: list[MonitorInfo] = []
        if HAS_WIN32:
            try:
                for hmon, _hdc, _rect in win32api.EnumDisplayMonitors(None, None):
                    info = win32api.GetMonitorInfo(hmon)
                    device = info.get("Device", "")
                    screen = next((s for s in screens if s.name() == device), None)
                    if screen is None:
                        # Fallback: match by physical size / origin heuristics
                        idx = len(result)
                        screen = screens[idx] if idx < len(screens) else None
                    if screen is None:
                        continue
                    result.append(MonitorInfo(
                        phys=tuple(info["Monitor"]),
                        phys_work=tuple(info["Work"]),
                        geometry=screen.geometry(),
                        work=screen.availableGeometry(),
                        screen=screen,
                        device=device,
                    ))
            except Exception:
                result = []
        if not result:
            for s in screens:
                g, w = s.geometry(), s.availableGeometry()
                dpr = s.devicePixelRatio()
                phys = (int(g.x() * dpr), int(g.y() * dpr),
                        int((g.x() + g.width()) * dpr), int((g.y() + g.height()) * dpr))
                result.append(MonitorInfo(phys, phys, g, w, s, s.name()))
        self.monitors = result

    def monitor_at(self, x: float, y: float | None = None) -> MonitorInfo:
        """Monitor containing logical point (x, y); y=None -> match on x only."""
        best, best_d = None, float("inf")
        for m in self.monitors:
            g = m.geometry
            inside_x = g.left() <= x <= g.right()
            inside_y = True if y is None else g.top() <= y <= g.bottom() + 2
            if inside_x and inside_y:
                return m
            cx = min(max(x, g.left()), g.right())
            cy = g.center().y() if y is None else min(max(y, g.top()), g.bottom())
            d = (cx - x) ** 2 + (cy - (y if y is not None else cy)) ** 2
            if d < best_d:
                best, best_d = m, d
        return best or self.monitors[0]

    def primary(self) -> MonitorInfo:
        prim = QGuiApplication.primaryScreen()
        for m in self.monitors:
            if m.screen is prim:
                return m
        return self.monitors[0]

    def phys_to_logical(self, px: int, py: int, mon: MonitorInfo | None = None) -> QPoint:
        mon = mon or next((m for m in self.monitors if m.contains_phys(px, py)), None)
        if mon is None:
            mon = min(self.monitors, key=lambda m: abs(px - m.phys[0]) + abs(py - m.phys[1]))
        r = mon.ratio
        return QPoint(int(mon.geometry.x() + (px - mon.phys[0]) / r),
                      int(mon.geometry.y() + (py - mon.phys[1]) / r))

    def _rect_to_logical(self, rect: tuple[int, int, int, int], mon: MonitorInfo) -> QRect:
        tl = self.phys_to_logical(rect[0], rect[1], mon)
        r = mon.ratio
        w = int((rect[2] - rect[0]) / r)
        h = int((rect[3] - rect[1]) / r)
        return QRect(tl.x(), tl.y(), w, h)

    # ---------------------------------------------------------- windows
    def _frame_rect(self, hwnd: int) -> tuple[int, int, int, int]:
        if self._dwm is not None:
            rect = wintypes.RECT()
            res = self._dwm.DwmGetWindowAttribute(
                wintypes.HWND(hwnd), wintypes.DWORD(DWMWA_EXTENDED_FRAME_BOUNDS),
                ctypes.byref(rect), ctypes.sizeof(rect))
            if res == 0:
                return rect.left, rect.top, rect.right, rect.bottom
        return win32gui.GetWindowRect(hwnd)

    def _is_cloaked(self, hwnd: int) -> bool:
        if self._dwm is None:
            return False
        cloaked = wintypes.DWORD(0)
        res = self._dwm.DwmGetWindowAttribute(
            wintypes.HWND(hwnd), wintypes.DWORD(DWMWA_CLOAKED),
            ctypes.byref(cloaked), ctypes.sizeof(cloaked))
        return res == 0 and cloaked.value != 0

    def _monitor_for_hwnd(self, hwnd: int) -> MonitorInfo | None:
        try:
            hmon = win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST)
            info = win32api.GetMonitorInfo(hmon)
        except Exception:
            return None
        device = info.get("Device", "")
        for m in self.monitors:
            if m.device == device:
                return m
        mrect = tuple(info["Monitor"])
        return next((m for m in self.monitors if m.phys == mrect), None)

    def is_own_window(self, hwnd: int) -> bool:
        try:
            _tid, pid = win32process.GetWindowThreadProcessId(hwnd)
            return pid == self._own_pid
        except Exception:
            return False

    def window_info(self, hwnd: int) -> WindowInfo | None:
        """Geometry & state of a window, or None if it's gone/invisible/shell."""
        if not HAS_WIN32 or not hwnd:
            return None
        try:
            if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
                return None
            cls = win32gui.GetClassName(hwnd)
            if cls in SHELL_CLASSES or self._is_cloaked(hwnd):
                return None
            minimized = bool(win32gui.IsIconic(hwnd))
            maximized = bool(self._user32.IsZoomed(wintypes.HWND(hwnd)))
            rect = self._frame_rect(hwnd)
            mon = self._monitor_for_hwnd(hwnd)
        except Exception:
            return None
        if mon is None:
            return None
        ml, mt, mr, mb = mon.phys
        l, t, r, b = rect
        fullscreen = l <= ml and t <= mt and r >= mr and b >= mb
        return WindowInfo(hwnd, self._rect_to_logical(rect, mon), fullscreen,
                          maximized, minimized, cls, mon)

    def foreground(self) -> WindowInfo | None:
        """Foreground window, skipping desktop/taskbar/shell and our own windows."""
        if not HAS_WIN32:
            return None
        try:
            hwnd = win32gui.GetForegroundWindow()
        except Exception:
            return None
        if not hwnd or self.is_own_window(hwnd):
            return None
        return self.window_info(hwnd)

    def foreground_hwnd(self) -> int:
        if not HAS_WIN32:
            return 0
        try:
            return int(win32gui.GetForegroundWindow() or 0)
        except Exception:
            return 0

    def fullscreen_monitor(self) -> MonitorInfo | None:
        """Monitor covered by a fullscreen foreground app (video, game, F11), if any."""
        info = self.foreground()
        if info and info.fullscreen and not info.minimized:
            return info.monitor
        return None

    # ------------------------------------------------------------- idle
    @staticmethod
    def idle_seconds() -> float:
        """Seconds since the last keyboard/mouse input anywhere (GetLastInputInfo)."""
        if not HAS_WIN32:
            return 0.0
        try:
            last = win32api.GetLastInputInfo()
            now = win32api.GetTickCount()
            return ((now - last) & 0xFFFFFFFF) / 1000.0
        except Exception:
            return 0.0
