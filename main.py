"""Desktop Pup - entry point & system tray controller."""
from __future__ import annotations

import os
import sys
import tempfile

from PyQt6.QtCore import QLockFile, Qt, QTimer
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtGui import (QAction, QActionGroup, QColor, QCursor, QGuiApplication, QIcon,
                         QPainter, QPixmap)
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

import comic_renderer as cr
import startup_manager
from doghouse import Doghouse
from settings_manager import SettingsManager
from settings_window import MENU_STYLE, SettingsWindow
from snoopy_pet import PupPet
from window_monitor import WindowMonitor

IPC_NAME = "DesktopPupIPC"
SCALE_PRESETS = [(0.5, "50%"), (0.6, "60% (default)"), (0.75, "75%"), (1.0, "100%"),
                 (1.5, "150%"), (2.0, "200%")]


def make_icon() -> QIcon:
    """Biscuit's face badge (window, taskbar and tray icon)."""
    return cr.make_app_icon()


def write_ico(path: str) -> bool:
    """Save the face badge as a multi-size .ico (used by the PyInstaller build)."""
    img = cr.face_badge_pixmap(256).toImage()
    return img.save(path, "ICO")


class TrayController:
    def __init__(self, app: QApplication, settings: SettingsManager, pet: PupPet,
                 house: Doghouse):
        self.app = app
        self.settings = settings
        self.pet = pet
        self.house = house
        self.window = SettingsWindow(settings, pet, house, pet.animator, self.quit)
        self.window.setWindowIcon(make_icon())
        self.tray = QSystemTrayIcon(make_icon(), app)
        self.tray.setToolTip("Desktop Pup - Biscuit")
        self.menu = QMenu()
        self.menu.setStyleSheet(MENU_STYLE)     # readable in Windows dark mode too
        self._build_menu()
        self.tray.setContextMenu(self.menu)
        pet.context_menu = self.menu          # right-click the pup -> same menu
        self.tray.activated.connect(self._activated)
        settings.changed.connect(self._sync)
        self.tray.show()

    def _build_menu(self) -> None:
        m = self.menu
        open_act = QAction("Settings...", m)
        font = open_act.font()
        font.setBold(True)
        open_act.setFont(font)
        open_act.triggered.connect(self.window.open)
        m.addAction(open_act)
        home_act = QAction("Send Biscuit Home", m)
        home_act.triggered.connect(self.pet.run_home)
        m.addAction(home_act)
        bring_act = QAction("Bring Biscuit to This Screen", m)
        bring_act.triggered.connect(lambda: self.pet.bring_to(QCursor.pos()))
        m.addAction(bring_act)
        m.addSeparator()

        # --- size
        size_menu = m.addMenu("Size Scale")
        self.scale_label = QAction("", size_menu)
        self.scale_label.setEnabled(False)
        size_menu.addAction(self.scale_label)
        size_menu.addSeparator()
        self.scale_group = QActionGroup(size_menu)
        self.scale_group.setExclusive(True)
        self.scale_actions: list[tuple[float, QAction]] = []
        for value, label in SCALE_PRESETS:
            act = QAction(label, size_menu, checkable=True)
            act.triggered.connect(lambda _c, v=value: self.settings.set("scale", v))
            self.scale_group.addAction(act)
            size_menu.addAction(act)
            self.scale_actions.append((value, act))

        # --- doghouse
        dir_menu = m.addMenu("Doghouse Direction")
        self.dir_group = QActionGroup(dir_menu)
        self.dir_group.setExclusive(True)
        self.dir_actions: dict[str, QAction] = {}
        for key, label in (("front", "Front View (Snoopy Peeking)"),
                           ("side", "Side View, No Door (He Sleeps Inside)")):
            act = QAction(label, dir_menu, checkable=True)
            act.triggered.connect(lambda _c, k=key: self.settings.set("doghouse_direction", k))
            self.dir_group.addAction(act)
            dir_menu.addAction(act)
            self.dir_actions[key] = act

        self.show_house = QAction("Show / Reposition Doghouse", m, checkable=True)
        self.show_house.triggered.connect(lambda c: self.house.set_preview(bool(c)))
        m.addAction(self.show_house)
        m.addSeparator()

        # --- roaming
        roam_menu = m.addMenu("Roam Mode")
        self.roam_group = QActionGroup(roam_menu)
        self.roam_group.setExclusive(True)
        self.roam_actions: dict[str, QAction] = {}
        for key, label in (("windows", "Taskbar + Active Windows"), ("taskbar", "Taskbar Only")):
            act = QAction(label, roam_menu, checkable=True)
            act.triggered.connect(lambda _c, k=key: self.settings.set("roam_mode", k))
            self.roam_group.addAction(act)
            roam_menu.addAction(act)
            self.roam_actions[key] = act

        self.choice_actions: list[tuple[str, str, QAction]] = []
        for title, key, options in (
                ("Walking Style", "gait", (("four", "On Four Legs"), ("two", "Upright on Two Legs"),
                                           ("mix", "Mix of Both"))),
                ("Lands on Windows", "perch_spot", (("top", "On Top of the Title Bar"),
                                                    ("inside", "Inside the Window")))):
            sub = m.addMenu(title)
            group = QActionGroup(sub)
            group.setExclusive(True)
            for value, label in options:
                act = QAction(label, sub, checkable=True)
                act.triggered.connect(lambda _c, k=key, v=value: self.settings.set(k, v))
                group.addAction(act)
                sub.addAction(act)
                self.choice_actions.append((key, value, act))

        self.hide_fs = QAction("Hide During Fullscreen Apps", m, checkable=True)
        self.hide_fs.triggered.connect(lambda c: self.settings.set("hide_in_fullscreen", bool(c)))
        m.addAction(self.hide_fs)

        self.startup = QAction("Launch at Windows Startup", m, checkable=True)
        self.startup.setEnabled(startup_manager.is_available())
        self.startup.triggered.connect(self._toggle_startup)
        m.addAction(self.startup)

        reload_act = QAction("Reload Sprite Assets", m)
        reload_act.triggered.connect(self._reload_assets)
        m.addAction(reload_act)
        m.addSeparator()

        quit_act = QAction("Quit", m)
        quit_act.triggered.connect(self.quit)
        m.addAction(quit_act)
        self.menu.aboutToShow.connect(self._sync_all)
        self._sync_all()

    # ------------------------------------------------------------- sync
    def _sync(self, _key: str = "", _value=None) -> None:
        self._sync_all()

    def _sync_all(self) -> None:
        s = self.settings
        scale = s.scale
        self.scale_label.setText(f"Current: {round(scale * 100)}%  (Ctrl + Wheel on pup)")
        matched = False
        for value, act in self.scale_actions:
            hit = abs(value - scale) < 0.01
            act.setChecked(hit)
            matched = matched or hit
        if not matched:
            self.scale_group.setExclusive(False)
            for _v, act in self.scale_actions:
                act.setChecked(False)
            self.scale_group.setExclusive(True)
        cur_dir = "front" if s.get("doghouse_direction") == "front" else "side"
        for key, act in self.dir_actions.items():
            act.setChecked(cur_dir == key)
        for key, act in self.roam_actions.items():
            act.setChecked(s.get("roam_mode") == key)
        for key, value, act in self.choice_actions:
            act.setChecked(s.get(key) == value)
        self.hide_fs.setChecked(bool(s.get("hide_in_fullscreen")))
        self.show_house.setChecked(self.house.preview)
        self.startup.setChecked(startup_manager.is_enabled())

    # ----------------------------------------------------------- actions
    def _toggle_startup(self, checked: bool) -> None:
        if not startup_manager.set_enabled(bool(checked)):
            QMessageBox.warning(None, "Desktop Pup", "Could not update the Windows startup entry.")
        self.startup.setChecked(startup_manager.is_enabled())

    def _reload_assets(self) -> None:
        self.pet.animator.reload()
        self.tray.showMessage("Desktop Pup",
                              f"Loaded {len(self.pet.animator.frames)} sprite animation(s) "
                              f"from {self.pet.animator.root}",
                              QSystemTrayIcon.MessageIcon.Information, 2500)

    def _activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.DoubleClick,
                      QSystemTrayIcon.ActivationReason.Trigger):
            self.window.open()

    def quit(self) -> None:
        """Let Biscuit wave goodbye and run off first (Quit again = immediate)."""
        if getattr(self, "_quitting", False):
            self._finish_quit()
            return
        self._quitting = True
        self.window.hide()
        self.menu.hide()
        self.pet.goodbye(self._finish_quit)
        QTimer.singleShot(6000, self._finish_quit)      # safety net

    def _finish_quit(self) -> None:
        if getattr(self, "_quit_done", False):
            return
        self._quit_done = True
        self.pet.shutdown()
        self.tray.hide()
        self.house.hide()
        self.pet.hide()
        self.app.quit()


