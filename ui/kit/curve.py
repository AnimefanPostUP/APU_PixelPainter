"""CurveEditor: edit a 0..1 -> 0..1 curve of anchors by pen (press / drag / release only).

Modes (``mode``: value or callable):

* ``'MOVE'``  press an anchor and drag it. The end anchors stay at x = 0 / 1;
  inner anchors stay between their neighbours. Dragging an inner anchor out of
  the box removes it (it comes back if dragged in again before lifting).
* ``'ADD'``   a press adds an anchor there (keep the pen down to place it);
  pressing an existing anchor moves it as in ``'MOVE'``.
* ``'DRAW'``  draw the curve freehand; on release the stroke is turned into
  anchors (:func:`stroke_to_curve`).

``points()`` returns the anchors ``[(x, y), ...]``; ``on_change(points)`` gets
every edit (sorted by x). ``sample(t)`` (optional callable, or a callable
returning one) draws the real curve -- e.g. the host's smoothed curve -- else
straight lines between anchors are drawn. ESC / right click while dragging
restores the anchors from before the press.
"""

import math

from . import draw
from .geometry import Rect
from .theme import with_alpha
from .widget import Widget, _resolve


MIN_GAP = 0.01        # minimum x distance between anchors


def _clamp01(v):
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v


def simplify(points, tolerance):
    """Ramer-Douglas-Peucker: drop points closer than ``tolerance`` to the simplified line."""
    if len(points) < 3:
        return list(points)
    (x0, y0), (x1, y1) = points[0], points[-1]
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy) or 1e-9
    worst, index = 0.0, 0
    for i in range(1, len(points) - 1):
        px, py = points[i]
        d = abs(dy * (px - x0) - dx * (py - y0)) / length
        if d > worst:
            worst, index = d, i
    if worst <= tolerance:
        return [points[0], points[-1]]
    return simplify(points[:index + 1], tolerance)[:-1] + simplify(points[index:], tolerance)


def stroke_to_curve(stroke, bins=48, tolerance=0.02, max_points=12):
    """Anchors for a freehand ``stroke`` (``[(x, y), ...]`` in 0..1): the stroke is
    read as y over x (later strokes over the same x win in each bin), gaps and the
    ends are filled, then simplified to at most ``max_points`` anchors spanning
    x = 0 .. 1. None when the stroke spans too little x."""
    if len(stroke) < 2:
        return None
    pts = [(_clamp01(x), _clamp01(y)) for x, y in stroke]
    if max(p[0] for p in pts) - min(p[0] for p in pts) < 0.05:
        return None
    # Densify so fast strokes still hit every bin.
    dense = [pts[0]]
    step = 0.5 / bins
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        n = max(1, int(abs(bx - ax) / step))
        dense += [(ax + (bx - ax) * i / n, ay + (by - ay) * i / n) for i in range(1, n + 1)]
    values = [None] * bins
    for x, y in dense:
        values[min(bins - 1, int(x * bins))] = y
    known = [i for i, v in enumerate(values) if v is not None]
    for i in range(bins):
        if values[i] is not None:
            continue
        lower = max((k for k in known if k < i), default=None)
        upper = min((k for k in known if k > i), default=None)
        if lower is None:
            values[i] = values[upper]
        elif upper is None:
            values[i] = values[lower]
        else:
            t = (i - lower) / (upper - lower)
            values[i] = values[lower] + (values[upper] - values[lower]) * t
    line = [(0.0, values[0])] + [((i + 0.5) / bins, v) for i, v in enumerate(values)] + [(1.0, values[-1])]
    while True:
        result = simplify(line, tolerance)
        if len(result) <= max_points:
            return [(round(x, 4), round(y, 4)) for x, y in result]
        tolerance *= 1.5


def insert_anchor(points, x, y):
    """``(points, index)`` with an anchor added at ``(x, y)`` between the ends
    (x kept ``MIN_GAP`` from its neighbours); index None when there is no room."""
    pts = sorted(points)
    x, y = _clamp01(x), _clamp01(y)
    for i in range(1, len(pts)):
        lo, hi = pts[i - 1][0] + MIN_GAP, pts[i][0] - MIN_GAP
        if pts[i - 1][0] <= x <= pts[i][0]:
            if lo > hi:
                return pts, None
            pts.insert(i, (min(max(x, lo), hi), y))
            return pts, i
    return pts, None


def move_anchor(points, index, x, y):
    """Anchor ``index`` moved to ``(x, y)``: ends keep their x, inner ones stay between neighbours."""
    pts = list(points)
    y = _clamp01(y)
    if index == 0 or index == len(pts) - 1:
        x = pts[index][0]
    else:
        x = min(max(x, pts[index - 1][0] + MIN_GAP), pts[index + 1][0] - MIN_GAP)
    pts[index] = (x, y)
    return pts


