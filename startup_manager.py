"""Launch-at-Windows-startup via HKCU\\...\\CurrentVersion\\Run."""
from __future__ import annotations

import os
import sys

try:
    import winreg
except ImportError:  # non-Windows: feature silently unavailable
    winreg = None  # type: ignore[assignment]

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "DesktopPup"


def launch_command() -> str:
    """Command line Windows should run at logon."""
    if getattr(sys, "frozen", False):
        # PyInstaller executable
        return f'"{os.path.abspath(sys.executable)}" --background'
    main_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    pythonw = os.path.join(exe_dir, "pythonw.exe")
    interpreter = pythonw if os.path.exists(pythonw) else sys.executable
    return f'"{interpreter}" "{main_py}" --background'


def is_available() -> bool:
    return winreg is not None


def is_enabled() -> bool:
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return bool(value)
    except OSError:
        return False


def set_enabled(enabled: bool) -> bool:
    """Returns True on success."""
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, launch_command())
            else:
                try:
                    winreg.DeleteValue(key, VALUE_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


def refresh_path_if_enabled() -> None:
    """If the app moved (e.g. new exe location), keep the Run entry pointing at it."""
    if is_enabled():
        set_enabled(True)
