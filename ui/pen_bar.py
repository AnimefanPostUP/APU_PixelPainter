"""Pen UI: on-screen controls made for pens / tablets -- the pen menu (a dial) and
the color selector, two floating elements.

Pens often cannot move the pointer without touching (no reliable hover), so
everything here works with press, drag and release only.

* **Floating elements**: the pen menu and the color selector are moved by
  dragging their empty background and resized by dragging the triangle in
  their bottom-right corner (each has its own size: pen menu 0.2x .. 2x,
  color selector 0.5x .. 2x, and never larger than the editor). The padlock
  (pen menu: bottom-left corner; color selector: top left) locks both. They are clipped to the editor
  borders (and an overlapping sidebar). Size and position are remembered;
  *Reset Pen UI* (settings popup, N-panel) restores the defaults: the pen
  menu in the bottom corner at the chosen side, the color selector beside it.
  The *X* in the top-right corner collapses the pen menu to a *Pen* tab /
  closes the color selector.
* **Pen menu** (:class:`~.kit.Dial`): everything around the *Size* knob in
  the center, as pie segments in two rings; categories are separated by a
  wider gap with a divider line:

  - top right: *S* / *A* / *M* (Strength, Alpha, Modifier) radial sliders,
    as deep as both rings: press sets the value from the distance to the
    center, drag keeps setting it;
  - top left: the tools (half in each ring; tap selects);
  - bottom left: *Blend* (inner ring, opens the flyout; shows the mode),
    *Alphalock* (protect transparent pixels), *Pixel* / *Free* (spacing),
    *RMB* (the pen tip paints like the right mouse button);
  - bottom right: *Undo* / *Redo* arrows (inner ring), the falloff presets
    (outer ring, continued in a second row along the circle in the corner;
    hard to soft to sharp from the top, then the special shapes); *Custom*
    in its own color.

  The corners of the square around the circle are buttons shaped to fit
  between the circle and the square (icons). Top left the color section: the
  color history along the circle (the last painted colors, newest left; tap
  paints with it), the secondary and primary color (tap a color: the pen
  paints with it -- the secondary one sets the RMB lock), each with its own
  *Picker* on its outer side (eyedropper for that color: arms it for the next canvas
  press; the active color's picker is bright, the other grey), and between
  them *Swap* with the *Mix* field behind it in the corner (the two colors
  half and half; tap: the active color becomes the mix);
  bottom left the palette band (24 slots in two bands along the circle) and
  *Palettes* (switches the band between the active palette's colors and the
  project's 24 palettes), *Color* (hue ring around the pen's color: shows /
  hides the color selector) and *Library* (the palette library window);
  bottom right, past the second falloff row, the *curve* button behind the
  Custom falloff (opens the curve flyout, selects Custom) and *Settings*
  (gear: the settings popup); top right a small *Save* at the right side
  (saves / packs the painted image as set in settings > Pen > Save Image; a
  green dot while it has unsaved changes) and the paint mask up to the top
  edge: *UV / Mesh* (islands or parts), *Mask* (on / off), *Invert* and
  *Pick* (tap islands / parts on the canvas to toggle them).
* **Palettes** are stored per project (in the .blend); the library window
  (``ui/pen_palettes.py``) imports / exports them to ``palettes.json`` and the
  clipboard -- project and library are not synced. *From image...* turns an
  image file's pixel colors into a new project palette.
* **Drag & drop** (setting *Drag Colors*): drag the primary / secondary color,
  a history color, a palette color or the color selector's old / new bubble (a
  short press stays a tap). Drop it on a palette slot to store it (palette onto
  palette: the two swap), on the primary / secondary color to set it; drop a
  palette color off the menu to remove it. In the palette view, palettes are
  dragged the same way: onto another slot (swap), into the library list
  (saved there), from the library onto a slot (loaded; replacing a palette
  asks first); a project palette dropped off the menu is deleted after a
  confirmation. Tap an empty palette slot to store the current color; tap a
  palette color to paint with it.
* **Curve flyout**: the custom falloff curve (the brush's falloff curve; x =
  distance from the center, y = weight). *Move*: drag anchors, drag one out of
  the box to remove it; *Add*: a tap adds an anchor; *Draw*: draw the falloff
  freehand, it becomes anchors on release; *Reset*: a smooth fade.
* **Size knob**: press and drag up / down; the value changes relative to
  where the drag started. A readout -- for Size with a preview of the brush
  footprint -- shows beside the menu while a knob or slider is dragged. Pens
  cannot scroll, so the knob and sliders stand in for the wheel.
* **Color selector** (:class:`~.kit.ColorSelector`): layout (Sheet, Square,
  Triangle, Wheel), model (HSV / HSL) and optional RGB / HSV / HSL sliders
  come from the settings popup (Color Selector tab). Every part is swiped
  like a touchpad; a tap jumps. It edits the color the pen paints (secondary
  with the RMB lock). The change applies when the pen is lifted; the color
  from before editing stays marked with a cross and shows in the old / new
  bubble at the top until the bubble is tapped (accept: the new color becomes
  the reference). With *Preview* on (settings popup, Color Selector tab) the
  selector only previews: the brush keeps its color (marked with the cross)
  and the picked one shows in the bubble until the bubble is tapped, which
  applies it.
* **Flyout** (Blend): opened by the *press*. Keep the pen down, drag
  onto an entry and lift -- or lift anywhere and tap an entry. A tap outside
  closes the flyout.

This module builds, lays out and draws the widgets (two non-modal UI-kit
layers). :class:`tools.pen_bar.PenBarTool` forwards events and provides the
``actions`` object the widgets call.
"""

import colorsys
import math

from .kit import (Button, ColorBubble, ColorSelector, Column, CurveEditor, Dial, DragBubble, Label, Overlay, Panel, Rect,
                  CornerSegment, RingSegment, RingSlider, Row, RoundButton, Widget)
from .kit import draw
from .kit.events import PRESS, RUNNING
from .kit.geometry import clamp_box, ring_segment_points
from .kit.theme import with_alpha
from .kit.widget import _resolve
from ..tools import blend_modes, color_history, color_palette, falloff


BAR_SCALE = 1.5          # everything (menu, color selector, flyouts) is this much larger than the kit default
# Each element's own size (resize triangle), relative to BAR_SCALE.
SCALE_LIMITS = {'bar': (0.2, 2.0), 'color': (0.5, 2.0)}
# Tool state keys holding the elements' size and position; Reset Pen UI restores these.
LAYOUT_STATE = {
    'pen_bar_scale': 1.0, 'pen_bar_pos': None,       # pos: (x0, y1) top-left in region px, None = default
    'pen_color_scale': 1.0, 'pen_color_pos': None,
}
COLOR_WIDTH = 220.0      # the color selector's width at scale 1, unscaled px
_HANDLE_SIZE = 18.0      # resize triangle legs, unscaled px (follows the UI scale, not the element's)
WINDOW_MARGIN = 4.0      # elements keep this far from the editor borders, unscaled px
FLYOUT_GAP = 10.0        # unscaled px between the menu and flyouts / readouts
SIZE_STEP_PX = 12.0      # drag distance per size step
MAX_SIZE = 64

CHANNEL_LABELS = {'size': "Size", 'strength': "Strength", 'alpha': "Alpha", 'modifier': "Modifier"}
# Pens cannot scroll: these sliders replace the wheel controls of the strength bubble.
# Listed counter-clockwise (Modifier lowest, Strength next to the top).
SLIDERS = (('modifier', "M", (0.84, 0.95, 0.36, 1.0)),
           ('alpha', "A", (0.80, 0.83, 0.90, 1.0)),
           ('strength', "S", (0.96, 0.38, 0.47, 1.0)))
ARM_HINTS = {'EYEDROPPER_PRIMARY': "Tap canvas: pick the primary color",
             'EYEDROPPER_SECONDARY': "Tap canvas: pick the secondary color"}
# Blend flyout columns after Favorites (titles as in the Shift+W pie).
BLEND_GROUPS = (("Contrast", 'CONTRAST'), ("Math", 'MATH'), ("HSL/HSV", 'HSL'))

