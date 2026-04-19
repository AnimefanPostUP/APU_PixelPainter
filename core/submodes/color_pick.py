"""Color-pick sub-mode handler."""

import colorsys

from .base import SubModeHandler


_COLOR_PICK_SHIFT_FACTOR = 10.0
_SATURATION_EPS = 0.01


class ColorPickSubMode(SubModeHandler):
    mode_name = 'COLOR_PICK'

    def __init__(self, state, settings, helpers, on_exit):
        self.state = state
        self.settings = settings
        self.helpers = helpers
        self.on_exit = on_exit

    def on_enter(self, context, event):
        rgb = self.settings.get_brush_rgb(context)
        sec_rgb = self.settings.get_brush_secondary_rgb(context)
        h_new, s_new, v_new = colorsys.rgb_to_hsv(*rgb)

        if self.state.get('sub_color_s') is None:
            self.state['sub_color_h'] = h_new
            self.state['sub_color_s'] = s_new
            self.state['sub_color_v'] = v_new
        else:
            if s_new > _SATURATION_EPS:
                self.state['sub_color_h'] = h_new
            self.state['sub_color_v'] = v_new

        self.state['sub_mode'] = self.mode_name
        self.state['sub_color_target'] = 'PRIMARY'
        self.state['sub_orig_color'] = rgb
        self.state['sub_orig_color_secondary'] = sec_rgb
        self.state['sub_color_start_h'] = self.state['sub_color_h']
        self.state['sub_color_start_v'] = self.state['sub_color_v']

        self.helpers.set_sub_start_to_event(self.state, event)
        self.helpers.warp_cursor_to_color_pick_hv(
            self.state,
            context,
            self.state['sub_color_h'],
            self.state['sub_color_v'],
        )
        self.state['sub_fake_cursor_x'] = self.state.get('sub_last_x')
        self.state['sub_fake_cursor_y'] = self.state.get('sub_last_y')

    def on_cancel(self, context):
        self.settings.set_brush_rgb(context, *self.state['sub_orig_color'])
        if self.state['sub_orig_color_secondary'] is not None:
            self.settings.set_brush_secondary_rgb(context, *self.state['sub_orig_color_secondary'])

    def on_mouse_move(self, context, event):
        dx = event.mouse_region_x - self.state['sub_last_x']
        dy = event.mouse_region_y - self.state['sub_last_y']
        self.state['sub_last_x'] = event.mouse_region_x
        self.state['sub_last_y'] = event.mouse_region_y

        sensitivity = _COLOR_PICK_SHIFT_FACTOR if event.shift else 1.0
        self.state['sub_color_total_dx'] += dx / sensitivity
        self.state['sub_color_total_dy'] += dy / sensitivity
        self.state['sub_color_h'] = (0.5 + self.state['sub_color_total_dx'] / self.helpers.COLOR_PICK_H_DIV) % 1.0
        self.state['sub_color_v'] = max(0.0, min(1.0, 0.5 + self.state['sub_color_total_dy'] / self.helpers.COLOR_PICK_V_DIV))

        rgb = colorsys.hsv_to_rgb(
            self.state['sub_color_h'],
            self.state['sub_color_s'],
            self.state['sub_color_v'],
        )
        if self.state.get('sub_color_target') == 'SECONDARY':
            self.settings.set_brush_secondary_rgb(context, *rgb)
        else:
            self.settings.set_brush_rgb(context, *rgb)

        if event.shift:
            self.helpers.warp_cursor_to_color_pick_hv(
                self.state, context, self.state['sub_color_h'], self.state['sub_color_v'])
        self.helpers.wrap_cursor_at_window_edge(self.state, context, event)
        self.state['sub_fake_cursor_x'] = self.state.get('sub_last_x')
        self.state['sub_fake_cursor_y'] = self.state.get('sub_last_y')
        context.area.tag_redraw()

    def on_shift_press(self, context, event):
        self._sync_cursor_to_hv(context)

    def on_shift_release(self, context, event):
        self._sync_cursor_to_hv(context)

    def on_wheel_up(self, context, event):
        self._adjust_saturation(context, event, 0.01 if event.shift else 0.05)

    def on_wheel_down(self, context, event):
        self._adjust_saturation(context, event, -(0.01 if event.shift else 0.05))

    def on_key_e_press(self, context, event):
        if event.shift:
            return
        if self.state.get('sub_color_target') == 'SECONDARY':
            if self.state.get('sub_orig_color_secondary') is not None:
                self.settings.set_brush_secondary_rgb(context, *self.state['sub_orig_color_secondary'])
            self.state['sub_color_target'] = 'PRIMARY'
            rgb = self.settings.get_brush_rgb(context)
        else:
            if self.state.get('sub_orig_color') is not None:
                self.settings.set_brush_rgb(context, *self.state['sub_orig_color'])
            self.state['sub_color_target'] = 'SECONDARY'
            rgb = self.settings.get_brush_secondary_rgb(context)

        h_new, s_new, v_new = colorsys.rgb_to_hsv(*rgb)
        if s_new > _SATURATION_EPS:
            self.state['sub_color_h'] = h_new
        self.state['sub_color_s'] = s_new
        self.state['sub_color_v'] = v_new
        self.state['sub_color_start_h'] = self.state['sub_color_h']
        self.state['sub_color_start_v'] = self.state['sub_color_v']
        self.helpers.warp_cursor_to_color_pick_hv(
            self.state,
            context,
            self.state['sub_color_h'],
            self.state['sub_color_v'],
        )
        self.state['sub_fake_cursor_x'] = self.state.get('sub_last_x')
        self.state['sub_fake_cursor_y'] = self.state.get('sub_last_y')
        context.area.tag_redraw()

    def on_mouse_left_press(self, context, event):
        self.on_exit(context, self.mode_name)
        context.area.tag_redraw()

    def on_mouse_right_press(self, context, event):
        self.on_cancel(context)
        self.on_exit(context, self.mode_name)
        context.area.tag_redraw()

    def _adjust_saturation(self, context, event, delta):
        sat = self.state.get('sub_color_s') or 0.0
        self.state['sub_color_s'] = max(0.0, min(1.0, sat + delta))
        rgb = colorsys.hsv_to_rgb(
            self.state['sub_color_h'],
            self.state['sub_color_s'],
            self.state['sub_color_v'],
        )
        if self.state.get('sub_color_target') == 'SECONDARY':
            self.settings.set_brush_secondary_rgb(context, *rgb)
        else:
            self.settings.set_brush_rgb(context, *rgb)
        if event.shift:
            self.helpers.warp_cursor_to_color_pick_hv(
                self.state, context, self.state['sub_color_h'], self.state['sub_color_v'])
        context.area.tag_redraw()

    def _sync_cursor_to_hv(self, context):
        self.helpers.warp_cursor_to_color_pick_hv(
            self.state,
            context,
            self.state.get('sub_color_h') or 0.5,
            self.state.get('sub_color_v') or 0.5,
        )
        self.state['sub_fake_cursor_x'] = self.state.get('sub_last_x')
        self.state['sub_fake_cursor_y'] = self.state.get('sub_last_y')
        context.area.tag_redraw()
