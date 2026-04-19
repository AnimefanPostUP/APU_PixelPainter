"""Strength sub-mode handler."""

import math

from .base import SubModeHandler


_ARC_RADIUS = 156.0
_ARC_THICKNESS = 8.0
_ARC_SPAN_DEG = 50.0
_SLIDER_HEIGHT = 150.0
_RADIUS_TOLERANCE = 16.0
_ANGLE_MARGIN_DEG = 12.0
_SHIFT_SLOW_FACTOR = 10.0
_CENTER_RADIUS = 24.0


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
    side_center = math.pi if side == 'STRENGTH' else 0.0
    half_span = math.radians(_ARC_SPAN_DEG * 0.5 + _ANGLE_MARGIN_DEG)
    delta = abs(_normalize_signed_angle(angle - side_center))
    return delta <= half_span


def _value_from_mouse_height(cy, my):
    return max(0.0, min(1.0, 0.5 + ((my - cy) / _SLIDER_HEIGHT)))


def _is_near_center_circle(cx, cy, mx, my):
    return math.hypot(mx - cx, my - cy) <= (_CENTER_RADIUS + 12.0)


def _strength_value_from_mouse_height(cy, my):
    # Expand low-end travel so small strength values get more bar distance.
    linear = _value_from_mouse_height(cy, my)
    return linear * linear


