"""Flat 2D comic-strip renderer (QPainter) + optional PNG sprite animator.

Everything is drawn in *units*: 1 unit == 1 logical pixel at scale 1.0.  The caller
translates the painter to the character's feet (origin = ground contact point,
y grows downward, the dog stands on y == 0) and scales by the user's size factor.

The built-in character is "Biscuit", an original black-and-white comic beagle
pup (black ears, saddle and head cap, white-tipped tail, red collar).  All posture data is facing RIGHT; the renderer mirrors for facing left.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (QBrush, QColor, QFont, QPainter, QPainterPath, QPen,
                         QPixmap, QPolygonF, QTransform)

# ----------------------------------------------------------------- palette
INK = QColor("#1b1b1b")
FUR = QColor("#fdfdfa")
FUR_SHADE = QColor("#e2e2dc")
PATCH = QColor("#1f1f1f")
PATCH_DARK = QColor("#2e2e2e")
EAR_FOLD = QColor(255, 255, 255, 170)   # white sketch highlight on black ears
NOSE = INK
COLLAR = QColor("#d63b2f")
TAG = QColor("#f2c230")
TONGUE = QColor("#f2788a")
MOUTH = QColor("#5a1c1c")
WHITE = QColor("#ffffff")
HEART = QColor("#e8384f")
NOTE = QColor("#3a6fd8")

WALL = QColor("#d8372b")
WALL_SHADE = QColor("#b42b21")
WALL_LINE = QColor("#9c2219")
ROOF = QColor("#e0382b")
ROOF_SHADE = QColor("#c22c20")
ROOF_LINE = QColor("#9c2219")
DOOR = QColor("#1d1210")
WOOD = QColor("#8a5a3b")
BONE = QColor("#fdf3dc")

INK_W = 2.6
COMIC_FONT = "Comic Sans MS"


def _pen(width: float = INK_W, color: QColor = INK) -> QPen:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


# =================================================================== POSES
class Pose:
    """Continuous skeleton values (lerpable) + discrete expression choices."""
    __slots__ = ("v", "mouth", "brow", "eyes")

    def __init__(self, v: dict[str, float], mouth: str = "smile",
                 brow: str = "neutral", eyes: str = "normal"):
        self.v = dict(v)
        self.mouth = mouth   # smile | flat | frown | pant | grr | yawn | o
        self.brow = brow     # neutral | angry | raised | sad | none
        self.eyes = eyes     # normal | happy | closed

    def copy(self) -> "Pose":
        return Pose(self.v, self.mouth, self.brow, self.eyes)

    def __getitem__(self, key: str) -> float:
        return self.v[key]

    def __setitem__(self, key: str, value: float) -> None:
        self.v[key] = value


_EXPR = dict(ear=0.15, flap=0.0, eye=1.0, lookx=0.0, looky=0.0, tongue=0.0,
             blush=0.0, breath=1.0, shakex=0.0, bob=0.0)


def _posture(**kw: float) -> dict[str, float]:
    d = dict(_EXPR)
    d.update(kw)
    return d


# Leg convention: hip (x, y); a = degrees from straight-down, positive swings the
# paw forward; l = length.  Tail: base (tx, ty), ta = degrees from straight-up,
# positive leans backward, tl = length, tc = curl.
POSTURES: dict[str, dict[str, float]] = {
    "stand": _posture(
        bx=-4, by=-36, bw=62, bh=30, brot=0, hx=30, hy=-64, hrot=0, nx0=14, ny0=-40,
        fnx=16, fny=-28, fna=0, fnl=28, ffx=9, ffy=-28, ffa=0, ffl=28,
        bnx=-22, bny=-28, bna=0, bnl=28, bfx=-29, bfy=-28, bfa=0, bfl=28,
        hax=-23, hay=-35, has=0.0, tx=-33, ty=-42, ta=35, tl=22, tc=0.35),
    "run": _posture(
        bx=-4, by=-38, bw=72, bh=26, brot=0, hx=36, hy=-56, hrot=8, nx0=20, ny0=-42,
        fnx=20, fny=-30, fna=0, fnl=28, ffx=14, ffy=-30, ffa=0, ffl=28,
        bnx=-26, bny=-30, bna=0, bnl=28, bfx=-32, bfy=-30, bfa=0, bfl=28,
        hax=-27, hay=-37, has=0.0, tx=-38, ty=-42, ta=75, tl=24, tc=0.2, ear=0.55),
    "jump": _posture(
        bx=-4, by=-40, bw=64, bh=28, brot=-10, hx=31, hy=-66, hrot=-6, nx0=15, ny0=-46,
        fnx=17, fny=-34, fna=45, fnl=22, ffx=11, ffy=-34, ffa=55, ffl=21,
        bnx=-22, bny=-30, bna=-40, bnl=24, bfx=-28, bfy=-30, bfa=-50, bfl=23,
        hax=-23, hay=-34, has=0.0, tx=-34, ty=-46, ta=25, tl=22, tc=0.2, ear=0.7),
    "sit": _posture(
        bx=-8, by=-33, bw=40, bh=50, brot=18, hx=14, hy=-74, hrot=0, nx0=2, ny0=-50,
        fnx=8, fny=-30, fna=0, fnl=30, ffx=2, ffy=-30, ffa=0, ffl=30,
        bnx=-14, bny=-7, bna=82, bnl=20, bfx=-19, bfy=-7, bfa=82, bfl=16,
        hax=-12, hay=-15, has=0.8, tx=-26, ty=-8, ta=100, tl=24, tc=0.45),
    "lie": _posture(
        bx=-12, by=-14, bw=68, bh=26, brot=0, hx=26, hy=-22, hrot=10, nx0=8, ny0=-20,
        fnx=12, fny=-6, fna=90, fnl=26, ffx=6, ffy=-5, ffa=90, ffl=24,
        bnx=-30, bny=-5, bna=86, bnl=16, bfx=-34, bfy=-5, bfa=86, bfl=12,
        hax=-30, hay=-13, has=1.1, tx=-44, ty=-14, ta=100, tl=24, tc=0.35, ear=0.0),
    "curl": _posture(
        bx=-2, by=-17, bw=72, bh=32, brot=0, hx=22, hy=-17, hrot=22, nx0=10, ny0=-18,
        fnx=14, fny=-5, fna=90, fnl=12, ffx=10, ffy=-5, ffa=90, ffl=10,
        bnx=-26, bny=-5, bna=90, bnl=10, bfx=-30, bfy=-5, bfa=90, bfl=8,
        hax=-24, hay=-15, has=1.0, tx=-34, ty=-10, ta=100, tl=24, tc=0.55, ear=0.0),
    "stretch": _posture(
        bx=-4, by=-36, bw=62, bh=28, brot=17, hx=34, hy=-36, hrot=6, nx0=18, ny0=-28,
        fnx=16, fny=-20, fna=62, fnl=26, ffx=10, ffy=-20, ffa=58, ffl=26,
        bnx=-24, bny=-42, bna=-4, bnl=42, bfx=-30, bfy=-42, bfa=-4, bfl=42,
        hax=-25, hay=-46, has=0.0, tx=-35, ty=-54, ta=12, tl=24, tc=0.4),
    # sitting up on the hind legs, front paws held up in front of the chest
    "beg": _posture(
        bx=-6, by=-33, bw=46, bh=36, brot=-70, hx=8, hy=-74, hrot=-6, nx0=0, ny0=-54,
        fnx=6, fny=-46, fna=112, fnl=20, ffx=1, ffy=-44, ffa=124, ffl=19,
        bnx=-8, bny=-7, bna=82, bnl=20, bfx=-13, bfy=-7, bfa=82, bfl=17,
        hax=-8, hay=-14, has=0.8, tx=-22, ty=-8, ta=100, tl=24, tc=0.4, ear=0.35),
    # standing / walking upright on the hind legs, front paws held like little arms
    "upright": _posture(
        bx=-5, by=-52, bw=46, bh=34, brot=-74, hx=7, hy=-94, hrot=-4, nx0=-1, ny0=-74,
        fnx=4, fny=-66, fna=28, fnl=22, ffx=-1, ffy=-64, ffa=40, ffl=21,
        bnx=-2, bny=-27, bna=4, bnl=28, bfx=-9, bfy=-27, bfa=-2, bfl=28,
        hax=-6, hay=-33, has=0.0, tx=-20, ty=-30, ta=118, tl=23, tc=0.35, ear=0.3),
    "dangle": _posture(
        bx=-4, by=-40, bw=60, bh=30, brot=0, hx=30, hy=-68, hrot=-4, nx0=14, ny0=-44,
        fnx=16, fny=-32, fna=-4, fnl=30, ffx=9, ffy=-32, ffa=4, ffl=30,
        bnx=-22, bny=-32, bna=-4, bnl=30, bfx=-29, bfy=-32, bfa=4, bfl=30,
        hax=-23, hay=-38, has=0.0, tx=-33, ty=-44, ta=150, tl=22, tc=0.2, ear=0.5),
}


def pose(name: str, mouth: str = "smile", brow: str = "neutral",
         eyes: str = "normal") -> Pose:
    return Pose(POSTURES[name], mouth, brow, eyes)


def lerp_pose(cur: Pose, tgt: Pose, k: float) -> None:
    """Move `cur` toward `tgt` by fraction k (in place)."""
    cv, tv = cur.v, tgt.v
    for key, value in tv.items():
        cv[key] = cv.get(key, value) + (value - cv.get(key, value)) * k
    cur.mouth, cur.brow, cur.eyes = tgt.mouth, tgt.brow, tgt.eyes


def apply_walk(p: Pose, phase: float, amp: float = 24.0, bob: float = 2.0) -> None:
    s = math.sin(phase)
    p["fna"] += amp * s
    p["bfa"] += amp * s
    p["ffa"] -= amp * s
    p["bna"] -= amp * s
    p["bob"] += -bob * abs(math.cos(phase))


def apply_upright_walk(p: Pose, phase: float, amp: float = 26.0, bob: float = 2.4) -> None:
    """Two-legged strut: hind legs alternate, front paws swing opposite, body sways."""
    s = math.sin(phase)
    p["bna"] += amp * s
    p["bfa"] -= amp * s
    p["fna"] -= amp * 0.8 * s
    p["ffa"] += amp * 0.8 * s
    p["brot"] += 3.0 * s
    p["hrot"] += 2.0 * s
    p["bob"] += -bob * abs(math.cos(phase))


def apply_gallop(p: Pose, phase: float, amp: float = 48.0) -> None:
    s, c = math.sin(phase), math.cos(phase)
    p["fna"] += amp * s + 8
    p["ffa"] += amp * math.sin(phase - 0.5) + 8
    p["bna"] += -amp * s - 6
    p["bfa"] += -amp * math.sin(phase - 0.5) - 6
    p["brot"] += 5 * c
    p["hy"] += 2 * c
    p["bob"] += -5 * abs(c)


# ============================================================== DOG DRAWING
def _limb(p: QPainter, a: QPointF, b: QPointF, width: float, fill: QColor) -> None:
    p.setPen(_pen(width + 2 * INK_W))
    p.drawLine(a, b)
    p.setPen(_pen(width, fill))
    p.drawLine(a, b)


def _tapered(p0: QPointF, ctrl: QPointF, p1: QPointF, w0: float, w1: float,
             n: int = 10, ease: float = 1.0) -> QPainterPath:
    """Smooth tapered stroke along a quadratic curve with rounded ends.

    ease > 1 keeps it thick near the start (a meaty thigh) and narrows it faster lower down.
    """
    left, right = [], []
    nrm0 = nrm1 = (0.0, 0.0)
    for i in range(n + 1):
        t = i / n
        mt = 1 - t
        x = mt * mt * p0.x() + 2 * mt * t * ctrl.x() + t * t * p1.x()
        y = mt * mt * p0.y() + 2 * mt * t * ctrl.y() + t * t * p1.y()
        dx = 2 * mt * (ctrl.x() - p0.x()) + 2 * t * (p1.x() - ctrl.x())
        dy = 2 * mt * (ctrl.y() - p0.y()) + 2 * t * (p1.y() - ctrl.y())
        ln = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / ln, dx / ln
        hw = (w1 + (w0 - w1) * (1 - t) ** ease) / 2
        left.append(QPointF(x + nx * hw, y + ny * hw))
        right.append(QPointF(x - nx * hw, y - ny * hw))
        if i == 0:
            nrm0 = (nx, ny)
        nrm1 = (nx, ny)
    poly = QPolygonF(left)
    a1 = math.atan2(nrm1[1], nrm1[0])
    for k in range(1, 6):
        a = a1 - k * math.pi / 6
        poly.append(QPointF(p1.x() + math.cos(a) * w1 / 2, p1.y() + math.sin(a) * w1 / 2))
    for pt in reversed(right):
        poly.append(pt)
    a0 = math.atan2(-nrm0[1], -nrm0[0])
    for k in range(1, 6):
        a = a0 - k * math.pi / 6
        poly.append(QPointF(p0.x() + math.cos(a) * w0 / 2, p0.y() + math.sin(a) * w0 / 2))
    path = QPainterPath()
    path.addPolygon(poly)
    path.closeSubpath()
    return path


def _leg_path(v: dict, key: str) -> tuple[QPainterPath, QPointF, QPointF]:
    """Leg outline: starts a little *inside* the body and has a thick, tapering thigh."""
    hip = QPointF(v[key + "x"], v[key + "y"])
    a = math.radians(v[key + "a"])
    length = v[key + "l"]
    d = (math.sin(a), math.cos(a))
    paw = QPointF(hip.x() + length * d[0], hip.y() + length * d[1])
    hind = key[0] == "b"
    root = QPointF(hip.x() - d[0] * 6, hip.y() - d[1] * 6)   # tucked up into the torso
    bend = -5.5 if hind else 1.8                     # hock curves back, wrist forward
    ctrl = QPointF((root.x() + paw.x()) / 2 + d[1] * bend,
                   (root.y() + paw.y()) / 2 - d[0] * bend)
    path = _tapered(root, ctrl, paw, 17.5 if hind else 14.5, 7.4, n=12,
                    ease=1.6 if hind else 1.4)
    return path, hip, paw


def _blend_leg_joint(p: QPainter, v: dict, key: str, fill: QColor,
                     body: QPainterPath) -> None:
    """Melt a leg into the body: erase the body outline where the leg meets it and
    redraw only the leg's side lines outside the body, so it reads as one shape."""
    path, hip, _paw = _leg_path(v, key)
    zone = QPainterPath()
    zone.addEllipse(hip, 15.0, 15.0)
    p.save()
    p.setClipPath(zone, Qt.ClipOperation.IntersectClip)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(fill)
    p.drawPath(path)
    p.restore()
    outside = zone.subtracted(body)
    p.save()
    p.setClipPath(outside, Qt.ClipOperation.IntersectClip)
    p.setPen(_pen())
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    p.restore()


