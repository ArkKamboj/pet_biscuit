"""Settings UI: a regular desktop window to configure the pup and his doghouse."""
from __future__ import annotations

import math
import os

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, QUrl
from PyQt6.QtGui import (QAction, QColor, QDesktopServices, QFont, QImage, QLinearGradient,
                         QPainter, QPen, QPolygonF)
from PyQt6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QFormLayout, QFrame,
                             QGroupBox, QHBoxLayout, QLabel, QMenu, QMessageBox,
                             QPushButton, QRadioButton, QScrollArea, QSlider, QSpinBox,
                             QTabWidget, QVBoxLayout, QWidget)

import comic_renderer as cr
import startup_manager
from doghouse import paint_house
from settings_manager import SettingsManager, config_dir

def _arrow_png(name: str, up: bool, color: str) -> str:
    """Draw a small rounded triangle arrow PNG once (Qt stylesheets need image files for
    spin-box / combo arrows) and return its path in stylesheet url() form."""
    folder = config_dir() / "ui"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.png"
    if not path.exists():
        img = QImage(20, 14, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor(0, 0, 0, 0))
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(QColor(color), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                      Qt.PenJoinStyle.RoundJoin))
        p.setBrush(QColor(color))
        tri = QPolygonF([QPointF(4, 10), QPointF(16, 10), QPointF(10, 3.5)] if up
                        else [QPointF(4, 4), QPointF(16, 4), QPointF(10, 10.5)])
        p.drawPolygon(tri)
        p.end()
        img.save(str(path))
    return path.as_posix()


