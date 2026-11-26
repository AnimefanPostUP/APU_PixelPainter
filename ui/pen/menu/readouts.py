"""What the pen menu draws over its widgets: value readouts while dragging, the falloff
and size previews, the dragged color, the picker hint.
"""


from ...kit import Rect
from ...kit import draw
from ....model import falloff
from ..metrics import ARM_HINTS, CHANNEL_LABELS, FALLOFF_PREVIEW_SIZE, FLYOUT_GAP, MASK_PICK_HINT, TINT_MASK
from ..windows.palettes import draw_palette_cells


class Readouts:
    """Part of :class:`.bar.PenBar` (a mixin: uses its state)."""

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
        field = getattr(self, 'falloff_field', None)
        if field is not None and field.dragging:
            self._draw_falloff_readout(field)
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

    def _draw_falloff_readout(self, field):
        """Hardness / sharpness beside the menu, and the falloff as a large disc beyond it."""
        theme = self.overlay.theme
        hardness, sharpness = field._current()
        box = self._pill(f"Hard {hardness * 100:.0f}%   Sharp {sharpness * 100:.0f}%", self.menu.rect,
                         field.rect.cy, 14.0, theme.accent)
        size = theme.px(FALLOFF_PREVIEW_SIZE)
        gap = theme.px(FLYOUT_GAP)
        cx = box.x1 + gap + size * 0.5 if box.cx > self.menu.rect.cx else box.x0 - gap - size * 0.5
        draw.circle(cx, box.cy, size * 0.5 + theme.px(3.0), theme.surface_dark)
        self.icons.draw(falloff.get('SHAPE').icon_key, cx, box.cy, size, 1.0)

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
            self._pill(MASK_PICK_HINT, self.menu.rect, self.windows_button.rect.cy, 12.0, (*TINT_MASK, 1.0))
            return
        kind = self.actions.armed()
        button = self.arm_buttons.get(kind)
        if button is None or self.menu.collapsed:
            return
        self._pill(ARM_HINTS[kind], self.menu.rect, button.rect.cy, 12.0, self.overlay.theme.accent_light)