def _leg(p: QPainter, v: dict, key: str, fill: QColor) -> None:
    path, _hip, paw = _leg_path(v, key)
    _outlined_path(p, path, fill)
    p.setPen(_pen(INK_W * 0.85))
    p.setBrush(fill)
    _draw_paw(p, paw, fill)


def _draw_paw(p: QPainter, at: QPointF, fill: QColor) -> None:
    """Iconic Snoopy flat oval foot with toe lines (images 2 & 3)."""
    x, y = at.x(), at.y()
    path = QPainterPath(QPointF(x - 5.5, y + 1.0))
    path.cubicTo(QPointF(x - 7.5, y - 3.5), QPointF(x - 2.0, y - 5.5), QPointF(x + 4.0, y - 4.5))
    path.cubicTo(QPointF(x + 11.0, y - 4.5), QPointF(x + 15.0, y - 1.5), QPointF(x + 14.0, y + 0.8))
    path.cubicTo(QPointF(x + 13.0, y + 2.4), QPointF(x - 3.0, y + 2.4), QPointF(x - 5.5, y + 1.0))
    path.closeSubpath()
    _outlined_path(p, path, fill, INK_W * 0.9)
    p.setPen(_pen(1.3))
    for tx in (6.0, 10.5):
        p.drawLine(QPointF(x + tx, y - 3.2), QPointF(x + tx + 0.2, y + 1.0))


