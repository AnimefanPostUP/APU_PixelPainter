"""Content of the pen menu's Mask and View windows (opened from the menu's top-right
corner; floating, movable windows like the color selector, see ``PenBar``).

Compact, icon-first layouts in the pen menu's style (tinted fills with a darker
rim, accent outline on hover, accent band when selected, round shapes; no boxed
groups); the explanations are hidden behind the window's '?' corner button
(``PenBar.help_shown``).

* Mask (tools/mask/): a circle menu -- Edit (choose islands / parts on the
  canvas) in the middle; around it Mask (on / off), Invert, Show (stripes),
  Clear; outside, Grow (an arc slider, below) and the source (UV Islands /
  Mesh Parts, on top -- only while editing).
* View (tools/pen/view_nav.py through the actions): two small dials -- a round
  button in the middle, eight segments around it.
  Orient: Front in the middle, Top / Bottom / Left / Right around it like the
  faces of an unfolded cube; the diagonals roll (top), level (bottom left) and
  Back (bottom right, darker: it is the face behind Front).
  Orbit: arrows around Fit; the diagonals zoom (top), Center, Persp / Ortho.
  Below: the compact toggle (hides the Orbit dial), Auto Fit and 1:1 (Image
  Editor). In the Image Editor only Fit /
  Center / zoom / 1:1 apply; the 3D-only buttons are disabled.

Each window has a *title plate* on top (lock, icon + title, '?', X, resize
triangle) and a background shaped to its parts -- a silhouette around each dial,
plates behind the other rows (:func:`window_shapes`, ``ui/pen/windows/shapes.py``).

Groups here do not block the pointer: dragging a window anywhere on its
background but on a control moves it; outside the shapes presses go through. Values through the pen menu's actions
(:class:`tools.pen.tool.PenBarTool`).
"""

import math

from ...kit import Dial, Group, Rect, RingSegment, Row, TextBlock, Widget
from ...kit import anim, draw
from ...kit.form import text_left
from ...kit.geometry import ring_segment_points, round_strip
from ...kit.theme import mix, with_alpha
from ...kit.widget import _resolve
from ..style import BUTTON_ROUND, PenButton, pen_fill
from .shapes import Plate, dial_star, plate_around

CELL = 32.0              # icon button size, unscaled px
GAP = 4.0
PAD_GAP = 12.0           # between the two View dials (their backgrounds stay apart: > 2 x SHAPE_PAD)
# View dials: a round button in the middle, eight 45-degree segments around it.
CENTER_RADIUS = 17.0
DIAL_RING = (CENTER_RADIUS + 2.5, 54.0)
DIAL_GAP = 2.5
# Title plate (on top): lock | icon + title | '?' X resize. Unscaled px.
PLATE_HEIGHT = 24.0
PLATE_GAP = 8.0          # between the plate and the content's background (> SHAPE_PAD: they stay apart)
ROW_GAP = 12.0           # between rows (their backgrounds stay apart: > 2 x SHAPE_PAD)
PLATE_ROUND = 7.0
PLATE_LEFT = 26.0        # room for the lock
PLATE_RIGHT = 62.0       # room for '?', X and the resize triangle
SHAPE_PAD = 5.0          # backgrounds reach this far past the parts
BODY_PAD = 4.0           # Settings / Palettes: their body's background past its content (= the panel padding)
BODY_ROUND = 10.0
FONT = 10.0              # button labels
TITLE_INDENT = 14.0      # the group title clears the window's padlock
HELP_SIZE = 9.0
LINE = 1.0               # icon stroke width, unscaled px (thin)