def build_style() -> str:
    up = _arrow_png("arrow_up_v2", True, "#1b1b1b")
    down = _arrow_png("arrow_down_v2", False, "#1b1b1b")
    down_off = _arrow_png("arrow_down_off_v2", False, "#b9b3a7")
    up_off = _arrow_png("arrow_up_off_v2", True, "#b9b3a7")
    return MENU_STYLE + """
QWidget#Root { background: #f6f3ec; }
QWidget { color: #1b1b1b; font-family: "Segoe UI"; font-size: 13px; }
QTabWidget QWidget { background: #ffffff; }
QScrollArea, QScrollArea > QWidget > QWidget { background: #ffffff; }
QCheckBox, QRadioButton, QLabel { background: transparent; }
QToolTip { background: #fffbe8; color: #1b1b1b; border: 1.5px solid #1b1b1b;
           border-radius: 6px; padding: 5px 7px; }

/* ---- header */
QLabel#Title { font-size: 21px; font-weight: 800; color: #1b1b1b; }
QLabel#Sub { color: #6b675f; }
QFrame#Header { background: #ffffff; border: 2px solid #1b1b1b; border-radius: 12px; }

/* ---- inputs: combo boxes and spin boxes */
QComboBox, QSpinBox {
    background: #ffffff; color: #1b1b1b; border: 2px solid #c9c3b6; border-radius: 8px;
    padding: 4px 8px; min-height: 22px;
    selection-background-color: #ffe27a; selection-color: #1b1b1b; }
QComboBox:hover, QSpinBox:hover { border-color: #8c877d; }
QComboBox:focus, QSpinBox:focus { border-color: #d63b2f; }
QComboBox:disabled, QSpinBox:disabled { color: #a8a295; background: #f4f2ec; border-color: #e1ddd3; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: center right;
    width: 26px; border: none; border-left: 1.5px solid #e1ddd3; }
QComboBox::down-arrow { image: url(%(down)s); width: 12px; height: 9px; }
QComboBox::down-arrow:disabled { image: url(%(down_off)s); }
QComboBox QAbstractItemView { background: #ffffff; color: #1b1b1b; border: 2px solid #1b1b1b;
    border-radius: 6px; padding: 4px; outline: none;
    selection-background-color: #fff3c4; selection-color: #1b1b1b; }

QSpinBox { min-width: 78px; padding-right: 30px; }
QSpinBox::up-button, QSpinBox::down-button {
    subcontrol-origin: border; width: 24px; border: none; background: #f4f1ea; }
QSpinBox::up-button { subcontrol-position: top right; border-top-right-radius: 6px;
    border-left: 1.5px solid #e1ddd3; border-bottom: 1px solid #e1ddd3; }
QSpinBox::down-button { subcontrol-position: bottom right; border-bottom-right-radius: 6px;
    border-left: 1.5px solid #e1ddd3; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #fff3c4; }
QSpinBox::up-button:pressed, QSpinBox::down-button:pressed { background: #ffe27a; }
QSpinBox::up-arrow { image: url(%(up)s); width: 10px; height: 7px; }
QSpinBox::down-arrow { image: url(%(down)s); width: 10px; height: 7px; }
QSpinBox::up-arrow:disabled, QSpinBox::up-arrow:off { image: url(%(up_off)s); }
QSpinBox::down-arrow:disabled, QSpinBox::down-arrow:off { image: url(%(down_off)s); }

/* ---- check boxes and radio buttons */
QCheckBox, QRadioButton { spacing: 8px; padding: 2px 0; }
QCheckBox::indicator, QRadioButton::indicator { width: 14px; height: 14px;
    border: 2px solid #1b1b1b; background: #ffffff; }
QCheckBox::indicator { border-radius: 4px; }
QRadioButton::indicator { border-radius: 9px; }
QCheckBox::indicator:hover, QRadioButton::indicator:hover { background: #fff3c4; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked { background: #d63b2f; }
QCheckBox:disabled, QRadioButton:disabled { color: #a8a295; }

/* ---- tabs and groups */
QTabWidget::pane { border: 2px solid #1b1b1b; border-radius: 12px; background: #ffffff; top: -2px; }
QTabBar::tab { color: #1b1b1b; background: #e9e4d8; border: 2px solid #1b1b1b; border-bottom: none;
               padding: 8px 20px; margin-right: 5px; border-top-left-radius: 10px;
               border-top-right-radius: 10px; font-weight: 700; }
QTabBar::tab:hover { background: #fff3c4; }
QTabBar::tab:selected { background: #ffffff; }
QGroupBox { font-weight: 700; border: 1.5px solid #e1ddd3; border-radius: 10px;
            margin-top: 16px; padding: 12px 12px 10px 12px; background: #fdfcf9; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px;
                   color: #d63b2f; background: transparent; }
QGroupBox QWidget { background: transparent; }
QGroupBox QComboBox, QGroupBox QSpinBox { background: #ffffff; }

/* ---- buttons */
QPushButton { background: #ffffff; border: 2px solid #1b1b1b; border-radius: 9px;
              padding: 6px 14px; font-weight: 600; }
QPushButton:hover { background: #fff3c4; }
QPushButton:pressed { background: #ffe27a; }
QPushButton:checked { background: #1b1b1b; color: #ffffff; }
QPushButton#Primary { background: #d63b2f; color: white; }
QPushButton#Primary:hover { background: #e9564a; }
QPushButton#Primary:pressed { background: #b92e23; }
QPushButton#Pose { padding: 5px 6px; border-radius: 14px; border-width: 1.5px; }
QPushButton#Menu { padding-right: 30px; }
QPushButton#Menu::menu-indicator { image: url(%(down)s); subcontrol-origin: padding;
    subcontrol-position: center right; right: 10px; width: 12px; height: 9px; }

/* ---- sliders and scroll bars */
QSlider::groove:horizontal { height: 6px; background: #e1ddd3; border-radius: 3px; }
QSlider::handle:horizontal { background: #ffffff; border: 2px solid #1b1b1b; width: 14px;
                             margin: -6px 0; border-radius: 9px; }
QSlider::handle:horizontal:hover { background: #fff3c4; }
QSlider::sub-page:horizontal { background: #d63b2f; border-radius: 3px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 4px 2px; }
QScrollBar::handle:vertical { background: #cfc9bc; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #a8a295; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
""" % {"up": up, "down": down, "down_off": down_off, "up_off": up_off}


# Light, readable menus everywhere (the App button and the tray / right-click menu).
# Without this, Windows dark mode gives a near-black menu with black text.
MENU_STYLE = """
QMenu { background: #ffffff; color: #1b1b1b; border: 2px solid #1b1b1b; border-radius: 10px;
        padding: 6px; font-family: "Segoe UI"; font-size: 13px; }
QMenu::item { background: transparent; color: #1b1b1b; padding: 7px 28px 7px 30px;
              border-radius: 6px; margin: 1px 0; }
QMenu::item:selected { background: #fff3c4; color: #1b1b1b; }
QMenu::item:disabled { color: #9a958b; }
QMenu::separator { height: 1.5px; background: #e1ddd3; margin: 5px 8px; }
QMenu::indicator { width: 14px; height: 14px; left: 8px; border: 2px solid #1b1b1b;
                   border-radius: 4px; background: #ffffff; }
QMenu::indicator:checked { background: #d63b2f; }
QMenu::right-arrow { width: 8px; height: 8px; }
"""