def _ear_path() -> QPainterPath:
    """Iconic Snoopy floppy black ear: narrow base, smooth rounded paddle bottom."""
    path = QPainterPath(QPointF(-2.5, 0))
    path.cubicTo(QPointF(-7.5, 8), QPointF(-9.5, 20), QPointF(-6.0, 28))
    path.cubicTo(QPointF(-3.0, 34), QPointF(5.0, 34), QPointF(7.5, 27))
    path.cubicTo(QPointF(9.5, 20), QPointF(6.5, 8), QPointF(2.5, 0))
    path.closeSubpath()
    return path


def _draw_ear(p: QPainter, at: QPointF, angle: float, color: QColor,
              scale: float = 1.0) -> None:
    p.save()
    p.translate(at)
    p.rotate(angle)
    p.scale(scale, scale)
    p.setPen(_pen(INK_W / max(scale, 0.5)))
    p.setBrush(color)
    p.drawPath(_ear_path())
    p.restore()


def ear_angle(lift: float, flap: float) -> float:
    return _lerp(20.0, 172.0, max(0.0, min(1.0, lift))) + flap


def _outlined_path(p: QPainter, path: QPainterPath, fill: QColor,
                   width: float = INK_W) -> None:
    p.setPen(_pen(width))
    p.setBrush(fill)
    p.drawPath(path)


def _ink_with_halo(p: QPainter, path: QPainterPath, width: float) -> None:
    """Ink stroke with a thin white halo so it reads on black fur too."""
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(_pen(width + 2.2, WHITE))
    p.drawPath(path)
    p.setPen(_pen(width))
    p.drawPath(path)


def _draw_eye(p: QPainter, center: QPointF, openness: float, lookx: float,
              looky: float, style: str, big: float = 1.0, tilt: float = 0.0) -> None:
    ex, ey = center.x(), center.y()
    if style == "happy":
        path = QPainterPath(QPointF(ex - 2.8 * big, ey + 1.2 * big))
        path.quadTo(QPointF(ex, ey - 3.2 * big), QPointF(ex + 2.8 * big, ey + 1.2 * big))
        _ink_with_halo(p, path, 2.2)
        return
    if style == "closed" or openness < 0.12:
        path = QPainterPath(QPointF(ex - 2.8 * big, ey - 0.4 * big))
        path.quadTo(QPointF(ex, ey + 2.0 * big), QPointF(ex + 2.8 * big, ey - 0.4 * big))
        _ink_with_halo(p, path, 2.2)
        return
    op = min(max(openness, 0.12), 1.0)
    rx = 1.75 * big
    ry = 3.1 * op * big
    cx = ex + lookx * 1.0
    cy = ey + (1.0 - op) * 1.5 + looky * 1.0 * op
    p.save()
    p.translate(cx, cy)
    if tilt != 0.0:
        p.rotate(tilt)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(INK)
    p.drawEllipse(QPointF(0, 0), rx, ry)
    p.restore()


def _draw_brow(p: QPainter, eye: QPointF, style: str, lift: float = 0.0) -> None:
    if style == "none":
        return
    ex, by = eye.x(), eye.y() - 6.5 - lift
    path = QPainterPath()
    if style == "angry":
        path.moveTo(ex - 4.5, by - 2.0)
        path.lineTo(ex + 4.5, by + 2.0)
        bw = 2.8
    elif style == "sad":
        path.moveTo(ex - 4.5, by + 1.8)
        path.lineTo(ex + 4.5, by - 1.8)
        bw = 2.4
    elif style == "raised":
        path.moveTo(ex - 4.0, by - 0.5)
        path.quadTo(QPointF(ex, by - 4.0), QPointF(ex + 4.0, by - 0.8))
        bw = 2.2
    else:  # neutral
        path.moveTo(ex - 3.5, by + 0.4)
        path.quadTo(QPointF(ex, by - 2.0), QPointF(ex + 3.5, by + 0.3))
        bw = 2.0
    _ink_with_halo(p, path, bw)


