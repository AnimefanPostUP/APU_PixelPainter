"""Content of the pen menu's Mask and View windows (opened from the menu's top-right
corner; floating, movable windows like the color selector, see ``PenBar``).

Compact, icon-first layouts in the pen menu's style (tinted fills with a darker
rim, accent outline on hover, accent band when selected, round shapes; no boxed
groups); the explanations are hidden behind the window's '?' corner button
(``PenBar.help_shown``).

* Mask (tools/mask.py): a circle menu -- Edit (choose islands / parts on the
  canvas) in the middle; around it Mask (on / off), Invert, Show (stripes),
  Clear; outside, Grow (an arc slider, below) and the source (UV Islands /
  Mesh Parts, on top -- only while editing).
* View (tools/view_nav.py through the actions): two small dials -- a round
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
plates behind the other rows (:func:`window_shapes`, ``ui/window_shapes.py``).

Groups here do not block the pointer: dragging a window anywhere on its
background but on a control moves it; outside the shapes presses go through. Values through the pen menu's actions
(:class:`tools.pen_bar.PenBarTool`).
"""

import math

from ..kit import Column, Dial, Group, Rect, RingSegment, Row, TextBlock, Widget
from ..kit import anim, draw
from ..kit.form import text_left
from ..kit.geometry import ring_segment_points, round_strip
from ..kit.theme import mix, with_alpha
from ..kit.widget import _resolve
from .icons import captioned, paint_mask, paint_mask_invert, paint_mask_pick, paint_view, thick_line
from .metrics import TINT_MASK, TINT_VIEW
from .settings import _icon_eye, _icon_reset
from .style import BUTTON_ROUND, PenButton, pen_fill

CELL = 32.0              # icon button size, unscaled px
GAP = 4.0
PAD_GAP = 12.0           # between the two View dials (their backgrounds stay apart: > 2 x SHAPE_PAD)
# View dials: a round button in the middle, eight 45-degree segments around it.
CENTER_RADIUS = 17.0
DIAL_RING = (CENTER_RADIUS + 2.5, 54.0)
DIAL_GAP = 2.5
# Mask circle menu: Edit in the middle, four quarter segments around it; outside them
# two arcs: the source on top (only while editing), Grow below.
MASK_CENTER = 24.0
MASK_RING = (MASK_CENTER + 2.5, 66.0)
MASK_BAND = (MASK_RING[1] + 3.0, MASK_RING[1] + 22.0)
MASK_BAND_ROUND = (MASK_BAND[1] - MASK_BAND[0]) * 0.5   # capsules
SOURCE_ARC = (52.0, 128.0)
GROW_ARC = (232.0, 308.0)
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

MASK_HELP = ("Mask: only chosen islands / parts get paint.",
             "Edit (middle): tap them on the canvas (drag:",
             "several); the arc on top switches between UV",
             "islands and connected mesh parts meanwhile.",
             "Invert: protect the chosen ones instead.",
             "Show: red stripes over protected pixels.",
             "Grow (arc below): extra pixels around each island.")
VIEW_HELP = ("Left dial: view from Front (middle), Top,",
             "Bottom, Left, Right; Back (bottom right) looks",
             "from behind. Upper diagonals roll 15, Level",
             "removes roll. Right dial: orbit 15 around the",
             "object, Fit (middle) zooms until it fills the",
             "view; zoom, Center, Persp / Ortho diagonally.",
             "Bottom left: hide / show the right dial.",
             "Auto Fit: re-fit after every orient / orbit / roll.")


class _WindowGroup(Group):
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
        self.grab_t = anim.approach(self.grab_t, self._grab_target(dc), speed)
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
    return _WindowGroup(title, content, tint=TINT_NEUTRAL, painter=painter)


def body_shapes(panel, theme):
    """Background of a :func:`build_body_window` window: the title plate and one rounded
    plate behind the whole body."""
    from .shapes import Plate, plate_around
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
    from .shapes import dial_star
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
    from .shapes import Plate, dial_star, plate_around
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


