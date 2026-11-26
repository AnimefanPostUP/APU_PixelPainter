"""The pen menu's color widgets: drag & drop of colors / palettes (:class:`ColorDrag`),
the primary / secondary corner buttons, the tertiary bubble, the gradient slider, the
old / new bubble, the color history swatches and the palette slots.
"""

import math

from ..kit import ColorBubble, CornerSegment, RingSegment
from ..kit import draw
from ..kit.geometry import best_circle, ring_segment_points
from ..kit.theme import with_alpha
from ..kit.widget import _resolve
from .metrics import DRAG_THRESHOLD, GRADIENT_MARKER, MIX_BUBBLE_MARGIN


class ColorDrag:
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


class ColorCorner(ColorDrag, CornerSegment):
    """The primary or secondary color (``which``) as a corner segment; the active one
    (the color the pen paints) is ringed, with a dotted ring while the tertiary color is
    selected and the color selector edits this one. Drag source and drop target."""

    def __init__(self, bar, which, rgb, role, **kwargs):
        super().__init__(**kwargs)
        self.bar = bar
        self.which = which      # 'PRIMARY' / 'SECONDARY'
        self.rgb = rgb          # () -> (r, g, b)
        self.role = role        # () -> 'ACTIVE' / 'TARGET' / None

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
        role = _resolve(self.role, None)
        if role == 'ACTIVE':
            draw.ring_segment_outline(inner, outer, with_alpha(theme.accent_light, dc.alpha), width=theme.px(2.5))
        elif role == 'TARGET':
            draw.ring_segment_dashed_outline(inner, outer, with_alpha(theme.accent_light, dc.alpha),
                                             width=theme.px(2.0), dash=theme.px(3.0), gap=theme.px(3.0))
        elif self.hover_t > 0.5:
            draw.ring_segment_outline(inner, outer, with_alpha(theme.accent, dc.alpha), width=theme.px(1.0))


class TertiaryBubble(ColorDrag, CornerSegment):
    """The tertiary color (picked on the gradient slider) as a bubble: the largest
    circle that fits its corner slot (on the slot's middle ray), ringed while selected.
    Tap: select it / back to the color before; drag source, not a drop target (it
    follows the two colors)."""

    def __init__(self, bar, rgb, active, **kwargs):
        super().__init__(**kwargs)
        self.bar = bar
        self.rgb = rgb          # () -> (r, g, b)
        self.active = active    # () -> bool: the tertiary color is selected
        self._bubble = (0.0, 0.0, 0.0)   # screen cx, cy, radius
        self._hit = 0.0

    def place_on(self, cx, cy, theme, gap):
        super().place_on(cx, cy, theme, gap)
        (x, y), room = best_circle(self.pr0, self.pr1, *self.angles, *self.insets, theme.px(self.chamfer))
        self._bubble = (cx + x, cy + y, max(0.0, room - theme.px(MIX_BUBBLE_MARGIN)))
        self._hit = room
        self._center = (cx + x, cy + y)

    def contains(self, x, y):
        bx, by, _r = self._bubble
        return self._hit > 0.0 and math.hypot(x - bx, y - by) <= self._hit

    def drag_color(self):
        return _resolve(self.rgb, None)

    def draw_self(self, dc):
        theme = dc.theme
        x, y, r = self._bubble
        if r <= 1.0:
            return
        rgb = _resolve(self.rgb, (0.0, 0.0, 0.0))
        draw.circle(x, y, r, (rgb[0], rgb[1], rgb[2], dc.alpha), rim=theme.edge_for(rgb, dc.alpha))
        if _resolve(self.active, False):
            draw.circle_outline(x, y, r, with_alpha(theme.accent_light, dc.alpha), width=theme.px(2.5))
        elif self.hover_t > 0.5:
            draw.circle_outline(x, y, r, with_alpha(theme.accent, dc.alpha), width=theme.px(1.0))


