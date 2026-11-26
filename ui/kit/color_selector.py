"""ColorSelector: pen-friendly color selector with interchangeable layouts.

Classes
-------
ColorSelector   the widget: drag / tap handling, commit, color model, the
                original-color marker and optional channel sliders underneath
ColorShape      base of the main area -- one per layout:
  SheetShape      hue across / tone up, plus hue, tone and saturation bars
  SquareShape     saturation across / tone up, plus a vertical hue bar
  TriangleShape   hue ring around a hue / white / black triangle
  WheelShape      hue around / saturation outward disc, plus a tone bar

"Tone" is the model's third channel: Value (HSV) or Lightness (HSL). The
selector works in its model (``model``: 'HSV' / 'HSL'); ``get_hsv`` /
``set_hsv`` always speak HSV, so hosts do not care which model is shown.

Interaction (every part of every layout) works like a touchpad, so pens
without hover can steer precisely: press anywhere on a part and drag -- the
selection moves by the drag (times ``gain``) instead of jumping under the pen.
2D parts (sheet, square, triangle, disc) move their cursor point, the hue
ring follows the pointer's rotation around its center, bars and sliders
move along their length. Hue wraps, the rest clamps. A tap (press + release
without dragging) jumps to the tapped spot. The selector shows the swipe live
and commits it on release (``set_hsv``); with ``live`` true it also commits
every step while the pen is down. ESC / right-click during a drag discard it.

Sliders (``sliders``: any of 'RGB', 'HSV', 'HSL') add three horizontal
channel bars per color space under the main area, swiped the same way. With
``fields`` each slider's value is an input field (tap, type, Enter): hue in
degrees, RGB 0..255, the rest in percent.

``layout``, ``model`` and ``sliders`` may be callables: they are re-read on
every layout pass (never during a drag), so settings apply immediately.

``original()`` (optional, HSV) is marked with a faint cross and bar ticks
(e.g. the applied color while a previewed change is pending); during a drag
without one, the color from before the drag is marked.
"""

import math

from . import draw
from .color_models import (
    CHANNELS, HSL, HSV, RGB, clamp01, convert, from_tone_weights, to_rgb, tone_weights, wraps,
)
from .geometry import Rect
from .textfield import NUMBER_CHARS, TextField
from .theme import with_alpha
from .widget import Widget, _resolve


TAP_TRAVEL = 4.0   # unscaled px; less pointer travel than this = a tap
REST_TIME = 0.18   # s: hover selection -- a pause this long marks the color to keep
_SAME_EPS = 1e-5

# (id, label, description) -- used for settings enums by hosts.
LAYOUTS = (
    ('SHEET', "Sheet", "Hue across, value / lightness up; hue, value and saturation bars around it"),
    ('SQUARE', "Square", "Saturation across, value / lightness up; hue bar beside it"),
    ('TRIANGLE', "Triangle", "Hue ring around a saturation / value triangle"),
    ('WHEEL', "Wheel", "Hue around, saturation outward; value / lightness bar beside it"),
)
SELECTOR_MODELS = (
    (HSV, "HSV", "Hue, Saturation, Value: full value is the brightest version of a hue"),
    (HSL, "HSL", "Hue, Saturation, Lightness: half lightness is the pure hue, full is white"),
)
SLIDER_SPACES = (
    (RGB, "RGB", "Red, green and blue sliders"),
    (HSV, "HSV", "Hue, saturation and value sliders"),
    (HSL, "HSL", "Hue, saturation and lightness sliders"),
)

H, S, T = 0, 1, 2          # channel indices: hue, saturation, tone (value / lightness)
_LABEL_W = 12.0            # slider letter column, unscaled px
_VALUE_W = 28.0            # slider value column, unscaled px
_FIELD_W = 36.0            # the value column with input fields (``fields``)
_SLIDER_GAP = 3.0          # between the sliders of one space
_GROUP_GAP = 6.0           # between spaces
_TOP_GAP = 12.0            # between the main area and the first slider
_PLATE_PAD = 5.0           # the sliders' plate reaches this far past them
_PLATE_ROUND = 8.0
_SLIDER_FONT = 8.0         # slider letters / values, unscaled px


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

def _rgba(model, color, alpha):
    return (*to_rgb(model, color), alpha)


def _pure(model, h, alpha):
    """The fully saturated hue ``h`` (the hue ring / bar color)."""
    return _rgba(model, (h, 1.0, 0.5 if model == HSL else 1.0), alpha)


CAPSULE = 1e9             # corner radius of the bars: half their thickness (round ends)
SHEET_ROUND = 6.0         # corner radius of the sheet / square, unscaled px


def _grid(rect, color_at, cols, rows, radius=CAPSULE):
    """``rect`` filled with ``color_at(fx, fy)`` (fractions 0..1), interpolated on a grid,
    corners rounded by ``radius`` screen px (default: a capsule -- the bars)."""
    draw.rounded_grid(rect, radius, color_at, cols, rows)


def _outline(r, grabbed, alpha, theme, radius=CAPSULE):
    if grabbed:
        grow = theme.px(2.0)
        draw.rounded_rect_outline(r.expand(grow), radius + grow, with_alpha(theme.accent_light, alpha),
                                  width=theme.px(1.5))
    else:
        draw.rounded_rect_outline(r, radius, with_alpha(theme.border, alpha), width=theme.px(1.0))


def _double_line(points, alpha, theme):
    """Handle stroke: black under white, readable on any color."""
    for width, color in ((3.0, (0.0, 0.0, 0.0, 0.9)), (1.5, (1.0, 1.0, 1.0, 1.0))):
        draw.polyline(points, with_alpha(color, alpha), theme.px(width))


def _handle_v(r, f, alpha, theme):
    y = r.y0 + f * r.height
    ext = theme.px(3.0)
    _double_line([(r.x0 - ext, y), (r.x1 + ext, y)], alpha, theme)