class _Btn(PenButton):
    """Window button (the shared pen style, ``ui/pen_style.py``), larger label."""

    def __init__(self, label="", *, font_size=FONT, layout='column', **kwargs):
        super().__init__(label, font_size=font_size, layout=layout, **kwargs)


class _DialCenter(Widget):
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


class _ShownSegment(_Shown, RingSegment):
    def __init__(self, shown, *args, **kwargs):
        super().__init__(*args, shown=shown, **kwargs)


class _ShownDial(_Shown, Dial):
    pass


class _FlexBtn(_Btn):
    """A :class:`_Btn` whose width (``width()``, unscaled) and ``layout`` may change."""

    def __init__(self, label="", *, width, height, layout='row', **kwargs):
        super().__init__(label, size=(0.0, height), **kwargs)
        self.width_fn = width
        self.layout_fn = layout

    def measure(self, theme):
        return theme.px(max(1.0, _resolve(self.width_fn, 1.0))), theme.px(self.size[1])

    def draw_self(self, dc):
        self.layout = _resolve(self.layout_fn, 'row')
        super().draw_self(dc)


class _ArcSlider(RingSegment):
    """A slider along an arc (an outer band of a dial): the value runs with the angle,
    from the ``a0`` end to the ``a1`` end. A press sets it from the pointer's angle,
    dragging keeps setting it; ESC / RMB restore the value from before. ``value()``,
    ``on_value(v)``, ``value_range`` (lo, hi) or a callable; ``label`` and the value
    are written on it."""

    draggable = True

    def __init__(self, label="", *, value, on_value, value_range=(0.0, 1.0), fill_color=None, **kwargs):
        super().__init__(label, **kwargs)
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
        return max(0.0, min(1.0, (angle - s0) / max(1e-6, s1 - s0)))

    def _fraction(self):
        lo, hi = self._range()
        v = float(_resolve(self.value, lo) or lo)
        return 0.0 if hi <= lo else max(0.0, min(1.0, (v - lo) / (hi - lo)))

    def drag_begin(self, x, y):
        self._original = _resolve(self.value, None)
        self.drag_update(x, y)

    def drag_update(self, x, y):
        lo, hi = self._range()
        self.on_value(lo + self.fraction_at(x, y) * (hi - lo))

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
            inner, outer = ring_segment_points(self.cx, self.cy, self.pr0, self.pr1, a0, a0 + (a1 - a0) * f,
                                               self.insets[0], inset1=self.insets[1] if f >= 1.0 else 0.0)
            inner, outer = round_strip(inner, outer, self._round_px, ends=(True, f >= 1.0))
            if inner:
                fill = self.fill_color or theme.accent
                dark = tuple(c * 0.62 for c in fill[:3])
                last = max(1, len(inner) - 1)
                colors = [(*(dark[k] + (fill[k] - dark[k]) * f * i / last for k in range(3)), 0.85 * alpha)
                          for i in range(len(inner))]
                draw.gradient_ring_segment(inner, outer, colors)
        x, y = self.middle()
        value = _resolve(self.value, 0) or 0
        draw.text_centered(f"{self.label} {int(round(float(value)))} px", x, y, theme.px(FONT * 0.9),
                           with_alpha(theme.text, alpha), theme.font_id)


# ---- icons: painter(dc, x, y, size, alpha) ----------------------------------------------

def _paint_edit(dc, x, y, size, alpha):
    """The Mask window's center: Edit (choose islands / parts on the canvas)."""
    paint_mask_pick(dc, x, y, size, alpha, caption=True)


def _paint_source_band(source):
    """The source arc: 'UV Islands' / 'Mesh Parts' written on it."""
    def paint(dc, x, y, size, alpha):
        theme = dc.theme
        text = "UV Islands" if _resolve(source, 'UV_ISLAND') != 'MESH_PART' else "Mesh Parts"
        draw.text_centered(text, x, y, theme.px(FONT * 0.9), with_alpha(theme.text, alpha), theme.font_id)
    return paint


