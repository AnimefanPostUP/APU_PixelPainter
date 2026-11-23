"""2D geometry helpers for the UI kit.

All coordinates are region pixels (origin bottom-left, as delivered by
``event.mouse_region_x/y`` and used by POST_PIXEL draw handlers).
This module has no Blender dependency.
"""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    """Axis-aligned rectangle. ``x0/y0`` is bottom-left, ``x1/y1`` top-right."""

    x0: float = 0.0
    y0: float = 0.0
    x1: float = 0.0
    y1: float = 0.0

    @classmethod
    def from_center(cls, cx, cy, width, height):
        hw = width * 0.5
        hh = height * 0.5
        return cls(cx - hw, cy - hh, cx + hw, cy + hh)

    @classmethod
    def from_size(cls, x, y, width, height):
        return cls(x, y, x + width, y + height)

    @property
    def width(self):
        return self.x1 - self.x0

    @property
    def height(self):
        return self.y1 - self.y0

    @property
    def cx(self):
        return (self.x0 + self.x1) * 0.5

    @property
    def cy(self):
        return (self.y0 + self.y1) * 0.5

    @property
    def is_empty(self):
        return self.width <= 0.0 or self.height <= 0.0

    def contains(self, x, y):
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1

    def offset(self, dx, dy):
        return Rect(self.x0 + dx, self.y0 + dy, self.x1 + dx, self.y1 + dy)

    def expand(self, margin):
        return Rect(self.x0 - margin, self.y0 - margin, self.x1 + margin, self.y1 + margin)

    def union(self, other):
        if other is None or other.is_empty:
            return self
        if self.is_empty:
            return other
        return Rect(min(self.x0, other.x0), min(self.y0, other.y0),
                    max(self.x1, other.x1), max(self.y1, other.y1))

    def scaled(self, factor):
        """Scale about the rect's own center."""
        return Rect.from_center(self.cx, self.cy, self.width * factor, self.height * factor)

    def as_tuple(self):
        return (self.x0, self.y0, self.x1, self.y1)


def clamp(value, lo, hi):
    return lo if value < lo else hi if value > hi else value


def lerp(a, b, t):
    return a + (b - a) * t


def lerp2(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def normalize(dx, dy, fallback=(0.0, 0.0)):
    """Return ``(ux, uy, length)``; ``fallback`` direction when degenerate."""
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return fallback[0], fallback[1], 0.0
    return dx / length, dy / length, length


def point_on_circle_toward(cx, cy, radius, tx, ty):
    ux, uy, _ = normalize(tx - cx, ty - cy)
    return cx + ux * radius, cy + uy * radius


def point_on_rect_toward(rect, tx, ty):
    """Point where the ray from the rect center toward ``(tx, ty)`` leaves the rect."""
    cx, cy = rect.cx, rect.cy
    half_w = rect.width * 0.5
    half_h = rect.height * 0.5
    dx = tx - cx
    dy = ty - cy
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return cx, cy
    scale = max(abs(dx) / max(half_w, 1e-6), abs(dy) / max(half_h, 1e-6))
    if scale <= 1e-6:
        return cx, cy
    return cx + dx / scale, cy + dy / scale


def fit_offset(bounds, width, height, margin=0.0):
    """Offset ``(dx, dy)`` that moves ``bounds`` inside a ``width x height`` area.

    When the bounds are larger than the area, they are aligned to the top/left
    edge so the most important (upper) part of a menu stays visible.
    """
    def _axis(lo, hi, size):
        avail_lo = margin
        avail_hi = size - margin
        if hi - lo > avail_hi - avail_lo:
            return avail_lo - lo if lo < avail_lo else 0.0
        if lo < avail_lo:
            return avail_lo - lo
        if hi > avail_hi:
            return avail_hi - hi
        return 0.0

    dx = _axis(bounds.x0, bounds.x1, width)
    # Vertically, prefer keeping the top visible when it does not fit.
    if bounds.height > height - 2.0 * margin:
        dy = (height - margin) - bounds.y1
    else:
        dy = _axis(bounds.y0, bounds.y1, height)
    return dx, dy
