"""Opacity sub-mode handler."""

from .base import SubModeHandler


class OpacitySubMode(SubModeHandler):
    mode_name = 'OPACITY'

    def __init__(self, state, settings, helpers, on_exit):
        self.state = state
        self.settings = settings
        self.helpers = helpers
        self.on_exit = on_exit

    def on_enter(self, context, event):
        self.state['sub_mode'] = self.mode_name
        self.state['sub_last_x'] = event.mouse_region_x
        self.state['sub_last_y'] = event.mouse_region_y
        self.state['sub_orig_opacity'] = self.settings.get_brush_opacity(context)
        self.state['sub_orig_modifier'] = self.settings.get_modifier(context)
        self.state['sub_total_delta'] = 0.0
        self.helpers.set_sub_start_to_event(self.state, event)

    def on_cancel(self, context):
        self.settings.set_brush_opacity(context, self.state.get('sub_orig_opacity'))
        self.settings.set_modifier(context, self.state.get('sub_orig_modifier'))

    def on_mouse_move(self, context, event):
        dx = event.mouse_region_x - self.state['sub_last_x']
        dy = event.mouse_region_y - self.state['sub_last_y']
        self.state['sub_last_x'] = event.mouse_region_x
        self.state['sub_last_y'] = event.mouse_region_y
        self.state['sub_total_delta'] += dx + dy
        divisor = 3000.0 if event.shift else 300.0
        orig_opacity = self.state.get('sub_orig_opacity') or 0.0
        self.settings.set_brush_opacity(context, orig_opacity + self.state['sub_total_delta'] / divisor)
        self.helpers.wrap_cursor_at_window_edge(self.state, context, event)
        context.area.tag_redraw()

    def on_wheel_up(self, context, event):
        step = 0.01 if event.shift else 0.05
        self.settings.set_modifier(context, self.settings.get_modifier(context) + step)
        context.area.tag_redraw()

    def on_wheel_down(self, context, event):
        step = 0.01 if event.shift else 0.05
        self.settings.set_modifier(context, self.settings.get_modifier(context) - step)
        context.area.tag_redraw()

    def on_mouse_left_press(self, context, event):
        self.on_exit(context, self.mode_name)
        context.area.tag_redraw()

    def on_mouse_right_press(self, context, event):
        self.on_cancel(context)
        self.on_exit(context, self.mode_name)
        context.area.tag_redraw()