def _handle_h(r, f, alpha, theme):
    x = r.x0 + f * r.width
    ext = theme.px(3.0)
    _double_line([(x, r.y0 - ext), (x, r.y1 + ext)], alpha, theme)


def _knob(r, f, rgba, grabbed, alpha, theme):
    """A channel slider's handle: a round knob in the slider's color (like the cursor)."""
    x = r.x0 + f * r.width
    radius = r.height * (0.72 if grabbed else 0.62)
    draw.circle(x, r.cy, radius, rgba, segments=20)
    draw.circle_outline(x, r.cy, radius, (0.0, 0.0, 0.0, 0.9 * alpha), width=theme.px(2.5), segments=20)
    draw.circle_outline(x, r.cy, radius, (1.0, 1.0, 1.0, alpha), width=theme.px(1.2), segments=20)


def _tick_v(r, f, color, theme):
    y = r.y0 + f * r.height
    draw.polyline([(r.x0 - theme.px(6.0), y), (r.x0 - theme.px(2.0), y)], color, theme.px(2.0))


def _tick_h(r, f, color, theme):
    x = r.x0 + f * r.width
    draw.polyline([(x, r.y0 - theme.px(6.0)), (x, r.y0 - theme.px(2.0))], color, theme.px(2.0))


def _cross(x, y, color, theme):
    arm = theme.px(4.0)
    draw.polyline([(x - arm, y), (x + arm, y)], color, theme.px(1.5))
    draw.polyline([(x, y - arm), (x, y + arm)], color, theme.px(1.5))


def _cursor(x, y, rgba, grabbed, alpha, theme):
    r = theme.px(6.0 if grabbed else 5.0)
    draw.circle(x, y, r, rgba)
    draw.circle_outline(x, y, r, (0.0, 0.0, 0.0, 0.9 * alpha), width=theme.px(3.0))
    draw.circle_outline(x, y, r, (1.0, 1.0, 1.0, alpha), width=theme.px(1.5))


def _faint(alpha):
    return (1.0, 1.0, 1.0, 0.55 * alpha)


def _wrap_angle(a):
    return (a + math.pi) % math.tau - math.pi


def _closest_on_segment(p, a, b):
    abx, aby = b[0] - a[0], b[1] - a[1]
    t = ((p[0] - a[0]) * abx + (p[1] - a[1]) * aby) / max(1e-12, abx * abx + aby * aby)
    t = clamp01(t)
    return a[0] + abx * t, a[1] + aby * t


# ---------------------------------------------------------------------------
# Layout variants
# ---------------------------------------------------------------------------

class ColorShape:
    """The main area of a :class:`ColorSelector`: how hue / saturation / tone map
    onto the screen. Colors are tuples in the selector's ``model``.

    Subclasses define the parts (name -> Rect, used for hit-testing and the
    grab highlight) and, per part, a relative ``swipe`` and an absolute ``tap``.
    """

    id = ''
    main = None            # the 2D part that can follow the pointer (hover hosts)
    free_channel = None    # the channel the main part does not set (wheel over the main part)
    part_channels = {}     # 1D part -> channel index it sets (wheel over that part)

    def __init__(self, selector):
        self.sel = selector
        self.parts = {}

    @property
    def model(self):
        return self.sel.model

    def _px(self, theme, value):
        """Unscaled px -> screen px, including the selector's fit-to-width factor."""
        return theme.px(value) * self.sel.fit_factor

    def natural_size(self):
        """Unscaled (w, h). Default: the sheet's width and a square-ish height."""
        sel = self.sel
        return sel.area[0] + 2.0 * (sel.bar + sel.gap), sel.area[1] * 1.35

    def arrange(self, rect, theme):
        """Lay the parts out in ``rect``; returns ``self.parts``."""
        raise NotImplementedError

    def part_at(self, x, y):
        raise NotImplementedError

    def follows(self, x, y):
        """Whether the pointer at ``x``/``y`` is over the main part (hover selection)."""
        return self.part_at(x, y) == self.main and self.parts[self.main].contains(x, y)

    def main_point(self, color):
        """Screen point of ``color`` on the main part."""
        raise NotImplementedError

    def channel_of(self, part):
        """Channel the mouse wheel changes over ``part`` (the free one over the main part)."""
        return self.part_channels.get(part, self.free_channel)

    def begin(self, part, color, x, y):
        """Drag state for a press on ``part`` (passed back to ``swipe``)."""
        return {}

    def swipe(self, part, color, x, y, dx, dy, data, gain):
        """``color`` after the pointer moved by ``dx``/``dy`` (now at ``x``/``y``)."""
        return color

    def tap(self, part, x, y, color):
        """``color`` with ``part`` set to the spot under ``x``/``y``."""
        return color

    def draw(self, dc, color, grabbed, original):
        raise NotImplementedError


