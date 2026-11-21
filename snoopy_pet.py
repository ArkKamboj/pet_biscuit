"""The desktop pup: 60 FPS behaviour state machine, physics and rendering widget."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from PyQt6.QtCore import QElapsedTimer, QPointF, Qt, QTimer
from PyQt6.QtGui import QCursor, QGuiApplication, QPainter
from PyQt6.QtWidgets import QWidget

import comic_renderer as cr
from doghouse import Doghouse
from settings_manager import SettingsManager
from window_monitor import WindowInfo, WindowMonitor

# Widget box in units (1 unit == 1 logical px at scale 1.0)
UNIT_W = 196.0
UNIT_H = 180.0
FOOT_PAD = 6.0

# Mouse speed thresholds, logical px / second
SPEED_SLOW = 260.0
SPEED_TROT = 850.0
SPEED_FAST = 1600.0

# Bored / sleep timings and the click count come from the settings (Settings window).
CLICK_WINDOW = 1.5          # seconds between clicks to keep the streak alive
MIN_RUN_TIME = 2.2          # the pup sprints at least this long before reaching the house

GRAVITY = 2600.0            # units / s^2 (scaled)
ACTIVE_GAP = 20.0           # s of no input that ends a "busy" streak (closed doghouse wake-up)
AIR_DRAG = 0.35            # 1/s, horizontal slow-down while airborne
WALL_BOUNCE = 0.45          # fraction of horizontal speed kept bouncing off a screen edge
BOUNCE = 0.28               # fraction of fall speed kept when he bounces off the taskbar
BOUNCE_MIN = 1150.0         # units/s (scaled): falls faster than this bounce once
SLIDE_KEEP = 0.35           # fraction of horizontal speed carried into a landing slide
SQUASH_K = 260.0            # squash & stretch spring stiffness
SQUASH_D = 13.0             # ...and damping (lower = wobblier)
INSIDE_INSET = 7.0         # logical px above a window's bottom edge for the "inside" perch
UPRIGHT_STATES = {"calm", "walk", "trot", "perch_approach", "exit_house"}

ROAM_STATES = {"calm", "walk", "trot", "excited", "bored_sit", "bored_lie"}
TRACKING_STATES = ROAM_STATES | {"growl", "obey", "startled", "perch_approach",
                                 "exit_house", "wake_stretch", "intro_hello", "outro_wave"}
SPRITE_FOR_STATE = {
    "calm": "idle", "walk": "walk", "trot": "trot", "excited": "excited",
    "bored_sit": "sit", "bored_lie": "lie", "drowsy": "drowsy", "sleep": "sleep",
    "wake_ears": "wake_ears", "growl": "growl", "obey": "obey_sit",
    "startled": "startled", "sprint": "run", "exit_house": "walk",
    "perch_approach": "trot", "dragged": "dragged",
    "intro_run": "run", "intro_hello": "hello", "outro_wave": "goodbye", "outro_run": "run",
}


@dataclass
class Bubble:
    kind: str
    x: float          # units, relative to the feet, NOT mirrored
    y: float
    vx: float
    vy: float
    life: float
    size: float = 1.0
    age: float = 0.0
    wobble: float = 0.0

    @property
    def alpha(self) -> float:
        a_in = min(1.0, self.age / 0.15)
        a_out = min(1.0, (self.life - self.age) / 0.45)
        return max(0.0, min(a_in, a_out))


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


class PupPet(QWidget):
    def __init__(self, settings: SettingsManager, monitor: WindowMonitor,
                 doghouse: Doghouse, animator: cr.SpriteAnimator):
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool
                         | Qt.WindowType.WindowDoesNotAcceptFocus
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setWindowTitle("Desktop Pup")

        self.settings = settings
        self.monitor = monitor
        self.house = doghouse
        self.animator = animator
        self.s = settings.scale
        cr.set_proportions(settings.get("proportions"))

        work = monitor.primary().work
        self.x = work.x() + work.width() * 0.62
        self.y = float(work.y() + work.height())
        self.vx = 0.0
        self.vy = 0.0
        self.airborne = False
        self.hop = False                 # small playful hop (keeps excited face)
        self.jump_target = 0             # hwnd we are jumping onto
        self.perch_hwnd = 0              # hwnd we're standing on (0 = taskbar)
        self.perch_rect = None           # last known logical rect of that window
        self.perch_tx = 0.0
        self.perch_candidate = 0
        self.facing = 1
        self.facing_vis = 1.0
        self.last_turn = 0.0
        self.walk_target = self.x
        self.move_speed = 0.0
        self.phase = 0.0
        # physics: ground momentum + springy secondary motion
        self.ground_v = 0.0
        self._prev_vel = 0.0
        self.accel_x = 0.0
        self.squash = 0.0
        self.squash_v = 0.0
        self.lean = 0.0
        self.ear_sp = self.ear_v = 0.0
        self.tail_sp = self.tail_v = 0.0

        self.state = "calm"
        self.state_t = 0.0
        self.t = 0.0
        self.pose = cr.pose("stand")
        self.bubbles: list[Bubble] = []
        self.next_bubble = 0.0

        # mouse tracking
        c = QCursor.pos()
        self.mx, self.my = float(c.x()), float(c.y())
        self.speed = 0.0
        self.still = 0.0
        self.moved_now = False
        self.excite = 0.0
        self.reversals: list[float] = []
        self.last_dx_sign = 0

        # timers / misc behaviour
        self.idle = 0.0
        self.fg: WindowInfo | None = None
        self.env_t = 0.0
        self.mon_t = 4.0
        self.perch_timer = random.uniform(12, 25)
        self.perch_stay = 0.0
        self.next_blink = 2.0
        self.blink_until = 0.0
        self.next_yawn = random.uniform(5, 9)
        self.yawn_until = 0.0
        self.next_look = random.uniform(3, 5)
        self.look_until = 0.0
        self.next_hop = 0.0
        self.tilt_target = 0.0
        self.next_tilt = 2.0
        self.next_beg = random.uniform(8, 15)
        self.beg_until = 0.0
        self.upright = settings.get("gait") == "two"   # walking on two legs right now
        self.next_gait = random.uniform(10, 20)          # "mix" mode switches now and then
        self.active_since = 0.0                          # start of your current busy streak
        # hello / goodbye animations
        self.offscreen_ok = False
        self.intro_target = self.x
        self.exit_x = self.x
        self._outro_done = None
        self.wake_active = 0.0
        self.wake_last = 0.0
        self.react_dur = 1.4
        self.last_reaction = ""
        self.click_count = 0
        self.last_click = -10.0
        self.house_stay = 0.0
        self.exit_target = 0.0
        self.home_door = QPointF()
        self.house_called = False
        self.context_menu = None         # set by main.py (same menu as the tray icon)

        # visibility
        self.opacity = 1.0
        self.hidden_fs = False
        self.in_house = False

        # dragging
        self._press = None
        self._press_off = (0.0, 0.0)
        self._dragging = False
        self._drag_hist: list[tuple[float, float, float]] = []

        self._resize()
        if settings.get("intro_outro"):
            self._start_intro()
        self._place()

        doghouse.exit_requested.connect(self.leave_house)
        settings.changed.connect(self._on_setting)
        app = QGuiApplication.instance()
        app.screenAdded.connect(lambda *_: self._screens_changed())
        app.screenRemoved.connect(lambda *_: self._screens_changed())

        self.clock = QElapsedTimer()
        self.clock.start()
        self._last = 0.0
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)

    # ================================================================ utils
    def _resize(self) -> None:
        self.setFixedSize(int(UNIT_W * self.s), int(UNIT_H * self.s))

    def _place(self) -> None:
        wx = self.x - self.width() / 2
        wy = self.y - self.height() + FOOT_PAD * self.s
        nx, ny = int(round(wx)), int(round(wy))
        if nx != self.pos().x() or ny != self.pos().y():
            self.move(nx, ny)

    def _mon(self):
        return self.monitor.monitor_at(self.x, self.y - 4)

    def _ground_y(self, mon=None) -> float:
        work = (mon or self._mon()).work
        return float(work.y() + work.height())

    def _surface_range(self) -> tuple[float, float]:
        work = self._mon().work
        lo, hi = work.left() + 42 * self.s, work.right() - 42 * self.s
        if self.perch_hwnd and self.perch_rect is not None:
            r = self.perch_rect
            lo = max(lo, r.left() + 28 * self.s)
            hi = min(hi, r.right() - 28 * self.s)
        if hi < lo:
            mid = (lo + hi) / 2
            return mid, mid
        return lo, hi

    # -------------------------------------------------------- perch helpers
    def _inside(self) -> bool:
        return self.settings.get("perch_spot") == "inside"

    def _floor_of(self, rect) -> float:
        """Y the pup stands on for a window: its title bar, or its inner bottom edge."""
        if self._inside():
            return float(rect.y() + rect.height() - INSIDE_INSET)
        return float(rect.top())

    def _perch_ok(self, info: WindowInfo | None, strict: bool = True) -> bool:
        """Can he stand on this window? `strict` is for starting a jump, loose for staying."""
        if (info is None or info.minimized or info.fullscreen or info.monitor is None
                or self.settings.get("roam_mode") != "windows"):
            return False
        r, mon = info.rect, info.monitor
        ground = self._ground_y(mon)
        if self._inside():
            room = (150 if strict else 120) * self.s      # he has to fit inside it
            low = (60 if strict else 30) * self.s         # floor clearly above the taskbar
            return r.height() >= room and self._floor_of(r) < ground - low
        head = (110 if strict else 95) * self.s           # head-room above the title bar
        low = (140 if strict else 60) * self.s
        return r.top() - mon.work.top() >= head and r.top() < ground - low

    def _set(self, state: str) -> None:
        if state == self.state:
            return
        if state in ("walk", "trot") and self.settings.get("gait") == "mix" \
                and self.state not in ("walk", "trot") and self.t > self.next_gait:
            self.next_gait = self.t + random.uniform(10, 20)
            self.upright = random.random() < 0.5
        self.state = state
        self.state_t = 0.0
        if state == "startled":
            self._say("exclaim", life=1.1, size=1.1)
        elif state == "growl":
            self._say("grr", life=self.react_dur, dy=-10, vy=-4, size=0.95)
        elif state == "obey":
            self._say("dots", life=1.3, size=0.9)
        elif state == "wake_ears":
            self._say("question", life=1.6, size=1.0)
            self.wake_active = 0.0
            self.wake_last = self.t
        elif state == "excited":
            self.next_hop = self.t + 0.15

    def _head_units(self) -> tuple[float, float]:
        sign = 1.0 if self.facing_vis >= 0 else -1.0
        return sign * self.pose["hx"] * abs(self.facing_vis), self.pose["hy"] + self.pose["bob"]

    def _say(self, kind: str, life: float = 1.5, dx: float = 0.0, dy: float = 0.0,
             vx: float = 0.0, vy: float = -18.0, size: float = 1.0) -> None:
        hx, hy = self._head_units()
        sign = 1.0 if self.facing >= 0 else -1.0
        if kind in ("question", "exclaim", "dots", "grr"):
            # only one speech bubble at a time
            self.bubbles = [b for b in self.bubbles
                            if b.kind not in ("question", "exclaim", "dots", "grr")]
            x = hx + sign * 14 + dx
            y = hy - 38 + dy
        else:
            x = hx + sign * 10 + dx
            y = hy - 22 + dy
        x = _clamp(x, -UNIT_W / 2 + 28, UNIT_W / 2 - 28)
        self.bubbles.append(Bubble(kind, x, y, vx, vy, life, size,
                                   wobble=random.uniform(0, 6.28)))

    # ================================================================= tick
    def _tick(self) -> None:
        now = self.clock.elapsed() / 1000.0
        dt = _clamp(now - self._last, 0.001, 0.05)
        self._last = now
        self.t += dt
        self.state_t += dt
        self._poll_env(dt)
        self._track_mouse(dt)
        if not self._dragging:
            self._update_perch()
            self._think(dt)
            self._physics(dt)
        self._secondary(dt)
        self._animate(dt)
        self._update_bubbles(dt)
        self._update_visibility(dt)
        self._place()
        if self.isVisible():
            self.update()

    # ---------------------------------------------------------- environment
    def _screens_changed(self) -> None:
        self.monitor.refresh_monitors()
        self.house.reposition()

    def _poll_env(self, dt: float) -> None:
        self.mon_t -= dt
        if self.mon_t <= 0:
            self.mon_t = 4.0
            self.monitor.refresh_monitors()   # taskbar moved / resolution changed
            if self.house.isVisible():
                self.house.reposition()
        self.env_t -= dt
        if self.env_t > 0:
            return
        self.env_t = 0.2
        self.idle = self.monitor.idle_seconds()
        if self.idle > ACTIVE_GAP:
            self.active_since = self.t          # a pause breaks the "you've been busy" streak
        self.fg = self.monitor.foreground()
        fs_mon = self.fg.monitor if (self.fg and self.fg.fullscreen and not self.fg.minimized) else None
        mine = self._mon()
        hide_ok = bool(self.settings.get("hide_in_fullscreen"))
        self.hidden_fs = hide_ok and fs_mon is not None and fs_mon.device == mine.device
        self.house.set_fullscreen_hidden(
            hide_ok and fs_mon is not None and fs_mon.device == self.house.monitor_device())
        # another real window took focus -> hop off the old one
        if self.perch_hwnd and not self.airborne:
            fgh = self.monitor.foreground_hwnd()
            if (fgh and fgh != self.perch_hwnd and not self.monitor.is_own_window(fgh)
                    and self.fg is not None and self.fg.hwnd == fgh):
                self._fall_from_perch()

    def _track_mouse(self, dt: float) -> None:
        c = QCursor.pos()
        cx, cy = float(c.x()), float(c.y())
        dx, dy = cx - self.mx, cy - self.my
        dist = math.hypot(dx, dy)
        self.mx, self.my = cx, cy
        inst = dist / dt
        self.speed += (inst - self.speed) * (1.0 - math.exp(-dt / 0.15))
        self.moved_now = dist > 1.5
        if self.moved_now:
            self.still = 0.0
        else:
            self.still += dt
        if abs(dx) > 4:
            sgn = 1 if dx > 0 else -1
            if sgn != self.last_dx_sign:
                self.reversals.append(self.t)
                self.last_dx_sign = sgn
        self.reversals = [r for r in self.reversals if self.t - r < 1.0]
        hx, hy = self.x + self.facing * 30 * self.s, self.y - 62 * self.s
        near_d = math.hypot(cx - hx, cy - hy)
        near = 1.0 if near_d < 450 * self.s else 0.55 if near_d < 1100 * self.s else 0.3
        erratic = len(self.reversals) >= 4 and self.speed > 650
        if self.speed > SPEED_FAST or erratic:
            self.excite += dt * 1.9 * near * float(self.settings.get("excite_sensitivity"))
        else:
            self.excite -= dt * 0.6
        self.excite = _clamp(self.excite, 0.0, 1.6)

    # --------------------------------------------------------------- perch
    def _update_perch(self) -> None:
        """Follow the window we stand on; drop to the taskbar if it becomes unusable."""
        if not self.perch_hwnd:
            return
        info = self.monitor.window_info(self.perch_hwnd)
        if not self._perch_ok(info, strict=False):
            self._fall_from_perch()
            return
        r = info.rect
        if self.perch_rect is not None:
            ddx = r.left() - self.perch_rect.left()
            self.x += ddx
            self.walk_target += ddx
        self.perch_rect = r
        if not self.airborne:
            self.y = self._floor_of(r)
            lo, hi = self._surface_range()
            if self.x < lo - 30 * self.s or self.x > hi + 30 * self.s:
                self._fall_from_perch()   # window shrank out from under us

    def _fall_from_perch(self) -> None:
        if not self.perch_hwnd:
            return
        self.perch_hwnd = 0
        self.perch_rect = None
        self.airborne = True
        self.hop = False
        self.jump_target = 0
        self.vx = 0.0
        self.vy = 0.0

    def _jump_down(self) -> None:
        self.perch_hwnd = 0
        self.perch_rect = None
        self.airborne = True
        self.hop = False
        self.jump_target = 0
        self.vy = -math.sqrt(2 * GRAVITY * self.s * 28 * self.s)
        self.vx = self.facing * 110 * self.s
        self.ground_v = 0.0
        self.squash_v = -5.0          # stretch as he pushes off

    def _jump_to(self, info: WindowInfo, tx: float) -> None:
        g = GRAVITY * self.s
        ty = self._floor_of(info.rect)
        h_up = max(0.0, self.y - ty) + 46 * self.s
        vy0 = -math.sqrt(2 * g * h_up)
        t_up = -vy0 / g
        fall = ty - (self.y - h_up)
        t_down = math.sqrt(max(0.0, 2 * fall / g))
        self.vx = (tx - self.x) / max(0.15, t_up + t_down)
        self.vy = vy0
        self.airborne = True
        self.hop = False
        self.jump_target = info.hwnd
        self.facing = 1 if tx >= self.x else -1
        self.ground_v = 0.0
        self.squash_v = -7.0          # stretch as he pushes off

    def _try_start_perch(self) -> bool:
        if self.settings.get("roam_mode") != "windows" or self.perch_hwnd:
            return False
        info = self.fg
        if not self._perch_ok(info):
            return False
        mon = self._mon()
        if info.monitor.device != mon.device:
            return False
        r = info.rect
        if r.width() < 170 * self.s:
            return False
        lo = max(r.left() + 40 * self.s, mon.work.left() + 42 * self.s)
        hi = min(r.right() - 40 * self.s, mon.work.right() - 42 * self.s)
        if hi <= lo:
            return False
        self.perch_candidate = info.hwnd
        self.perch_tx = _clamp(self.x + random.uniform(-80, 80) * self.s, lo, hi)
        self._set("perch_approach")
        return True

    # ================================================================ brain
    def _classify(self) -> str:
        st = self.state
        if self.excite > 1.0 or (st == "excited" and self.excite > 0.45):
            return "excited"
        lo, hi = self._surface_range()
        target = _clamp(self.mx, lo, hi)
        gap = abs(target - self.x)
        if self.speed > SPEED_SLOW and gap > 55 * self.s:
            self.walk_target = target
            return "trot" if self.speed > SPEED_TROT else "walk"
        if st in ("walk", "trot") and gap > 10 * self.s and self.still < 1.2:
            self.walk_target = target
            return st
        bored = float(self.settings.get("bored_after"))
        if self.still > bored + 13:
            return "bored_lie"
        if self.still > bored:
            return "bored_sit"
        return "calm"

    def _think(self, dt: float) -> None:
        st = self.state
        if self.airborne or self.in_house and st != "in_house":
            return

        if st in ROAM_STATES and self.idle > float(self.settings.get("sleep_after")):
            self._set("drowsy")
            return

        if st == "drowsy":
            if self.moved_now and self.state_t > 0.4:
                self._set("wake_ears")
            elif self.state_t > 3.6:
                self._set("sleep")
        elif st == "sleep":
            if self.moved_now:
                self._set("wake_ears")
            elif self.t > self.next_bubble:
                self.next_bubble = self.t + 1.3
                self._say("z", life=2.4, dx=random.uniform(-4, 6), vx=7, vy=-16,
                          size=random.uniform(0.75, 1.15))
        elif st == "wake_ears":
            if self.moved_now:
                self.wake_active += dt
                self.wake_last = self.t
            if self.t - self.wake_last > 2.6:
                self._set("sleep")
            elif self.wake_active >= 1.6:
                self._set("wake_stretch")
        elif st == "wake_stretch":
            if self.state_t > 2.3:
                self.still = 0.0
                self._set("calm")
        elif st in ("growl", "obey"):
            if self.state_t > self.react_dur:
                self._set("calm")
        elif st == "startled":
            if self.state_t > 0.75:
                self._set("sprint")
        elif st == "sprint":
            self._sprint_logic()
        elif st == "intro_run":
            self.walk_target = self.intro_target
            if (abs(self.x - self.intro_target) < 6 * self.s and abs(self.ground_v) < 40 * self.s) \
                    or self.state_t > 7.0:
                self.offscreen_ok = False
                self._set("intro_hello")
        elif st == "intro_hello":
            if self.state_t > 2.1:
                self.still = 0.0
                self._set("calm")
        elif st == "outro_wave":
            if self.state_t > 1.7:
                work = self._mon().work
                left = self.x - work.left() < work.right() - self.x
                self.exit_x = work.left() - 110 * self.s if left else work.right() + 110 * self.s
                self.offscreen_ok = True
                self._say("heart", life=1.2, vy=-30, size=0.9)
                self._set("outro_run")
        elif st == "outro_run":
            self.walk_target = self.exit_x
            if abs(self.x - self.exit_x) < 10 * self.s or self.state_t > 4.5:
                self._finish_outro()
        elif st == "in_house":
            if self.house.view == "closed":
                # asleep out of sight: only a click on the house, or you being busy for
                # a few minutes and then moving the mouse fast, gets him out
                need = float(self.settings.get("house_wake_minutes")) * 60.0
                busy = self.t - self.active_since
                if busy >= need and self.speed > SPEED_TROT and self.state_t > 3.0:
                    self.leave_house()
            elif self.state_t > self.house_stay:
                self.leave_house()
        elif st == "exit_house":
            if abs(self.x - self.exit_target) < 4 * self.s or self.state_t > 4.5:
                self._set("calm")
                self.house.hide_house()
        elif st == "perch_approach":
            info = self.monitor.window_info(self.perch_candidate)
            mon = self._mon()
            if not self._perch_ok(info) or self.excite > 1.2 or self.state_t > 8.0:
                self._set("calm")
                return
            lo = max(info.rect.left() + 40 * self.s, mon.work.left() + 42 * self.s)
            hi = min(info.rect.right() - 40 * self.s, mon.work.right() - 42 * self.s)
            if hi <= lo:
                self._set("calm")
                return
            self.perch_tx = _clamp(self.perch_tx, lo, hi)
            self.walk_target = self.perch_tx
            if abs(self.x - self.perch_tx) < 6 * self.s:
                self._jump_to(info, self.perch_tx)
                self._set("calm")
        else:
            self._roam_logic(dt)

    def _roam_logic(self, dt: float) -> None:
        st = self.state
        mood = self._classify()
        min_time = {"excited": 1.4, "walk": 0.35, "trot": 0.35, "calm": 0.25}.get(st, 0.0)
        if mood != st and (self.state_t >= min_time or mood in ("walk", "trot", "excited")
                           and st in ("bored_sit", "bored_lie")):
            self._set(mood)
            st = mood

        if st == "excited":
            if self.t > self.next_bubble:
                self.next_bubble = self.t + random.uniform(0.35, 0.7)
                self._say(random.choice(("note", "heart", "note")), life=1.4,
                          dx=random.uniform(-14, 14), vx=random.uniform(-14, 14),
                          vy=-38, size=random.uniform(0.8, 1.2))
            if self.t > self.next_hop:
                self.next_hop = self.t + random.uniform(0.45, 0.95)
                self.airborne = True
                self.hop = True
                self.jump_target = self.perch_hwnd
                if self.perch_hwnd:
                    self.perch_hwnd = 0      # re-acquired on landing
                self.vy = -math.sqrt(2 * GRAVITY * self.s * random.uniform(14, 26) * self.s)
                self.vx = 0.0
                if random.random() < 0.3:
                    self.facing = -self.facing   # happy spin
        elif st in ("bored_sit", "bored_lie"):
            if self.t > self.next_yawn:
                self.next_yawn = self.t + random.uniform(7, 12)
                self.yawn_until = self.t + 1.8
            if self.t > self.next_look:
                self.next_look = self.t + random.uniform(4, 7)
                self.look_until = self.t + 2.4

        # periodic curiosity: hop onto the active window / back down
        if self.perch_hwnd:
            self.perch_stay -= dt
            if self.perch_stay <= 0 and st in ("calm", "walk", "excited"):
                self._jump_down()
        elif st in ("calm", "excited", "trot", "walk"):
            self.perch_timer -= dt
            if self.perch_timer <= 0:
                self.perch_timer = random.uniform(18, 40)
                self._try_start_perch()

    # ------------------------------------------------------------ doghouse
    def run_home(self) -> None:
        """10-click trigger (also callable from the Settings window)."""
        if self.in_house or self.state in ("startled", "sprint"):
            return
        self.click_count = 0
        self.house_called = False
        if self._dragging:
            self._dragging = False
            self._press = None
            self.unsetCursor()
        if self.perch_hwnd:
            # hop down first; the house is planned on the taskbar of this screen
            self._jump_down()
        elif not self.airborne:
            self.vy = -math.sqrt(2 * GRAVITY * self.s * 18 * self.s)
            self.vx = 0.0
            self.airborne = True
            self.hop = True
            self.jump_target = 0
        self.home_door = self.house.plan_arrival(self.x, self._mon())
        self._set("startled")

    def _sprint_logic(self) -> None:
        if self.perch_hwnd:
            self._jump_down()
            return
        door = self.house.target_door_point()
        house_mon = self.monitor.monitor_at(door.x(), door.y() - 4)
        mon = self._mon()
        if house_mon.device != mon.device:
            # dash off this screen and pop in from the nearest edge of the other one
            work = house_mon.work
            edge = work.left() + 42 * self.s if door.x() > self.x else work.right() - 42 * self.s
            self.x = edge
            self.y = self._ground_y(house_mon)
        self.walk_target = door.x()
        # call the house in so it finishes sliding just as the pup gets there
        if not self.house_called:
            speed = 600 * self.s * float(self.settings.get("walk_speed"))
            eta = abs(door.x() - self.x) / max(1.0, speed)
            if self.state_t >= MIN_RUN_TIME * 0.5 and eta <= self.house.SLIDE_IN + 0.25:
                self.house_called = True
                self.house.start_arrival()
                self.raise_()
        if abs(self.x - door.x()) < 6 * self.s:
            if self.house.is_arrived:
                self._enter_house()
            elif not self.house_called:
                self.house_called = True
                self.house.start_arrival()
                self.raise_()

    def _enter_house(self) -> None:
        self.in_house = True
        self._set("in_house")
        lo = float(self.settings.get("house_stay_min"))
        hi = max(lo, float(self.settings.get("house_stay_max")))
        self.house_stay = random.uniform(lo, hi)
        self.bubbles.clear()
        self.house.set_occupied(True)

    def leave_house(self) -> None:
        if not self.in_house:
            return
        self.in_house = False
        self.house.set_occupied(False)
        door = self.house.door_point()
        self.x, self.y = door.x(), door.y()
        self.vx = self.vy = 0.0
        self.airborne = False
        direction = self.house.exit_direction()
        lo, hi = self._surface_range()
        self.exit_target = _clamp(self.x + direction * 120 * self.s, lo, hi)
        if abs(self.exit_target - self.x) < 30 * self.s:
            self.exit_target = _clamp(self.x - direction * 120 * self.s, lo, hi)
        self.facing = 1 if self.exit_target >= self.x else -1
        self.facing_vis = float(self.facing)
        self.walk_target = self.exit_target
        self.still = 0.0
        self.excite = 0.0
        self._set("exit_house")
        self.raise_()

    # ============================================================= physics
    def _physics(self, dt: float) -> None:
        if self.in_house:
            self.move_speed = 0.0
            return
        if self.airborne:
            g = GRAVITY * self.s
            prev_y = self.y
            self.vy += g * dt
            self.vx *= math.exp(-AIR_DRAG * dt)            # a little air resistance
            self.x += self.vx * dt
            # bounce off the outer edges of the desktop when thrown
            work = self.monitor.monitor_at(self.x, None).work
            if ((self.x < work.left() + 30 * self.s and self.vx < 0)
                    or (self.x > work.right() - 30 * self.s and self.vx > 0)):
                self.vx = -self.vx * WALL_BOUNCE
                self._impact(abs(self.vx) * 0.6)
            new_y = self.y + self.vy * dt
            landed = False
            if self.vy > 0 and self.jump_target:
                info = self.monitor.window_info(self.jump_target)
                if info is not None and not info.minimized:
                    top = self._floor_of(info.rect)
                    if (prev_y <= top + 2 <= new_y + 2
                            and info.rect.left() + 10 <= self.x <= info.rect.right() - 10):
                        self.y = top
                        self.perch_hwnd = info.hwnd
                        self.perch_rect = info.rect
                        if not self.hop:
                            self.perch_stay = random.uniform(25, 60)
                        landed = True
            if not landed:
                ground = self._ground_y(self.monitor.monitor_at(self.x, None))
                if new_y >= ground:
                    self.y = ground
                    self.perch_hwnd = 0
                    self.perch_rect = None
                    landed = True
                else:
                    self.y = new_y
            if landed:
                impact = self.vy
                self._impact(impact * (0.5 if self.hop else 1.0))
                if (not self.hop and not self.perch_hwnd
                        and impact > BOUNCE_MIN * self.s):
                    # thrown hard: bounce up a little instead of stopping dead
                    self.vy = -impact * BOUNCE
                    self.vx *= 0.65
                else:
                    self.airborne = False
                    self.hop = False
                    self.jump_target = 0
                    self.ground_v = self.vx * SLIDE_KEEP   # carry some momentum (slide)
                    self.vx = self.vy = 0.0
                    if not self.perch_hwnd:
                        self.y = self._ground_y()
            self._clamp_to_desktop()
            self.move_speed = 0.0
            return

        speed = {"walk": 95, "trot": 215, "perch_approach": 200, "exit_house": 100,
                 "sprint": 600, "intro_run": 380, "outro_run": 560,
                 }.get(self.state, 0) * self.s * float(self.settings.get("walk_speed"))
        lo, hi = self._surface_range()
        free = self.state in ("sprint", "intro_run", "outro_run")   # may run past the edges
        if not free:
            self.walk_target = _clamp(self.walk_target, lo, hi)
        # momentum: speed up / slow down smoothly and ease in to the target
        dx = self.walk_target - self.x
        if speed > 0 and abs(dx) > 0.5:
            accel = (3200.0 if self.state == "sprint" else 1400.0) * self.s
            desired = math.copysign(min(speed, math.sqrt(2 * accel * 0.85 * abs(dx))), dx)
            if abs(dx) > 2 * self.s:
                self._face(1 if dx > 0 else -1, force=True)
        else:
            accel = 1600.0 * self.s                       # friction when not walking
            desired = 0.0
        self.ground_v += _clamp(desired - self.ground_v, -accel * dt, accel * dt)
        if speed > 0 and dx * self.ground_v < 0 and abs(dx) < 3 * self.s:
            self.ground_v = 0.0                           # don't overshoot the target
        self.x += self.ground_v * dt
        self.move_speed = abs(self.ground_v)
        if not free:
            if self.x < lo or self.x > hi:
                self.ground_v = 0.0
            self.x = _clamp(self.x, lo, hi)
        if not self.perch_hwnd:
            self.y = self._ground_y()
        self._clamp_to_desktop()

    def _impact(self, speed: float) -> None:
        """Squash the body on a landing / wall hit, proportional to the impact speed."""
        amount = _clamp(speed / (1700.0 * self.s), 0.0, 0.55)
        if amount > 0.03:
            self.squash_v = max(self.squash_v, amount * 16.0)

    def _secondary(self, dt: float) -> None:
        """Springy follow-through: squash & stretch, body lean, ear and tail lag."""
        vel = self.vx if self.airborne else self.ground_v
        ax = (vel - self._prev_vel) / dt
        self._prev_vel = vel
        self.accel_x += (ax - self.accel_x) * min(1.0, dt * 10.0)
        fwd = _clamp(self.accel_x * self.facing / (1000.0 * self.s), -1.6, 1.6)

        # squash: damped spring around 0 (positive = squashed flat, negative = stretched)
        self.squash_v += (-SQUASH_K * self.squash - SQUASH_D * self.squash_v) * dt
        self.squash += self.squash_v * dt

        # ears & tail are dragged backwards when he speeds up, flung forward when he stops
        for pos, vel_name, k, d, gain in (("ear_sp", "ear_v", 140.0, 7.0, 260.0),
                                          ("tail_sp", "tail_v", 90.0, 6.0, 180.0)):
            p_, v_ = getattr(self, pos), getattr(self, vel_name)
            v_ += (-k * p_ - d * v_ + gain * fwd) * dt
            p_ = _clamp(p_ + v_ * dt, -40.0, 40.0)
            setattr(self, pos, p_)
            setattr(self, vel_name, v_)

    def _clamp_to_desktop(self) -> None:
        mon = self.monitor.monitor_at(self.x, None)
        work = mon.work
        if not self.offscreen_ok:       # the hello / goodbye runs start / end off-screen
            self.x = _clamp(self.x, work.left() + 30 * self.s, work.right() - 30 * self.s)
        if self.y > self._ground_y(mon):
            self.y = self._ground_y(mon)
        self.y = max(self.y, float(work.top()) + 40 * self.s)

    def _face(self, direction: int, force: bool = False) -> None:
        if direction == self.facing:
            return
        if force or self.t - self.last_turn > 0.8:
            self.facing = direction
            self.last_turn = self.t

    # ============================================================ animation
    def _look(self) -> tuple[float, float]:
        hx = self.x + self.facing * 30 * self.s
        hy = self.y - 62 * self.s
        dx = (self.mx - hx) * self.facing
        dy = self.my - hy
        return _clamp(dx / 260.0, -1, 1), _clamp(dy / 260.0, -1, 1)

    def _animate(self, dt: float) -> None:
        st, t, T = self.state, self.t, self.state_t
        lookx, looky = self._look()
        tgt: cr.Pose

        # body turns toward the cursor when it is behind him
        if st in ("calm", "excited", "bored_sit", "growl", "obey") and not self.airborne:
            if lookx < -0.35:
                before = self.facing
                self._face(-self.facing)
                if self.facing != before:
                    lookx = -lookx

        if self.state_t < 0.02 and st != "calm":
            self.phase = 0.0
        stride = 62.0 if st in ("sprint", "intro_run", "outro_run") \
            else 30.0 if self.upright else 40.0
        self.phase += self.move_speed * dt / (stride * self.s) * math.pi * 2

        if self._dragging:
            tgt = cr.pose("dangle", mouth="o", brow="raised")
            dvx = self._drag_velocity()[0]
            sw = _clamp(-dvx * 0.03, -35, 35)
            for leg in ("fna", "ffa", "bna", "bfa"):
                tgt[leg] += sw + 6 * math.sin(t * 9 + len(leg))
            tgt["ear"] = 0.55 + _clamp(abs(dvx) * 0.0006, 0, 0.4)
            tgt["flap"] = 10 * math.sin(t * 12)
            tgt["ta"] = 150 + sw
        elif self.airborne and not self.hop:
            falling = self.vy > 0
            tgt = cr.pose("jump", mouth="o" if falling else "smile",
                          brow="raised" if falling else "neutral")
            if falling:
                tgt["fna"], tgt["ffa"], tgt["bna"], tgt["bfa"] = 14, 22, -12, -18
                tgt["ear"] = 0.95
                tgt["flap"] = 8 * math.sin(t * 16)
            tgt["eye"] = 1.15 if falling else 1.0
        elif st == "calm":
            tgt = cr.pose("upright" if self.upright else "stand", mouth="smile")
            if t > self.next_tilt:
                self.next_tilt = t + random.uniform(2.5, 5.0)
                self.tilt_target = random.choice((0, 0, -9, 9)) if self.speed < SPEED_SLOW else 0
            tgt["hrot"] += self.tilt_target
            tgt["ear"] = 0.28 + 0.06 * math.sin(t * 1.4)
            tgt["ta"] = 35 + 12 * math.sin(t * 2 * math.pi * 1.0)
            # now and then he sits up on his hind legs and begs
            if t > self.next_beg:
                self.next_beg = t + random.uniform(12, 25)
                if self.settings.get("sit_up_idle") and self.speed < SPEED_SLOW:
                    self.beg_until = t + random.uniform(3.0, 4.5)
            if self.upright:
                sway = math.sin(t * 2.2)
                tgt["fna"] += 6 * sway
                tgt["ffa"] -= 6 * sway
                tgt["ta"] = 118 + 10 * math.sin(t * 2 * math.pi * 1.0)
            elif t < self.beg_until:
                tgt = cr.pose("beg", mouth="smile")
                tgt["tongue"] = 0.6
                tgt["ear"] = 0.35
                wiggle = 9 * math.sin(t * 7)
                tgt["fna"] += wiggle
                tgt["ffa"] -= wiggle
                tgt["ta"] = 100 + 8 * math.sin(t * 9)
        elif st in ("walk", "trot", "perch_approach", "exit_house"):
            trot = st in ("trot", "perch_approach")
            if self.upright:
                tgt = cr.pose("upright", mouth="smile")
                cr.apply_upright_walk(tgt, self.phase, 34 if trot else 26, 3.4 if trot else 2.4)
                tgt["ta"] = 118 + 14 * math.sin(t * 2 * math.pi * (2.6 if trot else 1.8))
            else:
                tgt = cr.pose("stand", mouth="smile")
                cr.apply_walk(tgt, self.phase, 34 if trot else 24, 3.2 if trot else 1.8)
                tgt["ta"] = 40 + 16 * math.sin(t * 2 * math.pi * (2.6 if trot else 1.8))
            tgt["ear"] = 0.55 if trot else 0.4
            tgt["flap"] = 6 * math.sin(self.phase)
            tgt["tongue"] = 0.5 if trot else 0.0
            tgt["hrot"] += 3 if trot else 0
        elif st == "excited":
            happy_eyes = (t % 2.2) < 1.2
            tgt = cr.pose("upright" if self.upright else "stand",
                          mouth="grin" if happy_eyes else "pant",
                          eyes="happy" if happy_eyes else "normal")
            if self.upright:
                cr.apply_upright_walk(tgt, t * 10.0, 30, 4.0)
            tgt["ear"] = 0.62
            tgt["flap"] = 30 * math.sin(t * 2 * math.pi * 4.5)
            tgt["tongue"] = 1.0
            tgt["blush"] = 1.0
            tgt["ta"] = 30 + 26 * math.sin(t * 2 * math.pi * 5)
            if self.airborne:
                tgt["fna"], tgt["ffa"], tgt["bna"], tgt["bfa"] = 30, 38, -30, -36
        elif st in ("bored_sit", "bored_lie"):
            lie = st == "bored_lie"
            tgt = cr.pose("lie" if lie else "sit", mouth="flat",
                          brow="sad" if lie else "neutral")
            tgt["eye"] = 0.55 if lie else 0.68
            tgt["ear"] = 0.0 if lie else 0.06
            tgt["ta"] += 5 * math.sin(t * 2 * math.pi * 0.3)
            if t < self.look_until:
                lookx = math.sin((self.look_until - t) * 2.6) * 1.0
                looky = -0.3
                tgt["eye"] = 0.9
                tgt["hrot"] += lookx * 5
            if t < self.yawn_until:
                tgt.mouth = "yawn"
                tgt["eye"] = 0.08
                tgt["hrot"] -= 16
                tgt["hy"] -= 4
                tgt.brow = "none"
        elif st == "drowsy":
            tgt = cr.pose("lie", mouth="flat", brow="sad")
            tgt["eye"] = max(0.06, 0.5 - T * 0.13)
            tgt["hy"] += 3.0 * max(0.0, math.sin(T * 2 * math.pi * 0.55))
            tgt["hrot"] += 8 * max(0.0, math.sin(T * 2 * math.pi * 0.55))
            tgt["ear"] = 0.0
        elif st == "sleep":
            tgt = cr.pose("curl", mouth="smile", eyes="closed", brow="none")
            tgt["eye"] = 0.0
            tgt["breath"] = 1.0 + 0.06 * math.sin(t * 2 * math.pi / 3.4)
            tgt["hy"] += 0.8 * math.sin(t * 2 * math.pi / 3.4)
        elif st == "wake_ears":
            tgt = cr.pose("curl", mouth="smile", eyes="closed", brow="none")
            tgt["eye"] = 0.0
            tgt["ear"] = 1.0          # ears shoot straight up, eyes still shut
            tgt["flap"] = 4 * math.sin(t * 7)
            tgt["breath"] = 1.0 + 0.04 * math.sin(t * 2 * math.pi / 3.4)
        elif st == "wake_stretch":
            if T < 1.3:
                tgt = cr.pose("stretch", mouth="yawn" if 0.25 < T < 1.15 else "flat",
                              eyes="closed" if T < 1.1 else "normal")
                tgt["eye"] = 0.3
                tgt["ta"] = 12 + 10 * math.sin(t * 6)
                tgt["ear"] = 0.1
            else:
                decay = max(0.0, 1.0 - (T - 1.3) / 0.9)
                tgt = cr.pose("stand", mouth="smile", eyes="happy" if T < 2.0 else "normal")
                w = math.sin(t * 2 * math.pi * 12)
                tgt["shakex"] = 3.2 * w * decay
                tgt["flap"] = 32 * w * decay
                tgt["ear"] = 0.45
                tgt["hrot"] += 6 * w * decay
                tgt["ta"] = 35 + 25 * w * decay
        elif st == "growl":
            tgt = cr.pose("stand", mouth="grr", brow="angry")
            tgt["bob"] = 3.0
            tgt["hy"] += 4
            tgt["hrot"] += 5
            tgt["ear"] = 0.0
            tgt["shakex"] = 1.2 * math.sin(t * 2 * math.pi * 26)
            tgt["ta"] = 55
            tgt["tc"] = 0.0
        elif st == "obey":
            tgt = cr.pose("sit", mouth="flat", brow="neutral")
            tgt["eye"] = 0.72
            tgt["ear"] = 0.04
            tgt["hrot"] -= 4
            tgt["ta"] += 4 * math.sin(t * 3)
        elif st == "startled":
            tgt = cr.pose("stand", mouth="o", brow="raised")
            tgt["eye"] = 1.3
            tgt["ear"] = 1.0
            tgt["flap"] = 5 * math.sin(t * 30)
            tgt["ta"] = 10
        elif st == "intro_hello":
            # skidded to a stop: happy sit, fast wag, ears perked
            tgt = cr.pose("sit", mouth="pant", eyes="happy" if (T % 1.6) < 1.0 else "normal")
            tgt["tongue"] = 1.0
            tgt["ear"] = 0.55 + 0.1 * math.sin(t * 9)
            tgt["ta"] = 95 + 22 * math.sin(t * 2 * math.pi * 4)
            tgt["blush"] = 0.8
            if T < 0.35:                      # little bounce as he plops down
                tgt["bob"] = -6 * math.sin(T / 0.35 * math.pi)
        elif st == "outro_wave":
            # sits up and waves goodbye with one front paw
            tgt = cr.pose("beg", mouth="smile")
            tgt["fna"] = 150 + 28 * math.sin(t * 11)
            tgt["fnl"] = 22
            tgt["ear"] = 0.4
            tgt["ta"] = 100 + 10 * math.sin(t * 8)
            tgt["hrot"] += 6 * math.sin(t * 5.5)
        elif st in ("sprint", "intro_run", "outro_run"):
            tgt = cr.pose("run", mouth="pant", brow="raised" if st == "sprint" else "neutral")
            cr.apply_gallop(tgt, self.phase)
            tgt["tongue"] = 1.0
            tgt["ear"] = 0.5
            tgt["flap"] = 14 * math.sin(self.phase)
        else:  # in_house / fallback
            tgt = cr.pose("stand")

        # always-on head & eye tracking for awake states
        awake = st in TRACKING_STATES or self._dragging or self.airborne
        if awake:
            if tgt.eyes == "normal" and t > self.next_blink:
                self.blink_until = t + 0.13
                self.next_blink = t + random.uniform(2.5, 6.0)
            if t < self.blink_until and tgt.eyes == "normal":
                tgt["eye"] = 0.0
            tgt["lookx"] = lookx
            tgt["looky"] = looky
            if st not in ("growl", "wake_stretch"):
                tgt["hrot"] += _clamp(looky * 11, -12, 12)

        k = 1.0 - math.exp(-dt * 16.0)
        cr.lerp_pose(self.pose, tgt, k)
        # crisp, non-smoothed components (high-frequency motion)
        self.pose["shakex"] = tgt["shakex"]
        self.pose["flap"] = tgt["flap"]
        if st in ("walk", "trot", "sprint", "perch_approach", "exit_house",
                  "intro_run", "outro_run") or self._dragging:
            for key in ("fna", "ffa", "bna", "bfa", "bob", "brot"):
                self.pose[key] += (tgt[key] - self.pose[key]) * min(1.0, dt * 30)

        # physics follow-through on top of the animation
        # (stored separately and added at paint time so the pose smoothing doesn't pile it up)
        self.lean = 0.0
        if not self._dragging and not self.in_house and not self.airborne \
                and st not in ("sleep", "drowsy", "wake_ears", "bored_lie"):
            fwd = _clamp(self.accel_x * self.facing / (1000.0 * self.s), -1.6, 1.6)
            self.lean = _clamp(fwd * 4.0, -6.0, 6.0)                    # lean into speed-ups

        step = dt * 9.0
        diff = self.facing - self.facing_vis
        self.facing_vis += _clamp(diff, -step, step)

    def _update_bubbles(self, dt: float) -> None:
        alive = []
        for b in self.bubbles:
            b.age += dt
            if b.age >= b.life:
                continue
            b.x += (b.vx + (6 * math.sin(b.age * 3 + b.wobble) if b.kind == "z" else 0)) * dt
            b.y += b.vy * dt
            alive.append(b)
        self.bubbles = alive

    def _update_visibility(self, dt: float) -> None:
        target = 0.0 if (self.in_house or self.hidden_fs) else 1.0
        rate = 8.0 if self.in_house else 3.0
        self.opacity += _clamp(target - self.opacity, -rate * dt, rate * dt)
        if self.opacity <= 0.01:
            if self.isVisible():
                self.hide()
        else:
            if not self.isVisible():
                self.show()
            if abs(self.windowOpacity() - self.opacity) > 0.01:
                self.setWindowOpacity(self.opacity)

    def _sprite_name(self) -> str:
        st = self.state
        if self._dragging:
            return "dragged"
        if self.airborne and not self.hop:
            return "fall" if self.vy > 0 else "jump"
        if st in ("bored_sit", "bored_lie") and self.t < self.yawn_until:
            return "yawn"
        if st == "wake_stretch":
            return "stretch" if self.state_t < 1.3 else "shake"
        if self.upright and st in UPRIGHT_STATES:
            if st == "calm" and self.animator.has("idle_upright"):
                return "idle_upright"
            if st != "calm" and self.animator.has("walk_upright"):
                return "walk_upright"
        if st == "calm" and self.t < self.beg_until and not self.upright:
            return "beg"
        return SPRITE_FOR_STATE.get(st, "idle")

    # ================================================================ paint
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.translate(self.width() / 2, self.height() - FOOT_PAD * self.s)
        p.scale(self.s, self.s)
        name = self._sprite_name()
        drawn = False
        if self.animator.has(name):
            p.save()
            p.translate(self.pose["shakex"], self.pose["bob"])
            drawn = self.animator.draw(p, name, self.state_t, self.facing_vis)
            p.restore()
        if not drawn:
            # squash & stretch around the feet (volume roughly preserved)
            sq = _clamp(self.squash, -0.3, 0.4)
            sx, sy = 1.0 + 0.45 * sq, 1.0 - 0.5 * sq
            if self.airborne and not self._dragging:
                st = _clamp(abs(self.vy) / (3000.0 * self.s), 0.0, 0.1)
                sx, sy = sx * (1.0 - 0.5 * st), sy * (1.0 + st)
            ps = self.pose
            if not self._dragging and not self.in_house:
                ps = self.pose.copy()
                ps["brot"] += self.lean
                ps["flap"] += self.ear_sp
                ps["ta"] += self.tail_sp
            p.save()
            p.scale(sx, sy)
            cr.draw_dog(p, ps, self.facing_vis)
            p.restore()
        for b in self.bubbles:
            cr.draw_bubble(p, b.kind, QPointF(b.x, b.y), b.alpha, b.age, b.size)
        p.end()

    # ================================================================ input
    def mousePressEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        g = e.globalPosition()
        self._press = (g.x(), g.y())
        self._press_off = (self.x - g.x(), self.y - g.y())
        self._drag_hist = [(self.t, g.x(), g.y())]

    def mouseMoveEvent(self, e) -> None:
        if self._press is None:
            return
        g = e.globalPosition()
        if self.state in ("outro_wave", "outro_run"):
            return                       # leaving: no dragging him back
        if not self._dragging and math.hypot(g.x() - self._press[0], g.y() - self._press[1]) > 6:
            self._dragging = True
            self.perch_hwnd = 0
            self.perch_rect = None
            self.airborne = False
            self.hop = False
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        if self._dragging:
            self.x = g.x() + self._press_off[0]
            self.y = g.y() + self._press_off[1]
            self._drag_hist.append((self.t, g.x(), g.y()))
            self._drag_hist = self._drag_hist[-8:]

    def _drag_velocity(self) -> tuple[float, float]:
        if len(self._drag_hist) < 2:
            return 0.0, 0.0
        t0, x0, y0 = self._drag_hist[0]
        t1, x1, y1 = self._drag_hist[-1]
        dt = max(0.016, t1 - t0)
        return (x1 - x0) / dt, (y1 - y0) / dt

    def mouseReleaseEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton or self._press is None:
            return
        self._press = None
        if self._dragging:
            self._dragging = False
            self.unsetCursor()
            vx, vy = self._drag_velocity()
            lim = 1400 * self.s
            self.vx = _clamp(vx * 0.5, -lim, lim)
            self.vy = _clamp(vy * 0.5, -lim, lim)
            self.airborne = True
            self.hop = False
            self.jump_target = 0
            if self.state in ("sleep", "drowsy", "wake_ears", "bored_sit", "bored_lie",
                              "perch_approach", "dragged", "intro_run", "intro_hello"):
                self.offscreen_ok = False
                self._set("calm")
            self.still = 0.0
            return
        self._on_click()

    def _on_click(self) -> None:
        if self.in_house or self.state in ("startled", "sprint", "exit_house", "intro_run",
                                           "outro_wave", "outro_run"):
            return
        if self.t - self.last_click > CLICK_WINDOW:
            self.click_count = 0
        self.click_count += 1
        self.last_click = self.t
        if self.click_count >= int(self.settings.get("clicks_to_home")):
            self.run_home()
            return
        if self.state in ("sleep", "drowsy"):
            self._set("wake_ears")
            self.wake_active = 0.9
            return
        if self.state == "wake_ears":
            self.wake_active += 0.5
            self.wake_last = self.t
            return
        # alternate-ish between a grumpy growl and an obedient sit
        if self.last_reaction and random.random() < 0.65:
            kind = "obey" if self.last_reaction == "growl" else "growl"
        else:
            kind = random.choice(("growl", "obey"))
        self.last_reaction = kind
        self.react_dur = 1.35 if kind == "growl" else 1.7
        if self.state == kind:
            self.state_t = 0.0
            if kind == "growl":
                self._say("grr", life=self.react_dur, dy=-10, vy=-4, size=0.95)
        else:
            self.state = ""          # force re-entry effects
            self._set(kind)

    def bring_to(self, point) -> None:
        """Drop the pup from the top of the screen containing `point`."""
        if self.in_house or self.state in ("startled", "sprint"):
            return
        mon = self.monitor.monitor_at(point.x(), point.y())
        work = mon.work
        self.perch_hwnd = 0
        self.perch_rect = None
        self.x = float(min(max(point.x(), work.left() + 60), work.right() - 60))
        self.y = float(work.top() + 80 * self.s)
        self.vx = self.vy = 0.0
        self.airborne = True
        self.hop = False
        self.jump_target = 0
        self.still = 0.0
        if self.state not in ROAM_STATES:
            self._set("calm")

    def contextMenuEvent(self, e) -> None:
        if self.context_menu is not None:
            self.context_menu.popup(e.globalPos())

    def wheelEvent(self, e) -> None:
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            step = 0.1 if e.angleDelta().y() > 0 else -0.1
            self.settings.set("scale", self.s + step)
            e.accept()
        else:
            e.ignore()

    # ============================================================ settings
    def _on_setting(self, key: str, value) -> None:
        if key == "scale":
            self.s = float(value)
            self._resize()
            self._place()
        elif key == "proportions":
            cr.set_proportions(value)
            self.house.update()
        elif key == "gait":
            self.upright = value == "two"
        elif key == "perch_spot":
            if self.perch_hwnd:
                self._fall_from_perch()      # re-perches at the new spot next time
            if self.state == "perch_approach":
                self._set("calm")
        elif key == "roam_mode" and value != "windows":
            if self.perch_hwnd:
                self._jump_down()
            if self.state == "perch_approach":
                self._set("calm")

    # ======================================================= hello / goodbye
    def _start_intro(self) -> None:
        """App start: gallop in from a screen edge, skid to a stop, happy hello."""
        work = self.monitor.primary().work
        self.intro_target = self.x
        from_left = random.random() < 0.5
        self.x = work.left() - 90 * self.s if from_left else work.right() + 90 * self.s
        self.walk_target = self.intro_target
        self.facing = 1 if from_left else -1
        self.facing_vis = float(self.facing)
        self.offscreen_ok = True
        self.state = "intro_run"
        self.state_t = 0.0
        self.pose = cr.pose("run")

    def goodbye(self, done) -> None:
        """App quit: wave goodbye, then gallop off the nearest edge; `done()` when gone."""
        if self._outro_done is not None:          # Quit pressed again -> don't wait
            self._finish_outro()
            return
        self._outro_done = done
        if self.in_house:
            # the house (with him in it) slides away instead
            self.house.set_occupied(False)
            self.house.depart()
            QTimer.singleShot(int(self.house.SLIDE_OUT * 1000) + 150, self._finish_outro)
            return
        visible = self.isVisible() and self.opacity > 0.5 and not self.hidden_fs
        if not self.settings.get("intro_outro") or not visible:
            self._finish_outro()
            return
        self.house.hide_house()
        if self._dragging:
            self._dragging = False
            self._press = None
            self.unsetCursor()
        if self.perch_hwnd:
            self._fall_from_perch()
        self.bubbles.clear()
        self.state = ""                        # force the entry effects
        self._set("outro_wave")
        self._say("dots", life=1.4, size=0.9)

    def _finish_outro(self) -> None:
        done, self._outro_done = self._outro_done, (lambda: None)
        if done is not None:
            done()

    def shutdown(self) -> None:
        self.timer.stop()
