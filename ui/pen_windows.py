"""Content of the pen menu's Mask and View windows (opened from the menu's top-right
corner; floating, movable windows like the color selector, see ``PenBar``).

Compact, icon-first layouts in the pen menu's style (tinted fills with a darker
rim, accent outline on hover, accent band when selected, round shapes; no boxed
groups); the explanations are hidden behind the window's '?' corner button
(``PenBar.help_shown``).

* Mask: Source / Mask / Invert / Pick, then show stripes / grow / clear
  (tools/mask.py) -- rounded buttons, a capsule Grow slider.
* View (tools/view_nav.py through the actions): two small dials -- a round
  button in the middle, eight segments around it.
  Orient: Front in the middle, Top / Bottom / Left / Right around it like the
  faces of an unfolded cube; the diagonals roll (top), level (bottom left) and
  Back (bottom right, darker: it is the face behind Front).
  Orbit: arrows around Fit; the diagonals zoom (top), Center, Persp / Ortho.
  Below: Auto Fit and 1:1 (Image Editor). In the Image Editor only Fit /
  Center / zoom / 1:1 apply; the 3D-only buttons are disabled.

Groups here do not block the pointer: dragging a window anywhere but on a
control moves it. Values through the pen menu's actions
(:class:`tools.pen_bar.PenBarTool`).
"""

import math

from .kit import Column, Dial, Group, IconButton, Rect, RingSegment, Row, Slider, TextBlock, Widget
from .kit import anim, draw
from .kit.form import text_left
from .kit.theme import mix, with_alpha
from .kit.widget import _resolve
from .pen_bar import (TINT_MASK, TINT_VIEW, _paint_mask, _paint_mask_invert, _paint_mask_pick,
                      _paint_mask_source, _paint_view, _thick_line)
from .pen_settings import _icon_eye, _icon_reset

CELL = 32.0              # icon button size, unscaled px
GAP = 4.0
PAD_GAP = 10.0           # between the two View dials
BUTTON_ROUND = 7.0       # corner radius of the window buttons (pen-menu style)
TINT_AMOUNT = 0.16       # category tint in the button fills (as the pen menu's segments)
# View dials: a round button in the middle, eight 45-degree segments around it.
CENTER_RADIUS = 17.0
DIAL_RING = (CENTER_RADIUS + 2.5, 54.0)
DIAL_GAP = 2.5
FONT = 10.0              # button labels
TITLE_INDENT = 14.0      # the group title clears the window's padlock
HELP_SIZE = 9.0
LINE = 1.0               # icon stroke width, unscaled px (thin)

MASK_HELP = ("Mask: only chosen islands / parts get paint.",
             "Pick: tap them on the canvas (drag: several).",
             "Invert: protect the chosen ones instead.",
             "Source: UV islands or connected mesh parts.",
             "Eye: red stripes over protected pixels.",
             "Grow: extra pixels around each island.")
VIEW_HELP = ("Left dial: view from Front (middle), Top,",
             "Bottom, Left, Right; Back (bottom right) looks",
             "from behind. Upper diagonals roll 15, Level",
             "removes roll. Right dial: orbit 15 around the",
             "object, Fit (middle) zooms until it fills the",
             "view; zoom, Center, Persp / Ortho diagonally.",
             "Auto Fit: re-fit after every orient / orbit / roll.")


class _WindowGroup(Group):
    """A Group that lets presses on its background / title / text through to the
    window's panel, so dragging anywhere but a control moves the window.

    Plain, like the pen menu: no box, stripe or divider -- only the icon and the
    title in the window's tint."""

    blocks_pointer = False

    def draw_self(self, dc):
        theme = dc.theme
        r = self.rect
        tint = (*self.tint[:3], 1.0)
        alpha = dc.alpha
        pad = theme.px(self.padding)
        size = theme.px(self.title_size)
        ty = r.y1 - pad - size * 0.5
        x = r.x0 + theme.px(3.0) + pad + theme.px(self.title_indent)
        if self.painter is not None:
            self.painter(dc, x + size * 0.6, ty, size * 1.4, alpha)
            x += size * 1.6
        text_left(str(_resolve(self.title, "")), x, ty, size, with_alpha(mix(theme.text, tint, 0.35), alpha),
                  theme.font_id)


class _Help(TextBlock):
    """Help text, shown while ``shown()`` (the window's '?' button)."""

    def __init__(self, shown, lines, **kwargs):
        self._shown = shown
        super().__init__(list(lines), **kwargs)

    visible = property(lambda self: bool(self._shown()), lambda self, value: None)


def _pen_fill(dc, widget, tint, base=None, tint_amount=TINT_AMOUNT):
    """A pen-menu segment's fill: the surface with the category tint mixed in, lighter
    while hovered / pressed, accent-tinted while selected (see ``RingSegment._fill``)."""
    theme = dc.theme
    base = base or theme.surface
    if tint is not None:
        base = mix(base, (*tint[:3], base[3]), tint_amount)
    pressed = dc.pressed is widget and dc.hot is widget
    t = anim.ease_in_out(widget.hover_t)
    fill = mix(base, theme.surface_pressed if pressed else theme.surface_hover, t * 0.8)
    if widget.is_selected:
        fill = mix(fill, theme.accent, 0.4)
    return fill, t