class SheetShape(ColorShape):
    """[T] [ hue -> / tone ^ sheet ] [S]  over  [ hue bar ]  (the classic ColorPad)."""

    id = 'SHEET'
    SHEET, HUE, VALUE, SATURATION = 'SHEET', 'HUE', 'VALUE', 'SATURATION'
    main = SHEET
    free_channel = S
    part_channels = {HUE: H, VALUE: T, SATURATION: S}

    def main_point(self, color):
        sheet = self.parts[self.SHEET]
        return sheet.x0 + color[H] * sheet.width, sheet.y0 + color[T] * sheet.height

    def natural_size(self):
        sel = self.sel
        return sel.area[0] + 2.0 * (sel.bar + sel.gap), sel.area[1] + sel.gap + sel.bar

    def arrange(self, rect, theme):
        bar, gap = self._px(theme, self.sel.bar), self._px(theme, self.sel.gap)
        sheet = Rect(rect.x0 + bar + gap, rect.y0 + bar + gap, rect.x1 - bar - gap, rect.y1)
        self.parts = {
            self.SHEET: sheet,
            self.HUE: Rect(sheet.x0, rect.y0, sheet.x1, rect.y0 + bar),
            self.VALUE: Rect(rect.x0, sheet.y0, rect.x0 + bar, sheet.y1),
            self.SATURATION: Rect(rect.x1 - bar, sheet.y0, rect.x1, sheet.y1),
        }
        return self.parts

    def part_at(self, x, y):
        """Nearest part, so gaps and corners count."""
        sheet, hue = self.parts[self.SHEET], self.parts[self.HUE]
        if y < sheet.y0 - (sheet.y0 - hue.y1) * 0.5:
            return self.HUE
        if x < sheet.x0:
            return self.VALUE
        if x > sheet.x1:
            return self.SATURATION
        return self.SHEET

    def swipe(self, part, color, x, y, dx, dy, data, gain):
        h, s, t = color
        sheet = self.parts[self.SHEET]
        hue_px = max(1.0, (self.parts[self.HUE] if part == self.HUE else sheet).width)
        val_px = max(1.0, sheet.height)
        if part in (self.SHEET, self.HUE):
            h = (h + dx * gain / hue_px) % 1.0
        if part in (self.SHEET, self.VALUE):
            t = clamp01(t + dy * gain / val_px)
        if part == self.SATURATION:
            s = clamp01(s + dy * gain / val_px)
        return h, s, t

    def tap(self, part, x, y, color):
        h, s, t = color
        r = self.parts[part]
        fx = clamp01((x - r.x0) / max(1.0, r.width))
        fy = clamp01((y - r.y0) / max(1.0, r.height))
        hue = fx if fx < 1.0 else 0.0
        if part == self.SHEET:
            return hue, s, fy
        if part == self.HUE:
            return hue, s, t
        if part == self.VALUE:
            return h, s, fy
        return h, fy, t

    def draw(self, dc, color, grabbed, original):
        theme, alpha, model = dc.theme, dc.alpha, self.model
        h, s, t = color
        p = self.parts
        sheet, hue, val, sat = p[self.SHEET], p[self.HUE], p[self.VALUE], p[self.SATURATION]
        corner = self._px(theme, SHEET_ROUND)
        _grid(sheet, lambda fx, fy: _rgba(model, (fx, s, fy), alpha), 24, 8, corner)
        _grid(hue, lambda fx, fy: _pure(model, fx, alpha), 24, 1)
        _grid(val, lambda fx, fy: _rgba(model, (h, s, fy), alpha), 1, 8)
        _grid(sat, lambda fx, fy: _rgba(model, (h, fy, t), alpha), 1, 8)
        for part, r in p.items():
            _outline(r, part == grabbed, alpha, theme, corner if part == self.SHEET else CAPSULE)

        if original is not None:
            oh, os_, ot = original
            faint = _faint(alpha)
            _cross(sheet.x0 + oh * sheet.width, sheet.y0 + ot * sheet.height, faint, theme)
            _tick_h(hue, oh, faint, theme)
            _tick_v(val, ot, faint, theme)
            _tick_v(sat, os_, faint, theme)

        _handle_h(hue, h, alpha, theme)
        _handle_v(val, t, alpha, theme)
        _handle_v(sat, s, alpha, theme)
        _cursor(sheet.x0 + h * sheet.width, sheet.y0 + t * sheet.height, _rgba(model, color, alpha),
                grabbed == self.SHEET, alpha, theme)


class SquareShape(ColorShape):
    """[ saturation -> / tone ^ square ] [hue bar]"""

    id = 'SQUARE'
    SQUARE, HUE = 'SQUARE', 'HUE'
    main = SQUARE
    free_channel = H
    part_channels = {HUE: H}

    def main_point(self, color):
        square = self.parts[self.SQUARE]
        return square.x0 + color[S] * square.width, square.y0 + color[T] * square.height

    def arrange(self, rect, theme):
        bar, gap = self._px(theme, self.sel.bar), self._px(theme, self.sel.gap)
        side = max(1.0, min(rect.height, rect.width - gap - bar))
        x0 = rect.cx - (side + gap + bar) * 0.5
        y0 = rect.cy - side * 0.5
        square = Rect(x0, y0, x0 + side, y0 + side)
        self.parts = {
            self.SQUARE: square,
            self.HUE: Rect(square.x1 + gap, y0, square.x1 + gap + bar, y0 + side),
        }
        return self.parts

    def part_at(self, x, y):
        square, hue = self.parts[self.SQUARE], self.parts[self.HUE]
        return self.HUE if x > (square.x1 + hue.x0) * 0.5 else self.SQUARE

    def swipe(self, part, color, x, y, dx, dy, data, gain):
        h, s, t = color
        r = self.parts[part]
        if part == self.HUE:
            return (h + dy * gain / max(1.0, r.height)) % 1.0, s, t
        return h, clamp01(s + dx * gain / max(1.0, r.width)), clamp01(t + dy * gain / max(1.0, r.height))

    def tap(self, part, x, y, color):
        h, s, t = color
        r = self.parts[part]
        fx = clamp01((x - r.x0) / max(1.0, r.width))
        fy = clamp01((y - r.y0) / max(1.0, r.height))
        if part == self.HUE:
            return (fy if fy < 1.0 else 0.0), s, t
        return h, fx, fy

    def draw(self, dc, color, grabbed, original):
        theme, alpha, model = dc.theme, dc.alpha, self.model
        h, s, t = color
        square, hue = self.parts[self.SQUARE], self.parts[self.HUE]
        corner = self._px(theme, SHEET_ROUND)
        _grid(square, lambda fx, fy: _rgba(model, (h, fx, fy), alpha), 8, 8, corner)
        _grid(hue, lambda fx, fy: _pure(model, fy, alpha), 1, 24)
        for part, r in self.parts.items():
            _outline(r, part == grabbed, alpha, theme, corner if part == self.SQUARE else CAPSULE)
        if original is not None:
            oh, os_, ot = original
            faint = _faint(alpha)
            _cross(square.x0 + os_ * square.width, square.y0 + ot * square.height, faint, theme)
            _tick_v(hue, oh, faint, theme)
        _handle_v(hue, h, alpha, theme)
        _cursor(square.x0 + s * square.width, square.y0 + t * square.height, _rgba(model, color, alpha),
                grabbed == self.SQUARE, alpha, theme)