class WindowGroup(Group):
    """A window's content under a *title plate*: a small rounded plate centered on
    top with the lock (left), the icon + title, and '?', X and the resize triangle
    (right; placed by ``Window._place_on_plate``). ``plate`` (screen Rect) is set by
    :meth:`arrange`. No box around the content: the window's background is shaped to
    its parts (:func:`window_shapes`).

    Presses on the title / text / background go through to the window's panel, so
    dragging anywhere but a control moves the window."""

    blocks_pointer = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.plate = None
        self.plate_round_px = 0.0
        self.grab_t = 0.0   # animated "drag me" highlight of the title plate, 0..1

    def _title_width(self, theme):
        size = theme.px(self.title_size)
        text = draw.text_size(str(_resolve(self.title, "")), size, theme.font_id)[0]
        return (size * 1.6 if self.painter is not None else 0.0) + text

    def _plate_size(self, theme):
        """Screen ``(width, height)`` of the plate: title plus room for the buttons."""
        sides = theme.px(PLATE_LEFT + PLATE_RIGHT)
        return self._title_width(theme) + sides, theme.px(PLATE_HEIGHT)

    def measure(self, theme):
        cw, ch = self.content.measure(theme)
        pw, ph = self._plate_size(theme)
        return max(cw, pw), ph + theme.px(PLATE_GAP) + ch

    def arrange(self, rect, theme):
        self.rect = rect
        pw, ph = self._plate_size(theme)
        self.plate = Rect.from_size(rect.cx - pw * 0.5, rect.y1 - ph, pw, ph)
        self.plate_round_px = theme.px(PLATE_ROUND)
        cw, ch = self.content.measure(theme)
        top = self.plate.y0 - theme.px(PLATE_GAP)   # the backgrounds keep PLATE_GAP - SHAPE_PAD apart
        self.content.arrange(Rect.from_size(rect.cx - cw * 0.5, top - ch, cw, ch), theme)
        # The plate sits right above the first row's drawn top (a dial whose top arc is
        # hidden leaves room above it: the plate moves down onto the dial).
        first = next((c for c in self.content.children if c.visible), None)
        drawn_top = _drawn_top(first, theme)
        if drawn_top is not None:
            y0 = min(self.plate.y0, drawn_top + theme.px(PLATE_GAP) - theme.px(SHAPE_PAD))
            self.plate = Rect.from_size(self.plate.x0, y0, pw, ph)

    def _grab_target(self, dc):
        """1.0 while the plate shows it can move the window: the pointer on the plate
        (not on its buttons: they are hot then) or the window being dragged; 0.0 locked."""
        panel = self.parent
        if panel is None or not getattr(panel, 'draggable', False):
            return 0.0
        if dc.pressed is panel:
            return 1.0
        x, y = dc.pointer
        return 1.0 if (dc.hot is panel and self.plate.contains(x, y)) else 0.0

    def draw_self(self, dc):
        if self.plate is None:
            return
        theme = dc.theme
        tint = (*self.tint[:3], 1.0)
        alpha = dc.alpha
        size = theme.px(self.title_size)
        p = self.plate
        speed = dc.dt / max(theme.hover_duration, 1e-4)
        target = self._grab_target(dc)
        self.grab_t = anim.approach(self.grab_t, target, speed)
        if self.grab_t != target:
            anim.request_frame()
        grab = anim.ease_in_out(self.grab_t)
        if grab > 0.01:
            draw.rounded_rect_outline(p, self.plate_round_px, with_alpha(theme.accent, grab * 0.8 * alpha),
                                      width=theme.px(1.5))
        title_color = mix(mix(theme.text, tint, 0.35), theme.accent, grab * 0.6)
        # Centered between the lock (left) and '?' / X / resize (right).
        left, right = p.x0 + theme.px(PLATE_LEFT), p.x1 - theme.px(PLATE_RIGHT)
        x = (left + right) * 0.5 - self._title_width(theme) * 0.5
        if self.painter is not None:
            self.painter(dc, x + size * 0.6, p.cy, size * 1.4, alpha)
            x += size * 1.6
        text_left(str(_resolve(self.title, "")), x, p.cy, size, with_alpha(title_color, alpha), theme.font_id)


TINT_NEUTRAL = (0.75, 0.75, 0.75)   # Settings / Palettes: no category color in the title