class StrengthSubMode(SubModeHandler):
    mode_name = 'STRENGTH'

    def __init__(self, state, settings, helpers, on_exit):
        self.state = state
        self.settings = settings
        self.helpers = helpers
        self.on_exit = on_exit

    @staticmethod
    def _tool_context(context):
        wm = context.window_manager
        mode = wm.pixel_painter_mode
        force_global = bool(mode == 'SMOOTH' and getattr(wm, 'pixel_painter_temp_smooth_force_global', False))
        return mode, force_global

    def on_enter(self, context, event):
        self.state['sub_mode'] = self.mode_name
        self.state['sub_last_x'] = event.mouse_region_x
        self.state['sub_last_y'] = event.mouse_region_y
        self.state['sub_fake_cursor_x'] = event.mouse_region_x
        self.state['sub_fake_cursor_y'] = event.mouse_region_y
        self.state['sub_strength_virtual_x'] = float(event.mouse_region_x)
        self.state['sub_strength_virtual_y'] = float(event.mouse_region_y)
        self.state['sub_edit_button'] = 'LMB'
        mode, force_global = self._tool_context(context)
        btn = 'LMB'
        self.state['sub_orig_strength'] = self.settings.get_tool_strength(context, mode, force_global=force_global, button=btn)
        self.state['sub_orig_alpha'] = self.settings.get_tool_alpha(context, mode, force_global=force_global, button=btn)
        self.state['sub_orig_modifier'] = self.settings.get_tool_modifier(context, mode, force_global=force_global, button=btn)
        self.state['sub_total_delta'] = 0.0
        self.state['sub_strength_hover_target'] = 'STRENGTH'
        self.helpers.set_sub_start_to_event(self.state, event)

    def on_cancel(self, context):
        mode, force_global = self._tool_context(context)
        btn = self.state.get('sub_edit_button', 'LMB')
        self.settings.set_tool_strength(context, mode, self.state.get('sub_orig_strength'), force_global=force_global, button=btn)
        self.settings.set_tool_alpha(context, mode, self.state.get('sub_orig_alpha'), force_global=force_global, button=btn)
        self.settings.set_tool_modifier(context, mode, self.state.get('sub_orig_modifier'), force_global=force_global, button=btn)
        self.settings.apply_tool_runtime_settings(context, mode, force_global=force_global)

    def on_mouse_move(self, context, event):
        dx = event.mouse_region_x - self.state['sub_last_x']
        dy = event.mouse_region_y - self.state['sub_last_y']
        self.state['sub_last_x'] = event.mouse_region_x
        self.state['sub_last_y'] = event.mouse_region_y

        vx = self.state.get('sub_strength_virtual_x')
        vy = self.state.get('sub_strength_virtual_y')
        if vx is None or vy is None:
            vx = float(event.mouse_region_x)
            vy = float(event.mouse_region_y)

        slow = _SHIFT_SLOW_FACTOR if event.shift else 1.0
        vx += dx / slow
        vy += dy / slow
        self.state['sub_strength_virtual_x'] = vx
        self.state['sub_strength_virtual_y'] = vy
        self.state['sub_fake_cursor_x'] = vx
        self.state['sub_fake_cursor_y'] = vy

        cx = self.state.get('sub_start_region_x')
        cy = self.state.get('sub_start_region_y')
        if cx is None or cy is None:
            return

        mx = vx
        my = vy
        near_left = _is_near_arc_side(cx, cy, mx, my, 'STRENGTH')
        near_right = _is_near_arc_side(cx, cy, mx, my, 'MODIFIER')
        near_center = _is_near_center_circle(cx, cy, mx, my)

        target = None
        if near_center:
            target = 'ALPHA'
        elif near_left and not near_right:
            target = 'STRENGTH'
        elif near_right and not near_left:
            target = 'MODIFIER'
        elif near_left and near_right:
            target = 'STRENGTH' if mx < cx else 'MODIFIER'

        if target is not None:
            mode, force_global = self._tool_context(context)
            btn = self.state.get('sub_edit_button', 'LMB')
            self.state['sub_strength_hover_target'] = target
            if target == 'STRENGTH':
                self.settings.set_tool_strength(
                    context,
                    mode,
                    _strength_value_from_mouse_height(cy, my),
                    force_global=force_global,
                    button=btn,
                )
            elif target == 'ALPHA':
                # Alpha is intentionally not changed by mouse movement.
                pass
            else:
                self.settings.set_tool_modifier(
                    context,
                    mode,
                    _value_from_mouse_height(cy, my),
                    force_global=force_global,
                    button=btn,
                )
            self.settings.apply_tool_runtime_settings(context, mode, force_global=force_global)

        self.helpers.wrap_cursor_at_window_edge(self.state, context, event)
        context.area.tag_redraw()

    def on_wheel_up(self, context, event):
        step = 0.01 if event.shift else 0.05
        mode, force_global = self._tool_context(context)
        btn = self.state.get('sub_edit_button', 'LMB')
        hover = self.state.get('sub_strength_hover_target', 'STRENGTH')
        if hover == 'MODIFIER':
            value = self.settings.get_tool_modifier(context, mode, force_global=force_global, button=btn)
            self.settings.set_tool_modifier(context, mode, value + step, force_global=force_global, button=btn)
        elif hover == 'ALPHA':
            value = self.settings.get_tool_alpha(context, mode, force_global=force_global, button=btn)
            self.settings.set_tool_alpha(context, mode, value + step, force_global=force_global, button=btn)
        else:
            value = self.settings.get_tool_strength(context, mode, force_global=force_global, button=btn)
            self.settings.set_tool_strength(context, mode, value + step, force_global=force_global, button=btn)
        self.settings.apply_tool_runtime_settings(context, mode, force_global=force_global)
        context.area.tag_redraw()

    def on_wheel_down(self, context, event):
        step = 0.01 if event.shift else 0.05
        mode, force_global = self._tool_context(context)
        btn = self.state.get('sub_edit_button', 'LMB')
        hover = self.state.get('sub_strength_hover_target', 'STRENGTH')
        if hover == 'MODIFIER':
            value = self.settings.get_tool_modifier(context, mode, force_global=force_global, button=btn)
            self.settings.set_tool_modifier(context, mode, value - step, force_global=force_global, button=btn)
        elif hover == 'ALPHA':
            value = self.settings.get_tool_alpha(context, mode, force_global=force_global, button=btn)
            self.settings.set_tool_alpha(context, mode, value - step, force_global=force_global, button=btn)
        else:
            value = self.settings.get_tool_strength(context, mode, force_global=force_global, button=btn)
            self.settings.set_tool_strength(context, mode, value - step, force_global=force_global, button=btn)
        self.settings.apply_tool_runtime_settings(context, mode, force_global=force_global)
        context.area.tag_redraw()

    def on_mouse_left_press(self, context, event):
        self.on_exit(context, self.mode_name)
        context.area.tag_redraw()

    def on_mouse_right_press(self, context, event):
        self.on_cancel(context)
        self.on_exit(context, self.mode_name)
        context.area.tag_redraw()

    def on_key_e_press(self, context, event):
        """Toggle between editing LMB and RMB settings."""
        current = self.state.get('sub_edit_button', 'LMB')
        new_btn = 'RMB' if current == 'LMB' else 'LMB'
        self.state['sub_edit_button'] = new_btn
        # Capture originals for the newly selected button so cancel restores correctly.
        mode, force_global = self._tool_context(context)
        self.state['sub_orig_strength'] = self.settings.get_tool_strength(context, mode, force_global=force_global, button=new_btn)
        self.state['sub_orig_alpha'] = self.settings.get_tool_alpha(context, mode, force_global=force_global, button=new_btn)
        self.state['sub_orig_modifier'] = self.settings.get_tool_modifier(context, mode, force_global=force_global, button=new_btn)
        context.area.tag_redraw()