class WheelShape(ColorShape):
    """[ disc: hue = angle, saturation = radius ] [tone bar]"""

    id = 'WHEEL'
    DISC, TONE = 'DISC', 'TONE'
    main = DISC
    free_channel = T
    part_channels = {TONE: T}
    _SEGMENTS = 72

    def follows(self, x, y):
        cx, cy = self.center
        return math.hypot(x - cx, y - cy) <= self.radius

    def main_point(self, color):
        px, py = self._point(color)
        cx, cy = self.center
        return cx + px * self.radius, cy + py * self.radius

    def arrange(self, rect, theme):
        bar, gap = self._px(theme, self.sel.bar), self._px(theme, self.sel.gap)
        d = max(1.0, min(rect.height, rect.width - 2.0 * gap - bar))
        x0 = rect.cx - (d + 2.0 * gap + bar) * 0.5
        y0 = rect.cy - d * 0.5
        disc = Rect(x0, y0, x0 + d, y0 + d)
        self.center = (disc.cx, disc.cy)
        self.radius = d * 0.5
        self.parts = {
            self.DISC: disc,
            self.TONE: Rect(disc.x1 + 2.0 * gap, y0, disc.x1 + 2.0 * gap + bar, y0 + d),
        }
        return self.parts

    def part_at(self, x, y):
        disc, tone = self.parts[self.DISC], self.parts[self.TONE]
        return self.TONE if x > (disc.x1 + tone.x0) * 0.5 else self.DISC

    def _point(self, color):
        """Normalized disc point (unit radius) of ``color``."""
        a = color[H] * math.tau
        return [color[S] * math.cos(a), color[S] * math.sin(a)]

    def _from_point(self, point, color):
        r = math.hypot(*point)
        if r > 1.0:
            point[0] /= r
            point[1] /= r
            r = 1.0
        h = (math.atan2(point[1], point[0]) / math.tau) % 1.0 if r > 1e-6 else color[H]
        return h, r, color[T]

    def begin(self, part, color, x, y):
        return {'point': self._point(color)} if part == self.DISC else {}

    def swipe(self, part, color, x, y, dx, dy, data, gain):
        if part == self.TONE:
            r = self.parts[self.TONE]
            return color[H], color[S], clamp01(color[T] + dy * gain / max(1.0, r.height))
        point = data['point']
        scale = gain / max(1.0, self.radius)
        point[0] += dx * scale
        point[1] += dy * scale
        return self._from_point(point, color)

    def tap(self, part, x, y, color):
        if part == self.TONE:
            r = self.parts[self.TONE]
            return color[H], color[S], clamp01((y - r.y0) / max(1.0, r.height))
        cx, cy = self.center
        point = [(x - cx) / max(1.0, self.radius), (y - cy) / max(1.0, self.radius)]
        return self._from_point(point, color)

    def draw(self, dc, color, grabbed, original):
        theme, alpha, model = dc.theme, dc.alpha, self.model
        h, s, t = color
        cx, cy = self.center
        rad = self.radius
        # Saturation is linear in RGB for both models: one ring of triangles is exact radially.
        mid = _rgba(model, (0.0, 0.0, t), alpha)
        verts, colors = [], []
        n = self._SEGMENTS
        for i in range(n):
            a0, a1 = i / n, (i + 1) / n
            verts += [(cx, cy),
                      (cx + math.cos(a0 * math.tau) * rad, cy + math.sin(a0 * math.tau) * rad),
                      (cx + math.cos(a1 * math.tau) * rad, cy + math.sin(a1 * math.tau) * rad)]
            colors += [mid, _rgba(model, (a0, 1.0, t), alpha), _rgba(model, (a1, 1.0, t), alpha)]
        draw.shaded_tris(verts, colors)
        tone = self.parts[self.TONE]
        _grid(tone, lambda fx, fy: _rgba(model, (h, s, fy), alpha), 1, 8)

        if grabbed == self.DISC:
            draw.circle_outline(cx, cy, rad + theme.px(2.0), with_alpha(theme.accent_light, alpha),
                                width=theme.px(1.5), segments=n)
        else:
            draw.circle_outline(cx, cy, rad, with_alpha(theme.border, alpha), width=theme.px(1.0), segments=n)
        _outline(tone, grabbed == self.TONE, alpha, theme)

        if original is not None:
            faint = _faint(alpha)
            ox, oy = self._point(original)
            _cross(cx + ox * rad, cy + oy * rad, faint, theme)
            _tick_v(tone, original[T], faint, theme)
        _handle_v(tone, t, alpha, theme)
        px, py = self._point(color)
        _cursor(cx + px * rad, cy + py * rad, _rgba(model, color, alpha), grabbed == self.DISC, alpha, theme)