class CurveEditor(Widget):
    interactive = True
    draggable = True

    def __init__(self, points, on_change, *, sample=None, mode='MOVE', size=(200.0, 140.0),
                 padding=8.0, hit=12.0, remove_margin=18.0, curve_color=None, **kwargs):
        super().__init__(**kwargs)
        self.points = points
        self.on_change = on_change
        self.sample = sample
        self.mode = mode
        self.size = size
        self.padding = padding
        self.hit = hit                    # unscaled px: pick radius around anchors
        self.remove_margin = remove_margin
        self.curve_color = curve_color
        self._scale = 1.0
        self._original = None             # anchors before the press (cancel)
        self._edit = None                 # anchors while dragging
        self._active = None               # index of the dragged anchor
        self._removed = False             # the dragged anchor is out of the box (removed)
        self._stroke = None               # DRAW: unit-space points

    # ---- geometry -------------------------------------------------------------------

    def measure(self, theme):
        self._scale = theme.scale
        return theme.px(self.size[0]), theme.px(self.size[1])

    @property
    def box(self):
        """The 0..1 area (inside the padding)."""
        pad = self.padding * self._scale
        r = self.rect
        return Rect(r.x0 + pad, r.y0 + pad, r.x1 - pad, r.y1 - pad)

    def to_unit(self, x, y):
        b = self.box
        return (x - b.x0) / max(1.0, b.width), (y - b.y0) / max(1.0, b.height)

    def to_screen(self, u, v):
        b = self.box
        return b.x0 + u * b.width, b.y0 + v * b.height

    def _anchors(self):
        if self._edit is not None:
            return self._edit
        try:
            pts = sorted(tuple(p) for p in (_resolve(self.points, []) or []))
        except TypeError:
            pts = []
        return pts or [(0.0, 1.0), (1.0, 0.0)]

    def anchor_at(self, x, y):
        """Index of the anchor within the pick radius of ``(x, y)`` (nearest), or None."""
        best, index = self.hit * self._scale, None
        for i, (u, v) in enumerate(self._anchors()):
            sx, sy = self.to_screen(u, v)
            d = math.hypot(sx - x, sy - y)
            if d <= best:
                best, index = d, i
        return index

    # ---- dragging ---------------------------------------------------------------------

    def _commit(self, pts):
        if self.on_change is not None:
            self.on_change(sorted(pts))

    def drag_begin(self, x, y):
        mode = _resolve(self.mode, 'MOVE')
        self._original = list(self._anchors())
        if mode == 'DRAW':
            self._stroke = [self.to_unit(x, y)]
            return
        index = self.anchor_at(x, y)
        pts = list(self._original)
        if index is None and mode == 'ADD':
            pts, index = insert_anchor(pts, *self.to_unit(x, y))
            if index is not None:
                self._commit(pts)
        self._edit, self._active, self._removed = pts, index, False

    def drag_update(self, x, y):
        if self._stroke is not None:
            self._stroke.append(self.to_unit(x, y))
            return
        if self._active is None:
            return
        pts = self._edit
        inner = 0 < self._active < len(pts) - 1
        reach = self.remove_margin * self._scale
        b = self.box
        self._removed = inner and not b.expand(reach).contains(x, y)
        u, v = self.to_unit(x, y)
        self._edit = move_anchor(pts, self._active, u, v)
        committed = list(self._edit)
        if self._removed:
            del committed[self._active]
        self._commit(committed)

    def drag_end(self, x, y, cancelled=False):
        if cancelled:
            if self._original is not None:
                self._commit(self._original)
        elif self._stroke is not None:
            self._stroke.append(self.to_unit(x, y))
            curve = stroke_to_curve(self._stroke)
            if curve is not None:
                self._commit(curve)
        self._original = self._edit = self._active = self._stroke = None
        self._removed = False

    # ---- drawing ----------------------------------------------------------------------

    def _sampler(self):
        sample = self.sample
        if callable(sample):
            try:
                inner = sample()
            except TypeError:
                return sample          # sample(t) itself
            except Exception:
                return None
            return inner if callable(inner) else None
        return None

    def draw_self(self, dc):
        theme = dc.theme
        alpha = dc.alpha
        r, b = self.rect, self.box
        draw.rect(r, with_alpha(theme.surface_dark, alpha))
        grid = with_alpha(theme.border, 0.6 * alpha)
        for i in range(1, 4):
            gx = b.x0 + b.width * i / 4.0
            gy = b.y0 + b.height * i / 4.0
            draw.polyline([(gx, b.y0), (gx, b.y1)], grid, 1.0)
            draw.polyline([(b.x0, gy), (b.x1, gy)], grid, 1.0)
        draw.rect_outline(b, with_alpha(theme.border, alpha), width=1.0)

        color = with_alpha(self.curve_color or theme.accent_light, alpha)
        anchors = self._anchors()
        sampler = None if self._edit is not None else self._sampler()
        if sampler is not None:
            steps = 48
            try:
                line = [self.to_screen(i / steps, _clamp01(float(sampler(i / steps)))) for i in range(steps + 1)]
            except Exception:
                line = None
        else:
            line = None
        if line is None:
            shown = [p for i, p in enumerate(anchors) if not (self._removed and i == self._active)]
            line = [self.to_screen(u, v) for u, v in shown]
        draw.polyline(line, color, max(1.0, theme.px(2.0)))

        if self._stroke:
            draw.polyline([self.to_screen(_clamp01(u), _clamp01(v)) for u, v in self._stroke],
                          with_alpha(theme.accent, alpha), max(1.0, theme.px(2.5)))
            return
        dot = theme.px(4.0)
        for i, (u, v) in enumerate(anchors):
            sx, sy = self.to_screen(u, v)
            active = i == self._active
            if active and self._removed:
                draw.circle_outline(sx, sy, dot, with_alpha(theme.text_muted, 0.6 * alpha), width=1.0)
                continue
            draw.circle(sx, sy, dot * (1.3 if active else 1.0),
                        with_alpha(theme.accent if active else theme.text, alpha), segments=16)
            draw.circle_outline(sx, sy, dot * (1.3 if active else 1.0), (0.0, 0.0, 0.0, 0.7 * alpha), width=1.0)