def _draw_mouth(p: QPainter, kind: str, tongue: float) -> None:
    p.setBrush(Qt.BrushStyle.NoBrush)
    if kind == "grin":
        path = QPainterPath(QPointF(31.5, 4.0))
        path.quadTo(QPointF(22.0, 8.0), QPointF(9.5, 6.0))
        path.quadTo(QPointF(15.0, 20.0), QPointF(26.0, 13.0))
        path.quadTo(QPointF(31.0, 9.0), QPointF(31.5, 4.0))
        _outlined_path(p, path, WHITE, 2.0)
        p.setPen(_pen(1.8))
        p.drawLine(QPointF(10.5, 9.5), QPointF(30.5, 7.0))
        for tx in (14.5, 18.5, 22.5, 26.5):
            p.drawLine(QPointF(tx, 8.5), QPointF(tx + 0.5, 14.5))
        p.drawLine(QPointF(8.0, 4.0), QPointF(11.0, 8.5))
    elif kind == "pant":
        path = QPainterPath(QPointF(28.0, 5.5))
        path.quadTo(QPointF(20, 7.5), QPointF(11.5, 7.5))
        path.quadTo(QPointF(15, 20), QPointF(23.5, 15.5))
        path.quadTo(QPointF(28, 12), QPointF(28.0, 5.5))
        _outlined_path(p, path, MOUTH, 2.1)
        if tongue > 0.05:
            tl = 4.5 + 4.5 * tongue
            tpath = QPainterPath()
            tpath.addRoundedRect(QRectF(15.5, 10.0, 8.5, tl + 4), 4.2, 4.2)
            _outlined_path(p, tpath, TONGUE, 1.9)
            p.setPen(_pen(1.2, QColor("#c2475a")))
            p.drawLine(QPointF(19.7, 12), QPointF(19.7, 10 + tl + 1))
    elif kind == "grr":
        rect = QPainterPath()
        rect.addRoundedRect(QRectF(10.5, 6.0, 18.5, 9.5), 3.0, 3.0)
        _outlined_path(p, rect, MOUTH, 2.0)
        p.save()
        p.setClipPath(rect, Qt.ClipOperation.IntersectClip)
        teeth = QPolygonF()
        teeth.append(QPointF(10, 6))
        x = 10.5
        while x < 29:
            teeth.append(QPointF(x + 1.6, 9.6))
            teeth.append(QPointF(x + 3.2, 6))
            x += 3.2
        teeth.append(QPointF(30, 5))
        bottom = QPolygonF()
        bottom.append(QPointF(10, 16))
        x = 10.5
        while x < 29:
            bottom.append(QPointF(x + 1.6, 12.2))
            bottom.append(QPointF(x + 3.2, 16))
            x += 3.2
        bottom.append(QPointF(30, 17))
        p.setPen(_pen(1.0))
        p.setBrush(WHITE)
        p.drawPolygon(teeth)
        p.drawPolygon(bottom)
        p.restore()
        p.setPen(_pen(1.6))
        p.drawArc(QRectF(12, -5.5, 6, 4), 20 * 16, 140 * 16)   # snout wrinkles
        p.drawArc(QRectF(17.5, -6.5, 6, 4), 20 * 16, 140 * 16)
    elif kind == "yawn":
        path = QPainterPath()
        path.addEllipse(QPointF(19.5, 11.0), 6.8, 8.4)
        _outlined_path(p, path, MOUTH, 2.0)
        p.save()
        p.setClipPath(path, Qt.ClipOperation.IntersectClip)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(TONGUE)
        p.drawEllipse(QPointF(19.5, 18.0), 5.2, 3.6)
        p.restore()
    elif kind == "o":
        path = QPainterPath()
        path.addEllipse(QPointF(21.0, 10.6), 2.9, 3.5)
        _outlined_path(p, path, MOUTH, 1.8)
    else:
        path = QPainterPath(QPointF(28.6, 2.5))
        if kind == "flat":
            path.lineTo(QPointF(27.3, 8.6))
            path.lineTo(QPointF(14.0, 10.0))
        elif kind == "frown":
            path.quadTo(QPointF(28.0, 7.8), QPointF(25.5, 9.6))
            path.quadTo(QPointF(19.5, 7.5), QPointF(13.0, 11.4))
        else:  # smile
            path.quadTo(QPointF(28.2, 7.2), QPointF(25.6, 9.0))
            path.quadTo(QPointF(19.0, 13.5), QPointF(11.5, 8.2))
        p.setPen(_pen(2.1))
        p.drawPath(path)
        if kind == "smile":
            p.setPen(_pen(2.0))
            p.drawLine(QPointF(10.2, 6.2), QPointF(12.8, 10.2))
            if tongue > 0.05:
                tpath = QPainterPath()
                tpath.addRoundedRect(QRectF(17.0, 9.4, 6.5, 3.5 + 4 * tongue), 3, 3)
                _outlined_path(p, tpath, TONGUE, 1.7)


def _head_path() -> QPainterPath:
    """Iconic Snoopy head: domed skull, brow slope, rounded bulbous cylindrical snout."""
    path = QPainterPath(QPointF(-15.0, 6.0))
    # skull dome
    path.cubicTo(QPointF(-18.5, -7.0), QPointF(-10.0, -18.5), QPointF(1.0, -17.5))
    # brow slope into muzzle
    path.cubicTo(QPointF(8.0, -16.5), QPointF(11.5, -11.0), QPointF(14.0, -8.0))
    # top of bulbous snout
    path.cubicTo(QPointF(19.0, -7.0), QPointF(26.0, -6.5), QPointF(32.0, -4.5))
    # round front curve of snout
    path.cubicTo(QPointF(37.5, -2.5), QPointF(37.5, 5.0), QPointF(33.0, 7.8))
    # bottom of snout into jaw
    path.cubicTo(QPointF(28.5, 10.5), QPointF(19.5, 12.0), QPointF(12.5, 12.2))
    # jaw into neck
    path.cubicTo(QPointF(5.5, 12.5), QPointF(-8.0, 12.5), QPointF(-15.0, 6.0))
    path.closeSubpath()
    return path


_HEAD_PATH: QPainterPath | None = None


def draw_head(p: QPainter, v: dict, mouth: str, brow: str, eyes: str) -> None:
    global _HEAD_PATH
    if _HEAD_PATH is None:
        _HEAD_PATH = _head_path()
    angle = ear_angle(v["ear"], v["flap"])
    # far ear peeks out behind the skull when lifted
    _draw_ear(p, QPointF(-1.0, -11.0), angle - 14 - v["flap"] * 0.6, PATCH_DARK, 0.9)
    _outlined_path(p, _HEAD_PATH, FUR)
    if v["blush"] > 0.02:
        p.save()
        p.setClipPath(_HEAD_PATH, Qt.ClipOperation.IntersectClip)
        p.setPen(Qt.PenStyle.NoPen)
        blush = QColor(255, 120, 140, int(120 * min(1.0, v["blush"])))
        p.setBrush(blush)
        p.drawEllipse(QPointF(-1.0, 6.5), 5.0, 3.0)
        p.restore()
    p.setPen(_pen())
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(_HEAD_PATH)
    big = 1.18 if v["eye"] > 1.05 else 1.0
    eye_rear = QPointF(3.8, -7.6)
    eye_front = QPointF(9.5, -8.0)
    _draw_eye(p, eye_rear, v["eye"], v["lookx"], v["looky"], eyes, big, tilt=15.0)
    _draw_eye(p, eye_front, v["eye"], v["lookx"], v["looky"], eyes, big, tilt=19.0)
    _draw_brow(p, eye_rear, brow, 2.0 if big > 1 else 0.0)
    p.save()
    p.translate(QPointF(30.2, -1.0))
    p.rotate(-10.0)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(NOSE)
    p.drawEllipse(QPointF(0, 0), 5.6, 3.6)
    p.restore()
    _draw_mouth(p, mouth, v["tongue"])
    _draw_ear(p, QPointF(-6.5, -9.5), angle, PATCH)