class TriangleShape(ColorShape):
    """Hue ring around a fixed triangle: pure hue (right), white (top left),
    black (bottom left). Saturation grows to the right, tone upward."""

    id = 'TRIANGLE'
    RING, TRIANGLE = 'RING', 'TRIANGLE'
    main = TRIANGLE
    free_channel = H
    part_channels = {RING: H}
    _SEGMENTS = 72

    def follows(self, x, y):
        return self.part_at(x, y) == self.TRIANGLE   # the triangle clamps the pointer onto it

    def main_point(self, color):
        return self._point(color)

    def arrange(self, rect, theme):
        bar, gap = self._px(theme, self.sel.bar), self._px(theme, self.sel.gap)
        d = max(1.0, min(rect.width, rect.height))
        cx, cy = rect.cx, rect.cy
        self.center = (cx, cy)
        self.outer = d * 0.5
        self.inner = max(1.0, self.outer - bar)
        rt = self.tri_radius = max(1.0, self.inner - gap)
        self.vertices = tuple(
            (cx + math.cos(a) * rt, cy + math.sin(a) * rt)
            for a in (0.0, math.tau / 3.0, 2.0 * math.tau / 3.0))   # hue, white, black
        xs = [v[0] for v in self.vertices]
        ys = [v[1] for v in self.vertices]
        self.parts = {
            self.RING: Rect.from_center(cx, cy, d, d),
            self.TRIANGLE: Rect(min(xs), min(ys), max(xs), max(ys)),
        }
        return self.parts

    def part_at(self, x, y):
        """Outside the middle of the gap between triangle and ring: the ring."""
        cx, cy = self.center
        edge = (self.inner + self.tri_radius) * 0.5
        return self.RING if math.hypot(x - cx, y - cy) > edge else self.TRIANGLE

    # ---- triangle mapping ------------------------------------------------------

    def _point(self, color):
        hue_v, white_v, black_v = self.vertices
        hw, ww = tone_weights(self.model, color[S], color[T])
        return (black_v[0] + hw * (hue_v[0] - black_v[0]) + ww * (white_v[0] - black_v[0]),
                black_v[1] + hw * (hue_v[1] - black_v[1]) + ww * (white_v[1] - black_v[1]))

    def _weights(self, p):
        hue_v, white_v, black_v = self.vertices
        e1x, e1y = hue_v[0] - black_v[0], hue_v[1] - black_v[1]
        e2x, e2y = white_v[0] - black_v[0], white_v[1] - black_v[1]
        px, py = p[0] - black_v[0], p[1] - black_v[1]
        det = e1x * e2y - e1y * e2x
        if abs(det) < 1e-12:
            return 0.0, 0.0
        return (px * e2y - py * e2x) / det, (e1x * py - e1y * px) / det

    def _clamp(self, p):
        hw, ww = self._weights(p)
        if hw >= 0.0 and ww >= 0.0 and hw + ww <= 1.0:
            return tuple(p)
        v = self.vertices
        candidates = [_closest_on_segment(p, v[i], v[(i + 1) % 3]) for i in range(3)]
        return min(candidates, key=lambda q: (q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2)

    def _from_point(self, p, color):
        hw, ww = self._weights(p)
        s, t = from_tone_weights(self.model, hw, ww, color[S])
        return color[H], s, t

    def _angle(self, x, y):
        cx, cy = self.center
        return math.atan2(y - cy, x - cx)

    # ---- interaction ---------------------------------------------------------------

    def begin(self, part, color, x, y):
        if part == self.RING:
            return {'angle': self._angle(x, y)}
        return {'point': self._point(color)}

    def swipe(self, part, color, x, y, dx, dy, data, gain):
        if part == self.RING:
            a = self._angle(x, y)
            da = _wrap_angle(a - data['angle'])
            data['angle'] = a
            return (color[H] + da / math.tau * gain) % 1.0, color[S], color[T]
        px, py = data['point']
        data['point'] = self._clamp((px + dx * gain, py + dy * gain))
        return self._from_point(data['point'], color)

    def tap(self, part, x, y, color):
        if part == self.RING:
            return (self._angle(x, y) / math.tau) % 1.0, color[S], color[T]
        return self._from_point(self._clamp((x, y)), color)

    # ---- drawing -------------------------------------------------------------------

    def draw(self, dc, color, grabbed, original):
        theme, alpha, model = dc.theme, dc.alpha, self.model
        h = color[H]
        cx, cy = self.center
        ro, ri = self.outer, self.inner
        n = self._SEGMENTS
        verts, colors = [], []
        for i in range(n):
            a0, a1 = i / n, (i + 1) / n
            c0, c1 = _pure(model, a0, alpha), _pure(model, a1, alpha)
            p0o = (cx + math.cos(a0 * math.tau) * ro, cy + math.sin(a0 * math.tau) * ro)
            p1o = (cx + math.cos(a1 * math.tau) * ro, cy + math.sin(a1 * math.tau) * ro)
            p0i = (cx + math.cos(a0 * math.tau) * ri, cy + math.sin(a0 * math.tau) * ri)
            p1i = (cx + math.cos(a1 * math.tau) * ri, cy + math.sin(a1 * math.tau) * ri)
            verts += [p0i, p0o, p1o, p0i, p1o, p1i]
            colors += [c0, c0, c1, c0, c1, c1]
        draw.shaded_tris(verts, colors)
        # Both models are linear in the (hue, white, black) weights: vertex colors are exact.
        draw.shaded_tris(list(self.vertices),
                         [_pure(model, h, alpha), (1.0, 1.0, 1.0, alpha), (0.0, 0.0, 0.0, alpha)])

        ring_grab = grabbed == self.RING
        ring_color = with_alpha(theme.accent_light if ring_grab else theme.border, alpha)
        ring_w = theme.px(1.5 if ring_grab else 1.0)
        draw.circle_outline(cx, cy, ro, ring_color, width=ring_w, segments=n)
        draw.circle_outline(cx, cy, ri, ring_color, width=ring_w, segments=n)
        tri_grab = grabbed == self.TRIANGLE
        tri_color = with_alpha(theme.accent_light if tri_grab else theme.border, alpha)
        draw.polyline([*self.vertices, self.vertices[0]], tri_color, theme.px(1.5 if tri_grab else 1.0))

        if original is not None:
            faint = _faint(alpha)
            ox, oy = self._point(original)
            _cross(ox, oy, faint, theme)
            a = original[H] * math.tau
            cos_a, sin_a = math.cos(a), math.sin(a)
            r0, r1 = ro + theme.px(2.0), ro + theme.px(6.0)
            draw.polyline([(cx + cos_a * r0, cy + sin_a * r0), (cx + cos_a * r1, cy + sin_a * r1)],
                          faint, theme.px(2.0))

        a = h * math.tau
        cos_a, sin_a = math.cos(a), math.sin(a)
        ext = theme.px(3.0)
        _double_line([(cx + cos_a * (ri - ext), cy + sin_a * (ri - ext)),
                      (cx + cos_a * (ro + ext), cy + sin_a * (ro + ext))], alpha, theme)
        px, py = self._point(color)
        _cursor(px, py, _rgba(model, color, alpha), tri_grab, alpha, theme)


SHAPES = {cls.id: cls for cls in (SheetShape, SquareShape, TriangleShape, WheelShape)}


# ---------------------------------------------------------------------------
# The widget
# ---------------------------------------------------------------------------

class ColorSelector(Widget):
    """``get_hsv()`` -> (h, s, v) of the edited color; ``set_hsv(h, s, v)`` commits it.

    ``layout``: 'SHEET' / 'SQUARE' / 'TRIANGLE' / 'WHEEL'; ``model``: 'HSV' / 'HSL';
    ``sliders``: iterable of 'RGB' / 'HSV' / 'HSL' -- each a value or a callable.
    ``area``: unscaled size of the sheet (the other layouts derive their size from it);
    ``bar`` / ``gap``: bar thickness and spacing; ``slider_bar``: the channel sliders'
    thickness; ``fields``: input fields for the slider values; ``gain``: swipe speed.
    """

    interactive = True
    draggable = True

    def __init__(self, get_hsv, set_hsv, *, original=None, live=False, layout='SHEET', model=HSV,
                 sliders=(), area=(150.0, 96.0), bar=14.0, gap=5.0, gain=0.5, slider_bar=10.0,
                 fields=False, **kwargs):
        super().__init__(**kwargs)
        self.get_hsv = get_hsv
        self.set_hsv = set_hsv
        self.original = original
        self.live = live              # bool or () -> bool: commit while dragging too
        self.layout_binding = layout
        self.model_binding = model
        self.sliders_binding = sliders
        self.fit_width = None         # screen px: scale the whole selector uniformly to this width
        self.fit_factor = 1.0
        self.area = area
        self.bar = bar
        self.gap = gap
        self.gain = gain
        self.slider_bar = slider_bar
        self.fields = fields
        self.value_fields = {}        # slider part key -> TextField (with ``fields``)

        self.model = HSV
        self.shape = None
        self.slider_spaces = ()
        self.sliders = []             # (part key, space, channel index), top to bottom
        self.main_rect = Rect()
        self.parts = {}               # part -> Rect (set by arrange)
        self.drag = None              # running drag: part, start, color, last point, travel, data
        self._config = None
        self._memo = None             # (model, hsv written, model color): survives grey / black
        self._tap_travel = TAP_TRAVEL
        self._follow = None           # hover selection state (follow_begin)
        self.sync_config()

    # ---- configuration -------------------------------------------------------

    def sync_config(self):
        """Re-read layout / model / sliders (not during a drag)."""
        if self.drag is not None:
            return
        layout = _resolve(self.layout_binding, 'SHEET')
        model = _resolve(self.model_binding, HSV)
        if model not in (HSV, HSL):
            model = HSV
        wanted = set(_resolve(self.sliders_binding, ()) or ())
        sliders = tuple(space for space, _label, _desc in SLIDER_SPACES if space in wanted)
        config = (SHAPES.get(layout, SheetShape), model, sliders)
        if config == self._config:
            return
        self._config = config
        self.shape = config[0](self)
        self.model = model
        self.slider_spaces = sliders
        self.sliders = [(f"{space}_{letter}", space, i)
                        for space in sliders for i, letter in enumerate(CHANNELS[space])]
        self.parts = {}
        self.children = []
        self.value_fields = {}
        if self.fields:
            for key, space, index in self.sliders:
                self.value_fields[key] = self.add(TextField(
                    lambda s=space, i=index: self._field_text(s, i),
                    lambda text, s=space, i=index: self.set_channel_text(s, i, text),
                    font_size=_SLIDER_FONT, allowed=NUMBER_CHARS, max_length=8, key=f"FIELD_{key}"))

    @property
    def layout_id(self):
        return self.shape.id

    # ---- layout --------------------------------------------------------------

    def _sliders_height(self):
        """Unscaled height of the slider block (0 without sliders)."""
        if not self.slider_spaces:
            return 0.0
        groups = len(self.slider_spaces)
        return (_TOP_GAP + _PLATE_PAD + (groups - 1) * _GROUP_GAP
                + groups * (3.0 * self.slider_bar + 2.0 * _SLIDER_GAP))

    def _value_w(self):
        return _FIELD_W if self.fields else _VALUE_W

    def _natural_size(self, theme):
        w, h = self.shape.natural_size()
        return theme.px(w), theme.px(h + self._sliders_height())

    def _fit(self, theme):
        """Uniform scale factor that makes the selector ``fit_width`` wide (1 without one)."""
        if not self.fit_width:
            return 1.0
        return max(0.1, self.fit_width / max(1.0, self._natural_size(theme)[0]))

    def measure(self, theme):
        self.sync_config()
        w, h = self._natural_size(theme)
        f = self._fit(theme)
        return w * f, h * f

    def arrange(self, rect, theme):
        """The main area takes what the sliders leave."""
        self.sync_config()
        self.rect = rect
        f = self.fit_factor = self._fit(theme)
        self._tap_travel = theme.px(TAP_TRAVEL)

        def px(value):
            return theme.px(value) * f

        main = Rect(rect.x0, rect.y0 + px(self._sliders_height()), rect.x1, rect.y1)
        self.main_rect = main
        parts = dict(self.shape.arrange(main, theme))
        y = main.y0
        space = None
        bar = px(self.slider_bar)
        for key, slider_space, _i in self.sliders:
            if space is None:
                y -= px(_TOP_GAP)
            else:
                y -= px(_GROUP_GAP if slider_space != space else _SLIDER_GAP)
            space = slider_space
            r = parts[key] = Rect(rect.x0 + px(_LABEL_W), y - bar, rect.x1 - px(self._value_w()), y)
            field = self.value_fields.get(key)
            if field is not None:
                field.scale = f
                fh = bar + px(_SLIDER_GAP) * 0.8
                field.arrange(Rect(r.x1 + px(4.0), r.cy - fh * 0.5, rect.x1, r.cy + fh * 0.5), theme)
            y -= bar
        self.parts = parts

    def part_at(self, x, y):
        """The part a press at ``x``/``y`` grabs (nearest, so gaps and corners count)."""
        if self.sliders and y < self.main_rect.y0:
            return min((key for key, _s, _i in self.sliders),
                       key=lambda k: abs(y - self.parts[k].cy))
        return self.shape.part_at(x, y)

    def _slider(self, part):
        for key, space, index in self.sliders:
            if key == part:
                return space, index
        return None

    # ---- color ---------------------------------------------------------------

    def _current(self):
        """The edited color in the selector's model."""
        hsv = tuple(float(c) for c in _resolve(self.get_hsv, (0.0, 0.0, 0.0)))
        memo = self._memo
        if memo is not None and memo[0] == self.model:
            if all(abs(a - b) <= _SAME_EPS for a, b in zip(hsv, memo[1])):
                return memo[2]
            return convert(hsv, HSV, self.model, hint=memo[2])
        return convert(hsv, HSV, self.model, hint=hsv)

    def _commit(self, color):
        hsv = convert(color, self.model, HSV, hint=color)
        self._memo = (self.model, hsv, tuple(color))
        self.set_hsv(*hsv)

    def _original(self):
        original = _resolve(self.original, None)
        if original is not None:
            return convert(original, HSV, self.model, hint=original)
        return self.drag['start'] if self.drag is not None else None

    def rgb(self):
        """The edited color as RGB (0..1)."""
        return tuple(to_rgb(self.model, self._current()))

    def set_rgb(self, rgb):
        """Commit ``rgb`` (0..1); hue / saturation survive greys. Ignored during a drag."""
        if self.drag is not None:
            return
        self._commit(convert(tuple(rgb), RGB, self.model, hint=self._current()))
        self._rested()

    def _field_text(self, space, index):
        color = self.drag['color'] if self.drag is not None else self._current()
        return _format(space, index, self._slider_values(space, color)[index])

    def set_channel_text(self, space, index, text):
        """An input field's text: channel ``index`` of ``space`` in display units (hue
        degrees, RGB 0..255, else percent). Unreadable text is ignored."""
        value = _parse_number(text)
        if value is None or self.drag is not None:
            return
        if wraps(space, index):
            value = (value % 360.0) / 360.0
        else:
            value = clamp01(value / (255.0 if space == RGB else 100.0))
        color = self._current()
        values = self._slider_values(space, color)
        values[index] = value
        self._commit(convert(values, space, self.model, hint=color))
        self._rested()

    # ---- pointer following (mouse hosts, e.g. the E key selector) -------------

    def follow_begin(self, now):
        """Start hover selection; the pointer is expected on the current color's spot."""
        self._follow = {'rest': self._current(), 'last': now, 'inside': True}

    def follow(self, x, y, now):
        """The main part follows the pointer (commits). Leaving the main part restores
        the color from where the pointer last rested (``REST_TIME``), so moving over to
        a bar does not change the picked color. True when the color changed."""
        f = self._follow
        if f is None or self.drag is not None or not self.parts:
            return False
        current = self._current()
        if self.shape.follows(x, y):
            if not f['inside'] or now - f['last'] >= REST_TIME:
                f['rest'] = current       # entered / rested on the previous spot
            f['inside'] = True
            f['last'] = now
            color = tuple(self.shape.tap(self.shape.main, x, y, current))
            if all(abs(a - b) <= _SAME_EPS for a, b in zip(color, current)):
                return False   # same spot (float noise): keep the color exactly
            self._commit(color)
            return True
        if not f['inside']:
            return False
        f['inside'] = False
        if f['rest'] == current:
            return False
        self._commit(f['rest'])
        return True

    def main_point(self, color=None):
        """Screen point of ``color`` (default: the current one) on the main part."""
        return self.shape.main_point(self._current() if color is None else color)

    def _rested(self):
        """A wheel / bar change is deliberate: keep it when the pointer leaves the main part."""
        if self._follow is not None:
            self._follow['rest'] = self._current()

    def wheel(self, x, y, delta):
        """Mouse wheel at ``x``/``y``: over a bar / slider its channel, elsewhere the
        channel the main part does not set. Ignored during a drag."""
        if self.drag is not None or not self.parts:
            return
        part = self.part_at(x, y) if self.rect.contains(x, y) else None
        slider = self._slider(part)
        if slider is None:
            self.nudge(self.shape.channel_of(part), delta)
        else:
            space, index = slider
            color = self._current()
            values = self._slider_values(space, color)
            if wraps(space, index):
                values[index] = (values[index] + delta) % 1.0
            else:
                values[index] = clamp01(values[index] + delta)
            self._commit(convert(values, space, self.model, hint=color))
        self._rested()

    def nudge(self, index, delta):
        """Shift channel ``index`` of the model (0 hue, 1 saturation, 2 tone) by
        ``delta`` and commit (e.g. the mouse wheel). Ignored during a drag."""
        if self.drag is not None:
            return
        color = list(self._current())
        if wraps(self.model, index):
            color[index] = (color[index] + delta) % 1.0
        else:
            color[index] = clamp01(color[index] + delta)
        self._commit(tuple(color))

    def _slider_values(self, space, color):
        hint = color if space in (HSV, HSL) else None
        return list(convert(color, self.model, space, hint=hint))

    # ---- drag ----------------------------------------------------------------

    def drag_begin(self, x, y):
        color = self._current()
        part = self.part_at(x, y)
        slider = self._slider(part)
        if slider is not None:
            data = {'values': self._slider_values(slider[0], color)}
        else:
            data = self.shape.begin(part, color, x, y)
        self.drag = {'part': part, 'start': color, 'color': color, 'last': (x, y),
                     'travel': 0.0, 'data': data}

    def _swipe(self, x, y, dx, dy):
        drag = self.drag
        part, color, data = drag['part'], drag['color'], drag['data']
        slider = self._slider(part)
        if slider is None:
            return self.shape.swipe(part, color, x, y, dx, dy, data, self.gain)
        space, index = slider
        values = data['values']
        step = dx * self.gain / max(1.0, self.parts[part].width)
        if wraps(space, index):
            values[index] = (values[index] + step) % 1.0
        else:
            values[index] = clamp01(values[index] + step)
        return convert(values, space, self.model, hint=color)

    def _tap(self, part, x, y, color):
        slider = self._slider(part)
        if slider is None:
            return self.shape.tap(part, x, y, color)
        space, index = slider
        r = self.parts[part]
        f = clamp01((x - r.x0) / max(1.0, r.width))
        values = self._slider_values(space, color)
        values[index] = 0.0 if wraps(space, index) and f >= 1.0 else f
        return convert(values, space, self.model, hint=color)

    def drag_update(self, x, y):
        drag = self.drag
        if drag is None:
            return
        lx, ly = drag['last']
        dx, dy = x - lx, y - ly
        drag['last'] = (x, y)
        drag['travel'] += math.hypot(dx, dy)
        if drag['travel'] < self._tap_travel:
            return  # might still be a tap
        drag['color'] = tuple(self._swipe(x, y, dx, dy))
        if _resolve(self.live, False):
            drag['live'] = True
            self._commit(drag['color'])

    def drag_end(self, x, y, cancelled=False):
        drag, self.drag = self.drag, None
        if drag is None:
            return
        if cancelled:
            if drag.get('live'):
                self._commit(drag['start'])  # undo the live steps
            return
        if drag['travel'] < self._tap_travel:
            if x is not None:
                self._commit(self._tap(drag['part'], x, y, drag['color']))
        else:
            self._commit(drag['color'])
        if self._follow is not None:
            self._rested()
            self._follow['inside'] = False

    # ---- drawing ---------------------------------------------------------------

    def draw_self(self, dc):
        if not self.parts:
            return
        color = self.drag['color'] if self.drag is not None else self._current()
        grabbed = self.drag['part'] if self.drag is not None else None
        original = self._original()
        self.shape.draw(dc, color, grabbed, original)
        if self.sliders:
            self._draw_sliders(dc, color, grabbed, original)

    def _draw_sliders(self, dc, color, grabbed, original):
        theme, alpha = dc.theme, dc.alpha
        f = self.fit_factor
        size = max(6.0, theme.px(_SLIDER_FONT) * f)
        label_color = with_alpha(theme.text_muted, alpha)
        # A soft plate behind the slider block (letters, bars, values).
        first, last = self.parts[self.sliders[0][0]], self.parts[self.sliders[-1][0]]
        pad = theme.px(_PLATE_PAD) * f
        plate = Rect(self.rect.x0, last.y0 - pad, self.rect.x1, first.y1 + pad)
        draw.rounded_rect(plate, theme.px(_PLATE_ROUND) * f, with_alpha(theme.surface_dark, 0.55 * alpha),
                          rim=theme.edge_for(theme.surface_dark, 0.55 * alpha))
        value_color = with_alpha(theme.text, 0.9 * alpha)
        faint = _faint(alpha)
        for key, space, index in self.sliders:
            r = self.parts[key]
            if grabbed == key:
                values = self.drag['data']['values']
            else:
                values = self._slider_values(space, color)

            def color_at(fx, _fy, values=values, space=space, index=index):
                c = list(values)
                c[index] = fx
                return (*to_rgb(space, c), alpha)

            _grid(r, color_at, 24 if wraps(space, index) else 4, 1)
            _outline(r, grabbed == key, alpha, theme)
            if original is not None:
                _tick_h(r, self._slider_values(space, original)[index], faint, theme)
            _knob(r, values[index], (*to_rgb(space, values), alpha), grabbed == key, alpha, theme)

            draw.text_centered(CHANNELS[space][index], r.x0 - theme.px(_LABEL_W) * f * 0.5, r.cy,
                               size, label_color)
            if key not in self.value_fields:
                draw.text_centered(_format(space, index, values[index]),
                                   r.x1 + theme.px(_VALUE_W) * f * 0.5, r.cy, size, value_color)


def _format(space, index, value):
    if wraps(space, index):
        return f"{round(value * 360) % 360}°"
    if space == RGB:
        return str(int(round(value * 255)))
    return str(int(round(value * 100)))


def _parse_number(text):
    """The number in an input field's text (``°`` / ``%`` and spaces ignored, a comma
    counts as the decimal point), or None."""
    t = (text or "").replace("°", "").replace("%", "").replace(",", ".").strip()
    try:
        value = float(t)
    except ValueError:
        return None
    return value if value == value and abs(value) != float('inf') else None