def _icon_compact(compact):
    """Compact View window: two dials, the right one dashed while it is hidden."""
    def paint(dc, x, y, size, alpha):
        theme = dc.theme
        r = min(size * 0.2, theme.px(6.0))
        color = with_alpha(theme.text, 0.92 * alpha)
        w = _stroke(theme)
        draw.circle_outline(x - r * 1.15, y, r, color, width=w * 1.4)
        draw.circle(x - r * 1.15, y, r * 0.35, color, segments=12)
        if _resolve(compact, False):
            for k in range(6):
                a0 = math.tau * k / 6.0
                draw.arc(x + r * 1.15, y, r, a0, a0 + math.tau / 12.0, with_alpha(color, 0.6), width=w)
        else:
            draw.circle_outline(x + r * 1.15, y, r, color, width=w * 1.4)
            draw.circle(x + r * 1.15, y, r * 0.35, color, segments=12)
    return paint


def _stroke(theme):
    return max(1.0, theme.px(LINE))


def _icon_face(side):
    """A cube face (square) seen from ``side``: Front = filled; else the edge facing
    that side is a solid strip (Top: upper edge ...), like an unfolded cube."""
    def paint(dc, x, y, size, alpha):
        theme = dc.theme
        s = min(size * 0.62, theme.px(16.0))
        box = Rect.from_center(x, y, s, s)
        color = with_alpha(theme.text, 0.92 * alpha)
        if side == 'FRONT':
            draw.rect(box, with_alpha(theme.text, 0.75 * alpha))
            return
        draw.rect(box, with_alpha(theme.text, 0.12 * alpha))
        draw.rect_outline(box, with_alpha(theme.text, 0.6 * alpha), width=_stroke(theme))
        t = s * 0.3
        strip = {'TOP': Rect(box.x0, box.y1 - t, box.x1, box.y1),
                 'BOTTOM': Rect(box.x0, box.y0, box.x1, box.y0 + t),
                 'LEFT': Rect(box.x0, box.y0, box.x0 + t, box.y1),
                 'RIGHT': Rect(box.x1 - t, box.y0, box.x1, box.y1)}[side]
        draw.rect(strip, color)
    return paint


def _icon_back(dc, x, y, size, alpha):
    """Back: a dashed square (the hidden face) with a turn-around arrow."""
    theme = dc.theme
    s = min(size * 0.62, theme.px(16.0)) * 0.5
    color = with_alpha(theme.text, 0.92 * alpha)
    w = _stroke(theme)
    dash = with_alpha(theme.text, 0.55 * alpha)
    corners = [(x - s, y - s), (x + s, y - s), (x + s, y + s), (x - s, y + s)]
    for (ax, ay), (bx, by) in zip(corners, corners[1:] + corners[:1]):
        for k in range(3):
            t0, t1 = (k * 2 + 0.3) / 6.0, (k * 2 + 1.3) / 6.0
            draw.polyline([(ax + (bx - ax) * t0, ay + (by - ay) * t0), (ax + (bx - ax) * t1, ay + (by - ay) * t1)],
                          dash, w)
    r = s * 0.55
    draw.arc(x, y, r, math.radians(200.0), math.radians(-20.0) + 2.0 * math.pi, color, width=w * 1.4, segments=20)
    end = math.radians(-20.0)
    px, py = x + math.cos(end) * r, y + math.sin(end) * r
    h = r * 0.75
    draw.triangle((px - h * 0.1, py - h * 0.9), (px + h * 0.6, py + h * 0.2), (px - h * 0.6, py + h * 0.2), color)


def _icon_arrow(angle_deg):
    """A straight arrow pointing at ``angle_deg`` (0 = right, 90 = up)."""
    def paint(dc, x, y, size, alpha):
        theme = dc.theme
        s = min(size * 0.32, theme.px(8.0))
        color = with_alpha(theme.text, 0.92 * alpha)
        a = math.radians(angle_deg)
        dx, dy = math.cos(a), math.sin(a)
        tip = (x + dx * s, y + dy * s)
        base = (x + dx * s * 0.05, y + dy * s * 0.05)
        thick_line((x - dx * s, y - dy * s), base, _stroke(theme) * 1.6, color)
        nx, ny = -dy, dx
        draw.triangle(tip, (base[0] + nx * s * 0.6, base[1] + ny * s * 0.6),
                      (base[0] - nx * s * 0.6, base[1] - ny * s * 0.6), color)
    return paint