def _draw_tail(p: QPainter, v: dict) -> None:
    """Tapered perky white Snoopy tail with ink outline."""
    base = QPointF(v["tx"], v["ty"])
    a = math.radians(v["ta"])
    d = QPointF(-math.sin(a), -math.cos(a))
    length = v["tl"] + 2
    end = QPointF(base.x() + d.x() * length, base.y() + d.y() * length)
    perp = QPointF(d.y(), -d.x())
    bend = v["tc"] * length * 0.45
    ctrl = QPointF((base.x() + end.x()) / 2 + perp.x() * bend,
                   (base.y() + end.y()) / 2 + perp.y() * bend)
    _outlined_path(p, _tapered(base, ctrl, end, 6.5, 3.2, 12), FUR)


def _torso_path(w: float, h: float) -> QPainterPath:
    """Snoopy torso: smooth rounded back, cute pear-shaped potbelly in front."""
    def P(x: float, y: float) -> QPointF:
        return QPointF(x * w, y * h)
    path = QPainterPath(P(-0.46, -0.22))
    path.cubicTo(P(-0.28, -0.52), P(0.04, -0.50), P(0.28, -0.42))
    path.cubicTo(P(0.48, -0.34), P(0.58, -0.05), P(0.48, 0.32))
    path.cubicTo(P(0.40, 0.58), P(0.06, 0.60), P(-0.16, 0.46))
    path.cubicTo(P(-0.30, 0.32), P(-0.42, 0.16), P(-0.46, -0.22))
    path.closeSubpath()
    return path


# Body proportions: "beagle" (realistic) or "cartoon" (big head, short stubby legs).
PROPORTIONS = {"beagle": (1.0, 1.0, 1.0), "cartoon": (1.45, 0.62, 0.9)}
_HEAD_K, _LEG_K, _BODY_K = PROPORTIONS["beagle"]
_LEG_KEYS = ("fn", "ff", "bn", "bf")
_Y_KEYS = ("by", "hy", "ny0", "ty", "hay") + tuple(k + "y" for k in _LEG_KEYS)


def set_proportions(name: str) -> None:
    global _HEAD_K, _LEG_K, _BODY_K
    _HEAD_K, _LEG_K, _BODY_K = PROPORTIONS.get(name, PROPORTIONS["beagle"])


def _proportioned(v: dict) -> dict:
    if _HEAD_K == 1.0 and _LEG_K == 1.0 and _BODY_K == 1.0:
        return v
    d = dict(v)
    drop = 0.0
    for k in _LEG_KEYS:
        d[k + "l"] = v[k + "l"] * _LEG_K
        drop += max(0.0, v[k + "l"] * math.cos(math.radians(v[k + "a"]))) * (1 - _LEG_K)
    drop /= len(_LEG_KEYS)        # lower the body only as much as the legs got shorter
    for k in _Y_KEYS:
        d[k] = v[k] + drop
    d["bw"] = v["bw"] * _BODY_K
    d["bh"] = v["bh"] * _BODY_K
    for k in ("bx", "tx", "hax", "nx0") + tuple(k + "x" for k in _LEG_KEYS):
        d[k] = v[k] * _BODY_K
    d["hy"] -= (_HEAD_K - 1) * 13      # bigger head sits a little higher...
    d["hx"] += (_HEAD_K - 1) * 5       # ...and further forward so it clears the chest
    return d


def draw_dog(p: QPainter, ps: Pose, facing: float = 1.0) -> None:
    """Draw the pup at the painter's origin (feet), in units."""
    v = _proportioned(ps.v)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.translate(v["shakex"], v["bob"])
    sign = 1.0 if facing >= 0 else -1.0
    p.scale(sign * max(0.18, abs(facing)), 1.0)

    _leg(p, v, "ff", FUR_SHADE)
    _leg(p, v, "bf", FUR_SHADE)
    _draw_tail(p, v)
    _leg(p, v, "bn", FUR)
    _leg(p, v, "fn", FUR)

    neck0 = QPointF(v["nx0"], v["ny0"])
    neck1 = QPointF(v["hx"] - 6, v["hy"] + 11)
    p.setPen(_pen(17 + 2 * INK_W))
    p.drawLine(neck0, neck1)

    # torso
    p.save()
    p.translate(v["bx"], v["by"])
    p.rotate(v["brot"])
    body = _torso_path(v["bw"], v["bh"] * v["breath"])
    _outlined_path(p, body, FUR)
    p.save()
    p.setClipPath(body, Qt.ClipOperation.IntersectClip)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(PATCH)
    p.drawEllipse(QPointF(-v["bw"] * 0.06, -v["bh"] * 0.52), v["bw"] * 0.34, v["bh"] * 0.34)  # saddle
    p.restore()
    p.setPen(_pen())
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(body)
    p.restore()

    # legs grow out of the body instead of being plugged into it
    body_dog = QTransform().translate(v["bx"], v["by"]).rotate(v["brot"]).map(body)
    _blend_leg_joint(p, v, "bn", FUR, body_dog)
    _blend_leg_joint(p, v, "fn", FUR, body_dog)

    if v["has"] > 0.05:
        # haunch: a soft thigh curve on the back edge, not a full outlined disc
        c = QPointF(v["hax"], v["hay"])
        rx, ry = 11.5 * v["has"], 10.5 * v["has"]
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(FUR)
        p.drawEllipse(c, rx, ry)
        p.setPen(_pen(INK_W * 0.9))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(c.x() - rx, c.y() - ry, 2 * rx, 2 * ry), 95 * 16, 150 * 16)

    p.setPen(_pen(17, FUR))
    p.drawLine(neck0, neck1)
    # collar
    cx = _lerp(neck0.x(), neck1.x(), 0.62)
    cy = _lerp(neck0.y(), neck1.y(), 0.62)
    dx, dy = neck1.x() - neck0.x(), neck1.y() - neck0.y()
    n = math.hypot(dx, dy) or 1.0
    px, py = -dy / n * 9.5, dx / n * 9.5
    a, b = QPointF(cx + px, cy + py), QPointF(cx - px, cy - py)
    _limb(p, a, b, 4.0, COLLAR)

    p.save()
    p.translate(v["hx"], v["hy"])
    p.rotate(v["hrot"])
    p.scale(_HEAD_K, _HEAD_K)
    draw_head(p, v, ps.mouth, ps.brow, ps.eyes)
    p.restore()
    p.restore()


