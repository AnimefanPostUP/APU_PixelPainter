"""ColorPad: compact HSV color selector operated by swiping (pen / touch friendly).

Layout (unscaled px)::

    [V]  [ hue -> / value ^ sheet ]  [S]
         [ hue bar               ]

Every part works like a touchpad: press anywhere on it and drag -- the
selection moves by the drag (times ``gain``) instead of jumping under the
pen, so the color cursor is separate from the pen and can be steered
precisely. Hue wraps around, the others clamp. A tap (press + release
without dragging) jumps to the tapped spot. The pad shows the swipe live and
commits it on release (``set_hsv``); with ``live`` true it also commits every
step while the pen is down. ESC / right-click during a drag discard it.

``original()`` (optional) returns an HSV to mark with a faint cross and bar
ticks (e.g. the applied color while a previewed change is pending); during a
drag without one, the color from before the drag is marked.

The pad keeps its own HSV while it is used, so hue survives grey / black
(where RGB has no hue) and dragging is free of RGB round-trip drift.
"""

import colorsys
import math

from . import draw
from .geometry import Rect
from .theme import with_alpha
from .widget import Widget, _resolve


SHEET, HUE, VALUE, SATURATION = 'SHEET', 'HUE', 'VALUE', 'SATURATION'
TAP_TRAVEL = 4.0   # unscaled px; less pointer travel than this = a tap
_SAME_RGB_EPS = 1e-4
_GREY_EPS = 1e-3


def hsv_for_rgb(rgb, remembered=None):
    """HSV for ``rgb``, given ``remembered = (rgb, hsv)`` last written by the pad.

    While the color is still the one written, the written HSV is returned
    (RGB loses hue at grey and hue + saturation at black). A color changed
    elsewhere is converted, borrowing only what its RGB cannot tell.
    """
    rgb = tuple(rgb)
    if remembered is not None and all(abs(a - b) <= _SAME_RGB_EPS for a, b in zip(rgb, remembered[0])):
        return tuple(remembered[1])
    h, s, v = colorsys.rgb_to_hsv(*rgb)
    if remembered is not None:
        old_h, old_s, _old_v = remembered[1]
        if v < _GREY_EPS:
            h, s = old_h, old_s
        elif s < _GREY_EPS:
            h = old_h
    return h, s, v


def wrap01(x):
    return x % 1.0


def clamp01(x):
    return max(0.0, min(1.0, x))


def swipe(hsv, part, dx, dy, spans, gain=1.0):
    """HSV after swiping ``part`` by ``dx``/``dy`` px. ``spans`` = (hue px, value px)
    for the full range of each axis (the part's length)."""
    h, s, v = hsv
    hue_px, val_px = spans
    if part == SHEET:
        h = wrap01(h + dx * gain / hue_px)
        v = clamp01(v + dy * gain / val_px)
    elif part == HUE:
        h = wrap01(h + dx * gain / hue_px)
    elif part == VALUE:
        v = clamp01(v + dy * gain / val_px)
    elif part == SATURATION:
        s = clamp01(s + dy * gain / val_px)
    return h, s, v