def build_body_window(title, content, painter=None):
    """A window around a rectangular body (Settings, Palettes): the title plate on top,
    ``content`` below it on one rounded background (:func:`body_shapes`)."""
    return WindowGroup(title, content, tint=TINT_NEUTRAL, painter=painter)


def body_shapes(panel, theme):
    """Background of a :func:`build_body_window` window: the title plate and one rounded
    plate behind the whole body."""
    group = panel.content
    pad = theme.px(BODY_PAD)
    shapes = [plate_around(group.content, pad, theme.px(BODY_ROUND))]
    if group.plate is not None:
        shapes.insert(0, Plate(group.plate, group.plate_round_px))
    return shapes


def _drawn_top(widget, theme):
    """Top of ``widget``'s background (a dial's silhouette, a row of dials), or None."""
    if widget is None:
        return None
    parts = widget.children if isinstance(widget, Row) else [widget]
    dials = [d for d in parts if d.visible and isinstance(d, Dial)]
    if not dials:
        return None
    pad = theme.px(SHAPE_PAD)
    tops = []
    for d in dials:
        star = dial_star(d, pad)
        tops.append(max(star.cy + math.sin(a) * star.radius_at(a)
                        for a in (math.radians(k) for k in range(30, 151, 4))))
    return max(tops)


def window_shapes(panel, theme):
    """The Mask / View window background (``PenBar._window(shape=...)``): the title
    plate, a silhouette around each dial, a plate behind every other row (buttons,
    help text)."""
    group = panel.content
    pad = theme.px(SHAPE_PAD)
    shapes = []
    if group.plate is not None:
        shapes.append(Plate(group.plate, group.plate_round_px))
    for child in group.content.children:
        if not child.visible:
            continue
        parts = child.children if isinstance(child, Row) else [child]
        dials = [c for c in parts if c.visible and isinstance(c, Dial)]
        if dials:
            shapes += [dial_star(d, pad) for d in dials]
        else:
            shapes.append(plate_around(child, pad, theme.px(BUTTON_ROUND) + pad))
    return shapes


class _Help(TextBlock):
    """Help text, shown while ``shown()`` (the window's '?' button)."""

    def __init__(self, shown, lines, **kwargs):
        self._shown = shown
        super().__init__(list(lines), **kwargs)

    visible = property(lambda self: bool(self._shown()), lambda self, value: None)


_pen_fill = pen_fill


class WindowButton(PenButton):
    """Window button (the shared pen style, ``ui/pen/style.py``), larger label."""

    def __init__(self, label="", *, font_size=FONT, layout='column', **kwargs):
        super().__init__(label, font_size=font_size, layout=layout, **kwargs)


class DialCenter(Widget):
    """The round button in the middle of a View dial (Front / Fit), styled like the
    pen menu's segments; ``painter`` draws its icon."""

    interactive = True

    def __init__(self, *, painter, tint=None, radius=CENTER_RADIUS, **kwargs):
        super().__init__(**kwargs)
        self.painter = painter
        self.tint = tint
        self.radius = radius

    def measure(self, theme):
        d = theme.px(self.radius) * 2.0
        return d, d

    def contains(self, x, y):
        return math.hypot(x - self.rect.cx, y - self.rect.cy) <= self.rect.width * 0.5

    def draw_self(self, dc):
        theme = dc.theme
        cx, cy, r = self.rect.cx, self.rect.cy, self.rect.width * 0.5
        alpha = dc.alpha * (1.0 if self.is_enabled else theme.disabled_alpha)
        fill, t = _pen_fill(dc, self, self.tint, base=theme.surface_dark, tint_amount=0.22)
        draw.circle(cx, cy, r, with_alpha(fill, alpha), rim=theme.edge_for(fill, alpha))
        if self.is_selected:
            draw.circle_outline(cx, cy, r - theme.px(1.5), with_alpha(theme.accent_light, alpha),
                                width=theme.px(2.0))
        elif t > 0.01:
            draw.circle_outline(cx, cy, r, with_alpha(theme.accent, t * alpha), width=theme.px(1.5))
        self.painter(dc, cx, cy, r * 1.6, alpha)