# ============================================================ FRONT FACE
def draw_front_face(p: QPainter, center: QPointF, r: float, lookx: float = 0.0,
                    looky: float = 0.0, eye_open: float = 1.0, ear: float = 0.15,
                    mouth: str = "smile", eyes: str = "normal",
                    brow: str = "neutral") -> None:
    """Frontal head (doghouse doorway peeking, tray icon)."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.translate(center)
    k = r / 19.0
    p.scale(k, k)
    lift = _lerp(2.0, 140.0, max(0.0, min(1.0, ear)))
    _draw_ear(p, QPointF(-14.5, -7.0), lift, PATCH, 0.85)
    _draw_ear(p, QPointF(14.5, -7.0), -lift, PATCH, 0.85)
    head = QPainterPath()
    head.addEllipse(QPointF(0, 0), 19.0, 17.5)
    _outlined_path(p, head, FUR)
    p.setPen(_pen())
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(head)
    for ex in (-7.0, 7.0):
        e = QPointF(ex, -3.0)
        _draw_eye(p, e, eye_open, lookx, looky, eyes, 0.9, tilt=-8.0 if ex < 0 else 8.0)
        if brow != "none":
            p.save()
            p.translate(e)
            if ex < 0:
                p.scale(-1, 1)
            _draw_brow(p, QPointF(0, 0.5), brow)
            p.restore()
    snout = QPainterPath()
    snout.addEllipse(QPointF(0, 7.5), 8.6, 6.2)
    _outlined_path(p, snout, FUR, 2.0)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(NOSE)
    p.drawEllipse(QPointF(0, 4.2), 4.8, 3.2)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(_pen(1.8))
    if mouth == "o":
        p.setBrush(MOUTH)
        p.drawEllipse(QPointF(0, 10.0), 2.0, 2.4)
    elif mouth == "pant":
        mp = QPainterPath(QPointF(-4.5, 9))
        mp.quadTo(QPointF(0, 17), QPointF(4.5, 9))
        mp.closeSubpath()
        _outlined_path(p, mp, MOUTH, 1.6)
        p.setBrush(TONGUE)
        p.drawRoundedRect(QRectF(-2.4, 10.5, 4.8, 6.0), 2.4, 2.4)
    else:
        mp = QPainterPath(QPointF(0, 7.0))
        mp.lineTo(QPointF(0, 9.3))
        mp.moveTo(QPointF(-4.2, 9.0))
        mp.quadTo(QPointF(-2.0, 11.6), QPointF(0, 9.3))
        mp.quadTo(QPointF(2.0, 11.6), QPointF(4.2, 9.0))
        p.drawPath(mp)
    p.restore()


def face_badge_pixmap(size: int, dpr: float = 1.0) -> QPixmap:
    """Biscuit's face on a round sunny badge: the app / tray / window icon."""
    px = max(1, int(round(size * dpr)))
    pm = QPixmap(px, px)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.scale(px / 64.0, px / 64.0)
    small = size <= 24
    p.setPen(_pen(3.2 if small else 2.6))
    p.setBrush(QColor("#ffd34d"))
    p.drawEllipse(QPointF(32, 32), 29.5, 29.5)
    # a big head for tiny sizes so the face still reads in the taskbar / tray
    cr_r = 19.0 if small else 17.0
    p.save()
    clip = QPainterPath()
    clip.addEllipse(QPointF(32, 32), 30.5, 30.5)
    p.setClipPath(clip, Qt.ClipOperation.IntersectClip)
    # long black drop ears hanging down beside the face -> reads as a beagle, even tiny
    draw_front_face(p, QPointF(32, 30), cr_r, 0, 0.1, 1.0, 0.0)
    p.restore()
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def make_app_icon() -> "QIcon":
    from PyQt6.QtGui import QIcon
    icon = QIcon()
    for size in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        icon.addPixmap(face_badge_pixmap(size))
    return icon


def draw_front_paws(p: QPainter, center: QPointF, spread: float, k: float) -> None:
    p.save()
    p.setPen(_pen(INK_W * k))
    p.setBrush(FUR)
    for sx in (-1, 1):
        p.drawEllipse(QPointF(center.x() + sx * spread, center.y()), 6.8 * k, 4.2 * k)
    p.restore()


# =============================================================== BUBBLES
def _text_path(text: str, size: float, center: QPointF) -> QPainterPath:
    font = QFont(COMIC_FONT)
    font.setBold(True)
    font.setPointSizeF(max(1.0, size))
    path = QPainterPath()
    path.addText(QPointF(0, 0), font, text)
    br = path.boundingRect()
    path.translate(center.x() - br.center().x(), center.y() - br.center().y())
    return path


def _heart_path(c: QPointF, s: float) -> QPainterPath:
    path = QPainterPath(QPointF(c.x(), c.y() + s * 0.9))
    path.cubicTo(QPointF(c.x() - s * 1.4, c.y() - s * 0.1),
                 QPointF(c.x() - s * 0.7, c.y() - s * 1.2), QPointF(c.x(), c.y() - s * 0.45))
    path.cubicTo(QPointF(c.x() + s * 0.7, c.y() - s * 1.2),
                 QPointF(c.x() + s * 1.4, c.y() - s * 0.1), QPointF(c.x(), c.y() + s * 0.9))
    return path


def _spiky_path(c: QPointF, rx: float, ry: float, spikes: int, jitter: float) -> QPainterPath:
    poly = QPolygonF()
    for i in range(spikes * 2):
        ang = math.pi * 2 * i / (spikes * 2)
        rr = 1.0 if i % 2 == 0 else 0.72 + 0.05 * math.sin(i * 1.7 + jitter)
        poly.append(QPointF(c.x() + math.cos(ang) * rx * rr, c.y() + math.sin(ang) * ry * rr))
    path = QPainterPath()
    path.addPolygon(poly)
    path.closeSubpath()
    return path