def _icon_roll(direction):
    """A curved arrow: ``direction`` +1 counter-clockwise, -1 clockwise."""
    def paint(dc, x, y, size, alpha):
        theme = dc.theme
        r = min(size * 0.26, theme.px(6.5))
        color = with_alpha(theme.text, 0.92 * alpha)
        a0, a1 = math.radians(-50.0), math.radians(210.0)
        draw.arc(x, y, r, a0, a1, color, width=_stroke(theme) * 1.4, segments=20)
        end = a1 if direction > 0 else a0
        px, py = x + math.cos(end) * r, y + math.sin(end) * r
        tx, ty = -math.sin(end) * direction, math.cos(end) * direction     # travel direction
        nx, ny = -ty, tx
        h = r * 0.75
        draw.triangle((px + tx * h, py + ty * h), (px + nx * h * 0.6, py + ny * h * 0.6),
                      (px - nx * h * 0.6, py - ny * h * 0.6), color)
    return paint


def _icon_level(dc, x, y, size, alpha):
    """A spirit level: a bar with a bubble in the middle."""
    theme = dc.theme
    s = min(size * 0.34, theme.px(8.0))
    color = with_alpha(theme.text, 0.92 * alpha)
    tube = Rect.from_center(x, y, s * 2.0, s * 0.7)
    draw.rect_outline(tube, color, width=_stroke(theme))
    draw.circle(x, y, s * 0.22, color, segments=12)
    for sx in (-1, 1):
        draw.polyline([(x + sx * s * 0.45, tube.y0), (x + sx * s * 0.45, tube.y1)], color, _stroke(theme))


def _icon_fit(dc, x, y, size, alpha):
    """Four corner brackets around a dot."""
    theme = dc.theme
    s = min(size * 0.3, theme.px(7.5))
    color = with_alpha(theme.text, 0.92 * alpha)
    w = _stroke(theme) * 1.4
    for sx in (-1, 1):
        for sy in (-1, 1):
            cx, cy = x + sx * s, y + sy * s
            thick_line((cx, cy), (cx - sx * s * 0.55, cy), w, color)
            thick_line((cx, cy), (cx, cy - sy * s * 0.55), w, color)
    draw.circle(x, y, s * 0.3, color, segments=12)


def _icon_center(dc, x, y, size, alpha):
    """A crosshair."""
    theme = dc.theme
    s = min(size * 0.3, theme.px(7.5))
    color = with_alpha(theme.text, 0.92 * alpha)
    w = _stroke(theme)
    draw.circle_outline(x, y, s * 0.6, color, width=w)
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        thick_line((x + dx * s * 0.3, y + dy * s * 0.3), (x + dx * s, y + dy * s), w, color)


def _icon_zoom(sign):
    """A magnifier with + / -."""
    def paint(dc, x, y, size, alpha):
        theme = dc.theme
        s = min(size * 0.28, theme.px(7.0))
        color = with_alpha(theme.text, 0.92 * alpha)
        w = _stroke(theme)
        gx, gy, gr = x - s * 0.2, y + s * 0.2, s * 0.72
        draw.circle_outline(gx, gy, gr, color, width=w)
        thick_line((gx + gr * 0.7, gy - gr * 0.7), (x + s, y - s), w * 2.0, color)
        thick_line((gx - gr * 0.5, gy), (gx + gr * 0.5, gy), w, color)
        if sign > 0:
            thick_line((gx, gy - gr * 0.5), (gx, gy + gr * 0.5), w, color)
    return paint


