"""Backgrounds that follow a floating window's shape (pen menu, Mask, View).

Instead of one rectangle, a window's background is a few shapes laid around its
parts (see ``PenBar._window(shape=...)``):

* :class:`Star` -- the silhouette of a :class:`~.kit.Dial`: around its rings, and
  further out wherever bands / corner segments reach (sampled per angle, small gaps
  between neighbours bridged, padded);
* :class:`Plate` -- a rounded rectangle (title plate, button rows, help text).

The shapes do not overlap (the background is translucent). Each can say whether
it contains a point: presses outside every shape fall through to the canvas.
"""

import math

from .kit import draw
from .kit.geometry import Rect
from .kit.ring import CornerSegment, RingSegment

STEP_DEG = 2.0           # silhouette resolution
BRIDGE_DEG = 7.0         # gaps narrower than this (between bands) are filled
OUTLINE_ALPHA = 0.5      # the faint rim around each shape, relative to the background's alpha


class Star:
    """Star-shaped polygon around ``(cx, cy)``: ``radii[k]`` at angle ``k * step``."""

    def __init__(self, cx, cy, radii, step_deg=STEP_DEG):
        self.cx, self.cy = cx, cy
        self.radii = list(radii)
        self.step = math.radians(step_deg)

    def points(self):
        return [(self.cx + math.cos(k * self.step) * r, self.cy + math.sin(k * self.step) * r)
                for k, r in enumerate(self.radii)]

    def radius_at(self, angle):
        n = len(self.radii)
        f = (angle % math.tau) / self.step
        k = int(f) % n
        t = f - int(f)
        return self.radii[k] + (self.radii[(k + 1) % n] - self.radii[k]) * t

    def contains(self, x, y):
        dx, dy = x - self.cx, y - self.cy
        return math.hypot(dx, dy) <= self.radius_at(math.atan2(dy, dx))

    def draw(self, color, rim=None):
        draw.star_polygon(self.cx, self.cy, self.points(), color, rim=rim)


class Plate:
    """Rounded rectangle."""

    def __init__(self, rect, radius):
        self.rect = rect
        self.radius = radius

    def contains(self, x, y):
        r = self.rect
        if not r.contains(x, y):
            return False
        rad = min(self.radius, r.width * 0.5, r.height * 0.5)
        qx = min(x - (r.x0 + rad), 0.0) + max(x - (r.x1 - rad), 0.0)
        qy = min(y - (r.y0 + rad), 0.0) + max(y - (r.y1 - rad), 0.0)
        return qx * qx + qy * qy <= rad * rad

    def draw(self, color, rim=None):
        draw.rounded_rect(self.rect, self.radius, color, rim=rim)


def _covers(angle, a0, a1):
    """``angle`` (radians) lies in ``a0 .. a1`` (counter-clockwise, may pass 2 pi)."""
    return (angle - a0) % math.tau <= (a1 - a0)


def dial_star(dial, pad):
    """The :class:`Star` around ``dial``'s visible parts (screen px, after arrange),
    ``pad`` px outside them."""
    cx, cy = dial.rect.cx, dial.rect.cy
    n = int(round(360.0 / STEP_DEG))
    angles = [math.radians(k * STEP_DEG) for k in range(n)]
    base = max([s.pr1 for s in dial.segments if s.visible], default=0.0)
    if dial.center is not None:
        base = max(base, dial.center.rect.width * 0.5)
    radii = [base] * n
    for seg in dial.corners:
        # Only ring segments (other widgets there, e.g. the favorite blend modes, lie
        # inside the rings).
        if not seg.visible or not isinstance(seg, RingSegment) or seg.pr1 <= 0.0:
            continue
        a0, a1 = seg.angles
        geo = getattr(seg, '_geo', None)
        half = geo[1] if isinstance(seg, CornerSegment) and geo is not None else None
        reach = seg.pr1 if half is None else half * math.sqrt(2.0)
        spread = pad / max(1.0, reach)          # the padding along the circle too
        for k, angle in enumerate(angles):
            if not _covers(angle, a0 - spread, a1 + spread):
                continue
            if half is None:
                r = seg.pr1
            else:                                # out to the square's edge
                r = half / max(abs(math.cos(angle)), abs(math.sin(angle)), 1e-6)
            radii[k] = max(radii[k], r)
    # Bridge small gaps between neighbouring bands (closing: dilate, then erode).
    w = max(1, int(round(BRIDGE_DEG / STEP_DEG * 0.5)))
    grown = [max(radii[(k + d) % n] for d in range(-w, w + 1)) for k in range(n)]
    closed = [min(grown[(k + d) % n] for d in range(-w, w + 1)) for k in range(n)]
    return Star(cx, cy, [r + pad for r in closed])


def plate_around(widget, pad, radius):
    r = widget.rect
    return Plate(Rect(r.x0 - pad, r.y0 - pad, r.x1 + pad, r.y1 + pad), radius)


def draw_shapes(shapes, color):
    rim = (color[0] * 1.6, color[1] * 1.6, color[2] * 1.6, color[3] * OUTLINE_ALPHA)
    for shape in shapes:
        shape.draw(color, rim=rim)