class _Shown:
    """Mixin: the widget is visible only while ``shown()`` (pass ``shown=``)."""

    def __init__(self, *args, shown, **kwargs):
        super().__init__(*args, **kwargs)
        self._shown = shown

    visible = property(lambda self: bool(getattr(self, '_shown', lambda: True)()), lambda self, value: None)


class ShownSegment(_Shown, RingSegment):
    def __init__(self, shown, *args, **kwargs):
        super().__init__(*args, shown=shown, **kwargs)


class ShownDial(_Shown, Dial):
    pass


class FlexWindowButton(WindowButton):
    """A :class:`WindowButton` whose width (``width()``, unscaled) and ``layout`` may change."""

    def __init__(self, label="", *, width, height, layout='row', **kwargs):
        super().__init__(label, size=(0.0, height), **kwargs)
        self.width_fn = width
        self.layout_fn = layout

    def measure(self, theme):
        return theme.px(max(1.0, _resolve(self.width_fn, 1.0))), theme.px(self.size[1])

    def draw_self(self, dc):
        self.layout = _resolve(self.layout_fn, 'row')
        super().draw_self(dc)


def knee_value(f, lo, hi, knee=None):
    """The value at slider fraction ``f`` (0..1) between ``lo`` and ``hi``; with ``knee``
    ``(kf, kv)`` two linear parts: ``0 .. kf`` of the slider covers ``lo .. kv``, the rest
    ``kv .. hi`` (finer control over small values)."""
    f = max(0.0, min(1.0, float(f)))
    if not knee:
        return lo + f * (hi - lo)
    kf, kv = knee
    if f <= kf:
        return lo + f / kf * (kv - lo)
    return kv + (f - kf) / (1.0 - kf) * (hi - kv)


def knee_fraction(v, lo, hi, knee=None):
    """Inverse of :func:`knee_value`."""
    if hi <= lo:
        return 0.0
    v = max(lo, min(hi, float(v)))
    if not knee:
        return (v - lo) / (hi - lo)
    kf, kv = knee
    if v <= kv:
        return kf * (v - lo) / max(1e-12, kv - lo)
    return kf + (1.0 - kf) * (v - kv) / max(1e-12, hi - kv)


