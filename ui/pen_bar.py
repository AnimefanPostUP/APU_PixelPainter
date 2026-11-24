"""Pen bar: on-screen controls in the bottom corner of the editor, made for pens / tablets.

Pens often cannot move the pointer without touching (no reliable hover), so
everything here works with press, drag and release only:

* **Layout** (top to bottom): *X* in the top corner on the edge side
  (collapses the bar); the color row -- swap chips, *Picker* (arms the
  eyedropper for the next canvas press), *Color* (shows / hides the color
  pad), *Settings* (opens the settings popup), the old / new bubble; the
  color pad, as wide as the bar; the **dial**. The bar sits in the bottom
  corner of the editor.
* **Dial** (:class:`~.kit.Dial`): everything around the *Size* knob in the
  center, as pie segments in two rings with equal gaps between them:

  - top right: *S* / *A* / *M* (Strength, Alpha, Modifier) radial sliders,
    as deep as both rings: press sets the value from the distance to the
    center, drag keeps setting it;
  - top left: the tools (half in each ring; tap selects);
  - bottom left: *Blend* (inner ring, opens the flyout; shows the mode),
    *Alphalock* (protect transparent pixels), *Pixel* / *Free* (spacing),
    *RMB* (the pen tip paints like the right mouse button);
  - bottom right: *Undo* / *Redo* arrows (inner ring), the falloff presets.

* **Size knob**: press and drag up / down; the value changes relative to
  where the drag started. A readout -- for Size with a preview of the brush
  footprint -- shows beside the bar while a knob or slider is dragged. Pens
  cannot scroll, so the knob and sliders stand in for the wheel.
* **Resize handle**: the triangle in the bar's top corner on the canvas side.
  Drag it outward / up to enlarge the bar (with flyouts), inward / down to
  shrink it; 0.2x .. 2x of the default size, remembered.
* **Color pad** (:class:`~.kit.ColorSelector`): layout (Sheet, Square,
  Triangle, Wheel), model (HSV / HSL) and optional RGB / HSV / HSL sliders
  come from the settings popup (Color Selector tab). Every part is swiped
  like a touchpad; a tap jumps. It
  edits the color the pen paints (secondary with the RMB lock). The change
  applies when the pen is lifted; the color from before editing stays marked
  with a cross and shows in the old / new bubble until the bubble is tapped
  (accept: the new color becomes the reference). With *Preview* on (settings
  popup, Color Selector tab) the pad only previews: the brush keeps its color (marked with the cross) and the
  picked one shows in the bubble until the bubble is tapped, which applies it.
* **Flyout** (Blend): opened by the *press*. Keep the pen down, drag
  onto an entry and lift -- or lift anywhere and tap an entry. A tap outside
  closes the flyout.

This module builds, lays out and draws the widgets (a non-modal UI-kit
layer). :class:`tools.pen_bar.PenBarTool` forwards events and provides the
``actions`` object the widgets call.
"""

import math

from .kit import (Button, ColorBubble, ColorSelector, Column, Dial, DragBubble, Label, Overlay, Panel, Rect,
                  RingSegment, RingSlider, Row, RoundButton, Widget)
from .kit import draw
from .kit.events import PRESS, RUNNING
from .kit.theme import with_alpha
from .kit.widget import _resolve
from ..tools import blend_modes, falloff


BAR_SCALE = 1.5          # everything on the bar (and its flyouts / pad) is this much larger than the kit default
MIN_USER_SCALE = 0.2     # the resize handle's range, relative to BAR_SCALE
MAX_USER_SCALE = 2.0
_HANDLE_SIZE = 18.0      # resize triangle legs, unscaled px (follows the UI scale, not the bar's)
FLYOUT_GAP = 10.0        # unscaled px between the bar and flyouts / readouts
SIZE_STEP_PX = 12.0      # drag distance per size step
VALUE_RANGE_PX = 240.0   # drag distance for the full 0..1 range of the other knobs
MAX_SIZE = 64

CHANNEL_LABELS = {'size': "Size", 'strength': "Strength", 'alpha': "Alpha", 'modifier': "Modifier"}
# Pens cannot scroll: these sliders replace the wheel controls of the strength bubble.
# Listed counter-clockwise (Modifier lowest, Strength next to the top).
SLIDERS = (('modifier', "M", (0.84, 0.95, 0.36, 1.0)),
           ('alpha', "A", (0.80, 0.83, 0.90, 1.0)),
           ('strength', "S", (0.96, 0.38, 0.47, 1.0)))