def main() -> int:
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("DesktopPup")
    app.setQuitOnLastWindowClosed(False)

    lock = QLockFile(os.path.join(tempfile.gettempdir(), "desktop_pup.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        # already running: ask that instance to open its settings window
        sock = QLocalSocket()
        sock.connectToServer(IPC_NAME)
        if sock.waitForConnected(500):
            sock.write(b"show")
            sock.flush()
            sock.waitForBytesWritten(500)
            sock.disconnectFromServer()
        return 0

    settings = SettingsManager()
    startup_manager.refresh_path_if_enabled()
    monitor = WindowMonitor()
    animator = cr.SpriteAnimator()
    house = Doghouse(settings, monitor, animator)
    pet = PupPet(settings, monitor, house, animator)
    app.setWindowIcon(make_icon())

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.information(None, "Desktop Pup",
                                "No system tray found - right-click menu unavailable.")
    tray = TrayController(app, settings, pet, house)
    server = QLocalServer()
    QLocalServer.removeServer(IPC_NAME)
    server.listen(IPC_NAME)

    def _incoming() -> None:
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.readyRead.connect(lambda: (conn.readAll(), tray.window.open()))

    server.newConnection.connect(_incoming)
    pet.show()
    if "--background" not in sys.argv:
        tray.window.open()          # launched by hand -> show the settings app
    rc = app.exec()
    lock.unlock()
    del tray
    return rc


if __name__ == "__main__":
    sys.exit(main())
