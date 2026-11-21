"""Persistent JSON settings with change notifications."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal

APP_NAME = "DesktopPup"

DEFAULTS: dict[str, Any] = {
    "scale": 0.6,                    # 0.5 .. 2.5
    "proportions": "cartoon",        # cartoon (big head, stubby legs) | beagle (realistic)
    "doghouse_direction": "front",   # front (see Snoopy in front) | side (auto left/right by screen side)
    "house_wake_minutes": 3,         # "closed" view: comes out after you've been active this long + a fast mouse move
    "doghouse_half_out": True,       # side views: head & paws out of the door
    "doghouse_x": None,              # logical global X of the house centre (None = auto)
    "roam_mode": "windows",          # windows (taskbar + active windows) | taskbar
    "hide_in_fullscreen": True,      # fade the pup out while a fullscreen app is active
    "house_arrival": "far",          # far | left | right | random  (screen side the house slides in from)
    "house_parking": "edge",         # edge (parks near the side it came from) | saved (dragged spot)
    "clicks_to_home": 10,            # clicks in a row that send the pup running home
    "bored_after": 15,               # seconds of a still cursor before boredom
    "sleep_after": 60,               # seconds of system idle before sleep
    "house_stay_min": 18,            # seconds spent inside the doghouse
    "house_stay_max": 38,
    "walk_speed": 1.0,               # movement speed multiplier
    "excite_sensitivity": 1.0,       # how easily fast mouse movement excites him
    "sit_up_idle": True,             # sometimes sits up on his hind legs when idle
    "gait": "two",                   # two (upright on hind legs like Snoopy) | mix | four
    "intro_outro": True,             # hello animation at start-up, goodbye wave when quitting
    "perch_spot": "top",            # top (on the title bar) | inside (on the window's bottom edge)
}

NUMERIC_LIMITS: dict[str, tuple[float, float, type]] = {
    "clicks_to_home": (3, 30, int),
    "house_wake_minutes": (1, 60, int),
    "bored_after": (5, 300, int),
    "sleep_after": (20, 1800, int),
    "house_stay_min": (3, 600, int),
    "house_stay_max": (3, 600, int),
    "walk_speed": (0.4, 2.5, float),
    "excite_sensitivity": (0.2, 3.0, float),
}

MIN_SCALE = 0.5
MAX_SCALE = 2.5


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


class SettingsManager(QObject):
    changed = pyqtSignal(str, object)  # key, new value

    def __init__(self, path: Path | None = None):
        super().__init__()
        self.path = path or (config_dir() / "settings.json")
        self._data: dict[str, Any] = dict(DEFAULTS)
        self.load()

    # ------------------------------------------------------------------ io
    def load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                stored = json.load(fh)
            if isinstance(stored, dict):
                for key, value in stored.items():
                    if key in DEFAULTS:
                        self._data[key] = value
        except (OSError, ValueError):
            pass
        self._sanitize()

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def _sanitize(self) -> None:
        try:
            self._data["scale"] = min(MAX_SCALE, max(MIN_SCALE, float(self._data["scale"])))
        except (TypeError, ValueError):
            self._data["scale"] = DEFAULTS["scale"]
        if self._data["doghouse_direction"] in ("left", "right", "closed"):
            self._data["doghouse_direction"] = "side"     # all side views are door-free now
        if self._data["doghouse_direction"] not in ("front", "side"):
            self._data["doghouse_direction"] = "front"
        if self._data["roam_mode"] not in ("windows", "taskbar"):
            self._data["roam_mode"] = "windows"
        if self._data["proportions"] not in ("cartoon", "beagle"):
            self._data["proportions"] = "cartoon"
        if self._data["house_arrival"] not in ("far", "left", "right", "random"):
            self._data["house_arrival"] = "far"
        if self._data["house_parking"] not in ("edge", "saved"):
            self._data["house_parking"] = "edge"
        if self._data["gait"] not in ("four", "two", "mix"):
            self._data["gait"] = "four"
        if self._data["perch_spot"] not in ("top", "inside"):
            self._data["perch_spot"] = "top"
        for key in NUMERIC_LIMITS:
            self._data[key] = self._coerce(key, self._data[key])
        if self._data["house_stay_max"] < self._data["house_stay_min"]:
            self._data["house_stay_max"] = self._data["house_stay_min"]
        if self._data["doghouse_x"] is not None:
            try:
                self._data["doghouse_x"] = int(self._data["doghouse_x"])
            except (TypeError, ValueError):
                self._data["doghouse_x"] = None
        for key in ("doghouse_half_out", "hide_in_fullscreen", "sit_up_idle", "intro_outro"):
            self._data[key] = bool(self._data[key])

    @staticmethod
    def _coerce(key: str, value: Any) -> Any:
        lo, hi, typ = NUMERIC_LIMITS[key]
        try:
            num = float(value)
        except (TypeError, ValueError):
            num = float(DEFAULTS[key])
        num = min(hi, max(lo, num))
        return int(round(num)) if typ is int else round(num, 2)

    def reset_defaults(self) -> None:
        for key, value in DEFAULTS.items():
            if key != "doghouse_x":
                self.set(key, value)

    # ------------------------------------------------------------- access
    def get(self, key: str) -> Any:
        return self._data.get(key, DEFAULTS.get(key))

    def set(self, key: str, value: Any) -> None:
        if key == "scale":
            value = round(min(MAX_SCALE, max(MIN_SCALE, float(value))), 2)
        elif key in NUMERIC_LIMITS:
            value = self._coerce(key, value)
        if self._data.get(key) == value:
            return
        self._data[key] = value
        self.save()
        self.changed.emit(key, value)

    @property
    def scale(self) -> float:
        return float(self._data["scale"])
