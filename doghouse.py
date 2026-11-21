"""The conditional 2D doghouse: slides in from a screen edge, front/left/right views."""
from __future__ import annotations

import math
import random

from PyQt6.QtCore import (QEasingCurve, QElapsedTimer, QPoint, QPointF,
                          QPropertyAnimation, QRectF, Qt, QTimer, pyqtSignal)
from PyQt6.QtGui import QColor, QCursor, QPainter, QPainterPath
from PyQt6.QtWidgets import QWidget

import comic_renderer as cr
from settings_manager import SettingsManager
from window_monitor import WindowMonitor

UNIT_W = 236.0   # extra width leaves room for dust puffs while sliding
UNIT_H = 168.0
FOOT_PAD = 3.0


def paint_house(p: QPainter, view: str, occupied: bool, half_out: bool,
                lookx: float, looky: float, blink: bool, t: float,
                preview: bool, animator: cr.SpriteAnimator | None = None) -> None:
    """Paint the house (and occupant) with the painter at the house's floor centre,
    already scaled to units."""
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if view == "closed":
        # long side, door out of sight: he's simply gone inside, Zzz drift off the roof
        if not (animator is not None and animator.draw_house(p, view)):
            cr.draw_house_long_side(p)
        if occupied:
            for i in range(3):
                phase = ((t + i * 0.9) % 2.7) / 2.7
                cr.draw_bubble(p, "z", QPointF(18 + i * 9 + 7 * math.sin(phase * 6 + i),
                                               -104 - phase * 40),
                               alpha=1.0 - phase, t=t, size=0.55 + 0.45 * phase)
        return
    custom = animator is not None and animator.draw_house(p, view)
    if not custom:
        cr.draw_doghouse_back(p, view)
    door, floor = cr.doghouse_door(view)
    eye_open = 0.05 if blink else 1.0
    if occupied:
        if view == "front":
            if animator is not None and animator.has("peek_front"):
                p.save()
                p.setClipPath(door, Qt.ClipOperation.IntersectClip)
                animator.draw(p, "peek_front", t, 1)
                p.restore()
            else:
                p.save()
                p.setClipPath(door, Qt.ClipOperation.IntersectClip)
                cr.draw_front_face(p, QPointF(0, -25), 15.5, lookx, looky, eye_open,
                                   0.25 + 0.1 * math.sin(t * 1.3))
                p.restore()
                cr.draw_front_paws(p, QPointF(0, -2), 7.5, 0.85)
        elif half_out:
            facing = -1.0 if view == "left" else 1.0
            sx = -1.0 if view == "left" else 1.0
            clip = QPainterPath(door)
            half = QPainterPath()
            if view == "left":
                half.addRect(QRectF(-400, -400, 400 + floor.x(), 400))
            else:
                half.addRect(QRectF(floor.x(), -400, 400, 400))
            clip = clip.united(half)
            p.save()
            p.setClipPath(clip, Qt.ClipOperation.IntersectClip)
            if animator is not None and animator.has("peek_side"):
                p.translate(floor.x(), 0)
                animator.draw(p, "peek_side", t, facing)
            else:
                k = 0.78
                pose = cr.pose("lie", mouth="smile")
                pose["hy"] = -31
                pose["hx"] = 25
                pose["hrot"] = -2 + looky * 8
                pose["ear"] = 0.25 + 0.08 * math.sin(t * 1.7)
                pose["eye"] = eye_open
                pose["lookx"] = max(-1.0, min(1.0, lookx * facing))
                pose["looky"] = looky
                pose["ta"] = 60
                p.translate(floor.x() + sx * -19.0, 0)
                p.scale(k, k)
                cr.draw_dog(p, pose, facing)
            p.restore()
        else:
            # fully inside: just a pair of eyes glinting in the dark doorway
            if not blink:
                for ex in (-4.5, 4.5):
                    c = QPointF(floor.x() + ex + lookx * 1.5, -25 + looky * 1.2)
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(cr.WHITE)
                    p.drawEllipse(c, 2.6, 3.2)
                    p.setBrush(cr.INK)
                    p.drawEllipse(QPointF(c.x() + lookx * 0.8, c.y() + looky * 0.8), 1.3, 1.6)
            phase = (t % 2.4) / 2.4
            cr.draw_bubble(p, "z", QPointF(floor.x() + 10 + 6 * math.sin(phase * 6),
                                           -50 - phase * 34),
                           alpha=1.0 - phase, t=t, size=0.7 + 0.4 * phase)
    pup_in_front = occupied and view != "front" and half_out
    if not custom and not pup_in_front:
        cr.draw_doghouse_threshold(p, view)
    if preview and not occupied:
        p.setPen(cr._pen(2.4))
        y = -134.0
        path = QPainterPath(QPointF(-24, y))
        path.lineTo(QPointF(24, y))
        for sx in (-1, 1):
            path.moveTo(QPointF(sx * 24 - sx * 7, y - 6))
            path.lineTo(QPointF(sx * 24, y))
            path.lineTo(QPointF(sx * 24 - sx * 7, y + 6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)


class Doghouse(QWidget):
    """Hidden by default.  When the pup is sent home the house slides in from the
    left or right edge of his screen (wobbling, kicking up dust), parks, and slides
    back out once he leaves.  'Show / Reposition' fades it in at the saved spot so
    it can be dragged along the taskbar."""

    exit_requested = pyqtSignal()   # user clicked the house while the pup is inside
    arrived = pyqtSignal()

    SLIDE_IN = 1.3
    SLIDE_OUT = 1.0

    def __init__(self, settings: SettingsManager, monitor: WindowMonitor,
                 animator: cr.SpriteAnimator):
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool
                         | Qt.WindowType.WindowDoesNotAcceptFocus
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setWindowTitle("Doghouse")
        self.settings = settings
        self.monitor = monitor
        self.animator = animator
        self.s = settings.scale
        self.occupied = False
        self.preview = False
        self.fullscreen_hidden = False
        self.mode = "hidden"            # hidden | arriving | parked | departing
        self.entered_by = "fade"        # fade | slide
        self.side = 1                   # screen edge used: -1 left, +1 right
        self.slide_from = 0.0
        self.slide_to = 0.0
        self.slide_t = 0.0
        self.slide_dur = 1.0
        self.wobble = 0.0
        self.hop = 0.0
        self.dust: list[list[float]] = []   # [x, y, vx, age, life, r]  (units)
        self._dust_timer = 0.0
        self.t = 0.0
        self.blink_until = 0.0
        self.next_blink = 2.0
        self._mon_device: str | None = None
        self._press: QPoint | None = None
        self._press_cx = 0.0
        self._dragging = False
        self._cx = self._saved_cx()

        self._anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self._fade_done)

        self._clock = QElapsedTimer()
        self._clock.start()
        self._last = 0.0
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        settings.changed.connect(self._on_setting)
        self._resize()

    # ------------------------------------------------------------ geometry
    def _saved_cx(self) -> float:
        saved = self.settings.get("doghouse_x")
        if saved is not None:
            return float(saved)
        work = self.monitor.primary().work
        return work.x() + work.width() - 260.0

    def _mon_info(self):
        if self._mon_device:
            for m in self.monitor.monitors:
                if m.device == self._mon_device:
                    return m
        return self.monitor.monitor_at(self._cx)

    def _clamp_cx(self, cx: float, mon=None) -> float:
        mon = mon or self.monitor.monitor_at(cx)
        half = 72 * self.s
        lo, hi = mon.work.left() + half, mon.work.right() - half
        return max(lo, min(hi, cx))

    def ground_y(self) -> float:
        work = self._mon_info().work
        return float(work.y() + work.height())

    def monitor_device(self) -> str:
        return self._mon_info().device

    def _door_dx(self) -> float:
        if self.view == "closed":
            # he slips round the end of the house that faces the middle of the screen
            return -self.side * (cr.SIDE_HALF - 6) * self.s
        _, floor = cr.doghouse_door(self.view)
        return floor.x() * self.s

    def door_point(self) -> QPointF:
        """Current global floor point of the doorway."""
        return QPointF(self._cx + self._door_dx(), self.ground_y())

    def target_door_point(self) -> QPointF:
        """Where the doorway will be once the house has finished arriving."""
        cx = self.slide_to if self.mode == "arriving" else self._cx
        return QPointF(cx + self._door_dx(), self.ground_y())

    def exit_direction(self) -> int:
        if self.view == "left":
            return -1
        if self.view == "right":
            return 1
        return -self.side   # walk away from the edge the house came from

    @property
    def view(self) -> str:
        # Front view shows the doorway; every side view is the long side with no door:
        # he slips round the back, vanishes and sleeps inside.
        return "front" if self.settings.get("doghouse_direction") == "front" else "closed"

    @property
    def is_arrived(self) -> bool:
        return self.mode == "parked"

    def _resize(self) -> None:
        self.setFixedSize(int(UNIT_W * self.s), int(UNIT_H * self.s))
        self.reposition()

    def reposition(self) -> None:
        if self.mode not in ("arriving", "departing"):
            self._cx = self._clamp_cx(self._cx, self._mon_info() if self._mon_device else None)
        x = self._cx - self.width() / 2
        y = self.ground_y() - self.height() + FOOT_PAD * self.s
        nx, ny = int(round(x)), int(round(y))
        if nx != self.pos().x() or ny != self.pos().y():
            self.move(nx, ny)

    def _offscreen_cx(self, side: int) -> float:
        work = self._mon_info().work
        half = self.width() / 2 + 6
        return work.right() + half if side > 0 else work.left() - half

    # ------------------------------------------------------------- arrival
    def plan_arrival(self, pet_x: float, mon) -> QPointF:
        """Pick the arrival edge and parking spot on monitor `mon`.
        Returns the doorway point the pup should run to."""
        if self.mode in ("parked", "arriving"):
            return self.target_door_point()
        self._mon_device = mon.device
        work = mon.work
        pref = self.settings.get("house_arrival")
        if pref == "left":
            side = -1
        elif pref == "right":
            side = 1
        elif pref == "random":
            side = random.choice((-1, 1))
        else:  # far side from the pup -> a nice long run
            side = 1 if (pet_x - work.left()) < (work.right() - pet_x) else -1
        self.side = side
        saved = self.settings.get("doghouse_x")
        if (self.settings.get("house_parking") == "saved" and saved is not None
                and work.left() <= saved <= work.right()):
            target = self._clamp_cx(float(saved), mon)
            self.side = 1 if target > work.center().x() else -1
        else:
            margin = 118 * self.s
            target = work.right() - margin if side > 0 else work.left() + margin
        self.slide_to = target
        return QPointF(target + self._door_dx(), float(work.y() + work.height()))

    def start_arrival(self) -> None:
        if self.mode in ("arriving", "parked"):
            return
        self.slide_from = self._offscreen_cx(self.side)
        self._cx = self.slide_from
        self.slide_t = 0.0
        self.slide_dur = self.SLIDE_IN
        self.mode = "arriving"
        self.entered_by = "slide"
        self.dust.clear()
        self._anim.stop()
        self.setWindowOpacity(0.0 if self.fullscreen_hidden else 1.0)
        self.reposition()
        self.show()
        self.raise_()
        self._start_timer()

    def depart(self) -> None:
        if self.mode == "hidden":
            return
        self.slide_from = self._cx
        self.slide_to = self._offscreen_cx(self.side)
        self.slide_t = 0.0
        self.slide_dur = self.SLIDE_OUT
        self.mode = "departing"
        self.dust.clear()
        self._start_timer()

    # ---------------------------------------------------------- visibility
    def hide_house(self) -> None:
        if self.preview or self.occupied or self.mode == "hidden":
            return
        if self.entered_by == "slide" and self.mode in ("parked", "arriving"):
            self.depart()
        else:
            self._fade(0.0)

    def set_preview(self, on: bool) -> None:
        self.preview = on
        if on:
            if self.mode == "hidden":
                self._mon_device = None
                self._cx = self._saved_cx()
                self.mode = "parked"
                self.entered_by = "fade"
                self.side = 1 if self._cx > self.monitor.monitor_at(self._cx).work.center().x() else -1
                self.reposition()
                self.setWindowOpacity(0.0)
                self.show()
                self._start_timer()
                self._fade(1.0)
        else:
            self.update()
            self.hide_house()

    def set_occupied(self, on: bool) -> None:
        self.occupied = on
        self.update()

    def set_fullscreen_hidden(self, hidden: bool) -> None:
        if hidden == self.fullscreen_hidden:
            return
        self.fullscreen_hidden = hidden
        if self.mode != "hidden":
            self._fade(0.0 if hidden else 1.0, keep=True)

    def _fade(self, target: float, keep: bool = False) -> None:
        self._fade_keep = keep
        self._anim.stop()
        self._anim.setDuration(350 if target > 0 else 450)
        self._anim.setStartValue(self.windowOpacity())
        self._anim.setEndValue(target)
        self._anim.start()

    def _fade_done(self) -> None:
        if self.windowOpacity() <= 0.01 and not getattr(self, "_fade_keep", False):
            self._finish_hide()

    def _finish_hide(self) -> None:
        self.hide()
        self._timer.stop()
        self.mode = "hidden"
        self._mon_device = None
        self._cx = self._saved_cx()
        self.dust.clear()

    # ---------------------------------------------------------------- loop
    def _start_timer(self) -> None:
        self._last = self._clock.elapsed() / 1000.0
        self._timer.start(16)

    @staticmethod
    def _out_back(p: float) -> float:
        c1 = 1.25
        c3 = c1 + 1
        return 1 + c3 * (p - 1) ** 3 + c1 * (p - 1) ** 2

    def _tick(self) -> None:
        now = self._clock.elapsed() / 1000.0
        dt = max(0.001, min(0.05, now - self._last))
        self._last = now
        self.t += dt
        if self.t > self.next_blink:
            self.blink_until = self.t + 0.14
            self.next_blink = self.t + random.uniform(2.5, 6.0)

        if self.mode in ("arriving", "departing"):
            self.slide_t += dt
            p = min(1.0, self.slide_t / self.slide_dur)
            arriving = self.mode == "arriving"
            e = self._out_back(p) if arriving else p * p * p
            prev = self._cx
            self._cx = self.slide_from + (self.slide_to - self.slide_from) * e
            vel = (self._cx - prev) / dt / self.s          # units / s
            energy = (1.0 - p) if arriving else min(1.0, p * 2)
            self.wobble = math.sin(self.t * 26) * 3.0 * energy
            self.hop = -abs(math.sin(self.t * 17)) * 5.0 * energy
            self._dust_timer -= dt
            if self._dust_timer <= 0 and abs(vel) > 60:
                self._dust_timer = 0.035
                back = -1 if vel > 0 else 1
                self.dust.append([back * 58 + random.uniform(-6, 6), -3 + random.uniform(-3, 2),
                                  -vel * 0.35 + random.uniform(-20, 20), 0.0,
                                  random.uniform(0.45, 0.75), random.uniform(5, 9)])
            self.reposition()
            if p >= 1.0:
                self.wobble = self.hop = 0.0
                if arriving:
                    self.mode = "parked"
                    self._cx = self.slide_to
                    self.reposition()
                    self.arrived.emit()
                else:
                    self._finish_hide()
                    return
        alive = []
        for d in self.dust:
            d[3] += dt
            if d[3] < d[4]:
                d[0] += d[2] * dt
                d[1] -= 14 * dt
                d[5] += 10 * dt
                alive.append(d)
        self.dust = alive
        self.update()

    def _on_setting(self, key: str, value) -> None:
        if key == "scale":
            self.s = float(value)
            self._resize()
        elif key in ("doghouse_direction", "doghouse_half_out"):
            self.update()
        elif key == "doghouse_x" and self.mode == "hidden":
            self._cx = self._saved_cx()

    # --------------------------------------------------------------- paint
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.translate(self.width() / 2, self.height() - FOOT_PAD * self.s)
        p.scale(self.s, self.s)
        for x, y, _vx, age, life, r in self.dust:
            a = max(0.0, 1.0 - age / life)
            p.setOpacity(0.85 * a)
            p.setPen(cr._pen(1.4, QColor(90, 80, 70)))
            p.setBrush(QColor(222, 214, 200))
            p.drawEllipse(QPointF(x, y), r, r * 0.8)
        p.setOpacity(1.0)
        p.save()
        p.translate(0, self.hop)
        p.rotate(self.wobble)
        cur = QCursor.pos()
        door = self.door_point()
        dx = cur.x() - door.x()
        dy = cur.y() - (door.y() - 25 * self.s)
        lookx = max(-1.0, min(1.0, dx / 300.0))
        looky = max(-1.0, min(1.0, dy / 300.0))
        paint_house(p, self.view, self.occupied, bool(self.settings.get("doghouse_half_out")),
                    lookx, looky, self.t < self.blink_until, self.t,
                    self.preview and self.mode == "parked", self.animator)
        p.restore()
        p.end()

    # --------------------------------------------------------------- mouse
    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.globalPosition().toPoint()
            self._press_cx = self._cx
            self._dragging = False

    def mouseMoveEvent(self, e) -> None:
        if self._press is None or self.mode != "parked":
            return
        g = e.globalPosition().toPoint()
        if not self._dragging and abs(g.x() - self._press.x()) > 4:
            self._dragging = True
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            self._mon_device = None
        if self._dragging:
            self._cx = self._press_cx + (g.x() - self._press.x())
            self.reposition()
            self.update()

    def mouseReleaseEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton or self._press is None:
            return
        self.unsetCursor()
        if self._dragging:
            self.settings.set("doghouse_x", int(self._cx))
            self.settings.set("house_parking", "saved")
            mon = self.monitor.monitor_at(self._cx)
            self.side = 1 if self._cx > mon.work.center().x() else -1
        elif self.occupied:
            self.exit_requested.emit()
        self._press = None
        self._dragging = False