ARM_HINTS = {'EYEDROPPER': "Tap canvas: pick color"}
# Blend flyout columns after Favorites (titles as in the Shift+W pie).
BLEND_GROUPS = (("Contrast", 'CONTRAST'), ("Math", 'MATH'), ("HSL/HSV", 'HSL'))

# Dial (unscaled px; angles in degrees counter-clockwise from +x, 90 = up).
DIAL_GAP = 2.5                 # spacing between segments of a category / rings / the Size knob
GROUP_GAP = 14.0               # spacing between categories (a divider line runs through it)
SIZE_RADIUS = 30.0
INNER_RING = (32.5, 72.5)
OUTER_RING = (75.0, 115.0)
SLIDER_ARC = (15.0, 90.0)      # S / A / M, through both rings
TOOL_ARC = (90.0, 210.0)       # tools, half in each ring
MODE_ARC = (210.0, 270.0)      # Blend | Alphalock, Pixel / Free, RMB
HISTORY_ARC = (270.0, 375.0)   # Undo / Redo | falloff presets
_INNER_FILL = (0.26, 0.26, 0.26, 0.95)   # the inner ring is a bit lighter than the outer
# Category tints (mixed lightly into the segment fills).
TINT_TOOLS = (0.35, 0.58, 1.00)
TINT_MODES = (1.00, 0.62, 0.25)
TINT_HISTORY = (0.95, 0.40, 0.45)
TINT_FALLOFF = (0.30, 0.85, 0.72)

_BUTTON_RADIUS = 19.0
_CLOSE_RADIUS = 17.0 * 0.25   # the X (drawn); taps hit a larger area
_CLOSE_HIT = 10.0        # extra tap radius around the X, unscaled px
_PANEL_PADDING = 4.0
# The bar's buttons sit this far from the editor edge (or an overlapping sidebar):
# 30% of a button's diameter (unscaled px; the panel padding is inside it).
EDGE_GAP = 0.3 * 2.0 * _BUTTON_RADIUS



def clamp_user_scale(scale):
    return max(MIN_USER_SCALE, min(MAX_USER_SCALE, scale))

class FlyoutButton(Button):
    """Flyout entry: also confirms when the pen is lifted over it after dragging in.

    ``marked`` (bool or callable): a small check mark at the right end (e.g. favorites).
    """

    drag_release = True

    def __init__(self, label="", *, marked=None, **kwargs):
        super().__init__(label, **kwargs)
        self.marked = marked

    def draw_self(self, dc):
        super().draw_self(dc)
        if not _resolve(self.marked, False) or self._visual is None:
            return
        theme, r = dc.theme, self._visual
        s = min(r.height * 0.28, theme.px(5.0))
        x, y = r.x1 - theme.px(6.0) - s * 2.0, r.cy
        draw.polyline([(x, y), (x + s * 0.7, y - s * 0.7), (x + s * 2.0, y + s * 0.8)],
                      with_alpha(theme.text, 0.85 * dc.alpha), theme.px(1.5))


class ColorChips(Widget):
    """Primary / secondary color chips; tap swaps them. The color the pen paints is ringed."""

    interactive = True

    def __init__(self, colors, secondary_active, *, radius=_BUTTON_RADIUS, **kwargs):
        super().__init__(**kwargs)
        self.colors = colors                      # () -> (primary_rgb, secondary_rgb)
        self.secondary_active = secondary_active  # () -> bool
        self.radius = radius

    def measure(self, theme):
        d = theme.px(self.radius) * 2.0
        return d, d

    def contains(self, x, y):
        return math.hypot(x - self.rect.cx, y - self.rect.cy) <= self.rect.width * 0.5

    def draw_self(self, dc):
        theme = dc.theme
        cx, cy = self.rect.cx, self.rect.cy
        r = self.rect.width * 0.5
        alpha = dc.alpha
        primary, secondary = _resolve(self.colors, ((1.0, 1.0, 1.0), (0.0, 0.0, 0.0)))
        secondary_active = bool(_resolve(self.secondary_active, False))

        draw.circle(cx, cy, r, with_alpha(theme.surface, alpha))
        chip = r * 0.58
        off = (r - chip) * 0.75
        chips = (
            (cx + off, cy - off, secondary, secondary_active),   # back, lower right
            (cx - off, cy + off, primary, not secondary_active),  # front, upper left
        )
        for x, y, rgb, active in chips:
            draw.circle(x, y, chip, (rgb[0], rgb[1], rgb[2], alpha))
            ring = theme.accent_light if active else (0.0, 0.0, 0.0, 0.85)
            draw.circle_outline(x, y, chip, with_alpha(ring, alpha), width=theme.px(2.0 if active else 1.0))
        border = theme.accent if self.hover_t > 0.5 else theme.border
        draw.circle_outline(cx, cy, r, with_alpha(border, alpha), width=theme.px(1.0))


