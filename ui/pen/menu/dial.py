"""The pen menu's dial: building its rings, knobs, sliders and corner buttons, and
dragging the knobs (size / strength / alpha / modifier).
"""

import math

from ...kit import Dial, DragBubble, CornerSegment, RingSegment, RingSlider
from ....model import blend_modes, color_history, color_palette, falloff
from ..widgets.blend import BlendButton, BlendFavorite, BlendFavorites
from ..widgets.color import ColorCorner, GradientSlider, PaletteSlot, Swatch, TertiaryBubble
from ..widgets.falloff_field import FalloffField
from ..widgets.grid_corner import GridCorner
from ..icons.menu import captioned, paint_alpha_lock, paint_arrow, paint_color_wheel, paint_curve, paint_gear, paint_mask_menu, paint_save, paint_spacing, paint_swap, paint_target_picker, paint_view, paint_windows
from ..metrics import BOTTOM_LEFT_ARC, BOTTOM_LEFT_RING, BRUSH_MODE_ARC, BRUSH_MODE_RING, COLORS_ARC, COLORS_WEIGHTS, COLOR_CORNER_INNER, COLOR_ROUND, COLOR_WHEEL_ARC, CORNER_INNER, CUSTOM_TINT_AMOUNT, DIAL_GAP, FALLOFF_FIELD_ARC, FALLOFF_SPLIT, FAVORITES_ARC, FAVORITE_FONT, GROUP_GAP, HISTORY_ARC, HISTORY_BAND_ARC, HISTORY_DEPTH, INNER_RING, MAX_SIZE, OUTER_RING, PALETTE_BUTTON_ARC, PALETTE_DEPTH, PALETTE_ROWS, SIZE_RADIUS, SIZE_STEP_PX, SLIDERS, SLIDER_ARC, SQUARE_HALF, SWAP_DEPTH, TINT_CUSTOM, TINT_FALLOFF, TINT_GRID, TINT_HISTORY, TINT_MASK, TINT_MODES, TINT_SAVE, TINT_TOOLS, TINT_VIEW, TINT_WINDOWS, TOOL_ARC, WINDOW_RING, WINDOW_RING_COVER, WINDOW_RING_START, INNER_FILL
from ..widgets.window_ring import WindowRing
from ..icons.palettes import paint_library, paint_palettes


def _add_capsule(dial, segments, r0, r1, a0, a1, **kwargs):
    """``segments`` as one capsule: a band ``r0 .. r1`` along ``a0 .. a1`` (split like
    :meth:`Dial.add_band`) whose two outer ends are half circles."""
    segments = dial.add_band(segments, r0, r1, a0, a1, **kwargs)
    for i, segment in enumerate(segments):
        segment.round = (r1 - r0) * 0.5
        segment.round_ends = (i == 0, i == len(segments) - 1)
        if len(segments) == 1:
            segment.edge_extra = (0.0, 0.0)   # its round ends set it apart; keep the room
    return segments