PREVIEW_POSES = [("Calm", "calm"), ("Walk", "walk"), ("Excited", "excited"),
                 ("Growl", "growl"), ("Sit", "sit"), ("Beg", "beg"), ("Bored", "lie"),
                 ("Sleep", "sleep"), ("Sprint", "run")]


class PupPreview(QWidget):
    """Animated, live preview of the pup in the chosen pose and size."""

    def __init__(self, settings: SettingsManager):
        super().__init__()
        self.settings = settings
        self.mode = "calm"
        self.t = 0.0
        self.setMinimumHeight(110)      # shrinks on short screens...
        self.setMaximumHeight(200)      # ...but never hogs a tall one
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)

    def _tick(self) -> None:
        self.t += 0.033
        if self.isVisible():
            self.update()

    def _pose(self) -> tuple[cr.Pose, float]:
        t, m = self.t, self.mode
        bob = 0.0
        gait = self.settings.get("gait")
        upright = gait == "two" or (gait == "mix" and int(t / 4) % 2 == 1)
        if m == "walk" and upright:
            ps = cr.pose("upright")
            cr.apply_upright_walk(ps, t * 8.0, 26, 2.4)
            ps["ear"] = 0.4
            ps["ta"] = 118 + 14 * math.sin(t * 11)
        elif m == "walk":
            ps = cr.pose("stand")
            cr.apply_walk(ps, t * 7.0, 26, 2)
            ps["ear"] = 0.4
            ps["ta"] = 40 + 15 * math.sin(t * 11)
        elif m == "calm" and gait == "two":
            ps = cr.pose("upright")
            ps["ear"] = 0.28 + 0.06 * math.sin(t * 1.4)
            ps["fna"] += 6 * math.sin(t * 2.2)
            ps["ffa"] -= 6 * math.sin(t * 2.2)
            ps["ta"] = 118 + 10 * math.sin(t * 6.28)
        elif m == "excited":
            happy = (t % 2.2) < 1.2
            ps = cr.pose("stand", mouth="pant", eyes="happy" if happy else "normal")
            ps["ear"], ps["tongue"], ps["blush"] = 0.62, 1.0, 1.0
            ps["flap"] = 30 * math.sin(t * 28)
            ps["ta"] = 30 + 26 * math.sin(t * 31)
            bob = -abs(math.sin(t * 6)) * 14
        elif m == "growl":
            ps = cr.pose("stand", mouth="grr", brow="angry")
            ps["bob"], ps["ear"], ps["ta"] = 3.0, 0.0, 55
            ps["hy"] += 4
            ps["shakex"] = 1.2 * math.sin(t * 160)
        elif m == "beg":
            ps = cr.pose("beg", mouth="smile")
            ps["tongue"], ps["ear"] = 0.6, 0.35
            ps["fna"] += 9 * math.sin(t * 7)
            ps["ffa"] -= 9 * math.sin(t * 7)
            ps["ta"] = 100 + 8 * math.sin(t * 9)
        elif m == "sit":
            ps = cr.pose("sit", mouth="flat")
            ps["eye"], ps["ear"] = 0.72, 0.05
        elif m == "lie":
            yawn = (t % 6) > 4.4
            ps = cr.pose("lie", mouth="yawn" if yawn else "flat", brow="none" if yawn else "sad")
            ps["eye"] = 0.08 if yawn else 0.55
            if yawn:
                ps["hrot"] -= 16
        elif m == "sleep":
            ps = cr.pose("curl", eyes="closed", brow="none")
            ps["eye"] = 0.0
            ps["breath"] = 1.0 + 0.06 * math.sin(t * 1.85)
        elif m == "run":
            ps = cr.pose("run", mouth="pant", brow="raised")
            cr.apply_gallop(ps, t * 14)
            ps["tongue"] = 1.0
        else:
            ps = cr.pose("stand")
            ps["ear"] = 0.28 + 0.06 * math.sin(t * 1.4)
            ps["ta"] = 35 + 12 * math.sin(t * 6.28)
            ps["hrot"] += 7 * math.sin(t * 0.8)
        if m not in ("sleep",) and (t % 4.0) < 0.13 and ps.eyes == "normal":
            ps["eye"] = 0.0
        ps["lookx"] = 0.6 * math.sin(t * 0.9)
        ps["looky"] = 0.3 * math.sin(t * 0.6)
        return ps, bob

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = self.rect()
        grad = QLinearGradient(0, 0, 0, r.height())
        grad.setColorAt(0, QColor("#dfeaf6"))
        grad.setColorAt(1, QColor("#f4f8fc"))
        p.setPen(QPen(QColor("#1b1b1b"), 2))
        p.setBrush(grad)
        p.drawRoundedRect(QRectF(r).adjusted(1, 1, -1, -1), 10, 10)
        ground = r.height() - 26
        p.setBrush(QColor("#2b3440"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(3, ground, r.width() - 6, 23), 6, 6)   # mini taskbar
        scale = self.settings.scale
        fit = min(scale, (ground - 14) / 120.0)
        ps, bob = self._pose()
        p.save()
        p.translate(r.width() / 2 - 8, ground + bob * fit)
        p.scale(fit, fit)
        cr.draw_dog(p, ps, 1.0)
        if self.mode == "sleep":
            ph = (self.t % 1.6) / 1.6
            cr.draw_bubble(p, "z", QPointF(30 + 8 * ph, -40 - 40 * ph), 1 - ph, self.t)
        elif self.mode == "growl":
            cr.draw_bubble(p, "grr", QPointF(52, -108), 1, self.t, 0.95)
        elif self.mode == "excited":
            ph = (self.t % 1.2) / 1.2
            cr.draw_bubble(p, "note" if int(self.t / 1.2) % 2 else "heart",
                           QPointF(44, -96 - 40 * ph), 1 - ph, self.t)
        p.restore()
        p.setPen(QColor("#5d5a55"))
        p.setFont(QFont("Segoe UI", 9))
        p.drawText(QRectF(10, 6, r.width() - 20, 18), Qt.AlignmentFlag.AlignRight,
                   f"{round(scale * 100)}%")
        p.end()


class HousePreview(QWidget):
    def __init__(self, settings: SettingsManager):
        super().__init__()
        self.settings = settings
        self.t = 0.0
        self.setFixedSize(190, 160)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(50)

    def _tick(self) -> None:
        self.t += 0.05
        if self.isVisible():
            self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(QColor("#d4cfc3"), 1.5))
        p.setBrush(QColor("#eef3f8"))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 10, 10)
        p.translate(self.width() / 2, self.height() - 10)
        p.scale(1.05, 1.05)
        blink = (self.t % 3.5) < 0.14
        v = self.settings.get("doghouse_direction")
        view_to_paint = "front" if v == "front" else "closed"
        if view_to_paint == "closed":
            p.scale(0.85, 0.85)          # the long side is wider than the front
        paint_house(p, view_to_paint, True,
                    bool(self.settings.get("doghouse_half_out")),
                    0.6 * math.sin(self.t * 0.7), 0.0, blink, self.t, False)
        p.end()