class _Spacer(Widget):
    def __init__(self, height):
        super().__init__()
        self.height = height

    def measure(self, theme):
        return 0.0, theme.px(self.height)


class _ResizeHandle(Widget):
    """Triangle in the bar's top corner on the canvas side; press and drag to resize.

    ``on_drag(dx, dy)`` gets the pointer offset from the press point.
    """

    interactive = True
    draggable = True

    def __init__(self, on_drag_begin, on_drag, on_drag_end, **kwargs):
        super().__init__(**kwargs)
        self.on_drag_begin = on_drag_begin
        self.on_drag = on_drag
        self.on_drag_end = on_drag_end
        self.drag_origin = None
        self.corner_right = True   # right angle in the top-right corner (bar on the left)

    def drag_begin(self, x, y):
        self.drag_origin = (x, y)
        self.on_drag_begin()

    def drag_update(self, x, y):
        if self.drag_origin is not None:
            self.on_drag(x - self.drag_origin[0], y - self.drag_origin[1])

    def drag_end(self, x, y, cancelled=False):
        self.drag_origin = None
        self.on_drag_end(cancelled)

    def draw_self(self, dc):
        theme = dc.theme
        r = self.rect
        if self.corner_right:
            corner, a, b = (r.x1, r.y1), (r.x0, r.y1), (r.x1, r.y0)
        else:
            corner, a, b = (r.x0, r.y1), (r.x1, r.y1), (r.x0, r.y0)
        active = self.drag_origin is not None or self.hover_t > 0.5
        fill = theme.accent if active else theme.border
        draw.triangle(corner, a, b, with_alpha(fill, dc.alpha))


class _CloseButton(Widget):
    """Small round X button. Its tap area is larger than the drawing (pens)."""

    interactive = True

    def __init__(self, *, radius=_CLOSE_RADIUS, hit=_CLOSE_HIT, **kwargs):
        super().__init__(**kwargs)
        self.radius = radius
        self.hit = hit
        self._hit_px = 0.0

    def measure(self, theme):
        self._hit_px = theme.px(self.hit)
        d = theme.px(self.radius) * 2.0
        return d, d

    def contains(self, x, y):
        reach = self.rect.width * 0.5 + self._hit_px
        return math.hypot(x - self.rect.cx, y - self.rect.cy) <= reach

    def draw_self(self, dc):
        theme = dc.theme
        cx, cy, r = self.rect.cx, self.rect.cy, self.rect.width * 0.5
        active = self.hover_t > 0.5
        draw.circle(cx, cy, r, with_alpha(theme.surface_pressed if active else theme.surface, dc.alpha))
        draw.circle_outline(cx, cy, r, with_alpha(theme.accent if active else theme.border, dc.alpha),
                            width=theme.px(1.0))
        arm = r * 0.5
        color = with_alpha(theme.text, 0.9 * dc.alpha)
        width = max(1.0, theme.px(1.2))
        draw.polyline([(cx - arm, cy - arm), (cx + arm, cy + arm)], color, width)
        draw.polyline([(cx - arm, cy + arm), (cx + arm, cy - arm)], color, width)


# ---- dial segment content: painter(dc, x, y, size, alpha) --------------------------------

def _paint_arrow(direction, caption):
    """Undo / Redo: a horizontal arrow with a caption under it."""
    def paint(dc, x, y, size, alpha):
        theme = dc.theme
        s = min(size * 0.55, theme.px(22.0))
        color = with_alpha(theme.text, 0.92 * alpha)
        d = 1.0 if direction == 'RIGHT' else -1.0
        ay = y + s * 0.15
        tip, tail = x + d * s * 0.5, x - d * s * 0.5
        base = tip - d * s * 0.45
        shaft = s * 0.13
        draw.rect(Rect(min(tail, base), ay - shaft, max(tail, base), ay + shaft), color)
        draw.triangle((tip, ay), (base, ay + s * 0.36), (base, ay - s * 0.36), color)
        draw.text_centered(caption, x, ay - s * 0.75, theme.px(8.0),
                           with_alpha(theme.text_muted, alpha), theme.font_id)
    return paint


def _paint_alpha_lock(dc, x, y, size, alpha):
    """Checkerboard (transparency) with a padlock on it."""
    theme = dc.theme
    s = size * 0.62
    half = s * 0.5
    light, dark = (0.78, 0.78, 0.78, alpha), (0.48, 0.48, 0.48, alpha)
    for i in range(2):
        for j in range(2):
            draw.rect(Rect.from_size(x - half + i * half, y - half + j * half, half, half),
                      light if (i + j) % 2 else dark)
    lock = (0.07, 0.07, 0.07, alpha)
    bw, bh = s * 0.5, s * 0.36
    body = Rect.from_size(x - bw * 0.5, y - s * 0.32, bw, bh)
    draw.rect(body, lock)
    draw.arc(x, body.y1, bw * 0.3, 0.0, math.pi, lock, width=max(1.0, theme.px(2.0)), segments=16)