class _Btn(IconButton):
    """Window button in the pen menu's style: rounded, tinted fill with a darker rim,
    an accent outline while hovered and an accent band along the bottom while selected."""

    outline = 1.0
    corner = BUTTON_ROUND

    def __init__(self, label="", *, font_size=FONT, tint=None, **kwargs):
        super().__init__(label, font_size=font_size, **kwargs)
        self.tint = tint

    def _colors(self, dc):
        fill, border, icon = super()._colors(dc)
        return fill, border, max(icon, 0.9)

    def draw_frame(self, dc, rect, fill, border, alpha):
        theme = dc.theme
        radius = theme.px(self.corner)
        fill, t = _pen_fill(dc, self, self.tint)
        draw.rounded_rect(rect, radius, with_alpha(fill, alpha), rim=theme.edge_for(fill, alpha))
        if self.is_selected:
            band = theme.px(3.0)
            inset = max(radius * 0.6, band)
            draw.rounded_rect(Rect(rect.x0 + inset, rect.y0 + band * 0.7, rect.x1 - inset, rect.y0 + band * 1.7),
                              band, with_alpha(theme.accent, alpha))
        if t > 0.01:
            draw.rounded_rect_outline(rect, radius, with_alpha(theme.accent, t * alpha), width=theme.px(1.5))


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
        if t > 0.01:
            draw.circle_outline(cx, cy, r, with_alpha(theme.accent, t * alpha), width=theme.px(1.5))
        self.painter(dc, cx, cy, r * 1.6, alpha)


def _stroke(theme):
    return max(1.0, theme.px(LINE))


# ---- icons: painter(dc, x, y, size, alpha) ----------------------------------------------

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
        _thick_line((x - dx * s, y - dy * s), base, _stroke(theme) * 1.6, color)
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
            _thick_line((cx, cy), (cx - sx * s * 0.55, cy), w, color)
            _thick_line((cx, cy), (cx, cy - sy * s * 0.55), w, color)
    draw.circle(x, y, s * 0.3, color, segments=12)


def _icon_center(dc, x, y, size, alpha):
    """A crosshair."""
    theme = dc.theme
    s = min(size * 0.3, theme.px(7.5))
    color = with_alpha(theme.text, 0.92 * alpha)
    w = _stroke(theme)
    draw.circle_outline(x, y, s * 0.6, color, width=w)
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        _thick_line((x + dx * s * 0.3, y + dy * s * 0.3), (x + dx * s, y + dy * s), w, color)


def _icon_zoom(sign):
    """A magnifier with + / -."""
    def paint(dc, x, y, size, alpha):
        theme = dc.theme
        s = min(size * 0.28, theme.px(7.0))
        color = with_alpha(theme.text, 0.92 * alpha)
        w = _stroke(theme)
        gx, gy, gr = x - s * 0.2, y + s * 0.2, s * 0.72
        draw.circle_outline(gx, gy, gr, color, width=w)
        _thick_line((gx + gr * 0.7, gy - gr * 0.7), (x + s, y - s), w * 2.0, color)
        _thick_line((gx - gr * 0.5, gy), (gx + gr * 0.5, gy), w, color)
        if sign > 0:
            _thick_line((gx, gy - gr * 0.5), (gx, gy + gr * 0.5), w, color)
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
    _paint_mask(dc, x, y, size * 1.4, alpha, caption=False)


# ---- windows -----------------------------------------------------------------------------

def _help_lines(bar, name, lines, width):
    return _Help(lambda: bar.help_shown(name), lines, size=HELP_SIZE, width=width)