class DialControls:
    """Part of :class:`.bar.PenBar` (a mixin: uses its state)."""

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
            enabled=lambda: self.actions.uses_value(channel),   # grayed out: the tool ignores it
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
                        icons=self.icons, font_size=8.0, fill=INNER_FILL if i >= half else None,
                        selected=lambda t=tool.tool_id: a.active_tool() == t,
                        on_click=lambda t=tool.tool_id: a.select_tool(t))
            for i, tool in enumerate(all_tools)
        ]
        dial.add_arc(reversed(tools[:half]), *OUTER_RING, *TOOL_ARC, tint=TINT_TOOLS)
        dial.add_arc(reversed(tools[half:]), *INNER_RING, *TOOL_ARC, tint=TINT_TOOLS)

        dial.add_arc([
            RingSegment("Undo", key='UNDO', fill=INNER_FILL, painter=paint_arrow('LEFT', "Undo"), on_click=a.undo),
            RingSegment("Redo", key='REDO', fill=INNER_FILL, painter=paint_arrow('RIGHT', "Redo"), on_click=a.redo),
        ], *INNER_RING, *HISTORY_ARC, tint=TINT_HISTORY)
        # Outside Undo / Redo: the favorite blend modes in rows (Blend: bottom-left corner).
        favorites = {
            b: BlendFavorite(blend_modes.short_label(b), key=f"FAVORITE_{b}", font_size=FAVORITE_FONT,
                              selected=lambda b=b: a.active_blend() == b,   # plain gray buttons
                              on_click=lambda b=b: a.set_blend(b))
            for b in blend_modes.ids()
        }
        self.favorites_ring = BlendFavorites(dial, favorites, *OUTER_RING, FAVORITES_ARC,
                                              a.blend_favorites)

        # Bottom right, the falloff: the Shape field in the outer ring (reaching in through
        # the inner ring's outer half: no gap to Custom / Curve), in its inner half Custom | Curve.
        from ...icons.falloff_icons import SHAPE_PREVIEWS, shape_preview_key
        self.falloff_field = FalloffField(
            "Falloff", key='FALLOFF_FIELD', icons=self.icons, value=a.falloff_shape,
            on_value=a.set_falloff_shape, active=lambda: a.active_falloff() == 'SHAPE',
            previews=[(hs, shape_preview_key(*hs)) for hs in SHAPE_PREVIEWS],
            marker_icon=falloff.get('SHAPE').icon_key,
            on_drag_state=a.set_cursor_hidden, warp=a.warp_cursor)
        dial.add_arc([self.falloff_field], FALLOFF_SPLIT, OUTER_RING[1], *FALLOFF_FIELD_ARC, tint=TINT_FALLOFF)
        custom_preset = falloff.get('CUSTOM')
        custom = RingSegment(custom_preset.label, key='FALLOFF_CUSTOM', icon=custom_preset.icon_key,
                             icons=self.icons, font_size=8.0, fill=INNER_FILL,
                             tint=TINT_CUSTOM, tint_amount=CUSTOM_TINT_AMOUNT,
                             selected=lambda: a.active_falloff() == 'CUSTOM',
                             on_click=lambda: a.set_falloff('CUSTOM'))
        curve = RingSegment("Curve", key='CURVE', painter=paint_curve, fill=INNER_FILL,
                            tint=TINT_CUSTOM, tint_amount=CUSTOM_TINT_AMOUNT,
                            selected=lambda: self.flyout is self.curve_flyout,
                            on_click=lambda: self._open_curve(curve))
        dial.add_arc([custom, curve], INNER_RING[0], FALLOFF_SPLIT, *FALLOFF_FIELD_ARC)
        self._add_corners(dial)
        return dial

    def _add_corners(self, dial):
        """Top left the color section: the gradient slider (tertiary color), secondary's
        Picker / secondary / Swap + tertiary bubble / primary / primary's Picker; top right
        the color history band and past it the Pixel / Free + Alphalock capsule; bottom right
        the palette, right of the circle its button; bottom left the Windows / Save / Grid /
        Blend capsule."""
        a = self.actions

        # Top right, outside S / A / M: the color history, newest at the top end.
        swatches = [Swatch(self, lambda i=i: self._history(i), a.use_history_color, key=f"HISTORY_{i}")
                    for i in range(color_history.HISTORY_SIZE)]
        dial.add_band(reversed(swatches), CORNER_INNER, CORNER_INNER + HISTORY_DEPTH, *HISTORY_BAND_ARC)
        # Past it, around the diagonal: Pixel / Free (spacing) and Alphalock, one capsule.
        _add_capsule(dial, [
            RingSegment("Spacing", key='SPACING', painter=paint_spacing(a.spacing), on_click=a.toggle_spacing),
            RingSegment("Alphalock", key='ALPHA_LOCK', painter=paint_alpha_lock,
                        selected=a.alpha_lock, on_click=a.toggle_alpha_lock),
        ], *BRUSH_MODE_RING, *BRUSH_MODE_ARC, tint=TINT_MODES)
        # Top left along the circle: the gradient primary (left) -> secondary (top).
        self.gradient_slider = GradientSlider("Tertiary", key='GRADIENT', colors=a.colors, value=a.tertiary_t,
                                               active=a.tertiary_active, on_value=a.set_tertiary_t)
        dial.add_band([self.gradient_slider], CORNER_INNER, CORNER_INNER + HISTORY_DEPTH, *COLORS_ARC)
        primary = ColorCorner(self, 'PRIMARY', lambda: a.colors()[0], lambda: a.color_role('PRIMARY'),
                               key='PRIMARY', round=COLOR_ROUND, on_click=lambda: a.select_color('PRIMARY'))
        secondary = ColorCorner(self, 'SECONDARY', lambda: a.colors()[1], lambda: a.color_role('SECONDARY'),
                                 key='SECONDARY', round=COLOR_ROUND, on_click=lambda: a.select_color('SECONDARY'))

        def picker(which, rgb, active):
            kind = f'EYEDROPPER_{which}'
            return CornerSegment(f"Pick {which.title()}", key=f'PICKER_{which}',
                                 painter=paint_target_picker(rgb, active), round=COLOR_ROUND,
                                 selected=lambda: a.armed() == kind, on_click=lambda: a.toggle_arm(kind))
        pick_primary = picker('PRIMARY', lambda: a.colors()[0], lambda: a.color_target() == 'PRIMARY')
        pick_secondary = picker('SECONDARY', lambda: a.colors()[1], lambda: a.color_target() == 'SECONDARY')
        self.arm_buttons = {'EYEDROPPER_PRIMARY': pick_primary, 'EYEDROPPER_SECONDARY': pick_secondary}
        mix = TertiaryBubble(self, a.tertiary_color, a.tertiary_active, key='TERTIARY', on_click=a.toggle_tertiary)
        dial.add_corner([pick_secondary, secondary, mix, primary, pick_primary], COLOR_CORNER_INNER, SQUARE_HALF,
                        *COLORS_ARC, weights=COLORS_WEIGHTS, chamfer=0.0)
        # Swap by the circle in the middle; the tertiary bubble behind it, toward the corner.
        swap_outer = COLOR_CORNER_INNER + SWAP_DEPTH
        swap = RingSegment("Swap", key='SWAP', painter=paint_swap, round=COLOR_ROUND, on_click=a.swap_colors)
        dial.add_band([swap], COLOR_CORNER_INNER, swap_outer, mix.a0, mix.a1)
        swap.edge_extra = (0.0, 0.0)      # side edges in line with the Mix slot's
        mix.r0 = swap_outer + DIAL_GAP

        palettes = RingSegment("Palettes", key='PALETTES', painter=paint_palettes, selected=a.palette_view,
                               on_click=lambda: a.set_palette_view(not a.palette_view()))
        _add_capsule(dial, [palettes], CORNER_INNER, CORNER_INNER + PALETTE_DEPTH, *PALETTE_BUTTON_ARC)

        # Palette band left of it: the active palette's colors, or (palette view) the
        # project's palettes. Slot 0 at the left.
        palette = [PaletteSlot(self, i, key=f"PALETTE_{i}") for i in range(color_palette.PALETTE_SIZE)]
        per_row = (len(palette) + PALETTE_ROWS - 1) // PALETTE_ROWS
        for row in range(PALETTE_ROWS):
            r0 = CORNER_INNER + row * (HISTORY_DEPTH + DIAL_GAP)
            dial.add_band(palette[row * per_row:(row + 1) * per_row], r0, r0 + HISTORY_DEPTH, *COLOR_WHEEL_ARC)

        # Bottom left, a capsule along the circle: Windows (opens the popup ring on
        # the press -- keep the pen down, drag onto an entry, lift), Save, Grid (tap: on /
        # off, drag: opacity), Blend (opens the flyout on the press; shows the mode).
        blend = BlendButton("Blend", key='BLEND', mode=lambda: blend_modes.short_label(a.active_blend()),
                             on_click=lambda: self.toggle_flyout(self.blend_flyout, blend),
                             selected=lambda: self.flyout is self.blend_flyout)
        blend.activate_on_press = True
        save = RingSegment("Save", key='SAVE_IMAGE', painter=paint_save(a.image_unsaved, caption=False),
                           tint=TINT_SAVE, on_click=a.save_image)
        grid = GridCorner("Grid", key='GRID', shown=a.grid_shown, value=a.grid_opacity,
                           on_value=a.set_grid_opacity, on_click=a.toggle_grid, tint=TINT_GRID)
        windows = RingSegment("Windows", key='WINDOWS', painter=paint_windows, tint=TINT_WINDOWS,
                              selected=lambda: self.flyout is self.window_ring,
                              on_click=lambda: self.toggle_flyout(self.window_ring, windows))
        windows.activate_on_press = True
        _add_capsule(dial, [windows, save, grid, blend], *BOTTOM_LEFT_RING, *BOTTOM_LEFT_ARC)
        self.windows_button = windows

        # The Windows popup ring (added last: over everything else of the dial).
        self.window_ring = dial.add(WindowRing(*WINDOW_RING, cover=WINDOW_RING_COVER, key='WINDOW_RING'))
        self.window_ring.add_entries(dial, [
            RingSegment("Settings", key='RING_SETTINGS', painter=captioned(paint_gear, "Settings"),
                        tint=TINT_WINDOWS, selected=lambda: a.panel_open('settings'),
                        on_click=self._flyout_action(lambda: self.toggle_window('settings'))),
            RingSegment("Mask", key='RING_MASK', painter=paint_mask_menu(a.mask_enabled), tint=TINT_MASK,
                        selected=lambda: a.panel_open('mask'),
                        on_click=self._flyout_action(lambda: self.toggle_window('mask'))),
            RingSegment("View", key='RING_VIEW', painter=paint_view, tint=TINT_VIEW,
                        selected=lambda: a.panel_open('view'),
                        on_click=self._flyout_action(lambda: self.toggle_window('view'))),
            RingSegment("Color", key='RING_COLOR', painter=captioned(paint_color_wheel(a.pen_rgb), "Color"),
                        tint=TINT_WINDOWS, selected=a.color_panel_open,
                        on_click=self._flyout_action(a.toggle_color_panel)),
            RingSegment("Palettes", key='RING_PALETTES', painter=captioned(paint_library, "Palettes"),
                        tint=TINT_WINDOWS, selected=lambda: a.panel_open('library'),
                        on_click=self._flyout_action(lambda: self.toggle_window('library'))),
        ], WINDOW_RING_START)

    def _history(self, index):
        colors = self.actions.color_history()
        return colors[index] if index < len(colors) else None

    def dragging(self):
        """Something is being dragged (an element moved / resized, a value or a color)."""
        return any(ov.dragging is not None for _w, ov in self.windows.values())

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