def _paint_spacing(mode):
    """Pixel / Free: the initial with a small square (solid for Pixel, fading for Free)."""
    def paint(dc, x, y, size, alpha):
        theme = dc.theme
        pixel = _resolve(mode, 'FREE') == 'PIXEL'
        letter = theme.px(15.0)
        draw.text_centered("P" if pixel else "F", x - letter * 0.12, y + size * 0.12, letter,
                           with_alpha(theme.text, alpha), theme.font_id)
        sq = letter * 0.32
        box = Rect.from_size(x + letter * 0.22, y + size * 0.12 - letter * 0.42, sq, sq)
        if pixel:
            draw.rect(box, (1.0, 1.0, 1.0, alpha))
        else:
            draw.gradient_quad(box, (1.0, 1.0, 1.0, alpha), (1.0, 1.0, 1.0, 0.1 * alpha),
                               (1.0, 1.0, 1.0, 0.1 * alpha), (1.0, 1.0, 1.0, alpha))
        draw.text_centered("Pixel" if pixel else "Free", x, y - size * 0.3, theme.px(7.5),
                           with_alpha(theme.text_muted, alpha), theme.font_id)
    return paint


def _paint_blend(label):
    """Blend: a black-to-white disc with the active blend mode under it."""
    def paint(dc, x, y, size, alpha):
        theme = dc.theme
        r = min(size * 0.3, theme.px(15.0))
        cy = y + r * 0.35
        draw.gradient_circle(x, cy, r, (0.0, 0.0, 0.0, alpha), (1.0, 1.0, 1.0, alpha))
        draw.circle_outline(x, cy, r, with_alpha(theme.border, alpha), width=theme.px(1.0))
        draw.text_centered(str(_resolve(label, "")), x, cy - r - theme.px(7.0), theme.px(8.0),
                           with_alpha(theme.text_muted, alpha), theme.font_id)
    return paint


class _CornerStrip(Widget):
    """A row holding one widget in its column's left or right corner (``edge_left``).

    Measures zero wide so it does not widen the column; aligns to the parent's rect,
    which a Column sets before arranging its children.
    """

    def __init__(self, child):
        super().__init__()
        self.child = self.add(child)
        self.edge_left = True

    def measure(self, theme):
        return 0.0, self.child.measure(theme)[1]

    def arrange(self, rect, theme):
        col = self.parent.rect if self.parent is not None else rect
        w, h = self.child.measure(theme)
        x0 = col.x0 if self.edge_left else col.x1 - w
        self.rect = Rect(col.x0, rect.y0, col.x1, rect.y1)
        self.child.arrange(Rect.from_size(x0, rect.cy - h * 0.5, w, h), theme)


class _Layer(Widget):
    """Root widget: the bar (or its collapsed tab) in the bottom corner at an editor
    edge, the resize handle in its top corner, flyouts beside their opener."""

    def __init__(self, bar, tab, flyouts, handle):
        super().__init__()
        self.bar = self.add(bar)
        self.tab = self.add(tab)
        self.flyouts = [self.add(flyout) for flyout in flyouts]
        self.handle = self.add(handle)   # last: picked before the bar under it
        self.handle_size = 0.0           # screen px, set by the PenBar
        self.openers = {}          # flyout -> the button that opened it
        self.side = 'LEFT'
        self.region_height = 0.0

    @property
    def shown(self):
        return self.tab if self.tab.visible else self.bar

    def measure(self, theme):
        return self.shown.measure(theme)

    def place(self, origin, theme):
        """``origin`` = (x of the edge the bar hugs, y of its bottom)."""
        edge_x, bottom = origin
        gap = theme.px(FLYOUT_GAP)
        margin = theme.px(theme.region_margin)

        # Bottom corner; if the region is too short the top stays visible.
        shown = self.shown
        w, h = shown.measure(theme)
        y0 = min(bottom, self.region_height - margin - h)
        x0 = edge_x if self.side == 'LEFT' else edge_x - w
        shown.arrange(Rect.from_size(x0, y0, w, h), theme)
        self.rect = shown.rect
        outer_x1, outer_x0 = shown.rect.x1, shown.rect.x0

        handle = self.handle
        handle.visible = self.bar.visible
        if handle.visible:
            size = self.handle_size
            bar = self.bar.rect
            handle.corner_right = self.side == 'LEFT'
            x0 = bar.x1 - size if handle.corner_right else bar.x0
            handle.arrange(Rect.from_size(x0, bar.y1 - size, size, size), theme)

        for flyout in self.flyouts:
            if not flyout.visible:
                continue
            fw, fh = flyout.measure(theme)
            opener = self.openers.get(flyout)
            fy = opener.rect.cy if opener is not None else shown.rect.cy
            y0 = min(fy - fh * 0.5, self.region_height - margin - fh)
            y0 = max(margin, y0)
            fx = outer_x1 + gap if self.side == 'LEFT' else outer_x0 - gap - fw
            flyout.arrange(Rect.from_size(fx, y0, fw, fh), theme)