class ColorPad(Widget):
    """``get_hsv()`` -> (h, s, v) of the edited color; ``set_hsv(h, s, v)`` commits it."""

    interactive = True
    draggable = True

    def __init__(self, get_hsv, set_hsv, *, original=None, live=False, sheet_size=(150.0, 96.0),
                 bar=14.0, gap=5.0, gain=0.5, **kwargs):
        super().__init__(**kwargs)
        self.get_hsv = get_hsv
        self.set_hsv = set_hsv
        self.original = original
        self.live = live          # bool or () -> bool: commit while dragging too
        self.fit_width = None     # screen px: scale the whole pad uniformly to this width
        self.sheet_size = sheet_size
        self.bar = bar
        self.gap = gap
        self.gain = gain
        self.parts = {}            # part -> Rect (set by arrange)
        self.drag = None           # running drag: part, start hsv, hsv, last point, travel
        self._tap_travel = TAP_TRAVEL

    # ---- layout --------------------------------------------------------------

    def _natural_size(self, theme):
        sw, sh = theme.px(self.sheet_size[0]), theme.px(self.sheet_size[1])
        bar, gap = theme.px(self.bar), theme.px(self.gap)
        return sw + 2.0 * (bar + gap), sh + gap + bar

    def _fit(self, theme):
        """Uniform scale factor that makes the pad ``fit_width`` wide (1 without one)."""
        if not self.fit_width:
            return 1.0
        return max(0.1, self.fit_width / max(1.0, self._natural_size(theme)[0]))

    def measure(self, theme):
        w, h = self._natural_size(theme)
        f = self._fit(theme)
        return w * f, h * f

    def arrange(self, rect, theme):
        """Fills ``rect``: the sheet takes whatever the bars leave."""
        self.rect = rect
        f = self._fit(theme)
        bar, gap = theme.px(self.bar) * f, theme.px(self.gap) * f
        self._tap_travel = theme.px(TAP_TRAVEL)
        sheet = Rect(rect.x0 + bar + gap, rect.y0 + bar + gap, rect.x1 - bar - gap, rect.y1)
        self.parts = {
            SHEET: sheet,
            HUE: Rect(sheet.x0, rect.y0, sheet.x1, rect.y0 + bar),
            VALUE: Rect(rect.x0, sheet.y0, rect.x0 + bar, sheet.y1),
            SATURATION: Rect(rect.x1 - bar, sheet.y0, rect.x1, sheet.y1),
        }

    def part_at(self, x, y):
        """The part a press at ``x``/``y`` grabs (nearest, so gaps / corners count)."""
        sheet = self.parts[SHEET]
        if y < sheet.y0 - self._gap_half():
            return HUE
        if x < sheet.x0:
            return VALUE
        if x > sheet.x1:
            return SATURATION
        return SHEET

    def _gap_half(self):
        hue = self.parts[HUE]
        return (self.parts[SHEET].y0 - hue.y1) * 0.5

    def _spans(self, part):
        sheet = self.parts[SHEET]
        hue_px = self.parts[HUE].width if part == HUE else sheet.width
        return max(1.0, hue_px), max(1.0, sheet.height)

    def value_at(self, part, x, y, hsv):
        """HSV with ``part`` set to the spot under ``x``/``y`` (a tap)."""
        h, s, v = hsv
        r = self.parts[part]
        fx = clamp01((x - r.x0) / max(1.0, r.width))
        fy = clamp01((y - r.y0) / max(1.0, r.height))
        if part == SHEET:
            return fx if fx < 1.0 else 0.0, s, fy
        if part == HUE:
            return fx if fx < 1.0 else 0.0, s, v
        if part == VALUE:
            return h, s, fy
        return h, fy, v

    # ---- drag ----------------------------------------------------------------

    def _current(self):
        hsv = _resolve(self.get_hsv, (0.0, 0.0, 0.0))
        return tuple(float(c) for c in hsv)

    def drag_begin(self, x, y):
        hsv = self._current()
        self.drag = {'part': self.part_at(x, y), 'start': hsv, 'hsv': hsv,
                     'last': (x, y), 'travel': 0.0}

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
        drag['hsv'] = swipe(drag['hsv'], drag['part'], dx, dy, self._spans(drag['part']), self.gain)
        if _resolve(self.live, False):
            drag['live'] = True
            self.set_hsv(*drag['hsv'])

    def drag_end(self, x, y, cancelled=False):
        drag, self.drag = self.drag, None
        if drag is None:
            return
        if cancelled:
            if drag.get('live'):
                self.set_hsv(*drag['start'])  # undo the live steps
            return
        if drag['travel'] < self._tap_travel:
            if x is not None:
                self.set_hsv(*self.value_at(drag['part'], x, y, drag['hsv']))
        else:
            self.set_hsv(*drag['hsv'])

    # ---- drawing ---------------------------------------------------------------

    def draw_self(self, dc):
        if not self.parts:
            return
        theme = dc.theme
        alpha = dc.alpha
        h, s, v = self.drag['hsv'] if self.drag is not None else self._current()
        p = self.parts

        def rgba(hh, ss, vv):
            return (*colorsys.hsv_to_rgb(hh, ss, vv), alpha)

        # Sheet: hue across (exact with 6 segments: RGB is linear between 60 deg stops), value up.
        sheet = p[SHEET]
        for i in range(6):
            h0, h1 = i / 6.0, (i + 1) / 6.0
            seg = Rect(sheet.x0 + sheet.width * h0, sheet.y0, sheet.x0 + sheet.width * h1, sheet.y1)
            draw.gradient_quad(seg, rgba(h0, s, 0.0), rgba(h1, s, 0.0), rgba(h1, s, 1.0), rgba(h0, s, 1.0))
        hue = p[HUE]
        for i in range(6):
            h0, h1 = i / 6.0, (i + 1) / 6.0
            seg = Rect(hue.x0 + hue.width * h0, hue.y0, hue.x0 + hue.width * h1, hue.y1)
            c0, c1 = rgba(h0, 1.0, 1.0), rgba(h1, 1.0, 1.0)
            draw.gradient_quad(seg, c0, c1, c1, c0)
        val, sat = p[VALUE], p[SATURATION]
        lo, hi = rgba(h, s, 0.0), rgba(h, s, 1.0)
        draw.gradient_quad(val, lo, lo, hi, hi)
        lo, hi = rgba(h, 0.0, v), rgba(h, 1.0, v)
        draw.gradient_quad(sat, lo, lo, hi, hi)

        border = with_alpha(theme.border, alpha)
        grabbed = self.drag['part'] if self.drag is not None else None
        for part, r in p.items():
            if part == grabbed:
                draw.rect_outline(r.expand(theme.px(2.0)), with_alpha(theme.accent_light, alpha), width=theme.px(1.5))
            else:
                draw.rect_outline(r, border, width=theme.px(1.0))

        # Original color: faint marks.
        faint = (1.0, 1.0, 1.0, 0.55 * alpha)
        original = _resolve(self.original, None)
        if original is None and self.drag is not None:
            original = self.drag['start']
        if original is not None:
            ph, ps, pv = original
            cx, cy = sheet.x0 + ph * sheet.width, sheet.y0 + pv * sheet.height
            arm = theme.px(4.0)
            draw.polyline([(cx - arm, cy), (cx + arm, cy)], faint, theme.px(1.5))
            draw.polyline([(cx, cy - arm), (cx, cy + arm)], faint, theme.px(1.5))
            self._tick_h(hue, ph, faint, theme)
            self._tick_v(val, pv, faint, theme)
            self._tick_v(sat, ps, faint, theme)

        # Current color: handles on the bars, a ring cursor on the sheet.
        self._handle_h(hue, h, alpha, theme)
        self._handle_v(val, v, alpha, theme)
        self._handle_v(sat, s, alpha, theme)
        cx, cy = sheet.x0 + h * sheet.width, sheet.y0 + v * sheet.height
        r = theme.px(6.0 if self.drag is not None and self.drag['part'] == SHEET else 5.0)
        draw.circle(cx, cy, r, rgba(h, s, v))
        draw.circle_outline(cx, cy, r, (0.0, 0.0, 0.0, 0.9 * alpha), width=theme.px(3.0))
        draw.circle_outline(cx, cy, r, (1.0, 1.0, 1.0, alpha), width=theme.px(1.5))

    @staticmethod
    def _handle_v(r, f, alpha, theme):
        y = r.y0 + f * r.height
        ext = theme.px(3.0)
        for width, color in ((3.0, (0.0, 0.0, 0.0, 0.9)), (1.5, (1.0, 1.0, 1.0, 1.0))):
            draw.polyline([(r.x0 - ext, y), (r.x1 + ext, y)], with_alpha(color, alpha), theme.px(width))

    @staticmethod
    def _handle_h(r, f, alpha, theme):
        x = r.x0 + f * r.width
        ext = theme.px(3.0)
        for width, color in ((3.0, (0.0, 0.0, 0.0, 0.9)), (1.5, (1.0, 1.0, 1.0, 1.0))):
            draw.polyline([(x, r.y0 - ext), (x, r.y1 + ext)], with_alpha(color, alpha), theme.px(width))

    @staticmethod
    def _tick_v(r, f, color, theme):
        y = r.y0 + f * r.height
        draw.polyline([(r.x0 - theme.px(6.0), y), (r.x0 - theme.px(2.0), y)], color, theme.px(2.0))

    @staticmethod
    def _tick_h(r, f, color, theme):
        x = r.x0 + f * r.width
        draw.polyline([(x, r.y0 - theme.px(6.0)), (x, r.y0 - theme.px(2.0))], color, theme.px(2.0))
