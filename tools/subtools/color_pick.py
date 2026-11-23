"""Color-pick subtool (E): drag to pick hue/value; saturation via the slider or the wheel.

The saturation slider right of the sheet is grabbed anywhere and swiped like a
wheel (relative, no jump); a tap without dragging jumps to the tapped spot.
While the pointer is in the slider's column, hue / value hold still.
"""

import colorsys

from ...core.framework import HoldTool, Shortcut, ToolFrame
from . import helpers


_COLOR_PICK_SHIFT_FACTOR = 10.0
_SATURATION_EPS = 0.01


class ColorPickTool(ToolFrame):
    """Modal HSV picker. LMB confirms, RMB / Esc cancel, E toggles primary/secondary."""

    label = "Color Pick"
    mode_name = 'COLOR_PICK'
    exclusive = True
    captures_input = True
    triggers = (Shortcut('E', shift=False, ctrl=False, alt=False),)

    state_defaults = {
        **helpers.SUB_MODE_STATE,
        'sub_orig_color':     None,
        'sub_orig_color_secondary': None,
        'sub_color_target':   'PRIMARY',
        'sub_color_h':        None,
        'sub_color_s':        None,
        'sub_color_v':        None,
        'sub_color_start_h':  None,
        'sub_color_start_v':  None,
        'sub_color_start_s':  None,   # previous color (marked on sheet + slider)
        'sub_color_sat_drag': None,   # {'travel': px} while the slider is held
        'sub_color_sat_hover': False,
        'sub_color_total_dx': 0.0,
        'sub_color_total_dy': 0.0,
    }

    def on_register(self):
        # Hold Shift = precision movement. A subtool backed by two methods of this object.
        self.precision = self.add_subtool(HoldTool(
            'SHIFT', on_hold=self._sync_cursor_to_hv, on_release=self._sync_cursor_to_hv))

        self.bind(Shortcut('MOUSEMOVE', None), self._on_mouse_move)
        self.bind(Shortcut('LEFTMOUSE'), self._on_press)
        self.bind(Shortcut('LEFTMOUSE', 'RELEASE'), self._on_release)
        self.bind(Shortcut(('RIGHTMOUSE', 'ESC')), self._cancel)
        self.bind(Shortcut('WHEELUPMOUSE', None), lambda ctx, ev: self._adjust_saturation(ctx, +1))
        self.bind(Shortcut('WHEELDOWNMOUSE', None), lambda ctx, ev: self._adjust_saturation(ctx, -1))
        self.bind(Shortcut('E'), self._toggle_target)

    # ---- lifecycle ---------------------------------------------------------------

    def on_activate(self, ctx, event):
        state, settings = ctx.state, ctx.settings
        rgb = settings.get_brush_rgb(ctx.context)
        sec_rgb = settings.get_brush_secondary_rgb(ctx.context)
        h_new, s_new, v_new = colorsys.rgb_to_hsv(*rgb)

        if state.get('sub_color_s') is None:
            state['sub_color_h'] = h_new
            state['sub_color_s'] = s_new
            state['sub_color_v'] = v_new
        else:
            if s_new > _SATURATION_EPS:
                state['sub_color_h'] = h_new
            state['sub_color_v'] = v_new

        state['sub_mode'] = self.mode_name
        state['sub_color_target'] = 'PRIMARY'
        state['sub_orig_color'] = rgb
        state['sub_orig_color_secondary'] = sec_rgb
        state['sub_color_start_h'] = state['sub_color_h']
        state['sub_color_start_v'] = state['sub_color_v']
        state['sub_color_start_s'] = state['sub_color_s']
        state['sub_color_sat_drag'] = None
        state['sub_color_sat_hover'] = False

        # Center the picker at the cursor and move the mouse onto the current color's spot.
        helpers.set_sub_start_to_event(state, event)
        helpers.warp_cursor_to_color_pick_hv(state, ctx.context, state['sub_color_h'], state['sub_color_v'], warp=True)
        state['sub_fake_cursor_x'] = state.get('sub_last_x')
        state['sub_fake_cursor_y'] = state.get('sub_last_y')
        ctx.redraw()

    def on_deactivate(self, ctx):
        ctx.state['sub_color_sat_drag'] = None
        ctx.state['sub_color_sat_hover'] = False
        if ctx.state.get('sub_mode') == self.mode_name:
            ctx.state['sub_mode'] = None
        ctx.redraw()

    def draw_overlay(self, ctx):
        from .. import draw_functions
        draw_functions.draw_sub_mode_overlay(ctx.context, ctx.state)

    # ---- actions -------------------------------------------------------------------

    def _confirm(self, ctx, event):
        self.deactivate(ctx)

    def _on_press(self, ctx, event):
        x, y = event.mouse_region_x, event.mouse_region_y
        if helpers.over_sat_bar(ctx.state, x, y):
            ctx.state['sub_color_sat_drag'] = {'travel': 0.0}
            self._track_pointer(ctx.state, x, y)
            ctx.redraw()
            return
        self._confirm(ctx, event)

    def _on_release(self, ctx, event):
        state = ctx.state
        drag = state.get('sub_color_sat_drag')
        if drag is None:
            return False  # not ours (the picker applies on press)
        state['sub_color_sat_drag'] = None
        if drag['travel'] < helpers.SAT_TAP_TRAVEL:  # a tap: jump to the spot
            state['sub_color_s'] = helpers.sat_at(state, event.mouse_region_y)
            self._write_color(ctx)
        state['sub_color_sat_hover'] = helpers.over_sat_bar(state, event.mouse_region_x, event.mouse_region_y)
        ctx.redraw()

    def _cancel(self, ctx, event):
        state, settings = ctx.state, ctx.settings
        settings.set_brush_rgb(ctx.context, *state['sub_orig_color'])
        if state['sub_orig_color_secondary'] is not None:
            settings.set_brush_secondary_rgb(ctx.context, *state['sub_orig_color_secondary'])
        self.deactivate(ctx)

    def _write_color(self, ctx):
        state = ctx.state
        rgb = colorsys.hsv_to_rgb(state['sub_color_h'], state['sub_color_s'], state['sub_color_v'])
        if state.get('sub_color_target') == 'SECONDARY':
            ctx.settings.set_brush_secondary_rgb(ctx.context, *rgb)
        else:
            ctx.settings.set_brush_rgb(ctx.context, *rgb)

    def _track_pointer(self, state, x, y):
        """Follow the real pointer without changing hue / value (keeps the
        position -> hue/value mapping consistent for when it moves on)."""
        state['sub_last_x'], state['sub_last_y'] = x, y
        state['sub_color_total_dx'] = x - state['sub_start_region_x']
        state['sub_color_total_dy'] = y - state['sub_start_region_y']
        state['sub_fake_cursor_x'], state['sub_fake_cursor_y'] = x, y

    def _on_mouse_move(self, ctx, event):
        state = ctx.state
        x, y = event.mouse_region_x, event.mouse_region_y
        dx = x - state['sub_last_x']
        dy = y - state['sub_last_y']

        drag = state.get('sub_color_sat_drag')
        if drag is not None:  # swiping the slider: relative, like a wheel
            drag['travel'] += abs(dx) + abs(dy)
            scale = 1.0 / _COLOR_PICK_SHIFT_FACTOR if self.precision.is_active else 1.0
            sat = (state.get('sub_color_s') or 0.0) + dy * scale / helpers.COLOR_PICK_V_DIV
            state['sub_color_s'] = max(0.0, min(1.0, sat))
            self._write_color(ctx)
            self._track_pointer(state, x, y)
            ctx.redraw()
            return

        state['sub_color_sat_hover'] = helpers.over_sat_bar(state, x, y)
        if helpers.in_sat_column(state, x):  # on the way to / on the slider
            self._track_pointer(state, x, y)
            ctx.redraw()
            return

        state['sub_last_x'] = x
        state['sub_last_y'] = y

        sensitivity = _COLOR_PICK_SHIFT_FACTOR if self.precision.is_active else 1.0
        state['sub_color_total_dx'] += dx / sensitivity
        state['sub_color_total_dy'] += dy / sensitivity
        state['sub_color_h'] = (0.5 + state['sub_color_total_dx'] / helpers.COLOR_PICK_H_DIV) % 1.0
        state['sub_color_v'] = max(0.0, min(1.0, 0.5 + state['sub_color_total_dy'] / helpers.COLOR_PICK_V_DIV))
        self._write_color(ctx)

        if self.precision.is_active:
            helpers.warp_cursor_to_color_pick_hv(state, ctx.context, state['sub_color_h'], state['sub_color_v'])
        state['sub_fake_cursor_x'] = state.get('sub_last_x')
        state['sub_fake_cursor_y'] = state.get('sub_last_y')
        ctx.redraw()

    def _adjust_saturation(self, ctx, direction):
        state = ctx.state
        step = 0.01 if self.precision.is_active else 0.05
        sat = state.get('sub_color_s') or 0.0
        state['sub_color_s'] = max(0.0, min(1.0, sat + direction * step))
        self._write_color(ctx)
        if self.precision.is_active:
            helpers.warp_cursor_to_color_pick_hv(state, ctx.context, state['sub_color_h'], state['sub_color_v'])
        ctx.redraw()

    def _toggle_target(self, ctx, event):
        if event.shift:
            return  # swallowed: Shift+E must not open STRENGTH on top
        state, settings, context = ctx.state, ctx.settings, ctx.context
        if state.get('sub_color_target') == 'SECONDARY':
            if state.get('sub_orig_color_secondary') is not None:
                settings.set_brush_secondary_rgb(context, *state['sub_orig_color_secondary'])
            state['sub_color_target'] = 'PRIMARY'
            rgb = settings.get_brush_rgb(context)
        else:
            if state.get('sub_orig_color') is not None:
                settings.set_brush_rgb(context, *state['sub_orig_color'])
            state['sub_color_target'] = 'SECONDARY'
            rgb = settings.get_brush_secondary_rgb(context)

        h_new, s_new, v_new = colorsys.rgb_to_hsv(*rgb)
        if s_new > _SATURATION_EPS:
            state['sub_color_h'] = h_new
        state['sub_color_s'] = s_new
        state['sub_color_v'] = v_new
        state['sub_color_start_h'] = state['sub_color_h']
        state['sub_color_start_v'] = state['sub_color_v']
        state['sub_color_start_s'] = state['sub_color_s']
        helpers.warp_cursor_to_color_pick_hv(state, context, state['sub_color_h'], state['sub_color_v'], warp=True)
        state['sub_fake_cursor_x'] = state.get('sub_last_x')
        state['sub_fake_cursor_y'] = state.get('sub_last_y')
        ctx.redraw()

    def _sync_cursor_to_hv(self, ctx):
        state = ctx.state
        helpers.warp_cursor_to_color_pick_hv(
            state, ctx.context, state.get('sub_color_h') or 0.5, state.get('sub_color_v') or 0.5)
        state['sub_fake_cursor_x'] = state.get('sub_last_x')
        state['sub_fake_cursor_y'] = state.get('sub_last_y')
        ctx.redraw()