def _is_inside(widget, ancestor):
    while widget is not None:
        if widget is ancestor:
            return True
        widget = widget.parent
    return False


class PenBar:
    """Widget layer of the pen bar. ``actions`` is the :class:`tools.pen_bar.PenBarTool`."""

    def __init__(self, actions):
        from .icons import ICONS  # late import: ui.icons imports the tool catalog
        self.actions = actions
        self.icons = ICONS
        self.flyout = None          # open flyout panel
        self.flyout_opener = None
        self._drag = None           # (channel, value at drag start) while a knob is dragged
        self.knobs = {}
        self.arm_buttons = {}

        self.color_pad = ColorSelector(actions.pen_hsv, actions.set_pen_hsv, original=actions.original_hsv,
                                       live=actions.color_preview, layout=actions.color_layout,
                                       model=actions.color_model, sliders=actions.color_sliders,
                                       key='COLOR_PAD')  # part of the bar
        bar, tab = self._build_bar(), RoundButton("Pen", radius=17.0, on_click=lambda: self.set_collapsed(False))
        self.blend_flyout = self._build_blend_flyout()
        self.blend_flyout.visible = False
        tab.visible = False
        self._resize = None         # (scale, bar width, bar height) while the handle is dragged
        handle = _ResizeHandle(self._begin_resize, self._resize_to, self._end_resize, key='RESIZE')
        self.root = _Layer(bar, tab, [self.blend_flyout], handle)
        self.overlay = Overlay(self.root, modal=False, animate=False)

    # ---- building ------------------------------------------------------------------

    def _knob(self, channel, label, radius, font_size, value_font_size):
        if channel == 'size':
            value_text = lambda: str(self._value('size'))
            fraction = lambda: math.sqrt(max(0, self._value('size')) / MAX_SIZE)
        else:
            value_text = lambda: str(int(round(self._value(channel) * 100)))
            fraction = lambda: self._value(channel)
        knob = DragBubble(
            label, radius=radius, font_size=font_size, value_font_size=value_font_size,
            value_text=value_text, fraction=fraction, key=f"KNOB_{channel}",
            on_drag_begin=lambda: self._begin_drag(channel),
            on_drag=self._drag_to,
            on_drag_end=self._end_drag,
        )
        self.knobs[channel] = knob
        return knob

    @staticmethod
    def _button(label, on_click, selected=None, opener=False):
        button = RoundButton(label, radius=_BUTTON_RADIUS, font_size=9.0, on_click=on_click,
                             selected=selected, key=label.upper())
        button.activate_on_press = opener
        return button

    def _slider(self, channel, label, color):
        slider = RingSlider(
            label, key=f"SLIDER_{channel}", font_size=11.0, fill_color=color,
            value=lambda: self._value(channel),
            on_drag_begin=lambda: self._begin_drag(channel),
            on_value=lambda v: self.actions.set_value(channel, v),
            on_drag_end=self._end_drag,
        )
        self.knobs[channel] = slider   # the drag readout sits beside it
        return slider

    def _build_dial(self):
        """Size knob in the center, everything else in pie segments around it (see the module docs)."""
        a = self.actions
        dial = Dial(self._knob('size', "Size", SIZE_RADIUS, 11.0, 20.0), gap=DIAL_GAP, group_gap=GROUP_GAP)

        dial.add_arc([self._slider(*spec) for spec in SLIDERS], INNER_RING[0], OUTER_RING[1], *SLIDER_ARC)

        # Tools: the first half in the outer ring, listed from the bottom up.
        all_tools = a.tools()
        half = (len(all_tools) + 1) // 2
        tools = [
            RingSegment(tool.label, key=f"TOOL_{tool.tool_id}", icon=tool.tool_id if tool.icon else None,
                        icons=self.icons, font_size=8.0, fill=_INNER_FILL if i >= half else None,
                        selected=lambda t=tool.tool_id: a.active_tool() == t,
                        on_click=lambda t=tool.tool_id: a.select_tool(t))
            for i, tool in enumerate(all_tools)
        ]
        dial.add_arc(reversed(tools[:half]), *OUTER_RING, *TOOL_ARC, tint=TINT_TOOLS)
        dial.add_arc(reversed(tools[half:]), *INNER_RING, *TOOL_ARC, tint=TINT_TOOLS)

        blend = RingSegment("Blend", key='BLEND', fill=_INNER_FILL,
                            painter=_paint_blend(lambda: blend_modes.label(a.active_blend())),
                            on_click=lambda: self.toggle_flyout(self.blend_flyout, blend),
                            selected=lambda: self.flyout is self.blend_flyout)
        blend.activate_on_press = True
        dial.add_arc([blend], *INNER_RING, *MODE_ARC, tint=TINT_MODES)
        dial.add_arc([
            RingSegment("Alphalock", key='ALPHA_LOCK', painter=_paint_alpha_lock,
                        selected=a.alpha_lock, on_click=a.toggle_alpha_lock),
            RingSegment("Spacing", key='SPACING', painter=_paint_spacing(a.spacing),
                        on_click=a.toggle_spacing),
            RingSegment("RMB", key='RMB', font_size=9.0, selected=a.rmb_lock, on_click=a.toggle_rmb_lock),
        ], *OUTER_RING, *MODE_ARC, tint=TINT_MODES)

        dial.add_arc([
            RingSegment("Undo", key='UNDO', fill=_INNER_FILL, painter=_paint_arrow('LEFT', "Undo"), on_click=a.undo),
            RingSegment("Redo", key='REDO', fill=_INNER_FILL, painter=_paint_arrow('RIGHT', "Redo"), on_click=a.redo),
        ], *INNER_RING, *HISTORY_ARC, tint=TINT_HISTORY)
        # Falloff presets: the first one at the top.
        self.falloff_buttons = [
            RingSegment(preset.label, key=f"FALLOFF_{preset.id}", icon=preset.icon_key, icons=self.icons,
                        font_size=8.0, selected=lambda p=preset.id: a.active_falloff() == p,
                        on_click=lambda p=preset.id: a.set_falloff(p))
            for preset in falloff.picker_presets()
        ]
        dial.add_arc(reversed(self.falloff_buttons), *OUTER_RING, *HISTORY_ARC, tint=TINT_FALLOFF)
        return dial

    def _build_bar(self):
        a = self.actions

        def arm(kind):
            return lambda: a.toggle_arm(kind)

        def armed(kind):
            return lambda: a.armed() == kind

        # Top corner (edge side): collapse.
        hide = _CloseButton(key='HIDE', on_click=lambda: self.set_collapsed(True))
        self.corner = _CornerStrip(hide)
        self.dial = self._build_dial()

        # Color row: swap chips, eyedropper, color pad toggle, Settings + old / new bubble.
        picker = self._button("Picker", arm('EYEDROPPER'), armed('EYEDROPPER'))
        picker.font_size = 8.0
        self.arm_buttons = {'EYEDROPPER': picker}
        chips = ColorChips(a.colors, a.rmb_lock, on_click=a.swap_colors, key='COLORS')
        color = self._button("Color", a.toggle_color_panel, a.color_panel_open)
        settings = self._button("Settings", a.open_settings)
        settings.font_size = 8.0
        self.color_bubble = ColorBubble(a.preview_colors, True, a.has_color_change, radius=_BUTTON_RADIUS,
                                        on_click=a.accept_color_change, key='COLOR_BUBBLE')
        self.color_row = Row([chips, picker, color, settings, self.color_bubble], gap=6.0)

        # The color pad sits under the color row, stretched to the bar's width (layout()).
        content = Column([self.corner, self.color_row, self.color_pad, _Spacer(4.0), self.dial], gap=8.0)
        return Panel(content, padding=_PANEL_PADDING)

    def _flyout_action(self, fn):
        def _run():
            fn()
            self.close_flyout()
        return _run

    def _build_blend_flyout(self):
        """Same groups as the Shift+W blend pie, as four columns: Favorites, Contrast,
        Math, HSL/HSV. Favorites are check-marked; the Favorites column follows the
        favorites chosen in the settings (see ``_sync_favorites``)."""
        a = self.actions

        def entry(blend_id, key):
            return FlyoutButton(
                blend_modes.label(blend_id), key=key, size=(84.0, 26.0),
                selected=lambda b=blend_id: a.active_blend() == b,
                marked=lambda b=blend_id: b in a.blend_favorites(),
                on_click=self._flyout_action(lambda b=blend_id: a.set_blend(b)),
            )

        self.favorite_entries = {b: entry(b, f"BLEND_FAV_{b}") for b in blend_modes.ids()}
        columns = [Column([Label("Favorites", size=10.0), *self.favorite_entries.values()], gap=3.0)]
        for title, group in BLEND_GROUPS:
            columns.append(Column([Label(title, size=10.0)]
                                  + [entry(b, f"BLEND_{b}") for b in blend_modes.ids(group)], gap=3.0))
        return Panel(Row(columns, gap=10.0, align='top'), title="Blend Mode", padding=8.0)

    def _sync_favorites(self):
        try:
            favorites = self.actions.blend_favorites()
        except Exception:
            favorites = blend_modes.DEFAULT_FAVORITES
        for blend_id, button in self.favorite_entries.items():
            button.visible = blend_id in favorites

    # ---- state -----------------------------------------------------------------------

    def _value(self, channel):
        try:
            return self.actions.get_value(channel)
        except Exception:
            return 0

    def toggle_flyout(self, flyout, opener):
        if self.flyout is flyout:
            self.close_flyout()
            return
        self.close_flyout(relayout=False)
        if flyout is self.blend_flyout:
            self._sync_favorites()
        flyout.visible = True
        self.flyout = flyout
        self.flyout_opener = opener
        self.root.openers[flyout] = opener
        self.overlay.layout()

    def close_flyout(self, relayout=True):
        for flyout in self.root.flyouts:
            flyout.visible = False
        self.flyout = None
        self.flyout_opener = None
        if relayout:
            self.overlay.layout()

    def set_collapsed(self, collapsed):
        self.actions.set_collapsed(collapsed)
        self.close_flyout(relayout=False)
        self._sync_collapsed()
        self.overlay.layout()

    def _sync_collapsed(self):
        collapsed = bool(self.actions.collapsed())
        self.root.bar.visible = not collapsed
        self.root.tab.visible = collapsed
        self.color_pad.visible = bool(self.actions.color_panel_open())

    def reset(self):
        """End drags, close flyouts, forget hover (session end / bar hidden)."""
        if self.overlay.dragging is not None:
            self.overlay.end_drag()
        self.close_flyout()
        self.overlay.hot = None
        self.overlay.pressed = None
        self.overlay.pointer_widget = None

    def end_drag(self):
        """The host lost the pointer: keep the dragged value."""
        if self.overlay.dragging is not None:
            self.overlay.end_drag()

    # ---- knob drags ------------------------------------------------------------------

    def _begin_drag(self, channel):
        self._drag = (channel, self._value(channel))

    def _drag_to(self, dx, dy):
        if self._drag is None:
            return
        channel, start = self._drag
        theme = self.overlay.theme
        if channel == 'size':
            value = start + int(round(dy / theme.px(SIZE_STEP_PX)))
        else:
            value = start + dy / theme.px(VALUE_RANGE_PX)
        self.actions.set_value(channel, value)

    def _end_drag(self, cancelled):
        if cancelled and self._drag is not None:
            self.actions.set_value(*self._drag)  # restore the value from before the drag
        self._drag = None

    # ---- resize handle -----------------------------------------------------------------

    def _begin_resize(self):
        bar = self.root.bar.rect
        self._resize = (self._user_scale(), bar.width, bar.height)

    def _resize_to(self, dx, dy):
        """Scale so the handle corner follows the pen. The bar hugs the side edge and
        the bottom, so its top corner moves by (dW, dH) per scale step."""
        if self._resize is None:
            return
        scale, w, h = self._resize
        out = dx if self.root.side == 'LEFT' else -dx
        factor = 1.0 + (out * w + dy * h) / max(1.0, w * w + h * h)
        self.actions.set_bar_scale(clamp_user_scale(scale * factor))

    def _end_resize(self, cancelled):
        if cancelled and self._resize is not None:
            self.actions.set_bar_scale(self._resize[0])
        self._resize = None

    def _user_scale(self):
        try:
            return clamp_user_scale(float(self.actions.bar_scale()))
        except Exception:
            return 1.0

    # ---- layout / events -----------------------------------------------------------------

    def layout(self, region_width, region_height, side, inset_left, inset_right, theme):
        """Place the bar in the bottom corner at the ``side`` edge ('LEFT' / 'RIGHT').

        ``inset_left`` / ``inset_right``: width of overlapping regions to keep
        clear of (the sidebar; the toolbar is ignored).
        """
        self.root.handle_size = theme.px(_HANDLE_SIZE)
        theme = theme.scaled(theme.scale * BAR_SCALE * self._user_scale())
        self.overlay.theme = theme
        self._sync_collapsed()
        if self.root.tab.visible and self.flyout is not None:
            self.close_flyout(relayout=False)
        self.root.side = side
        self.root.region_height = region_height
        self.corner.edge_left = side == 'LEFT'
        # The bar's content width: the dial or the color row, whichever is wider.
        self.color_pad.fit_width = max(self.color_row.measure(theme)[0], self.dial.measure(theme)[0])
        margin = theme.px(max(0.0, EDGE_GAP - _PANEL_PADDING))
        x = inset_left + margin if side == 'LEFT' else region_width - inset_right - margin
        self.overlay.origin = (x, margin)
        self.overlay.layout()

    def handle(self, event):
        """Forward a :class:`~.kit.UIEvent` (region coords); True when the bar used it."""
        overlay = self.overlay
        if self.flyout is not None and overlay.dragging is None and event.value == PRESS:
            if event.type in {'ESC', 'RIGHTMOUSE'}:
                self.close_flyout()
                return True
            if event.type == 'LEFTMOUSE':
                hit = self.root.pick(event.x, event.y)
                if hit is None:
                    self.close_flyout()
                    return True  # a tap outside only closes the flyout
                if not _is_inside(hit, self.flyout) and hit is not self.flyout_opener:
                    self.close_flyout()
        return overlay.handle(event) == RUNNING

    # ---- drawing -----------------------------------------------------------------------

    def draw(self):
        self.overlay.draw()
        with draw.blend_mode('ALPHA'):
            self._draw_drag_readout()
            self._draw_arm_hint()

    def _beside_bar(self, width, cy):
        """Rect of ``width`` beside the bar on the canvas side, centered at ``cy``."""
        theme = self.overlay.theme
        bar = self.root.shown.rect
        gap = theme.px(FLYOUT_GAP)
        x0 = bar.x1 + gap if self.root.side == 'LEFT' else bar.x0 - gap - width
        return x0

    def _pill(self, text, cy, font_size, border):
        theme = self.overlay.theme
        size = theme.px(font_size)
        tw, _th = draw.text_size(text, size, theme.font_id)
        pad = theme.px(8.0)
        w, h = tw + pad * 2.0, size + pad * 2.0
        box = Rect.from_size(self._beside_bar(w, cy), cy - h * 0.5, w, h)
        draw.rect(box, theme.surface_dark)
        draw.rect_outline(box, border, width=theme.px(1.0))
        draw.text_centered(text, box.cx, box.cy, size, theme.text, theme.font_id)
        return box

    def _draw_drag_readout(self):
        if self._resize is not None:
            self._pill(f"Scale  {self._user_scale() * 100:.0f}%", self.root.handle.rect.cy, 14.0,
                       self.overlay.theme.accent)
            return
        if self._drag is None:
            return
        channel = self._drag[0]
        knob = self.knobs.get(channel)
        if knob is None:
            return
        theme = self.overlay.theme
        value = self._value(channel)
        if channel == 'size':
            text = f"{CHANNEL_LABELS[channel]}  {value}"
        else:
            text = f"{CHANNEL_LABELS[channel]}  {value * 100:.0f}%"
        box = self._pill(text, knob.rect.cy, 16.0, theme.accent)
        if channel == 'size':
            self._draw_size_preview(box, value)

    def _draw_size_preview(self, box, radius):
        """The brush footprint at the current zoom, next to the readout."""
        theme = self.overlay.theme
        texel = self.actions.texel_screen_px()
        if not texel:
            return
        half = min((2 * radius + 1) * texel * 0.5, 600.0)
        gap = theme.px(FLYOUT_GAP)
        cx = box.x1 + gap + half if self.root.side == 'LEFT' else box.x0 - gap - half
        cy = box.cy
        if self.actions.brush_shape() == 'SQUARE':
            rect = Rect.from_center(cx, cy, half * 2.0, half * 2.0)
            draw.rect_outline(rect, (0.0, 0.0, 0.0, 0.8), width=theme.px(3.0))
            draw.rect_outline(rect, (1.0, 1.0, 1.0, 0.95), width=theme.px(1.5))
        else:
            draw.circle_outline(cx, cy, half, (0.0, 0.0, 0.0, 0.8), width=theme.px(3.0))
            draw.circle_outline(cx, cy, half, (1.0, 1.0, 1.0, 0.95), width=theme.px(1.5))

    def _draw_arm_hint(self):
        kind = self.actions.armed()
        button = self.arm_buttons.get(kind)
        if button is None or not self.root.bar.visible:
            return
        self._pill(ARM_HINTS[kind], button.rect.cy, 12.0, self.overlay.theme.accent_light)