# Dial (unscaled px; angles in degrees counter-clockwise from +x, 90 = up).
DIAL_GAP = 2.5                 # spacing between segments of a category / rings / the Size knob
GROUP_GAP = 14.0               # spacing between categories (a divider line runs through it)
SQUARE_HALF = 172.0                  # half size of the enclosing square
HISTORY_DEPTH = 14.0                 # the color history band / each palette band
PALETTE_ROWS = 2                     # palette bands; color_palette.PALETTE_SIZE slots split between them
PALETTE_DEPTH = PALETTE_ROWS * HISTORY_DEPTH + (PALETTE_ROWS - 1) * DIAL_GAP
CORNER_GAP = 4.0                     # circle -> first band (divider lines end in the bands' end gaps)
# The circle fills the square except for the palette bands' depth on each side;
# the rings keep their original proportions (designed for an outer radius of 115).
DIAL_RADIUS = SQUARE_HALF - CORNER_GAP - PALETTE_DEPTH
_RING_SCALE = DIAL_RADIUS / 115.0
SIZE_RADIUS = 30.0 * _RING_SCALE
INNER_RING = (SIZE_RADIUS + DIAL_GAP, 72.5 * _RING_SCALE)
OUTER_RING = (INNER_RING[1] + DIAL_GAP, DIAL_RADIUS)
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
TINT_CUSTOM = (1.00, 0.80, 0.20)     # the Custom falloff and its curve button stand out
CUSTOM_TINT_AMOUNT = 0.45
# Falloff presets, both rows listed from the bottom (270 degrees) up; read from the
# top they go hard -> soft -> sharp (outer ring, then the band), then the special shapes.
# Custom sits near the diagonal, in front of its curve button.
FALLOFF_RING_ORDER = ('LINEAR', 'SMOOTH', 'ROOT', 'SPHERE', 'PLATEAU', 'CONSTANT')
FALLOFF_BAND_ORDER = ('INVERTED', 'RING', 'CUSTOM', 'STEPPED', 'SPIKE', 'SHARPEN')
# Corner buttons: between the dial's circle and its enclosing square (angles as above).
CORNER_INNER = OUTER_RING[1] + CORNER_GAP
CORNER_CHAMFER = 30.0                # the square's corners are cut: room for the lock / X / resize triangle
# Top left: history band along the circle; then secondary's Picker | secondary |
# Swap + Mix | primary | primary's Picker (the colors toward the corner). Swap sits by
# the circle, the Mix field behind it fills the square's corner (not cut: the menu's
# lock is bottom left).
COLORS_ARC = (90.0, 180.0)
COLORS_WEIGHTS = (2.0, 1.6, 1.4, 1.6, 2.0)
SWAP_DEPTH = 27.0                    # Swap's radial depth; the Mix field starts past it
COLOR_WHEEL_ARC = (180.0, 270.0)     # bottom left: the palette (2 bands along the circle)
# Palettes | Color | Library: pushed together toward the diagonal, the only part of
# the corner with room left past the palette bands.
PALETTE_BUTTON_ARC = (200.0, 250.0)
PALETTE_BUTTON_WEIGHTS = (1.2, 1.0, 1.2)
COLOR_CORNER_INNER = CORNER_INNER + HISTORY_DEPTH + DIAL_GAP
WHEEL_CORNER_INNER = CORNER_INNER + PALETTE_DEPTH + DIAL_GAP
FALLOFF_BAND_DEPTH = PALETTE_DEPTH   # the second falloff row (bottom right), as deep as the palette
FALLOFF_CORNER_INNER = CORNER_INNER + FALLOFF_BAND_DEPTH + DIAL_GAP
CURVE_SETTINGS_ARC = (295.0, 335.0)  # bottom right past the band: Curve | Settings, around the diagonal
# Top right, past the S / A / M sliders (the X sits in the cut corner): a small Save at the
# right side, then the mask buttons Source | Mask | Invert | Pick up to the top edge.
SAVE_ARC = (17.0, 29.0)
MASK_ARC = (32.0, 88.0)
MASK_WEIGHTS = (1.0, 1.35, 1.0, 1.0)
TINT_SAVE = (0.45, 0.80, 0.45)
TINT_MASK = (0.78, 0.52, 1.00)
MASK_PICK_HINT = "Tap islands / parts to toggle them (Pick again: done)"
DRAG_THRESHOLD = 6.0                 # unscaled px a color must be dragged before it counts as a drag (else: tap)
CURVE_EDITOR_SIZE = (220.0, 150.0)
CURVE_MODES = (('MOVE', "Move"), ('ADD', "Add"), ('DRAW', "Draw"))
CURVE_HINTS = {'MOVE': "Drag anchors; drag out of the box: remove",
               'ADD': "Tap to add an anchor (keep the pen down to place it)",
               'DRAW': "Draw the falloff: center left, edge right"}

_CORNER_RADIUS = 6.0     # lock / X in the elements' top corners (drawn); taps hit a larger area
_CORNER_HIT = 9.0
_CORNER_INSET = 4.0
_PANEL_PADDING = 4.0
# The menu's default spot keeps this far from the editor edge (unscaled px; the panel padding is inside it).
EDGE_GAP = 0.3 * 2.0 * 19.0


def clamp_scale(name, scale):
    lo, hi = SCALE_LIMITS[name]
    return max(lo, min(hi, scale))


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



class _ColorDrag:
    """Drag & drop for pen menu widgets (mixin, before the widget class).

    A drag carries a payload: ``('color', rgb, origin)`` or ``('palette', palette,
    origin)``; ``origin`` names where it came from (``('palette_color', i)``,
    ``('project', i)``, ``('library', i)`` or None). ``drag_payload()`` gives it
    (default: ``drag_color()`` as a color); None: nothing to drag. A press that
    moves less than ``DRAG_THRESHOLD`` is a tap (``activate``); a longer move
    carries the payload, shown under the pen, and the release drops it
    (:meth:`PenBar.drop`). Targets define ``accepts(payload)`` and
    ``accept_drop(payload, source)``. Off with the *Drag Colors* setting."""

    bar = None

    def drag_color(self):
        return None

    def drag_payload(self):
        rgb = self.drag_color()
        return None if rgb is None else ('color', tuple(rgb), None)

    @property
    def draggable(self):
        try:
            return self.bar.actions.color_drag_enabled() and self.drag_payload() is not None
        except Exception:
            return False

    def accepts(self, payload):
        return False

    def drag_begin(self, x, y):
        self._press = (x, y)
        self._carry = self.drag_payload()
        self._moved = False

    def drag_update(self, x, y):
        if not self._moved:
            reach = self.bar.overlay.theme.px(DRAG_THRESHOLD)
            self._moved = math.hypot(x - self._press[0], y - self._press[1]) >= reach
        if self._moved:
            self.bar.drag_preview = (self._carry, x, y, self)

    def drag_end(self, x, y, cancelled=False):
        self.bar.drag_preview = None
        if cancelled:
            return
        if self._moved:
            self.bar.drop(self._carry, x, y, self)
        else:
            self.activate()


class _ColorCorner(_ColorDrag, CornerSegment):
    """The primary or secondary color (``which``) as a corner segment; the active one
    (the color the pen paints) is ringed. Drag source and drop target."""

    def __init__(self, bar, which, rgb, active, **kwargs):
        super().__init__(**kwargs)
        self.bar = bar
        self.which = which      # 'PRIMARY' / 'SECONDARY'
        self.rgb = rgb          # () -> (r, g, b)
        self.active = active    # () -> bool

    def drag_color(self):
        return _resolve(self.rgb, None)

    def accepts(self, payload):
        return payload[0] == 'color'

    def accept_drop(self, payload, source):
        self.bar.actions.set_color(self.which, payload[1])

    def draw_self(self, dc):
        theme = dc.theme
        inner, outer = self.points()
        if not inner:
            return
        rgb = _resolve(self.rgb, (0.0, 0.0, 0.0))
        draw.ring_segment(inner, outer, (rgb[0], rgb[1], rgb[2], dc.alpha), rim=theme.edge_for(rgb, dc.alpha))
        if _resolve(self.active, False):
            draw.ring_segment_outline(inner, outer, with_alpha(theme.accent_light, dc.alpha), width=theme.px(2.5))
        elif self.hover_t > 0.5:
            draw.ring_segment_outline(inner, outer, with_alpha(theme.accent, dc.alpha), width=theme.px(1.0))


class _MixCorner(_ColorDrag, CornerSegment):
    """The primary and secondary color mixed half and half. Tap: the active color
    becomes the mix (tap again for the next step toward the other color); drag
    source, not a drop target (it follows the two colors)."""

    def __init__(self, bar, rgb, **kwargs):
        super().__init__(**kwargs)
        self.bar = bar
        self.rgb = rgb          # () -> (r, g, b)

    def drag_color(self):
        return _resolve(self.rgb, None)

    def draw_self(self, dc):
        theme = dc.theme
        inner, outer = self.points()
        if not inner:
            return
        rgb = _resolve(self.rgb, (0.0, 0.0, 0.0))
        draw.ring_segment(inner, outer, (rgb[0], rgb[1], rgb[2], dc.alpha), rim=theme.edge_for(rgb, dc.alpha))
        if self.hover_t > 0.5:
            draw.ring_segment_outline(inner, outer, with_alpha(theme.accent, dc.alpha), width=theme.px(1.0))