def build_mask_window(bar):
    """The Mask window's content (a Group)."""
    a = bar.actions
    big = (46.0, 46.0)

    def icon(painter):
        return lambda dc, x, y, size, alpha: painter(dc, x, y, size * 1.25, alpha, caption=False)

    source = _paint_mask_source(a.mask_source, caption=False)
    tint = TINT_MASK
    main = Row([
        _Btn(lambda: "Islands" if a.mask_source() != 'MESH_PART' else "Parts", painter=source, size=big,
             key='MASKWIN_SOURCE', tint=tint, on_click=a.toggle_mask_source),
        _Btn("Mask", painter=icon(_paint_mask), size=big, key='MASKWIN_MASK', tint=tint,
             selected=a.mask_enabled, on_click=a.toggle_mask),
        _Btn("Invert", painter=icon(_paint_mask_invert), size=big, key='MASKWIN_INVERT', tint=tint,
             selected=a.mask_inverted, on_click=a.toggle_mask_invert),
        _Btn("Pick", painter=icon(_paint_mask_pick), size=big, key='MASKWIN_PICK', tint=tint,
             selected=a.mask_picking, on_click=a.toggle_mask_pick),
    ], gap=GAP)
    width = 4 * big[0] + 3 * GAP
    small = (CELL, 28.0)
    show = _Btn("", painter=_icon_eye, layout='icon', size=small, key='MASKWIN_SHOW', tint=tint,
                selected=lambda: bool(a.wm_get('mask_show')),
                on_click=lambda: a.wm_set('mask_show', not a.wm_get('mask_show')))
    clear = _Btn("", painter=_icon_reset, layout='icon', size=small, key='MASKWIN_CLEAR', tint=tint,
                 on_click=lambda: bar.confirm(["Forget all chosen islands / parts?"], a.clear_mask, "Clear"))
    grow = Slider("Grow", lambda: a.wm_get('mask_grow', 0) or 0,
                  lambda v: a.wm_set('mask_grow', int(round(v))), value_range=lambda: a.wm_range('mask_grow')[:2],
                  step=1, size=(width - 2 * small[0] - 2 * GAP, small[1]), fill_color=(*TINT_MASK, 1.0),
                  font_size=FONT, corner=small[1] * 0.5)
    content = Column([main, Row([show, grow, clear], gap=GAP), _help_lines(bar, 'mask', MASK_HELP, width)],
                     gap=GAP + 2.0)
    return _WindowGroup("Mask", content, tint=TINT_MASK, painter=_icon_mask_title, title_indent=TITLE_INDENT)


def build_view_window(bar):
    """The View window's content (a Group): the Orient and Orbit pads, Auto Fit / 1:1."""
    a = bar.actions
    is3d = a.in_view3d
    tint = TINT_VIEW

    def segment(key, action, painter, enabled=is3d, **kwargs):
        return RingSegment("", painter=painter, key=f'VIEW_{key}', tint=tint, enabled=enabled,
                           on_click=action, **kwargs)

    def dial(key, action, painter, ring, enabled=True):
        """``ring``: eight segments counter-clockwise from the right (0, 45, ... 315 degrees)."""
        center = _DialCenter(painter=painter, tint=tint, key=f'VIEW_{key}', enabled=enabled, on_click=action)
        result = Dial(center, gap=DIAL_GAP)
        for i, seg in enumerate(ring):
            angle = i * 45.0
            result.add_segment(seg, *DIAL_RING, angle - 22.5, angle + 22.5)
        return result

    step = 15.0
    face = lambda axis: segment(axis, lambda: a.view_axis(axis), _icon_face(axis))
    # Orient: Front in the middle, the faces around it like an unfolded cube; the
    # diagonals roll (top), level (bottom left) and Back (bottom right, darker).
    orient = dial('FRONT', lambda: a.view_axis('FRONT'), _icon_face('FRONT'), [
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
    # Orbit: arrows around Fit; the diagonals zoom (top), Center, Persp / Ortho.
    orbit = dial('FIT', a.view_fit, _icon_fit, [
        segment('ORBIT_RIGHT', lambda: a.view_orbit(step, 0.0), _icon_arrow(0.0)),
        segment('ZOOM_OUT', lambda: a.view_zoom(-1), _icon_zoom(-1), enabled=True),
        segment('ORBIT_UP', lambda: a.view_orbit(0.0, step), _icon_arrow(90.0)),
        segment('ZOOM_IN', lambda: a.view_zoom(1), _icon_zoom(1), enabled=True),
        segment('ORBIT_LEFT', lambda: a.view_orbit(-step, 0.0), _icon_arrow(180.0)),
        segment('CENTER', a.view_center, _icon_center, enabled=True),
        segment('ORBIT_DOWN', lambda: a.view_orbit(0.0, -step), _icon_arrow(270.0)),
        segment('PERSPECTIVE', a.toggle_view_perspective, _icon_perspective(a.view_perspective)),
    ])
    width = 4 * DIAL_RING[1] + PAD_GAP
    one = (CELL * 1.6, 26.0)
    auto = _Btn("Auto Fit", painter=_icon_fit, layout='row', size=(width - one[0] - GAP, one[1]),
                key='VIEW_AUTOFIT', tint=tint, enabled=is3d, selected=a.view_autofit,
                on_click=a.toggle_view_autofit)
    one_to_one = _Btn("1:1", layout='row', size=one, key='VIEW_ONE_TO_ONE', tint=tint,
                      enabled=lambda: not is3d(), on_click=a.view_one_to_one)
    content = Column([Row([orient, orbit], gap=PAD_GAP), Row([auto, one_to_one], gap=GAP),
                      _help_lines(bar, 'view', VIEW_HELP, width)], gap=GAP + 2.0)
    return _WindowGroup("View", content, tint=TINT_VIEW, painter=_paint_view_title, title_indent=TITLE_INDENT)


def _paint_view_title(dc, x, y, size, alpha):
    _paint_view(dc, x, y - size * 0.15, size * 1.6, alpha)