def _icon_perspective(persp):
    """A trapezoid (perspective) or a square (orthographic) with a center line."""
    def paint(dc, x, y, size, alpha):
        theme = dc.theme
        s = min(size * 0.3, theme.px(7.5))
        color = with_alpha(theme.text, 0.92 * alpha)
        w = _stroke(theme)
        top = s * (0.45 if _resolve(persp, True) else 1.0)
        draw.polyline([(x - s, y - s), (x + s, y - s), (x + top, y + s), (x - top, y + s)], color, w, closed=True)
        draw.polyline([(x, y - s), (x, y + s)], color, w)
    return paint


def _icon_mask_title(dc, x, y, size, alpha):
    paint_mask(dc, x, y, size * 1.4, alpha, caption=False)


# ---- windows -----------------------------------------------------------------------------

def _help_lines(bar, name, lines, width):
    return _Help(lambda: bar.help_shown(name), lines, size=HELP_SIZE, width=width)


def build_mask_window(bar):
    """The Mask window's content (a Group): a circle menu. Edit (choose islands / parts
    on the canvas) in the middle; around it Mask (on / off), Invert, Show (stripes) and
    Clear; the Grow arc below. The source (UV Islands / Mesh Parts) arc above only shows
    while editing."""
    a = bar.actions
    tint = TINT_MASK

    def segment(key, painter, **kwargs):
        return RingSegment("", painter=painter, key=f'MASKWIN_{key}', tint=tint, **kwargs)

    center = _DialCenter(painter=_paint_edit, tint=tint, radius=MASK_CENTER, key='MASKWIN_EDIT',
                         selected=a.mask_picking, on_click=a.toggle_mask_pick)
    dial = Dial(center, gap=DIAL_GAP)
    ring = [   # counter-clockwise from the right: top right, top left, bottom left, bottom right
        segment('INVERT', paint_mask_invert, selected=a.mask_inverted, on_click=a.toggle_mask_invert),
        segment('MASK', paint_mask, selected=a.mask_enabled, on_click=a.toggle_mask),
        segment('SHOW', captioned(_icon_eye, "Show"), selected=lambda: bool(a.wm_get('mask_show')),
                on_click=lambda: a.wm_set('mask_show', not a.wm_get('mask_show'))),
        segment('CLEAR', captioned(_icon_reset, "Clear"),
                on_click=lambda: bar.confirm(["Forget all chosen islands / parts?"], a.clear_mask, "Clear")),
    ]
    for i, seg in enumerate(ring):
        dial.add_segment(seg, *MASK_RING, i * 90.0, (i + 1) * 90.0)
    source = _ShownSegment(a.mask_picking, "", painter=_paint_source_band(a.mask_source),
                           key='MASKWIN_SOURCE', tint=tint, round=MASK_BAND_ROUND, on_click=a.toggle_mask_source)
    grow = _ArcSlider("Grow", value=lambda: a.wm_get('mask_grow', 0) or 0,
                      on_value=lambda v: a.wm_set('mask_grow', int(round(v))),
                      value_range=lambda: a.wm_range('mask_grow')[:2], fill_color=(*TINT_MASK, 1.0),
                      key='MASKWIN_GROW', tint=tint, round=MASK_BAND_ROUND)
    dial.add_band([source], *MASK_BAND, *SOURCE_ARC)
    dial.add_band([grow], *MASK_BAND, *GROW_ARC)
    width = 2.0 * MASK_BAND[1]
    content = Column([dial, _help_lines(bar, 'mask', MASK_HELP, width)], gap=ROW_GAP)
    return _WindowGroup("Mask", content, tint=TINT_MASK, painter=_icon_mask_title, title_indent=TITLE_INDENT)