class GradientSlider(RingSegment):
    """The gradient from the primary color (at ``a1``, the left end) to the secondary
    one (at ``a0``, the top) along the circle; a marker shows the tertiary color's spot.
    A press sets it from the pointer's angle (and selects the tertiary color), dragging
    keeps setting it: ``on_value(t)`` with t = 0 at the primary, 1 at the secondary end."""

    draggable = True
    _STEPS = 24

    def __init__(self, label="", *, colors, value, active, on_value, **kwargs):
        super().__init__(label, **kwargs)
        self.colors = colors        # () -> (primary rgb, secondary rgb)
        self.value = value          # () -> t
        self.active = active        # () -> bool: the tertiary color is selected
        self.on_value = on_value
        self.dragging = False

    def _span(self):
        """Screen angles (radians) of the drawn ends: (secondary end, primary end)."""
        a0, a1 = self.angles
        r = max(1.0, (self.pr0 + self.pr1) * 0.5)
        return (a0 + math.asin(min(1.0, self.insets[0] / r)),
                a1 - math.asin(min(1.0, self.insets[1] / r)))

    def value_at(self, x, y):
        s0, s1 = self._span()
        angle = math.atan2(y - self.cy, x - self.cx) % math.tau
        mid = (s0 + s1) * 0.5    # unwrap around the slider's middle
        angle = mid + (angle - mid + math.pi) % math.tau - math.pi
        return max(0.0, min(1.0, (s1 - angle) / (s1 - s0)))

    def drag_begin(self, x, y):
        self.dragging = True
        self.drag_update(x, y)

    def drag_update(self, x, y):
        if self.dragging and self.on_value is not None:
            self.on_value(self.value_at(x, y))

    def drag_end(self, x, y, cancelled=False):
        self.dragging = False

    def draw_self(self, dc):
        theme = dc.theme
        alpha = self._alpha(dc)
        primary, secondary = _resolve(self.colors, ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)))
        if primary is None or secondary is None:
            return
        s0, s1 = self._span()
        if s1 <= s0:
            return
        # Gradient: thin slices from the secondary end to the primary end.
        steps = self._STEPS
        inner, outer = [], []
        for i in range(steps + 1):
            a = s0 + (s1 - s0) * i / steps
            ux, uy = math.cos(a), math.sin(a)
            inner.append((self.cx + ux * self.pr0, self.cy + uy * self.pr0))
            outer.append((self.cx + ux * self.pr1, self.cy + uy * self.pr1))
        colors = []
        for i in range(steps + 1):
            t = 1.0 - i / steps
            c = [p + (q - p) * t for p, q in zip(primary[:3], secondary[:3])]
            colors.append((c[0], c[1], c[2], alpha))
        draw.gradient_ring_segment(inner, outer, colors)
        on = _resolve(self.active, False)
        edge = with_alpha(theme.accent_light, alpha) if on else theme.edge_for((0.5, 0.5, 0.5), alpha)
        draw.ring_segment_outline(inner, outer, edge, width=theme.px(1.5) if on else 1.0)
        # Marker at the tertiary color's spot: a dark bar with a light core, past both edges.
        t = max(0.0, min(1.0, float(_resolve(self.value, 0.5) or 0.0)))
        a = s1 - (s1 - s0) * t
        ux, uy = math.cos(a), math.sin(a)
        reach = theme.px(2.0)
        p0 = (self.cx + ux * (self.pr0 - reach), self.cy + uy * (self.pr0 - reach))
        p1 = (self.cx + ux * (self.pr1 + reach), self.cy + uy * (self.pr1 + reach))
        half = theme.px(GRADIENT_MARKER)
        draw.polyline([p0, p1], (0.05, 0.05, 0.05, 0.9 * alpha), half * 2.0)
        draw.polyline([p0, p1], (1.0, 1.0, 1.0, alpha) if on else (0.8, 0.8, 0.8, 0.85 * alpha), half * 0.8)


class BubbleDrag(ColorDrag, ColorBubble):
    """The color selector's old / new bubble: tap accepts, dragging carries the new color."""

    def __init__(self, bar, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bar = bar

    def drag_color(self):
        try:
            return tuple(self.bar.actions.preview_colors()[1])
        except Exception:
            return None


class Swatch(ColorDrag, RingSegment):
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


class PaletteSlot(ColorDrag, RingSegment):
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