class _BubbleDrag(_ColorDrag, ColorBubble):
    """The color selector's old / new bubble: tap accepts, dragging carries the new color."""

    def __init__(self, bar, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bar = bar

    def drag_color(self):
        try:
            return tuple(self.bar.actions.preview_colors()[1])
        except Exception:
            return None


def _paint_swap(dc, x, y, size, alpha):
    """Double arrow between the primary and the secondary color (along the top-left diagonal)."""
    theme = dc.theme
    r = min(size * 0.5, theme.px(12.0))
    color = with_alpha(theme.text, 0.9 * alpha)
    ux, uy = math.cos(math.radians(45.0)), math.sin(math.radians(45.0))
    length, head = r * 0.8, r * 0.4
    a = (x - ux * length, y - uy * length)
    b = (x + ux * length, y + uy * length)
    draw.polyline([a, b], color, max(1.0, theme.px(1.5)))
    for (tx, ty), d in ((a, -1.0), (b, 1.0)):
        bx, by = tx - ux * head * d, ty - uy * head * d
        draw.triangle((tx, ty), (bx - uy * head * 0.6, by + ux * head * 0.6),
                      (bx + uy * head * 0.6, by - ux * head * 0.6), color)


def _thick_line(a, b, width, color):
    draw.gradient_line(a, b, color, color, width)


def _paint_eyedropper(dc, x, y, size, alpha, color=None):
    """Picker icon: an eyedropper, bulb top right, tip bottom left."""
    theme = dc.theme
    s = min(size * 0.62, theme.px(24.0))
    color = with_alpha(theme.text, 0.92 * alpha) if color is None else color
    ux = uy = math.sqrt(0.5)
    tip = (x - ux * s * 0.5, y - uy * s * 0.5)
    neck = (x + ux * s * 0.12, y + uy * s * 0.12)
    _thick_line(tip, neck, s * 0.16, color)
    _thick_line((neck[0] + uy * s * 0.2, neck[1] - ux * s * 0.2),
                (neck[0] - uy * s * 0.2, neck[1] + ux * s * 0.2), s * 0.12, color)
    draw.circle(x + ux * s * 0.3, y + uy * s * 0.3, s * 0.17, color, segments=16)


def _paint_target_picker(rgb, active):
    """Picker for one color (``rgb()``): bright while that color is the active one
    (``active()``), grey otherwise; a dot of the color at its tip."""
    def paint(dc, x, y, size, alpha):
        theme = dc.theme
        on = _resolve(active, False)
        ink = (1.0, 1.0, 1.0, alpha) if on else with_alpha(theme.text_muted, 0.55 * alpha)
        _paint_eyedropper(dc, x, y, size, alpha, color=ink)
        c = _resolve(rgb, None)
        if c is not None:
            s = min(size * 0.62, theme.px(24.0))
            dx = dy = -math.sqrt(0.5) * s * 0.5     # the eyedropper's tip
            dx, dy = x + dx, y + dy
            dot = (c[0], c[1], c[2], alpha if on else 0.6 * alpha)
            draw.circle(dx, dy, max(2.0, s * 0.16), dot, rim=theme.edge_for(c, dot[3]), segments=16)
    return paint


def _paint_color_wheel(rgb):
    """Color icon: a hue ring around the color the pen paints."""
    def paint(dc, x, y, size, alpha):
        theme = dc.theme
        r = min(size * 0.36, theme.px(13.0))
        steps = 24
        for i in range(steps):
            c = colorsys.hsv_to_rgb(i / steps, 0.85, 1.0)
            draw.sector(x, y, r, math.tau * i / steps, math.tau * (i + 1) / steps, (*c, alpha), segments=2)
        draw.circle(x, y, r * 0.6, with_alpha(theme.surface_dark, alpha), segments=24)
        cur = _resolve(rgb, (1.0, 1.0, 1.0))
        draw.circle(x, y, r * 0.42, (cur[0], cur[1], cur[2], alpha), segments=24)
    return paint


def _paint_gear(dc, x, y, size, alpha):
    """Settings icon: a gear."""
    theme = dc.theme
    r = min(size * 0.34, theme.px(12.0))
    color = with_alpha(theme.text, 0.92 * alpha)
    for k in range(8):
        a = k * math.pi / 4.0
        _thick_line((x + math.cos(a) * r * 0.55, y + math.sin(a) * r * 0.55),
                    (x + math.cos(a) * r, y + math.sin(a) * r), r * 0.34, color)
    draw.circle(x, y, r * 0.74, color, segments=24)
    draw.circle(x, y, r * 0.32, with_alpha(theme.surface_dark, alpha), segments=16)


def _paint_save(unsaved, caption=True):
    """Save icon: a floppy disk; a dot in the accent color while ``unsaved()``."""
    def paint(dc, x, y, size, alpha):
        theme = dc.theme
        s = min(size * 0.5, theme.px(20.0 if caption else 14.0))
        color = with_alpha(theme.text, 0.92 * alpha)
        body = Rect.from_center(x, y, s, s)
        draw.rect(body, color)
        hole = with_alpha(theme.surface_dark, alpha)
        draw.rect(Rect(body.x0 + s * 0.22, body.y1 - s * 0.34, body.x1 - s * 0.22, body.y1 - s * 0.06), hole)
        draw.rect(Rect(body.x0 + s * 0.16, body.y0 + s * 0.1, body.x1 - s * 0.16, body.y0 + s * 0.48), hole)
        if _resolve(unsaved, False):
            dot = (*TINT_SAVE, alpha)
            draw.circle(body.x1, body.y1, max(2.5, s * 0.2), dot, rim=theme.edge_for(TINT_SAVE, alpha), segments=16)
        if caption:
            draw.text_centered("Save", x, body.y0 - theme.px(7.0), theme.px(8.0),
                               with_alpha(theme.text_muted, alpha), theme.font_id)
    return paint


def _caption(dc, x, y, text, alpha):
    theme = dc.theme
    draw.text_centered(text, x, y, theme.px(7.5), with_alpha(theme.text_muted, alpha), theme.font_id)


def _paint_mask(dc, x, y, size, alpha):
    """Mask on / off: a square, half texture (light) and half protected (dark)."""
    theme = dc.theme
    s = min(size * 0.42, theme.px(16.0))
    box = Rect.from_center(x, y + s * 0.2, s, s)
    draw.rect(Rect(box.x0, box.y0, box.cx, box.y1), (0.85, 0.85, 0.85, alpha))
    draw.rect(Rect(box.cx, box.y0, box.x1, box.y1), (0.12, 0.12, 0.12, alpha))
    draw.rect_outline(box, with_alpha(theme.text, 0.9 * alpha), width=max(1.0, theme.px(1.2)))
    _caption(dc, x, box.y0 - theme.px(6.0), "Mask", alpha)


def _paint_mask_source(source):
    """UV Islands / Mesh Parts: the source in big letters."""
    def paint(dc, x, y, size, alpha):
        theme = dc.theme
        uv = _resolve(source, 'UV_ISLAND') != 'MESH_PART'
        draw.text_centered("UV" if uv else "Mesh", x, y + size * 0.1, theme.px(11.0 if uv else 9.0),
                           with_alpha(theme.text, alpha), theme.font_id)
        _caption(dc, x, y - size * 0.25, "Islands" if uv else "Parts", alpha)
    return paint


def _paint_mask_invert(dc, x, y, size, alpha):
    """Invert: a disc, half light and half dark, with a curved arrow."""
    theme = dc.theme
    r = min(size * 0.22, theme.px(9.0))
    cy = y + r * 0.45
    draw.sector(x, cy, r, math.pi * 0.5, math.pi * 1.5, (0.85, 0.85, 0.85, alpha), segments=12)
    draw.sector(x, cy, r, -math.pi * 0.5, math.pi * 0.5, (0.12, 0.12, 0.12, alpha), segments=12)
    draw.circle_outline(x, cy, r, with_alpha(theme.text, 0.9 * alpha), width=max(1.0, theme.px(1.2)))
    _caption(dc, x, cy - r - theme.px(6.0), "Invert", alpha)


def _paint_mask_pick(dc, x, y, size, alpha):
    """Pick: a pointer tapping an island."""
    theme = dc.theme
    s = min(size * 0.4, theme.px(15.0))
    color = with_alpha(theme.text, 0.92 * alpha)
    cy = y + s * 0.25
    draw.circle_outline(x, cy, s * 0.5, color, width=max(1.0, theme.px(1.2)))
    draw.circle(x, cy, s * 0.16, color, segments=12)
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        draw.polyline([(x + dx * s * 0.55, cy + dy * s * 0.55), (x + dx * s * 0.8, cy + dy * s * 0.8)],
                      color, max(1.0, theme.px(1.2)))
    _caption(dc, x, cy - s * 0.8 - theme.px(5.0), "Pick", alpha)


def _paint_curve(dc, x, y, size, alpha):
    """Curve button icon: a falloff curve with anchors."""
    theme = dc.theme
    s = min(size * 0.6, theme.px(24.0))
    color = with_alpha((*TINT_CUSTOM, 1.0), alpha)
    x0, y0 = x - s * 0.5, y - s * 0.4
    pts = []
    for i in range(17):
        t = i / 16.0
        pts.append((x0 + s * t, y0 + s * 0.8 * (1.0 - t * t * (3.0 - 2.0 * t))))
    draw.polyline([(x0, y0), (x0 + s, y0)], with_alpha(theme.text_muted, alpha), 1.0)
    draw.polyline(pts, color, max(1.0, theme.px(2.0)))
    for i in (0, 8, 16):
        draw.circle(pts[i][0], pts[i][1], max(1.5, s * 0.08), with_alpha(theme.text, alpha), segments=12)


class _Swatch(_ColorDrag, RingSegment):
    """A history color along the circle (``color()``: RGB or None). Tap: ``use(rgb)``; drag source."""

    def __init__(self, bar, color, use, **kwargs):
        super().__init__(on_click=self._tap, **kwargs)
        self.bar = bar
        self.color = color
        self.use = use

    def drag_color(self):
        return _resolve(self.color, None)

    def _tap(self):
        rgb = _resolve(self.color, None)
        if rgb is not None:
            self.use(rgb)

    def draw_self(self, dc):
        theme = dc.theme
        inner, outer = self.points()
        if not inner:
            return
        rgb = _resolve(self.color, None)
        if rgb is None:
            draw.ring_segment(inner, outer, with_alpha(theme.surface, 0.5 * dc.alpha))
        else:
            draw.ring_segment(inner, outer, (rgb[0], rgb[1], rgb[2], dc.alpha), rim=theme.edge_for(rgb, dc.alpha))
        if self.hover_t > 0.5:
            draw.ring_segment_outline(inner, outer, with_alpha(theme.accent, dc.alpha), width=theme.px(1.0))


class _PaletteSlot(_ColorDrag, RingSegment):
    """Slot ``index`` of the palette band. Color view: the active palette's color
    ``index`` (tap: paint with it; empty: store the current color). Palette view
    (``actions.palette_view()``): the project's palette ``index`` as a little grid of
    its first colors, the active one outlined (tap: make it active, back to the color
    view; empty: a new palette). Drag source and drop target in both views."""

    def __init__(self, bar, index, **kwargs):
        super().__init__(on_click=self._tap, **kwargs)
        self.bar = bar
        self.index = index

    @property
    def view(self):
        try:
            return self.bar.actions.palette_view()
        except Exception:
            return False

    def color(self):
        colors = self.bar.actions.palette() or []
        return colors[self.index] if self.index < len(colors) else None

    def palette(self):
        return self.bar.actions.project_palette(self.index)

    def drag_payload(self):
        if self.view:
            pal = self.palette()
            return None if pal is None else ('palette', pal, ('project', self.index))
        rgb = self.color()
        return None if rgb is None else ('color', tuple(rgb), ('palette_color', self.index))

    def accepts(self, payload):
        return payload[0] == ('palette' if self.view else 'color')

    def accept_drop(self, payload, source):
        self.bar.drop_on_slot(self.index, payload)

    def _tap(self):
        a = self.bar.actions
        if self.view:
            a.select_palette(self.index)
            a.set_palette_view(False)
            return
        rgb = self.color()
        if rgb is not None:
            a.use_history_color(rgb)
        else:
            a.set_palette_slot(self.index, a.pen_rgb())

    def draw_self(self, dc):
        theme = dc.theme
        inner, outer = self.points()
        if not inner:
            return
        if self.view:
            self._draw_palette(dc, inner, outer)
        else:
            rgb = self.color()
            if rgb is None:
                draw.ring_segment(inner, outer, with_alpha(theme.surface, 0.5 * dc.alpha))
                draw.ring_segment_outline(inner, outer, with_alpha(theme.border, 0.8 * dc.alpha), width=1.0)
            else:
                draw.ring_segment(inner, outer, (rgb[0], rgb[1], rgb[2], dc.alpha), rim=theme.edge_for(rgb, dc.alpha))
        if self.hover_t > 0.5:
            draw.ring_segment_outline(inner, outer, with_alpha(theme.accent, dc.alpha), width=theme.px(1.0))

    def _draw_palette(self, dc, inner, outer):
        """2 x 3 grid of the palette's first colors inside the slot."""
        theme = dc.theme
        pal = self.palette()
        draw.ring_segment(inner, outer, with_alpha(theme.surface_dark if pal else theme.surface, 0.9 * dc.alpha))
        colors = [c for c in (pal or {}).get("colors", []) if c][:6]
        if colors:
            r0, r1 = self.pr0 + 1.0, self.pr1 - 1.0
            rm = (r0 + r1) * 0.5
            a0, a1 = self.angles
            b0 = a0 + (self.insets[0] + 1.0) / max(rm, 1.0)
            b1 = a1 - (self.insets[1] + 1.0) / max(rm, 1.0)
            for k, c in enumerate(colors):
                row, col = divmod(k, 3)
                ra, rb = (r0, rm - 0.5) if row == 0 else (rm + 0.5, r1)
                aa = b0 + (b1 - b0) * col / 3.0
                ab = b0 + (b1 - b0) * (col + 1) / 3.0
                draw.ring_segment(*ring_segment_points(self.cx, self.cy, ra, rb, aa, ab), (c[0], c[1], c[2], dc.alpha))
        if pal is not None and self.index == self.bar.actions.active_palette_index():
            draw.ring_segment_outline(inner, outer, with_alpha(theme.accent_light, dc.alpha), width=theme.px(2.0))
        elif pal is None:
            draw.ring_segment_outline(inner, outer, with_alpha(theme.border, 0.8 * dc.alpha), width=1.0)
        else:
            draw.ring_segment_outline(inner, outer, theme.edge_for((0.5, 0.5, 0.5), dc.alpha), width=1.0)


class _HintLabel(Label):
    """Label whose text comes from ``text_fn()``."""

    def __init__(self, text_fn, **kwargs):
        super().__init__("", **kwargs)
        self.text_fn = text_fn

    def measure(self, theme):
        self.text = str(_resolve(self.text_fn, ""))
        return super().measure(theme)


class _CornerButton(Widget):
    """Small round button in an element's corner: ``glyph`` 'CLOSE' (X) or 'LOCK'
    (padlock, closed while ``selected``). Its tap area is larger than the drawing (pens)."""

    interactive = True

    def __init__(self, glyph, *, radius=_CORNER_RADIUS, hit=_CORNER_HIT, **kwargs):
        super().__init__(**kwargs)
        self.glyph = glyph
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
        hot = self.hover_t > 0.5
        on = self.is_selected
        fill = theme.accent if on else (theme.surface_pressed if hot else theme.surface)
        draw.circle(cx, cy, r, with_alpha(fill, dc.alpha))
        draw.circle_outline(cx, cy, r, with_alpha(theme.accent if hot else theme.border, dc.alpha),
                            width=theme.px(1.0))
        color = with_alpha(theme.text, 0.9 * dc.alpha)
        width = max(1.0, theme.px(1.2))
        if self.glyph == 'CLOSE':
            arm = r * 0.5
            draw.polyline([(cx - arm, cy - arm), (cx + arm, cy + arm)], color, width)
            draw.polyline([(cx - arm, cy + arm), (cx + arm, cy - arm)], color, width)
            return
        # Padlock; the shackle opens (lifts, one leg free) while unlocked.
        bw, bh = r * 0.95, r * 0.7
        body = Rect.from_size(cx - bw * 0.5, cy - r * 0.6, bw, bh)
        draw.rect(body, color)
        lift = 0.0 if on else r * 0.25
        sr = bw * 0.32
        sx = cx if on else cx + sr * 0.5
        draw.arc(sx, body.y1 + lift + sr * 0.2, sr, 0.0, math.pi, color, width=width, segments=12)
        draw.polyline([(sx - sr, body.y1 + lift + sr * 0.2), (sx - sr, body.y1 + (lift if not on else 0.0))],
                      color, width)
        draw.polyline([(sx + sr, body.y1 + lift + sr * 0.2), (sx + sr, body.y1)], color, width)


class _ResizeHandle(Widget):
    """Triangle in an element's bottom-right corner; press and drag to resize.

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
        active = self.drag_origin is not None or self.hover_t > 0.5
        fill = theme.accent if active else theme.border
        draw.triangle((r.x1, r.y0), (r.x0, r.y0), (r.x1, r.y1), with_alpha(fill, dc.alpha))


class _MovePanel(Panel):
    """Panel whose empty background moves its element when dragged (unless ``locked``)."""

    interactive = True

    def __init__(self, content, *, locked, on_move_begin, on_move, on_move_end, **kwargs):
        super().__init__(content, **kwargs)
        self.locked = locked
        self.on_move_begin = on_move_begin
        self.on_move = on_move
        self.on_move_end = on_move_end
        self.drag_origin = None

    @property
    def draggable(self):
        return not _resolve(self.locked, False)

    def drag_begin(self, x, y):
        self.drag_origin = (x, y)
        self.on_move_begin()

    def drag_update(self, x, y):
        if self.drag_origin is not None:
            self.on_move(x - self.drag_origin[0], y - self.drag_origin[1])

    def drag_end(self, x, y, cancelled=False):
        self.drag_origin = None
        self.on_move_end(cancelled)


class _Window(Widget):
    """A floating element: a movable panel with a lock (top left, or bottom left with
    ``lock_bottom``), an optional X (top right) and a resize triangle (bottom right,
    hidden while locked). ``tab`` (optional) replaces it while ``collapsed``. Placed
    by its top-left corner."""

    def __init__(self, panel, lock, grip, *, locked, close=None, tab=None, lock_bottom=False):
        super().__init__()
        self.lock_bottom = lock_bottom
        self.panel = self.add(panel)
        self.tab = self.add(tab) if tab is not None else None
        self.lock = self.add(lock)
        self.close = self.add(close) if close is not None else None
        self.grip = self.add(grip)      # last: picked before the panel under it
        self.locked = locked
        self.collapsed = False
        self.grip_size = 0.0            # screen px, set by the PenBar

    @property
    def shown(self):
        return self.tab if (self.collapsed and self.tab is not None) else self.panel

    def measure(self, theme):
        return self.shown.measure(theme)

    def place(self, origin, theme):
        """``origin`` = (x0, y1): the top-left corner."""
        x0, y1 = origin
        shown = self.shown
        w, h = shown.measure(theme)
        shown.arrange(Rect.from_size(x0, y1 - h, w, h), theme)
        self.rect = shown.rect
        expanded = shown is self.panel
        self.panel.visible = expanded
        if self.tab is not None:
            self.tab.visible = not expanded
        for corner in (self.lock, self.close):
            if corner is not None:
                corner.visible = expanded
        self.grip.visible = expanded and not _resolve(self.locked, False)
        if not expanded:
            return
        r = self.panel.rect
        inset = theme.px(_CORNER_INSET)
        lw, lh = self.lock.measure(theme)
        ly = r.y0 + inset if self.lock_bottom else r.y1 - inset - lh
        self.lock.arrange(Rect.from_size(r.x0 + inset, ly, lw, lh), theme)
        if self.close is not None:
            cw, ch = self.close.measure(theme)
            self.close.arrange(Rect.from_size(r.x1 - inset - cw, r.y1 - inset - ch, cw, ch), theme)
        g = self.grip_size
        self.grip.arrange(Rect.from_size(r.x1 - g, r.y0, g, g), theme)


class _MenuLayer(Widget):
    """Root of the pen menu's layer: the menu window and its flyouts (beside it, toward the canvas)."""

    def __init__(self, window, flyouts, dialog=None):
        super().__init__()
        self.window = self.add(window)
        self.flyouts = [self.add(flyout) for flyout in flyouts]
        self.dialog = self.add(dialog) if dialog is not None else None   # last: drawn / picked on top
        self.openers = {}          # flyout -> the widget that opened it
        self.region = (0.0, 0.0)

    def measure(self, theme):
        return self.window.measure(theme)

    def place(self, origin, theme):
        self.window.place(origin, theme)
        self.rect = win = self.window.rect
        gap = theme.px(FLYOUT_GAP)
        margin = theme.px(theme.region_margin)
        width, height = self.region
        for flyout in self.flyouts:
            if not flyout.visible:
                continue
            fw, fh = flyout.measure(theme)
            opener = self.openers.get(flyout)
            fy = opener.rect.cy if opener is not None else win.cy
            right = win.cx < width * 0.5
            fx = win.x1 + gap if right else win.x0 - gap - fw
            fx, y0 = clamp_box(fx, fy - fh * 0.5, fw, fh, (margin, margin, width - margin, height - margin))
            flyout.arrange(Rect.from_size(fx, y0, fw, fh), theme)
        if self.dialog is not None and self.dialog.visible:   # centered over the menu
            dw, dh = self.dialog.measure(theme)
            dx, dy = clamp_box(win.cx - dw * 0.5, win.cy - dh * 0.5, dw, dh,
                               (margin, margin, width - margin, height - margin))
            self.dialog.arrange(Rect.from_size(dx, dy, dw, dh), theme)


def _is_inside(widget, ancestor):
    while widget is not None:
        if widget is ancestor:
            return True
        widget = widget.parent
    return False


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



class PenBar:
    """Widget layers of the pen menu and the color selector.
    ``actions`` is the :class:`tools.pen_bar.PenBarTool`."""

    def __init__(self, actions):
        from .icons import ICONS  # late import: ui.icons imports the tool catalog
        self.actions = actions
        self.icons = ICONS
        self.flyout = None          # open flyout panel
        self.flyout_opener = None
        self._drag = None           # (channel, value at drag start) while a knob / slider is dragged
        self._move = None           # (element, stored pos, top-left, size) while an element is moved
        self._resize = None         # (element, scale, width, height, top-left, stored pos) while resized
        self._args = None           # the last layout() arguments
        self.drag_preview = None    # (rgb, x, y, source) while a color is dragged
        self.bounds = (0.0, 0.0, 0.0, 0.0)
        self.knobs = {}
        self.arm_buttons = {}

        # Pen menu.
        self.blend_flyout = self._build_blend_flyout()
        self.blend_flyout.visible = False
        self.curve_mode = 'MOVE'
        self.curve_flyout = self._build_curve_flyout()
        self.curve_flyout.visible = False
        from .pen_settings import SettingsMenu  # late import: it imports this module
        self.settings_menu = SettingsMenu(self)
        self.settings_flyout = self.settings_menu.panel
        self.settings_flyout.visible = False
        from .pen_palettes import ConfirmDialog, PaletteLibrary  # late import: they import this module
        self.library_menu = PaletteLibrary(self)
        self.library_flyout = self.library_menu.panel
        self.library_flyout.visible = False
        self.confirm_dialog = ConfirmDialog(self)
        tab = RoundButton("Pen", radius=17.0, key='PEN_TAB', on_click=lambda: self.set_collapsed(False))
        self.menu = self._window('bar', self._build_dial(),
                                 _CornerButton('CLOSE', key='HIDE', on_click=lambda: self.set_collapsed(True)),
                                 tab=tab, lock_bottom=True)   # top left: the Mix color field
        self.root = _MenuLayer(self.menu, [self.blend_flyout, self.curve_flyout, self.settings_flyout,
                                           self.library_flyout], self.confirm_dialog.panel)
        self.overlay = Overlay(self.root, modal=False, animate=False)

        # Color selector.
        a = actions
        self.color_pad = ColorSelector(a.pen_hsv, a.set_pen_hsv, original=a.original_hsv,
                                       live=a.color_preview, layout=a.color_layout,
                                       model=a.color_model, sliders=a.color_sliders, key='COLOR_PAD')
        self.color_bubble = _BubbleDrag(self, a.preview_colors, True, a.has_color_change, radius=12.0,
                                        on_click=a.accept_color_change, key='COLOR_BUBBLE')
        content = Column([Row([self.color_bubble]), self.color_pad], gap=6.0)
        self.color_window = self._window('color', content,
                                         _CornerButton('CLOSE', key='COLOR_CLOSE', on_click=a.toggle_color_panel))
        self.color_overlay = Overlay(self.color_window, modal=False, animate=False)
        self.windows = {'bar': (self.menu, self.overlay), 'color': (self.color_window, self.color_overlay)}

    # ---- building ------------------------------------------------------------------

    def _window(self, name, content, close, tab=None, lock_bottom=False):
        locked = lambda: self._locked(name)
        panel = _MovePanel(content, padding=_PANEL_PADDING, key=f"{name.upper()}_PANEL", locked=locked,
                           on_move_begin=lambda: self._begin_move(name), on_move=self._move_to,
                           on_move_end=self._end_move)
        lock = _CornerButton('LOCK', key=f"{name.upper()}_LOCK", selected=locked,
                             on_click=lambda: self._toggle_lock(name))
        grip = _ResizeHandle(lambda: self._begin_resize(name), self._resize_to, self._end_resize,
                             key=f"{name.upper()}_RESIZE")
        return _Window(panel, lock, grip, locked=locked, close=close, tab=tab, lock_bottom=lock_bottom)

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
        # Falloff presets: the outer ring, then a band along the circle in the corner
        # (both from the bottom up); Custom in its own color.
        def falloff_button(preset):
            return RingSegment(preset.label, key=f"FALLOFF_{preset.id}", icon=preset.icon_key, icons=self.icons,
                               font_size=8.0, selected=lambda p=preset.id: a.active_falloff() == p,
                               on_click=lambda p=preset.id: a.set_falloff(p))
        ring = [falloff_button(falloff.get(i)) for i in FALLOFF_RING_ORDER]
        band = [falloff_button(falloff.get(i)) for i in FALLOFF_BAND_ORDER]
        self.falloff_buttons = ring + band
        custom = self.falloff_buttons[(FALLOFF_RING_ORDER + FALLOFF_BAND_ORDER).index('CUSTOM')]
        custom.tint, custom.tint_amount = TINT_CUSTOM, CUSTOM_TINT_AMOUNT
        dial.add_arc(ring, *OUTER_RING, *HISTORY_ARC, tint=TINT_FALLOFF)
        dial.add_band(band, CORNER_INNER, CORNER_INNER + FALLOFF_BAND_DEPTH, *HISTORY_ARC, tint=TINT_FALLOFF)
        self._add_corners(dial)
        return dial

    def _add_corners(self, dial):
        """Top left the color section: the color history band, secondary's Picker /
        secondary / Swap + Mix / primary / primary's Picker; bottom left the palette and its
        buttons; bottom right, past the second falloff row, Curve and Settings."""
        a = self.actions
        corner = dict(chamfer=CORNER_CHAMFER)

        # Color history along the circle, newest at the left end (next to the primary color).
        swatches = [_Swatch(self, lambda i=i: self._history(i), a.use_history_color, key=f"HISTORY_{i}")
                    for i in range(color_history.HISTORY_SIZE)]
        dial.add_band(reversed(swatches), CORNER_INNER, CORNER_INNER + HISTORY_DEPTH, *COLORS_ARC)
        primary_active = lambda: not a.rmb_lock()
        primary = _ColorCorner(self, 'PRIMARY', lambda: a.colors()[0], primary_active, key='PRIMARY',
                               on_click=lambda: a.set_rmb_lock(False))
        secondary = _ColorCorner(self, 'SECONDARY', lambda: a.colors()[1], a.rmb_lock, key='SECONDARY',
                                 on_click=lambda: a.set_rmb_lock(True))

        def picker(which, rgb, active):
            kind = f'EYEDROPPER_{which}'
            return CornerSegment(f"Pick {which.title()}", key=f'PICKER_{which}',
                                 painter=_paint_target_picker(rgb, active),
                                 selected=lambda: a.armed() == kind, on_click=lambda: a.toggle_arm(kind))
        pick_primary = picker('PRIMARY', lambda: a.colors()[0], primary_active)
        pick_secondary = picker('SECONDARY', lambda: a.colors()[1], a.rmb_lock)
        self.arm_buttons = {'EYEDROPPER_PRIMARY': pick_primary, 'EYEDROPPER_SECONDARY': pick_secondary}
        mix = _MixCorner(self, a.mix_color, key='MIX', on_click=a.use_mix_color)
        dial.add_corner([pick_secondary, secondary, mix, primary, pick_primary], COLOR_CORNER_INNER, SQUARE_HALF,
                        *COLORS_ARC, weights=COLORS_WEIGHTS, chamfer=0.0)
        # Swap by the circle in the middle; the Mix field behind it, out to the corner.
        swap_outer = COLOR_CORNER_INNER + SWAP_DEPTH
        swap = RingSegment("Swap", key='SWAP', painter=_paint_swap, on_click=a.swap_colors)
        dial.add_band([swap], COLOR_CORNER_INNER, swap_outer, mix.a0, mix.a1)
        swap.edge_extra = (0.0, 0.0)      # side edges in line with the Mix field's
        mix.r0 = swap_outer + DIAL_GAP

        from .pen_palettes import paint_library, paint_palettes
        palettes = CornerSegment("Palettes", key='PALETTES', painter=paint_palettes, selected=a.palette_view,
                                 on_click=lambda: a.set_palette_view(not a.palette_view()))
        color = CornerSegment("Color", key='COLOR', painter=_paint_color_wheel(a.pen_rgb),
                              selected=a.color_panel_open, on_click=a.toggle_color_panel)
        library = CornerSegment("Library", key='LIBRARY', painter=paint_library,
                                selected=lambda: self.flyout is self.library_flyout,
                                on_click=lambda: self.open_library(library))
        dial.add_corner([palettes, color, library], WHEEL_CORNER_INNER, SQUARE_HALF, *PALETTE_BUTTON_ARC,
                        weights=PALETTE_BUTTON_WEIGHTS, **corner)

        # Palette band in front of them: the active palette's colors, or (palette view) the
        # project's palettes. Slot 0 at the left.
        palette = [_PaletteSlot(self, i, key=f"PALETTE_{i}") for i in range(color_palette.PALETTE_SIZE)]
        per_row = (len(palette) + PALETTE_ROWS - 1) // PALETTE_ROWS
        for row in range(PALETTE_ROWS):
            r0 = CORNER_INNER + row * (HISTORY_DEPTH + DIAL_GAP)
            dial.add_band(palette[row * per_row:(row + 1) * per_row], r0, r0 + HISTORY_DEPTH, *COLOR_WHEEL_ARC)

        # Past the second falloff row, around the diagonal: the curve button (behind
        # the Custom falloff) and Settings.
        curve = CornerSegment("Curve", key='CURVE', painter=_paint_curve,
                              tint=TINT_CUSTOM, tint_amount=CUSTOM_TINT_AMOUNT,
                              selected=lambda: self.flyout is self.curve_flyout,
                              on_click=lambda: self._open_curve(curve))
        settings = CornerSegment("Settings", key='SETTINGS', painter=_paint_gear,
                                 selected=lambda: self.flyout is self.settings_flyout,
                                 on_click=lambda: self.toggle_flyout(self.settings_flyout, settings))
        dial.add_corner([curve, settings], FALLOFF_CORNER_INNER, SQUARE_HALF, *CURVE_SETTINGS_ARC, **corner)

        # Top right, past the S / A / M sliders: a small Save at the right side, then the
        # paint mask (Source | Mask | Invert | Pick) up to the top edge.
        save = CornerSegment("Save", key='SAVE_IMAGE', painter=_paint_save(a.image_unsaved, caption=False),
                             tint=TINT_SAVE, on_click=a.save_image)
        dial.add_corner([save], CORNER_INNER, SQUARE_HALF, *SAVE_ARC, **corner)
        mask_buttons = [
            CornerSegment("Mask Source", key='MASK_SOURCE', painter=_paint_mask_source(a.mask_source),
                          on_click=a.toggle_mask_source),
            CornerSegment("Mask", key='MASK', painter=_paint_mask, selected=a.mask_enabled,
                          on_click=a.toggle_mask),
            CornerSegment("Invert Mask", key='MASK_INVERT', painter=_paint_mask_invert,
                          selected=a.mask_inverted, on_click=a.toggle_mask_invert),
            CornerSegment("Pick Mask", key='MASK_PICK', painter=_paint_mask_pick,
                          selected=a.mask_picking, on_click=a.toggle_mask_pick),
        ]
        self.mask_pick_button = mask_buttons[-1]
        dial.add_corner(mask_buttons, CORNER_INNER, SQUARE_HALF, *MASK_ARC,
                        weights=MASK_WEIGHTS, tint=TINT_MASK, **corner)

    def open_library(self, opener):
        """The library flyout; the palette band switches to its palette view (drag targets)."""
        if self.flyout is not self.library_flyout:
            self.library_menu.opened()
            self.actions.set_palette_view(True)
        self.toggle_flyout(self.library_flyout, opener)

    def confirm(self, lines, action, label="Delete"):
        """Ask before ``action`` (deleting / replacing a palette): dialog over the menu."""
        self.confirm_dialog.open(lines, action, label)
        self.overlay.layout()

    def drop_on_slot(self, index, payload):
        """A payload dropped on palette slot ``index``."""
        a = self.actions
        kind, value, origin = payload
        origin = origin or ('', None)
        if kind == 'color':
            if origin[0] == 'palette_color':
                a.swap_palette_slots(origin[1], index)
            else:
                a.set_palette_slot(index, value)
            return
        if origin[0] == 'project':
            if origin[1] != index:
                a.swap_project_palettes(origin[1], index)
            return
        current = a.project_palette(index)          # from the library: load a copy
        if current is None or color_palette.is_empty(current):
            a.set_project_palette(index, value)
        else:
            self.confirm([f"Replace “{current['name']}”", f"with “{value['name']}”?"],
                         lambda: a.set_project_palette(index, value), "Replace")

    def drop(self, payload, x, y, source):
        """End of a drag at ``(x, y)``: the widget there (or an ancestor) takes it. Off the
        menu: a palette color is removed, a project palette deleted after a confirmation."""
        target = self._drop_target(x, y, source, payload)
        if target is not None:
            target.accept_drop(payload, source)
            return
        if not self._removes(x, y, payload):
            return
        kind, value, (place, index) = payload
        if place == 'palette_color':
            self.actions.set_palette_slot(index, None)
        else:
            self.confirm([f"Delete the palette “{value['name']}”", "from this project?"],
                         lambda: self.actions.set_project_palette(index, None), "Delete")

    def _removes(self, x, y, payload):
        """Released off the menu and the color selector: removes palette colors / project palettes."""
        origin = payload[2] or ('', None)
        return (origin[0] in ('palette_color', 'project') and self.root.pick(x, y) is None
                and not self._over_color_window(x, y))

    def _over_color_window(self, x, y):
        return self.color_window.visible and self.color_window.pick(x, y) is not None

    def _drop_target(self, x, y, source, payload):
        """The widget under ``(x, y)`` -- or its nearest ancestor -- that accepts ``payload``."""
        widget = self.root.pick(x, y)
        while widget is not None:
            if widget is not source and hasattr(widget, 'accept_drop') and widget.accepts(payload):
                return widget
            widget = widget.parent
        return None

    def _history(self, index):
        colors = self.actions.color_history()
        return colors[index] if index < len(colors) else None

    def _open_curve(self, opener):
        if self.flyout is not self.curve_flyout:
            self.actions.use_custom_falloff()
        self.toggle_flyout(self.curve_flyout, opener)

    def _build_curve_flyout(self):
        """Custom falloff curve: the editor, Move / Add / Draw modes and Reset."""
        a = self.actions
        self.curve_editor = CurveEditor(a.custom_curve_points, a.set_custom_curve_points,
                                        sample=a.custom_curve_sampler, mode=lambda: self.curve_mode,
                                        size=CURVE_EDITOR_SIZE, curve_color=(*TINT_CUSTOM, 1.0),
                                        key='CURVE_EDITOR')

        def mode_button(mode, label):
            return Button(label, key=f"CURVE_{mode}", size=(52.0, 26.0),
                          selected=lambda: self.curve_mode == mode,
                          on_click=lambda: setattr(self, 'curve_mode', mode))

        buttons = [mode_button(mode, label) for mode, label in CURVE_MODES]
        buttons.append(Button("Reset", key='CURVE_RESET', size=(52.0, 26.0), on_click=a.reset_custom_curve))
        hint = _HintLabel(lambda: CURVE_HINTS.get(self.curve_mode, ""), size=9.0)
        return Panel(Column([self.curve_editor, Row(buttons, gap=4.0), hint], gap=6.0),
                     title="Custom Falloff", padding=8.0)

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

    def _get(self, key, default=None):
        try:
            value = self.actions.get_state(key)
        except Exception:
            return default
        return default if value is None else value

    def _locked(self, name):
        return bool(self._get(f'pen_{name}_locked', False))

    def _toggle_lock(self, name):
        self.actions.set_state(f'pen_{name}_locked', not self._locked(name))
        self._relayout()   # shows / hides the resize triangle

    def _scale(self, name):
        try:
            return clamp_scale(name, float(self._get(f'pen_{name}_scale', 1.0)))
        except (TypeError, ValueError):
            return 1.0

    def _theme(self, name):
        """The element's theme; shrunk (not stored) while the editor is too small for it."""
        base = self._args[-1]
        theme = base.scaled(base.scale * BAR_SCALE * self._scale(name))
        if name == 'color':
            self.color_pad.fit_width = theme.px(COLOR_WIDTH)
        w, h = self.windows[name][0].measure(theme)
        bx0, by0, bx1, by1 = self.bounds
        fit = min(1.0, (bx1 - bx0) / max(1.0, w), (by1 - by0) / max(1.0, h))
        if fit < 1.0:
            theme = theme.scaled(theme.scale * fit)
            if name == 'color':
                self.color_pad.fit_width = theme.px(COLOR_WIDTH)
        return theme

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
        self._relayout()

    def _sync_visibility(self):
        collapsed = bool(self.actions.collapsed())
        self.menu.collapsed = collapsed
        self.color_window.visible = bool(self.actions.color_panel_open()) and not collapsed
        if collapsed and self.flyout is not None:
            self.close_flyout(relayout=False)

    def busy(self):
        """A flyout or the confirmation is open, or something is dragged."""
        return (self.flyout is not None or self.confirm_dialog.is_open
                or any(ov.dragging is not None for _w, ov in self.windows.values()))

    def reset(self):
        """End drags, close flyouts, forget hover (session end / bar hidden)."""
        self.end_drag()
        self.confirm_dialog.close()
        self.close_flyout()
        for _window, overlay in self.windows.values():
            overlay.hot = None
            overlay.pressed = None
            overlay.pointer_widget = None

    def end_drag(self):
        """The host lost the pointer: keep the dragged value (a carried color is dropped nowhere)."""
        self.drag_preview = None
        for _window, overlay in self.windows.values():
            if overlay.dragging is not None:
                overlay.end_drag()

    # ---- knob / slider drags -----------------------------------------------------------

    def _begin_drag(self, channel):
        self._drag = (channel, self._value(channel))

    def _drag_to(self, dx, dy):
        if self._drag is None:
            return
        channel, start = self._drag
        value = start + int(round(dy / self.overlay.theme.px(SIZE_STEP_PX)))
        self.actions.set_value(channel, value)

    def _end_drag(self, cancelled):
        if cancelled and self._drag is not None:
            self.actions.set_value(*self._drag)  # restore the value from before the drag
        self._drag = None

    # ---- moving / resizing elements ------------------------------------------------------

    def _clamp(self, x0, y1, width, height):
        """Top-left of an element kept inside the editor (see ``bounds``)."""
        x0, y0 = clamp_box(x0, y1 - height, width, height, self.bounds)
        return x0, y0 + height

    def _begin_move(self, name):
        r = self.windows[name][0].rect
        self._move = (name, self._get(f'pen_{name}_pos'), (r.x0, r.y1), (r.width, r.height))

    def _move_to(self, dx, dy):
        if self._move is None:
            return
        name, _stored, (x0, y1), (w, h) = self._move
        self.actions.set_state(f'pen_{name}_pos', self._clamp(x0 + dx, y1 + dy, w, h))
        self._relayout()

    def _end_move(self, cancelled):
        if cancelled and self._move is not None:
            name, stored = self._move[0], self._move[1]
            self.actions.set_state(f'pen_{name}_pos', stored)
        self._move = None
        self._relayout()

    def _begin_resize(self, name):
        r = self.windows[name][0].panel.rect
        self._resize = (name, self._scale(name), r.width, r.height, (r.x0, r.y1), self._get(f'pen_{name}_pos'))

    def _resize_to(self, dx, dy):
        """Scale so the bottom-right corner follows the pen; the top-left corner stays.
        Limited to the element's size range and to the room left in the editor."""
        if self._resize is None:
            return
        name, scale, w, h, (x0, y1), _stored = self._resize
        factor = 1.0 + (dx * w - dy * h) / max(1.0, w * w + h * h)
        bx0, by0, bx1, by1 = self.bounds
        factor = min(factor, (bx1 - x0) / max(1.0, w), (y1 - by0) / max(1.0, h))
        self.actions.set_state(f'pen_{name}_scale', clamp_scale(name, scale * factor))
        self.actions.set_state(f'pen_{name}_pos', (x0, y1))
        self._relayout()

    def _end_resize(self, cancelled):
        if cancelled and self._resize is not None:
            name, scale, _w, _h, _tl, stored = self._resize
            self.actions.set_state(f'pen_{name}_scale', scale)
            self.actions.set_state(f'pen_{name}_pos', stored)
        self._resize = None
        self._relayout()

    # ---- layout / events -----------------------------------------------------------------

    def _relayout(self):
        if self._args is not None:
            self.layout(*self._args)

    def layout(self, region_width, region_height, side, inset_left, inset_right, theme):
        """Place the elements: where they were left (clipped to the editor), else the
        menu in the bottom corner at the ``side`` edge ('LEFT' / 'RIGHT') and the color
        selector beside it. ``inset_left`` / ``inset_right``: width of overlapping
        regions to keep clear of (the sidebar; the toolbar is ignored)."""
        self._args = (region_width, region_height, side, inset_left, inset_right, theme)
        margin = theme.px(WINDOW_MARGIN)
        self.bounds = (inset_left + margin, margin, region_width - inset_right - margin, region_height - margin)
        self._sync_visibility()
        self.root.region = (region_width, region_height)

        menu_theme = self._theme('bar')
        self.overlay.theme = menu_theme
        self.menu.grip_size = theme.px(_HANDLE_SIZE)
        w, h = self.menu.measure(menu_theme)
        pos = self._get('pen_bar_pos')
        if pos is None:
            gap = menu_theme.px(max(0.0, EDGE_GAP - _PANEL_PADDING))
            x0 = inset_left + gap if side == 'LEFT' else region_width - inset_right - gap - w
            pos = (x0, gap + h)
        self.overlay.origin = self._clamp(pos[0], pos[1], w, h)
        self.overlay.layout()

        if not self.color_window.visible:
            return
        color_theme = self._theme('color')
        self.color_overlay.theme = color_theme
        self.color_window.grip_size = theme.px(_HANDLE_SIZE)
        cw, ch = self.color_window.measure(color_theme)
        pos = self._get('pen_color_pos')
        if pos is None:   # beside the menu, toward the canvas, bottoms level
            menu = self.menu.rect
            gap = theme.px(FLYOUT_GAP)
            x0 = menu.x1 + gap if menu.cx < region_width * 0.5 else menu.x0 - gap - cw
            pos = (x0, menu.y0 + ch)
        self.color_overlay.origin = self._clamp(pos[0], pos[1], cw, ch)
        self.color_overlay.layout()

    def _stack(self):
        """Overlays, top-most first: the menu while its flyout is open, else the color selector."""
        if self.flyout is not None or self.confirm_dialog.is_open:
            return [self.overlay, self.color_overlay]
        return [self.color_overlay, self.overlay]

    def handle(self, event):
        """Forward a :class:`~.kit.UIEvent` (region coords); True when an element used it."""
        stack = [ov for ov in self._stack() if ov.root.visible]
        for overlay in stack:
            if overlay.dragging is not None:
                return overlay.handle(event) == RUNNING
        if self.confirm_dialog.is_open:
            # Modal: only the dialog reacts; a press elsewhere, ESC or right click cancel.
            if event.value == PRESS and event.type in {'ESC', 'RIGHTMOUSE'}:
                self.confirm_dialog.close()
                self.overlay.layout()
                return True
            if event.value == PRESS and event.type == 'LEFTMOUSE':
                hit = self.root.pick(event.x, event.y)
                if not _is_inside(hit, self.confirm_dialog.panel):
                    self.confirm_dialog.close()
                    self.overlay.layout()
                    return True
            self.overlay.handle(event)
            return event.type in {'LEFTMOUSE', 'RIGHTMOUSE', 'ESC', 'MOUSEMOVE'}
        if self.flyout is not None and event.value == PRESS:
            if event.type in {'ESC', 'RIGHTMOUSE'}:
                self.close_flyout()
                return True
            if event.type == 'LEFTMOUSE':
                hit = self.root.pick(event.x, event.y)
                if hit is None:
                    self.close_flyout()
                    return True  # a tap outside only closes the flyout
                in_menu = _is_inside(hit, self.menu)
                if getattr(self.flyout, 'stays_open', False) and in_menu:
                    pass   # e.g. the library: the menu's palette band is used together with it
                elif not _is_inside(hit, self.flyout) and hit is not self.flyout_opener:
                    self.close_flyout()
        for overlay in stack:
            if overlay.handle(event) == RUNNING:
                return True
        return False

    # ---- drawing -----------------------------------------------------------------------

    def draw(self):
        for overlay in reversed(self._stack()):
            if overlay.root.visible:
                overlay.draw()
        with draw.blend_mode('ALPHA'):
            self._draw_drag_readout()
            self._draw_arm_hint()
            self._draw_color_drag()

    def _beside(self, rect, width):
        """x0 of a box ``width`` wide beside ``rect``, toward the middle of the editor."""
        gap = self.overlay.theme.px(FLYOUT_GAP)
        region_width = self._args[0] if self._args else 0.0
        return rect.x1 + gap if rect.cx < region_width * 0.5 else rect.x0 - gap - width

    def _pill(self, text, rect, cy, font_size, border):
        """Readout box beside ``rect`` (toward the editor's middle), centered at ``cy``."""
        theme = self.overlay.theme
        size = theme.px(font_size)
        tw, _th = draw.text_size(text, size, theme.font_id)
        pad = theme.px(8.0)
        w, h = tw + pad * 2.0, size + pad * 2.0
        box = Rect.from_size(self._beside(rect, w), cy - h * 0.5, w, h)
        draw.rect(box, theme.surface_dark)
        draw.rect_outline(box, border, width=theme.px(1.0))
        draw.text_centered(text, box.cx, box.cy, size, theme.text, theme.font_id)
        return box

    def _draw_drag_readout(self):
        theme = self.overlay.theme
        if self._resize is not None:
            name = self._resize[0]
            window = self.windows[name][0]
            self._pill(f"Scale  {self._scale(name) * 100:.0f}%", window.rect, window.grip.rect.cy, 14.0,
                       theme.accent)
            return
        if self._drag is None:
            return
        channel = self._drag[0]
        knob = self.knobs.get(channel)
        if knob is None:
            return
        value = self._value(channel)
        if channel == 'size':
            text = f"{CHANNEL_LABELS[channel]}  {value}"
        else:
            text = f"{CHANNEL_LABELS[channel]}  {value * 100:.0f}%"
        box = self._pill(text, self.menu.rect, knob.rect.cy, 16.0, theme.accent)
        if channel == 'size':
            self._draw_size_preview(box, value)

    def _draw_size_preview(self, box, radius):
        """The brush footprint at the current zoom, next to the readout (away from the menu)."""
        theme = self.overlay.theme
        texel = self.actions.texel_screen_px()
        if not texel:
            return
        half = min((2 * radius + 1) * texel * 0.5, 600.0)
        gap = theme.px(FLYOUT_GAP)
        cx = box.x1 + gap + half if box.cx > self.menu.rect.cx else box.x0 - gap - half
        cy = box.cy
        if self.actions.brush_shape() == 'SQUARE':
            rect = Rect.from_center(cx, cy, half * 2.0, half * 2.0)
            draw.rect_outline(rect, (0.0, 0.0, 0.0, 0.8), width=theme.px(3.0))
            draw.rect_outline(rect, (1.0, 1.0, 1.0, 0.95), width=theme.px(1.5))
        else:
            draw.circle_outline(cx, cy, half, (0.0, 0.0, 0.0, 0.8), width=theme.px(3.0))
            draw.circle_outline(cx, cy, half, (1.0, 1.0, 1.0, 0.95), width=theme.px(1.5))

    def _draw_color_drag(self):
        """The carried color / palette under the pen; the target it would land in is
        outlined; something about to be removed (off the menu) is crossed out."""
        if self.drag_preview is None:
            return
        payload, x, y, source = self.drag_preview
        theme = self.overlay.theme
        target = self._drop_target(x, y, source, payload)
        if target is not None:
            inner, outer = target.points() if hasattr(target, 'points') else ([], [])
            if inner:
                draw.ring_segment_outline(inner, outer, theme.accent_light, width=theme.px(2.5))
            else:
                draw.rect_outline(target.rect, theme.accent_light, width=theme.px(2.5))
        if payload[0] == 'palette':
            w, h = theme.px(96.0), theme.px(18.0)
            box = Rect.from_center(x, y + h * 1.6, w, h)
            from .pen_palettes import draw_palette_cells
            draw_palette_cells(box, payload[1], 1.0, theme)
            draw.rect_outline(box, theme.text, width=theme.px(1.5))
            cx, cy, r = box.cx, box.cy, h * 0.5
        else:
            rgb = payload[1]
            r = theme.px(13.0)
            cx, cy = x, y + r * 1.6      # above the pen tip, so it stays visible
            draw.circle(cx, cy, r, (rgb[0], rgb[1], rgb[2], 1.0), rim=theme.edge_for(rgb))
            draw.circle_outline(cx, cy, r + theme.px(1.0), theme.text, width=theme.px(1.5))
        if target is None and self._removes(x, y, payload):
            arm = r * 0.55
            red = (0.95, 0.25, 0.25, 1.0)
            draw.polyline([(cx - arm, cy - arm), (cx + arm, cy + arm)], red, theme.px(2.5))
            draw.polyline([(cx - arm, cy + arm), (cx + arm, cy - arm)], red, theme.px(2.5))

    def _draw_arm_hint(self):
        if self.actions.mask_picking() and not self.menu.collapsed:
            self._pill(MASK_PICK_HINT, self.menu.rect, self.mask_pick_button.rect.cy, 12.0, (*TINT_MASK, 1.0))
            return
        kind = self.actions.armed()
        button = self.arm_buttons.get(kind)
        if button is None or self.menu.collapsed:
            return
        self._pill(ARM_HINTS[kind], self.menu.rect, button.rect.cy, 12.0, self.overlay.theme.accent_light)