class ArcSlider(RingSegment):
    """A slider along an arc (an outer band of a dial): the value runs with the angle,
    from the ``a0`` end to the ``a1`` end. A press sets it from the pointer's angle,
    dragging keeps setting it; ESC / RMB restore the value from before. ``value()``,
    ``on_value(v)``, ``value_range`` (lo, hi) or a callable; ``label`` and the value
    are written on it (``fmt(value)``: the value's text, default "<n> px"). ``short``:
    only the label's first letter, upright (arcs on the sides of a dial, where longer
    level text would cross the band) -- :meth:`readout` gives the full name and value for
    a readout beside the window while dragging (like the pen menu's S / A / M);
    ``reverse``: the value grows from the ``a1`` end. ``tag``: a short name written
    instead of the first letter (``short`` sliders; e.g. "Dist"). ``knee`` ``(kf, kv)``: a
    two-part scale, the first ``kf`` of the slider up to the value ``kv`` (:func:`knee_value`)."""

    draggable = True

    def __init__(self, label="", *, value, on_value, value_range=(0.0, 1.0), fill_color=None, fmt=None,
                 short=False, reverse=False, tag=None, knee=None, **kwargs):
        super().__init__(label, **kwargs)
        self.tag = tag
        self.knee = knee
        self.fmt = fmt              # value -> text (default: "<n> px")
        self.short = short
        self.reverse = reverse
        self.value = value
        self.on_value = on_value
        self.value_range = value_range
        self.fill_color = fill_color
        self._original = None

    def _range(self):
        lo, hi = _resolve(self.value_range, (0.0, 1.0))
        return float(lo), float(hi)

    def _span(self):
        """Screen angles (radians) of the drawn ends."""
        a0, a1 = self.angles
        r = max(1.0, (self.pr0 + self.pr1) * 0.5)
        return (a0 + math.asin(min(1.0, self.insets[0] / r)),
                a1 - math.asin(min(1.0, self.insets[1] / r)))

    def fraction_at(self, x, y):
        s0, s1 = self._span()
        angle = math.atan2(y - self.cy, x - self.cx) % math.tau
        mid = (s0 + s1) * 0.5    # unwrap around the slider's middle
        angle = mid + (angle - mid + math.pi) % math.tau - math.pi
        f = max(0.0, min(1.0, (angle - s0) / max(1e-6, s1 - s0)))
        return 1.0 - f if self.reverse else f

    def _fraction(self):
        lo, hi = self._range()
        v = float(_resolve(self.value, lo) or lo)
        return knee_fraction(v, lo, hi, self.knee)

    @property
    def dragging(self):
        return self._original is not None

    def value_text(self):
        value = float(_resolve(self.value, 0) or 0)
        return self.fmt(value) if self.fmt is not None else f"{int(round(value))} px"

    def readout(self):
        """The full name and value (shown beside the window while dragging)."""
        return f"{self.label}  {self.value_text()}"

    def drag_begin(self, x, y):
        self._original = _resolve(self.value, None)
        self.drag_update(x, y)

    def drag_update(self, x, y):
        lo, hi = self._range()
        self.on_value(knee_value(self.fraction_at(x, y), lo, hi, self.knee))

    def drag_end(self, x, y, cancelled=False):
        if cancelled and self._original is not None:
            self.on_value(self._original)
        self._original = None

    def draw_self(self, dc):
        theme = dc.theme
        alpha = self.draw_frame(dc, active=1.0 if self._original is not None else None)
        f = self._fraction()
        if f > 0.0:
            a0, a1 = self.angles
            full = f >= 1.0
            if self.reverse:    # filled from the a1 end
                inner, outer = ring_segment_points(self.cx, self.cy, self.pr0, self.pr1, a1 - (a1 - a0) * f, a1,
                                                   self.insets[0] if full else 0.0, inset1=self.insets[1])
                inner, outer = round_strip(inner, outer, self._round_px, ends=(full, True))
            else:
                inner, outer = ring_segment_points(self.cx, self.cy, self.pr0, self.pr1, a0, a0 + (a1 - a0) * f,
                                                   self.insets[0], inset1=self.insets[1] if full else 0.0)
                inner, outer = round_strip(inner, outer, self._round_px, ends=(True, full))
            if inner:
                fill = self.fill_color or theme.accent
                dark = tuple(c * 0.62 for c in fill[:3])
                last = max(1, len(inner) - 1)
                colors = [(*(dark[k] + (fill[k] - dark[k]) * f * i / last for k in range(3)), 0.85 * alpha)
                          for i in range(len(inner))]
                if self.reverse:   # brightest at the moving end
                    colors.reverse()
                draw.gradient_ring_segment(inner, outer, colors)
        x, y = self.middle()
        if self.short:
            # The tag (or the first letter) with the value under it, both upright (compact: no
            # space before a unit).
            name = self.tag or str(self.label)[:1].upper()
            letter_size, value_size = theme.px(FONT * (0.9 if self.tag else 1.1)), theme.px(FONT * 0.8)
            gap = (letter_size + value_size) * 0.28
            draw.text_centered(name, x, y + gap, letter_size,
                               with_alpha(theme.text, alpha), theme.font_id)
            draw.text_centered(self.value_text().replace(" ", ""), x, y - gap, value_size,
                               with_alpha(theme.text_muted, alpha), theme.font_id)
            return
        draw.text_centered(f"{self.label} {self.value_text()}", x, y, theme.px(FONT * 0.9),
                           with_alpha(theme.text, alpha), theme.font_id)


# ---- windows -----------------------------------------------------------------------------

def help_lines(bar, name, lines, width):
    return _Help(lambda: bar.help_shown(name), lines, size=HELP_SIZE, width=width)
