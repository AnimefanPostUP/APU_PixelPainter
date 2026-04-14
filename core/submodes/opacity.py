"""Opacity sub-mode handler."""

import math

from .base import SubModeHandler


_ARC_RADIUS = 156.0
_ARC_THICKNESS = 8.0
_ARC_SPAN_DEG = 50.0
_SLIDER_HEIGHT = 150.0
_RADIUS_TOLERANCE = 16.0
_ANGLE_MARGIN_DEG = 12.0


def _normalize_signed_angle(rad):
    while rad <= -math.pi:
        rad += math.tau
    while rad > math.pi:
        rad -= math.tau
    return rad


def _is_near_arc_side(cx, cy, mx, my, side):
    dx = mx - cx
    dy = my - cy
    dist = math.hypot(dx, dy)
    if dist <= 1e-6:
        return False

    mid_radius = _ARC_RADIUS
    # Accept cursor positions on the arc and also farther out from the center
    # past the slider, while still rejecting points too close to the center.
    min_radius = max(0.0, mid_radius - (_ARC_THICKNESS * 0.5 + _RADIUS_TOLERANCE))
    if dist < min_radius:
        return False

    angle = math.atan2(dy, dx)
    side_center = math.pi if side == 'OPACITY' else 0.0
    half_span = math.radians(_ARC_SPAN_DEG * 0.5 + _ANGLE_MARGIN_DEG)
    delta = abs(_normalize_signed_angle(angle - side_center))
    return delta <= half_span


def _value_from_mouse_height(cy, my):
    return max(0.0, min(1.0, 0.5 + ((my - cy) / _SLIDER_HEIGHT)))


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
        self.state['sub_opacity_hover_target'] = 'OPACITY'
        self.helpers.set_sub_start_to_event(self.state, event)

    def on_cancel(self, context):
        self.settings.set_brush_opacity(context, self.state.get('sub_orig_opacity'))
        self.settings.set_modifier(context, self.state.get('sub_orig_modifier'))

    def on_mouse_move(self, context, event):
        self.state['sub_last_x'] = event.mouse_region_x
        self.state['sub_last_y'] = event.mouse_region_y

        cx = self.state.get('sub_start_region_x')
        cy = self.state.get('sub_start_region_y')
        if cx is None or cy is None:
            return

        mx = event.mouse_region_x
        my = event.mouse_region_y
        near_left = _is_near_arc_side(cx, cy, mx, my, 'OPACITY')
        near_right = _is_near_arc_side(cx, cy, mx, my, 'MODIFIER')

        target = None
        if near_left and not near_right:
            target = 'OPACITY'
        elif near_right and not near_left:
            target = 'MODIFIER'
        elif near_left and near_right:
            target = 'OPACITY' if mx < cx else 'MODIFIER'

        if target is not None:
            self.state['sub_opacity_hover_target'] = target
            value = _value_from_mouse_height(cy, my)
            if target == 'OPACITY':
                self.settings.set_brush_opacity(context, value)
            else:
                self.settings.set_modifier(context, value)

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