class SettingsWindow(QWidget):
    def __init__(self, settings: SettingsManager, pet, house, animator, quit_cb):
        super().__init__()
        self.setObjectName("Root")
        self.settings = settings
        self.pet = pet
        self.house = house
        self.animator = animator
        self.quit_cb = quit_cb
        self.setWindowTitle("Desktop Pup - Settings")
        self.setStyleSheet(build_style())
        self.setWindowIcon(cr.make_app_icon())
        self.setMinimumWidth(780)
        self.resize(840, 780)
        self._syncing = False

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        # header card: Biscuit's face badge + title
        header = QFrame()
        header.setObjectName("Header")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(12, 8, 14, 8)
        hl.setSpacing(12)
        badge = QLabel()
        badge.setPixmap(cr.face_badge_pixmap(52, self.devicePixelRatioF()))
        badge.setFixedSize(52, 52)
        hl.addWidget(badge)
        words = QVBoxLayout()
        words.setSpacing(0)
        title = QLabel("Biscuit, your desktop pup")
        title.setObjectName("Title")
        sub = QLabel("Black-and-white comic beagle. Changes apply instantly and are saved.")
        sub.setObjectName("Sub")
        words.addWidget(title)
        words.addWidget(sub)
        hl.addLayout(words, 1)
        root.addWidget(header)

        self.preview = PupPreview(settings)
        root.addWidget(self.preview, 0)
        pose_row = QHBoxLayout()
        pose_row.setSpacing(5)
        self.pose_group = QButtonGroup(self)
        for i, (label, key) in enumerate(PREVIEW_POSES):
            b = QPushButton(label)
            b.setObjectName("Pose")
            b.setCheckable(True)
            b.setChecked(i == 0)
            b.clicked.connect(lambda _c, k=key: setattr(self.preview, "mode", k))
            self.pose_group.addButton(b)
            pose_row.addWidget(b)
        root.addLayout(pose_row)

        tabs = QTabWidget()
        tabs.addTab(self._dog_tab(), "Dog && abilities")
        tabs.addTab(self._house_tab(), "House")
        root.addWidget(tabs, 1)

        bottom = QHBoxLayout()
        home = QPushButton("Send Biscuit home now")
        home.setObjectName("Primary")
        home.clicked.connect(self.pet.run_home)
        bring = QPushButton("Bring him to this screen")
        bring.clicked.connect(self._bring_here)
        app_btn = QPushButton("App")
        app_btn.setObjectName("Menu")
        app_btn.setMenu(self._app_menu())
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        bottom.addWidget(home)
        bottom.addWidget(bring)
        bottom.addStretch(1)
        bottom.addWidget(app_btn)
        bottom.addWidget(close)
        root.addLayout(bottom)

        settings.changed.connect(lambda *_: self.sync())
        self.sync()

    # --------------------------------------------------------------- tabs
    def _dog_tab(self) -> QWidget:
        """Everything about Biscuit himself: looks, how he moves, where he goes, his mood."""
        inner = QWidget()
        cols = QHBoxLayout(inner)
        cols.setSpacing(12)
        left = QVBoxLayout()
        right = QVBoxLayout()

        # ---- left column: looks + how he walks
        box = QGroupBox("Size")
        g = QVBoxLayout(box)
        row = QHBoxLayout()
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(50, 250)
        self.size_slider.setSingleStep(5)
        self.size_slider.setPageStep(25)
        self.size_label = QLabel()
        self.size_label.setMinimumWidth(48)
        self.size_slider.valueChanged.connect(self._size_changed)
        row.addWidget(self.size_slider, 1)
        row.addWidget(self.size_label)
        g.addLayout(row)
        presets = QHBoxLayout()
        for pct in (50, 60, 75, 100, 150):
            b = QPushButton(f"{pct}%")
            b.clicked.connect(lambda _c, v=pct: self.settings.set("scale", v / 100))
            presets.addWidget(b)
        g.addLayout(presets)
        tip = QLabel("Tip: hold Ctrl and scroll the mouse wheel over Biscuit to resize him on the fly.")
        tip.setObjectName("Sub")
        tip.setWordWrap(True)
        g.addWidget(tip)
        left.addWidget(box)

        look = QGroupBox("Proportions")
        ll = QVBoxLayout(look)
        self.prop_cartoon = QRadioButton("Cartoon: big head, short stubby legs")
        self.prop_beagle = QRadioButton("Realistic beagle: long legs, deep chest")
        self.prop_cartoon.toggled.connect(lambda on: on and self._set("proportions", "cartoon"))
        self.prop_beagle.toggled.connect(lambda on: on and self._set("proportions", "beagle"))
        ll.addWidget(self.prop_cartoon)
        ll.addWidget(self.prop_beagle)
        left.addWidget(look)

        gait = QGroupBox("Walking style")
        gl = QVBoxLayout(gait)
        self.gait_buttons: dict[str, QRadioButton] = {}
        for key, label in (("four", "On all four legs"),
                           ("two", "Upright on two legs"),
                           ("mix", "Mix: switches between the two now and then")):
            rb = QRadioButton(label)
            rb.toggled.connect(lambda on, k=key: on and self._gait_changed(k))
            gl.addWidget(rb)
            self.gait_buttons[key] = rb
        self.sit_up = QCheckBox("Sometimes sit up and beg when idle (four-legged)")
        self.sit_up.toggled.connect(lambda on: self._set("sit_up_idle", bool(on)))
        gl.addWidget(self.sit_up)
        self.intro_outro = QCheckBox("Run in and say hello at start-up, wave goodbye when quitting")
        self.intro_outro.toggled.connect(lambda on: self._set("intro_outro", bool(on)))
        gl.addWidget(self.intro_outro)
        left.addWidget(gait)
        left.addStretch(1)

        # ---- right column: where he goes + personality
        roam = QGroupBox("Where can he go?")
        rl = QVBoxLayout(roam)
        self.roam_windows = QRadioButton("Taskbar + jump onto the active window")
        self.roam_taskbar = QRadioButton("Taskbar only")
        self.roam_windows.toggled.connect(
            lambda on: on and self._set("roam_mode", "windows"))
        self.roam_taskbar.toggled.connect(
            lambda on: on and self._set("roam_mode", "taskbar"))
        rl.addWidget(self.roam_windows)
        rl.addWidget(self.roam_taskbar)
        spot_row = QHBoxLayout()
        spot_row.setContentsMargins(22, 0, 0, 0)
        spot_row.addWidget(QLabel("He lands"))
        self.perch_spot = QComboBox()
        self.perch_spot.addItem("on top of the title bar", "top")
        self.perch_spot.addItem("inside the window (bottom edge)", "inside")
        self.perch_spot.currentIndexChanged.connect(
            lambda _i: self._set("perch_spot", self.perch_spot.currentData()))
        spot_row.addWidget(self.perch_spot, 1)
        rl.addLayout(spot_row)
        self.hide_fs = QCheckBox("Hide him while a fullscreen app (video, game, F11) is active")
        self.hide_fs.toggled.connect(lambda on: self._set("hide_in_fullscreen", bool(on)))
        rl.addWidget(self.hide_fs)
        right.addWidget(roam)

        mood = QGroupBox("Personality")
        f = QFormLayout(mood)
        self.speed_slider, speed_row = self._slider_row(40, 250, "walk_speed", "%")
        f.addRow("Walking / running speed", speed_row)
        self.excite_slider, excite_row = self._slider_row(20, 300, "excite_sensitivity", "%")
        f.addRow("Excitement sensitivity", excite_row)
        self.bored_spin = self._spin(5, 300, " s", "bored_after")
        f.addRow("Gets bored after cursor is still for", self.bored_spin)
        self.sleep_spin = self._spin(20, 1800, " s", "sleep_after")
        f.addRow("Falls asleep after computer idle for", self.sleep_spin)
        self.clicks_spin = self._spin(3, 30, " clicks", "clicks_to_home")
        f.addRow("Runs to his doghouse after", self.clicks_spin)
        right.addWidget(mood)
        right.addStretch(1)

        cols.addLayout(left, 1)
        cols.addLayout(right, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(inner)
        return scroll

    def _gait_changed(self, key: str) -> None:
        self._set("gait", key)
        if not self._syncing:
            self.preview.mode = "walk"       # show the new walking style right away
            for b in self.pose_group.buttons():
                b.setChecked(b.text() == "Walk")

    def _house_tab(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        left = QVBoxLayout()

        view = QGroupBox("Doghouse direction")
        vl = QVBoxLayout(view)
        self.dir_buttons: dict[str, QRadioButton] = {}
        for key, label in (("front", "Front view (Snoopy peeking out)"),
                           ("side", "Side view, no door: he goes round the back and sleeps")):
            rb = QRadioButton(label)
            rb.toggled.connect(lambda on, k=key: on and self._set("doghouse_direction", k))
            vl.addWidget(rb)
            self.dir_buttons[key] = rb
        left.addWidget(view)

        arrive = QGroupBox("When he runs home")
        af = QFormLayout(arrive)
        self.arrival = QComboBox()
        for key, label in (("far", "Far side of the screen (longest run)"),
                           ("left", "Left side of the screen"),
                           ("right", "Right side of the screen"),
                           ("random", "Random side")):
            self.arrival.addItem(label, key)
        self.arrival.currentIndexChanged.connect(
            lambda _i: self._set("house_arrival", self.arrival.currentData()))
        af.addRow("House slides in from", self.arrival)
        self.parking = QComboBox()
        self.parking.addItem("Near the edge it slid in from", "edge")
        self.parking.addItem("My saved spot (drag it there)", "saved")
        self.parking.currentIndexChanged.connect(
            lambda _i: self._set("house_parking", self.parking.currentData()))
        af.addRow("House parks", self.parking)
        stay_row = QHBoxLayout()
        self.stay_min = self._spin(3, 600, " s", "house_stay_min")
        self.stay_max = self._spin(3, 600, " s", "house_stay_max")
        stay_row.addWidget(self.stay_min)
        stay_row.addWidget(QLabel("to"))
        stay_row.addWidget(self.stay_max)
        af.addRow("Stays inside for", stay_row)
        self.wake_spin = self._spin(1, 60, " min", "house_wake_minutes")
        self.wake_spin.setToolTip("Door-hidden view only: he sleeps until you click the house, "
                                  "or until you've been using the PC this long and then move "
                                  "the mouse fast.")
        af.addRow("Door hidden: wakes after you're busy for", self.wake_spin)
        self.reposition = QPushButton("Show / reposition doghouse on the taskbar")
        self.reposition.setCheckable(True)
        self.reposition.toggled.connect(self._toggle_reposition)
        af.addRow(self.reposition)
        left.addWidget(arrive)
        left.addStretch(1)
        lay.addLayout(left, 1)

        right = QVBoxLayout()
        right.addWidget(QLabel("Preview"))
        right.addWidget(HousePreview(self.settings))
        hint = QLabel("Click the house while he's inside to call him out early.")
        hint.setObjectName("Sub")
        hint.setWordWrap(True)
        hint.setMaximumWidth(190)
        right.addWidget(hint)
        right.addStretch(1)
        lay.addLayout(right)
        scroll = QScrollArea()          # scrolls inside the window on short screens
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(w)
        return scroll

    def _app_menu(self) -> QMenu:
        """App-level options (not about the dog or the house) live in the bottom-bar menu."""
        m = QMenu(self)
        m.setStyleSheet(MENU_STYLE)
        self.startup =QAction("Launch Desktop Pup when Windows starts", m, checkable=True)
        self.startup.setEnabled(startup_manager.is_available())
        self.startup.toggled.connect(self._toggle_startup)
        m.addAction(self.startup)
        m.addSeparator()
        self.sprite_status = QAction("", m)
        self.sprite_status.setEnabled(False)
        m.addAction(self.sprite_status)
        m.addAction("Open custom sprites (assets) folder", self._open_assets)
        m.addAction("Reload sprites", self._reload)
        m.addSeparator()
        m.addAction("Open settings folder",
                    lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(config_dir()))))
        m.addAction("Reset all settings...", self._reset)
        m.addSeparator()
        m.addAction("Quit Desktop Pup", self.quit_cb)
        m.aboutToShow.connect(self.sync)
        return m

    # ------------------------------------------------------------ helpers
    def _set(self, key: str, value) -> None:
        if not self._syncing:
            self.settings.set(key, value)

    def _spin(self, lo: int, hi: int, suffix: str, key: str) -> QSpinBox:
        sp = QSpinBox()
        sp.setRange(lo, hi)
        sp.setSuffix(suffix)
        sp.valueChanged.connect(lambda v: self._set(key, v))
        return sp

    def _slider_row(self, lo: int, hi: int, key: str, suffix: str):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        sl = QSlider(Qt.Orientation.Horizontal)
        sl.setRange(lo, hi)
        lab = QLabel()
        lab.setMinimumWidth(44)
        sl.valueChanged.connect(lambda v: (lab.setText(f"{v}{suffix}"), self._set(key, v / 100)))
        h.addWidget(sl, 1)
        h.addWidget(lab)
        sl._label = lab  # type: ignore[attr-defined]
        return sl, row

    def _size_changed(self, v: int) -> None:
        self.size_label.setText(f"{v}%")
        self._set("scale", v / 100)

    def _toggle_reposition(self, on: bool) -> None:
        if not self._syncing:
            self.house.set_preview(bool(on))

    def _toggle_startup(self, on: bool) -> None:
        if self._syncing:
            return
        if not startup_manager.set_enabled(bool(on)):
            QMessageBox.warning(self, "Desktop Pup", "Could not update the Windows startup entry.")
        self.sync()

    def _open_assets(self) -> None:
        root = self.animator.root
        os.makedirs(root, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(root)))

    def _reload(self) -> None:
        self.animator.reload()
        self.sync()

    def _reset(self) -> None:
        if QMessageBox.question(self, "Desktop Pup", "Reset every setting to its default?") \
                == QMessageBox.StandardButton.Yes:
            self.settings.reset_defaults()

    def _bring_here(self) -> None:
        self.pet.bring_to(self.frameGeometry().center())

    # --------------------------------------------------------------- sync
    def sync(self) -> None:
        s = self.settings
        self._syncing = True
        try:
            pct = round(s.scale * 100)
            self.size_slider.setValue(pct)
            self.size_label.setText(f"{pct}%")
            self.prop_cartoon.setChecked(s.get("proportions") == "cartoon")
            self.prop_beagle.setChecked(s.get("proportions") == "beagle")
            self.roam_windows.setChecked(s.get("roam_mode") == "windows")
            self.roam_taskbar.setChecked(s.get("roam_mode") == "taskbar")
            self.hide_fs.setChecked(bool(s.get("hide_in_fullscreen")))
            self.sit_up.setChecked(bool(s.get("sit_up_idle")))
            self.intro_outro.setChecked(bool(s.get("intro_outro")))
            for key, rb in self.gait_buttons.items():
                rb.setChecked(s.get("gait") == key)
            self.perch_spot.setCurrentIndex(max(0, self.perch_spot.findData(s.get("perch_spot"))))
            self.perch_spot.setEnabled(s.get("roam_mode") == "windows")
            for slider, key in ((self.speed_slider, "walk_speed"),
                                (self.excite_slider, "excite_sensitivity")):
                v = round(float(s.get(key)) * 100)
                slider.setValue(v)
                slider._label.setText(f"{v}%")
            self.bored_spin.setValue(int(s.get("bored_after")))
            self.sleep_spin.setValue(int(s.get("sleep_after")))
            self.clicks_spin.setValue(int(s.get("clicks_to_home")))
            cur_dir = "front" if s.get("doghouse_direction") == "front" else "side"
            for key, rb in self.dir_buttons.items():
                rb.setChecked(cur_dir == key)
            self.arrival.setCurrentIndex(max(0, self.arrival.findData(s.get("house_arrival"))))
            self.parking.setCurrentIndex(max(0, self.parking.findData(s.get("house_parking"))))
            self.stay_min.setValue(int(s.get("house_stay_min")))
            self.stay_max.setValue(int(s.get("house_stay_max")))
            self.wake_spin.setValue(int(s.get("house_wake_minutes")))
            closed = s.get("doghouse_direction") != "front"
            self.wake_spin.setEnabled(closed)
            self.stay_min.setEnabled(not closed)
            self.stay_max.setEnabled(not closed)
            self.reposition.setChecked(self.house.preview)
            self.startup.setChecked(startup_manager.is_enabled())
            n = len(self.animator.frames)
            self.sprite_status.setText(
                f"{n} custom sprite animation(s) loaded" if n
                else "Using the built-in hand-drawn pup")
        finally:
            self._syncing = False

    def fit_to_screen(self) -> None:
        """Keep the whole window (title bar to bottom buttons) on the screen it's on."""
        screen = self.screen() or QApplication.primaryScreen()
        avail = screen.availableGeometry()
        frame_extra = max(0, self.frameGeometry().height() - self.geometry().height()) or 32
        max_h = avail.height() - frame_extra - 16
        max_w = avail.width() - 16
        w = min(max(self.width(), 780), max_w)
        h = min(self.height(), max_h)
        self.setMaximumHeight(max(420, avail.height() - frame_extra))
        self.resize(w, h)
        fg = self.frameGeometry()
        x = min(max(fg.x(), avail.left() + 8), avail.right() - fg.width() - 8)
        y = min(max(fg.y(), avail.top() + 8), avail.bottom() - fg.height() - 8)
        self.move(max(avail.left(), x), max(avail.top(), y))

    def showEvent(self, e) -> None:
        super().showEvent(e)
        QTimer.singleShot(0, self.fit_to_screen)

    def open(self) -> None:
        self.sync()
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.raise_()
        self.activateWindow()

    def closeEvent(self, e) -> None:
        e.ignore()
        self.hide()