def draw_bubble(p: QPainter, kind: str, center: QPointF, alpha: float = 1.0,
                t: float = 0.0, size: float = 1.0) -> None:
    """kinds: z, note, heart, question, exclaim, grr, dots"""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setOpacity(max(0.0, min(1.0, alpha)))
    p.translate(center)
    p.scale(size, size)
    o = QPointF(0, 0)
    if kind == "z":
        _outlined_path(p, _text_path("Z", 13, o), QColor("#7aa7ff"), 2.0)
    elif kind == "note":
        p.rotate(math.sin(t * 6) * 12)
        _outlined_path(p, _text_path(chr(0x266A), 15, o), NOTE, 1.6)
    elif kind == "heart":
        sc = 1.0 + 0.12 * math.sin(t * 10)
        _outlined_path(p, _heart_path(o, 7.5 * sc), HEART, 2.0)
    elif kind in ("question", "exclaim", "dots"):
        bubble = QPainterPath()
        bubble.addEllipse(o, 11.5, 10.5)
        tail = QPainterPath(QPointF(-5, 7))
        tail.lineTo(QPointF(-9, 16))
        tail.lineTo(QPointF(1, 9))
        tail.closeSubpath()
        _outlined_path(p, bubble.united(tail), WHITE, 2.2)
        txt = {"question": "?", "exclaim": "!", "dots": "..."}[kind]
        col = QColor("#d8372b") if kind == "exclaim" else INK
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawPath(_text_path(txt, 12 if kind != "dots" else 9, QPointF(0, -0.5)))
    elif kind == "grr":
        spiky = _spiky_path(o, 25, 15, 11, t * 20)
        _outlined_path(p, spiky, QColor("#fff27a"), 2.2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#c0281e"))
        p.drawPath(_text_path("Grrr!", 8.5, QPointF(0, 0)))
    p.restore()


# ============================================================== DOGHOUSE
HOUSE_W = 140.0   # unit bounding box (origin bottom-centre)
HOUSE_H = 122.0


def doghouse_door(view: str) -> tuple[QPainterPath, QPointF]:
    """Door path in house units and the door's floor centre point."""
    if view == "front":
        cx, half, top, bottom = 0.0, 18.0, -42.0, 0.0
    else:
        cx, half, top, bottom = -38.0, 14.5, -36.0, 0.0
        if view == "right":
            cx = -cx
    path = QPainterPath(QPointF(cx - half, bottom))
    path.lineTo(QPointF(cx - half, top))
    path.arcTo(QRectF(cx - half, top - half, half * 2, half * 2), 180, -180)
    path.lineTo(QPointF(cx + half, bottom))
    path.closeSubpath()
    return path, QPointF(cx, bottom)


def draw_doghouse_back(p: QPainter, view: str) -> None:
    """Everything behind the occupant (walls, roof, dark doorway)."""
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if view == "front":
        _draw_house_front(p)
    else:
        p.save()
        if view == "right":
            p.scale(-1, 1)
        _draw_house_side(p)
        p.restore()
    door, _ = doghouse_door(view)
    _outlined_path(p, door, DOOR, INK_W)


def _draw_house_front(p: QPainter) -> None:
    """Snoopy's iconic front-facing red doghouse with red gabled roof."""
    walls = QPolygonF([QPointF(-46, 0), QPointF(46, 0), QPointF(46, -64),
                       QPointF(0, -100), QPointF(-46, -64)])
    wp = QPainterPath()
    wp.addPolygon(walls)
    wp.closeSubpath()
    _outlined_path(p, wp, WALL)
    p.save()
    p.setClipPath(wp, Qt.ClipOperation.IntersectClip)
    p.setPen(_pen(1.4, WALL_LINE))
    for x in (-31, -15.5, 0, 15.5, 31):
        p.drawLine(QPointF(x, -110), QPointF(x, 0))
    p.restore()
    p.setPen(_pen())
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(wp)
    roof = QPolygonF([QPointF(-62, -56), QPointF(0, -116), QPointF(62, -56),
                      QPointF(50, -54), QPointF(0, -101), QPointF(-50, -54)])
    rp = QPainterPath()
    rp.addPolygon(roof)
    rp.closeSubpath()
    _outlined_path(p, rp, ROOF)
    p.setPen(_pen(1.3, ROOF_LINE))
    for i in range(1, 5):
        t = i / 5
        p.drawLine(QPointF(_lerp(-56, 0, t), _lerp(-55, -108.5, t)),
                   QPointF(_lerp(-56, 0, t) + 6, _lerp(-55, -108.5, t) + 3))
        p.drawLine(QPointF(_lerp(56, 0, t), _lerp(-55, -108.5, t)),
                   QPointF(_lerp(56, 0, t) - 6, _lerp(-55, -108.5, t) + 3))
    p.setPen(_pen(INK_W))
    p.drawLine(QPointF(-48, 0), QPointF(48, 0))


def _draw_house_side(p: QPainter) -> None:
    """Snoopy's iconic side 3/4 red doghouse view with the gable/doorway on the LEFT."""
    side = QPolygonF([QPointF(-14, 0), QPointF(56, -5), QPointF(56, -60), QPointF(-14, -63)])
    sp = QPainterPath()
    sp.addPolygon(side)
    sp.closeSubpath()
    _outlined_path(p, sp, WALL_SHADE)
    p.save()
    p.setClipPath(sp, Qt.ClipOperation.IntersectClip)
    p.setPen(_pen(1.3, WALL_LINE))
    for i in range(1, 6):
        y0 = -63 + i * 10.5
        p.drawLine(QPointF(-14, y0), QPointF(56, y0 + 0.08 * 70 - i * 0.9))
    p.restore()
    p.setPen(_pen())
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(sp)
    front = QPolygonF([QPointF(-62, 0), QPointF(-14, 0), QPointF(-14, -63),
                       QPointF(-38, -94), QPointF(-62, -63)])
    fp = QPainterPath()
    fp.addPolygon(front)
    fp.closeSubpath()
    _outlined_path(p, fp, WALL)
    p.save()
    p.setClipPath(fp, Qt.ClipOperation.IntersectClip)
    p.setPen(_pen(1.3, WALL_LINE))
    for x in (-54, -46, -30, -22):
        p.drawLine(QPointF(x, -100), QPointF(x, 0))
    p.restore()
    p.setPen(_pen())
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(fp)
    roof = QPolygonF([QPointF(-38, -99), QPointF(34, -93), QPointF(64, -55), QPointF(-8, -58)])
    rp = QPainterPath()
    rp.addPolygon(roof)
    rp.closeSubpath()
    _outlined_path(p, rp, ROOF)
    p.setPen(_pen(1.3, ROOF_LINE))
    for i in range(1, 4):
        t = i / 4
        a = QPointF(_lerp(-38, -8, t), _lerp(-99, -58, t))
        b = QPointF(_lerp(34, 64, t), _lerp(-93, -55, t))
        p.drawLine(a, b)
    trim = QPainterPath(QPointF(-67, -58))
    trim.lineTo(QPointF(-38, -99))
    trim.lineTo(QPointF(-8, -58))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(_pen(7 + 2 * INK_W))
    p.drawPath(trim)
    p.setPen(_pen(7, ROOF))
    p.drawPath(trim)
    p.setPen(_pen(INK_W))
    p.drawLine(QPointF(-64, 0), QPointF(58, -5))


SIDE_ROOF = QColor("#3e8e4c")
SIDE_ROOF_SHADE = QColor("#2f7040")
SIDE_ROOF_LINE = QColor("#235531")
SIDE_WALL = QColor("#cf3a2c")
SIDE_WALL_LINE = QColor("#a12a1f")
SIDE_HALF = 62.0     # half length of the long side, in units


def draw_house_long_side(p: QPainter) -> None:
    """Biscuit's house seen from its long side: the door is on the far side, out of view.
    Red plank walls, green scalloped roof, a bone sign and a little round vent."""
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    h = SIDE_HALF
    # wooden base
    base = QPainterPath()
    base.addRoundedRect(QRectF(-h - 5, -7, 2 * h + 10, 7), 2.5, 2.5)
    _outlined_path(p, base, WOOD)
    # wall with horizontal planks
    wall = QPainterPath()
    wall.addRect(QRectF(-h, -60, 2 * h, 53))
    _outlined_path(p, wall, SIDE_WALL)
    p.save()
    p.setClipPath(wall, Qt.ClipOperation.IntersectClip)
    p.setPen(_pen(1.3, SIDE_WALL_LINE))
    for i in range(1, 5):
        y = -60 + i * 10.6
        p.drawLine(QPointF(-h, y), QPointF(h, y))
        # staggered plank joints
        jx = -h + (28 if i % 2 else 52)
        while jx < h:
            p.drawLine(QPointF(jx, y - 10.6), QPointF(jx, y))
            jx += 48
    p.restore()
    p.setPen(_pen())
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(wall)
    # round vent window near one end
    p.setPen(_pen(INK_W * 0.9))
    p.setBrush(DOOR)
    p.drawEllipse(QPointF(h - 20, -42), 6.0, 6.0)
    p.setPen(_pen(1.3, SIDE_WALL_LINE))
    p.drawLine(QPointF(h - 26, -42), QPointF(h - 14, -42))
    # bone sign in the middle
    _draw_bone(p, QPointF(-6, -36), 1.15)
    # roof slope facing us, overhanging both ends, with scalloped shingle rows
    roof = QPainterPath(QPointF(-h - 10, -56))
    roof.lineTo(QPointF(h + 10, -56))
    roof.lineTo(QPointF(h + 4, -98))
    roof.lineTo(QPointF(-h - 4, -98))
    roof.closeSubpath()
    _outlined_path(p, roof, SIDE_ROOF)
    p.save()
    p.setClipPath(roof, Qt.ClipOperation.IntersectClip)
    p.setPen(_pen(1.3, SIDE_ROOF_LINE))
    p.setBrush(Qt.BrushStyle.NoBrush)
    for row in range(4):
        y = -90 + row * 10.5
        off = 0 if row % 2 else 6
        x = -h - 16 + off
        scallops = QPainterPath(QPointF(x, y))
        while x < h + 16:
            scallops.quadTo(QPointF(x + 6, y + 7), QPointF(x + 12, y))
            x += 12
        p.drawPath(scallops)
    p.restore()
    p.setPen(_pen())
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(roof)
    # ridge cap
    ridge = QPainterPath()
    ridge.addRoundedRect(QRectF(-h - 7, -103, 2 * h + 14, 7), 3, 3)
    _outlined_path(p, ridge, SIDE_ROOF_SHADE)


def _draw_bone(p: QPainter, c: QPointF, k: float) -> None:
    path = QPainterPath()
    path.addRoundedRect(QRectF(c.x() - 9 * k, c.y() - 2.4 * k, 18 * k, 4.8 * k), 2 * k, 2 * k)
    for sx in (-1, 1):
        for sy in (-1, 1):
            knob = QPainterPath()
            knob.addEllipse(QPointF(c.x() + sx * 9.5 * k, c.y() + sy * 2.6 * k), 3.1 * k, 3.1 * k)
            path = path.united(knob)
    _outlined_path(p, path, BONE, INK_W * 0.85)


def draw_doghouse_threshold(p: QPainter, view: str) -> None:
    """Re-draw the doorway outline on top of an occupant for a crisp edge."""
    door, _ = doghouse_door(view)
    p.setPen(_pen())
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(door)


# ======================================================== SPRITE ANIMATOR
ANIMATIONS = (
    "idle", "walk", "trot", "run", "jump", "fall", "sit", "lie", "yawn", "drowsy",
    "sleep", "wake_ears", "stretch", "shake", "growl", "obey_sit", "excited",
    "startled", "dragged", "beg", "idle_upright", "walk_upright", "hello", "goodbye",
    "peek_front", "peek_side",
)


def app_base_dirs() -> list[Path]:
    dirs: list[Path] = []
    if getattr(sys, "frozen", False):
        dirs.append(Path(sys.executable).resolve().parent)
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            dirs.append(Path(meipass))
    else:
        dirs.append(Path(__file__).resolve().parent)
    return dirs


class SpriteAnimator:
    """Loads optional PNG animations from ./assets/ (see README).

    Each animation is either a folder of frames  assets/<name>/<name>_000.png ...
    or a horizontal strip                       assets/<name>_strip.png
    Optional assets/sprites.json tunes fps, loop, frame width and size.
    Frames face RIGHT; their bottom-centre is placed on the pup's feet.
    """

    def __init__(self, root: Path | None = None):
        if root is None:
            root = next((d / "assets" for d in app_base_dirs() if (d / "assets").is_dir()),
                        app_base_dirs()[0] / "assets")
        self.root = root
        self.frames: dict[str, list[QPixmap]] = {}
        self.meta: dict[str, dict] = {}
        self.defaults = {"fps": 10.0, "loop": True, "height_units": 110.0}
        self.house: dict[str, QPixmap] = {}
        self.reload()

    def reload(self) -> None:
        self.frames.clear()
        self.meta.clear()
        self.house.clear()
        if not self.root.is_dir():
            return
        cfg: dict = {}
        cfg_path = self.root / "sprites.json"
        if cfg_path.is_file():
            try:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                cfg = {}
        self.defaults.update({k: v for k, v in cfg.get("defaults", {}).items()})
        anim_cfg = cfg.get("animations", {})
        for name in ANIMATIONS:
            meta = dict(self.defaults)
            meta.update(anim_cfg.get(name, {}))
            frames: list[QPixmap] = []
            folder = self.root / name
            if folder.is_dir():
                for f in sorted(folder.glob("*.png")):
                    pm = QPixmap(str(f))
                    if not pm.isNull():
                        frames.append(pm)
            strip = self.root / f"{name}_strip.png"
            if not frames and strip.is_file():
                sheet = QPixmap(str(strip))
                if not sheet.isNull():
                    fw = int(meta.get("frame_width") or sheet.height())
                    count = max(1, sheet.width() // max(1, fw))
                    frames = [sheet.copy(i * fw, 0, fw, sheet.height()) for i in range(count)]
            if frames:
                self.frames[name] = frames
                self.meta[name] = meta
        house_dir = self.root / "doghouse"
        for view in ("front", "left", "right", "closed"):
            f = house_dir / f"{view}.png"
            if f.is_file():
                pm = QPixmap(str(f))
                if not pm.isNull():
                    self.house[view] = pm

    def has(self, name: str) -> bool:
        return name in self.frames

    def frame(self, name: str, t: float) -> QPixmap | None:
        frames = self.frames.get(name)
        if not frames:
            return None
        meta = self.meta[name]
        idx = int(t * float(meta.get("fps", 10)))
        if meta.get("loop", True):
            idx %= len(frames)
        else:
            idx = min(idx, len(frames) - 1)
        return frames[idx]

    def draw(self, p: QPainter, name: str, t: float, facing: float) -> bool:
        pm = self.frame(name, t)
        if pm is None:
            return False
        h = float(self.meta[name].get("height_units", 110.0))
        w = h * pm.width() / max(1, pm.height())
        p.save()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        if facing < 0:
            p.scale(-1, 1)
        p.drawPixmap(QRectF(-w / 2, -h, w, h), pm, QRectF(pm.rect()))
        p.restore()
        return True

    def draw_house(self, p: QPainter, view: str) -> bool:
        pm = self.house.get(view)
        if pm is None:
            return False
        h = HOUSE_H
        w = h * pm.width() / max(1, pm.height())
        p.save()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawPixmap(QRectF(-w / 2, -h, w, h), pm, QRectF(pm.rect()))
        p.restore()
        return True