def build_view_window(bar):
    """The View window's content (a Group): the Orient and Orbit pads, Auto Fit / 1:1."""
    a = bar.actions
    is3d = a.in_view3d
    tint = TINT_VIEW

    def segment(key, action, painter, enabled=is3d, **kwargs):
        return RingSegment("", painter=painter, key=f'VIEW_{key}', tint=tint, enabled=enabled,
                           on_click=action, **kwargs)

    def dial(key, action, painter, ring, enabled=True, cls=Dial, **kwargs):
        """``ring``: eight segments counter-clockwise from the right (0, 45, ... 315 degrees)."""
        center = _DialCenter(painter=painter, tint=tint, key=f'VIEW_{key}', enabled=enabled, on_click=action)
        result = cls(center, gap=DIAL_GAP, **kwargs)
        for i, seg in enumerate(ring):
            angle = i * 45.0
            result.add_segment(seg, *DIAL_RING, angle - 22.5, angle + 22.5)
        return result

    step = 15.0
    face = lambda axis: segment(axis, lambda: a.view_axis(axis), _icon_face(axis))
    # Orient: Front in the middle, the faces around it like an unfolded cube; the
    # diagonals roll (top), level (bottom left) and Back (bottom right, darker).
    orient = dial('FRONT', lambda: a.view_axis('FRONT'), _icon_face('FRONT'), ring=[
        face('RIGHT'),
        segment('ROLL_RIGHT', lambda: a.view_roll(-step), _icon_roll(-1)),
        face('TOP'),
        segment('ROLL_LEFT', lambda: a.view_roll(step), _icon_roll(1)),
        face('LEFT'),
        segment('LEVEL', a.view_level, _icon_level),
        face('BOTTOM'),
        segment('BACK', lambda: a.view_axis('BACK'), _icon_back, fill=(0.12, 0.12, 0.12, 0.95),
                tint_amount=0.35),
    ], enabled=is3d)
    # Orbit: arrows around Fit; the diagonals zoom (top), Center, Persp / Ortho. Hidden in
    # the compact window (the button bottom left).
    compact = a.view_compact
    orbit = dial('FIT', a.view_fit, _icon_fit, cls=_ShownDial, shown=lambda: not compact(), ring=[
        segment('ORBIT_RIGHT', lambda: a.view_orbit(step, 0.0), _icon_arrow(0.0)),
        segment('ZOOM_OUT', lambda: a.view_zoom(-1), _icon_zoom(-1), enabled=True),
        segment('ORBIT_UP', lambda: a.view_orbit(0.0, step), _icon_arrow(90.0)),
        segment('ZOOM_IN', lambda: a.view_zoom(1), _icon_zoom(1), enabled=True),
        segment('ORBIT_LEFT', lambda: a.view_orbit(-step, 0.0), _icon_arrow(180.0)),
        segment('CENTER', a.view_center, _icon_center, enabled=True),
        segment('ORBIT_DOWN', lambda: a.view_orbit(0.0, -step), _icon_arrow(270.0)),
        segment('PERSPECTIVE', a.toggle_view_perspective, _icon_perspective(a.view_perspective)),
    ])
    full = 4 * DIAL_RING[1] + PAD_GAP
    small = 2 * DIAL_RING[1]
    width = lambda: small if compact() else full
    h = 26.0
    toggle = _Btn("", painter=_icon_compact(compact), layout='icon', size=(CELL, h), key='VIEW_COMPACT',
                  tint=tint, selected=compact, on_click=a.toggle_view_compact)
    one_w = lambda: CELL if compact() else CELL * 1.6
    one_to_one = _FlexBtn("1:1", width=one_w, height=h, layout='row', key='VIEW_ONE_TO_ONE', tint=tint,
                          enabled=lambda: not is3d(), on_click=a.view_one_to_one)
    # Auto Fit takes the rest of the row (icon only in the compact window).
    auto = _FlexBtn("Auto Fit", width=lambda: width() - CELL - one_w() - 2 * GAP, height=h, painter=_icon_fit,
                    layout=lambda: 'icon' if compact() else 'row', key='VIEW_AUTOFIT', tint=tint, enabled=is3d,
                    selected=a.view_autofit, on_click=a.toggle_view_autofit)
    content = Column([Row([orient, orbit], gap=PAD_GAP), Row([toggle, auto, one_to_one], gap=GAP),
                      _help_lines(bar, 'view', VIEW_HELP, full)], gap=ROW_GAP)
    return _WindowGroup("View", content, tint=TINT_VIEW, painter=_paint_view_title, title_indent=TITLE_INDENT)


def _paint_view_title(dc, x, y, size, alpha):
    paint_view(dc, x, y - size * 0.15, size * 1.6, alpha)
