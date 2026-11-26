"""Strength subtool (Shift+E): arc sliders for strength / modifier / alpha."""

import math

from ...core.framework import HoldTool, Shortcut, ToolFrame
from . import helpers


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


class StrengthTool(ToolFrame):
    """Modal strength/modifier editor. LMB confirms, RMB / Esc cancel, E toggles LMB/RMB settings."""

    label = "Strength"
    mode_name = 'STRENGTH'
    exclusive = True
    captures_input = True
    triggers = (Shortcut('E', shift=True, ctrl=False, alt=False),)

    state_defaults = {
        **helpers.SUB_MODE_STATE,
        'sub_strength_virtual_x': None,
        'sub_strength_virtual_y': None,
        'sub_strength_hover_target': 'STRENGTH',
        'sub_edit_button':    'LMB',  # which button's settings STRENGTH edits
        'sub_orig_strength':  None,
        'sub_orig_alpha':     None,
        'sub_orig_modifier':  None,
        'sub_total_delta':    0.0,
    }

    def on_register(self):
        # Shift is usually still held from Shift+E, so follow its state on any event.
        self.precision = self.add_subtool(HoldTool('SHIFT', activate_on_any_event=True))

        self.bind(Shortcut('MOUSEMOVE', None), self._on_mouse_move)
        self.bind(Shortcut('LEFTMOUSE'), self._confirm)
        self.bind(Shortcut(('RIGHTMOUSE', 'ESC')), self._cancel)
        self.bind(Shortcut('WHEELUPMOUSE', None), lambda ctx, ev: self._step_hovered(ctx, +1))
        self.bind(Shortcut('WHEELDOWNMOUSE', None), lambda ctx, ev: self._step_hovered(ctx, -1))
        self.bind(Shortcut('E'), self._toggle_button)

    @staticmethod
    def _tool_context(ctx):
        return ctx.mode, ctx.force_global

    def _capture_originals(self, ctx, button):
        state, settings, context = ctx.state, ctx.settings, ctx.context
        mode, force_global = self._tool_context(ctx)
        state['sub_orig_strength'] = settings.get_tool_strength(context, mode, force_global=force_global, button=button)
        state['sub_orig_alpha'] = settings.get_tool_alpha(context, mode, force_global=force_global, button=button)
        state['sub_orig_modifier'] = settings.get_tool_modifier(context, mode, force_global=force_global, button=button)

    # ---- lifecycle ---------------------------------------------------------------

    def on_activate(self, ctx, event):
        state = ctx.state
        state['sub_mode'] = self.mode_name
        state['sub_last_x'] = event.mouse_region_x
        state['sub_last_y'] = event.mouse_region_y
        state['sub_fake_cursor_x'] = event.mouse_region_x
        state['sub_fake_cursor_y'] = event.mouse_region_y
        state['sub_strength_virtual_x'] = float(event.mouse_region_x)
        state['sub_strength_virtual_y'] = float(event.mouse_region_y)
        state['sub_edit_button'] = 'LMB'
        self._capture_originals(ctx, 'LMB')
        state['sub_total_delta'] = 0.0
        state['sub_strength_hover_target'] = 'STRENGTH'
        helpers.set_sub_start_to_event(state, event)
        ctx.redraw()

    def on_deactivate(self, ctx):
        if ctx.state.get('sub_mode') == self.mode_name:
            ctx.state['sub_mode'] = None
        helpers.warp_cursor_to_sub_start(ctx.state, ctx.context)
        ctx.redraw()

    def draw_overlay(self, ctx):
        from ...paint import pixels as draw_functions
        draw_functions.draw_sub_mode_overlay(ctx.context, ctx.state)

    # ---- actions -------------------------------------------------------------------

    def _confirm(self, ctx, event):
        self.deactivate(ctx)

    def _cancel(self, ctx, event):
        state, settings, context = ctx.state, ctx.settings, ctx.context
        mode, force_global = self._tool_context(ctx)
        btn = state.get('sub_edit_button', 'LMB')
        settings.set_tool_strength(context, mode, state.get('sub_orig_strength'), force_global=force_global, button=btn)
        settings.set_tool_alpha(context, mode, state.get('sub_orig_alpha'), force_global=force_global, button=btn)
        settings.set_tool_modifier(context, mode, state.get('sub_orig_modifier'), force_global=force_global, button=btn)
        settings.apply_tool_runtime_settings(context, mode, force_global=force_global)
        self.deactivate(ctx)

    def _on_mouse_move(self, ctx, event):
        state, settings, context = ctx.state, ctx.settings, ctx.context
        dx = event.mouse_region_x - state['sub_last_x']
        dy = event.mouse_region_y - state['sub_last_y']
        state['sub_last_x'] = event.mouse_region_x
        state['sub_last_y'] = event.mouse_region_y

        vx = state.get('sub_strength_virtual_x')
        vy = state.get('sub_strength_virtual_y')
        if vx is None or vy is None:
            vx = float(event.mouse_region_x)
            vy = float(event.mouse_region_y)

        slow = _SHIFT_SLOW_FACTOR if self.precision.is_active else 1.0
        vx += dx / slow
        vy += dy / slow
        state['sub_strength_virtual_x'] = vx
        state['sub_strength_virtual_y'] = vy
        state['sub_fake_cursor_x'] = vx
        state['sub_fake_cursor_y'] = vy

        cx = state.get('sub_start_region_x')
        cy = state.get('sub_start_region_y')
        if cx is None or cy is None:
            return

        near_left = _is_near_arc_side(cx, cy, vx, vy, 'STRENGTH')
        near_right = _is_near_arc_side(cx, cy, vx, vy, 'MODIFIER')
        near_center = _is_near_center_circle(cx, cy, vx, vy)

        target = None
        if near_center:
            target = 'ALPHA'
        elif near_left and not near_right:
            target = 'STRENGTH'
        elif near_right and not near_left:
            target = 'MODIFIER'
        elif near_left and near_right:
            target = 'STRENGTH' if vx < cx else 'MODIFIER'

        if target is not None:
            mode, force_global = self._tool_context(ctx)
            btn = state.get('sub_edit_button', 'LMB')
            state['sub_strength_hover_target'] = target
            if target == 'STRENGTH':
                settings.set_tool_strength(context, mode, _strength_value_from_mouse_height(cy, vy),
                                           force_global=force_global, button=btn)
            elif target == 'MODIFIER':
                settings.set_tool_modifier(context, mode, _value_from_mouse_height(cy, vy),
                                           force_global=force_global, button=btn)
            # ALPHA is intentionally not changed by mouse movement.
            settings.apply_tool_runtime_settings(context, mode, force_global=force_global)

        helpers.wrap_cursor_at_window_edge(state, context, event)
        ctx.redraw()

    def _step_hovered(self, ctx, direction):
        state, settings, context = ctx.state, ctx.settings, ctx.context
        step = direction * (0.01 if self.precision.is_active else 0.05)
        mode, force_global = self._tool_context(ctx)
        btn = state.get('sub_edit_button', 'LMB')
        channel = {'MODIFIER': 'modifier', 'ALPHA': 'alpha'}.get(
            state.get('sub_strength_hover_target', 'STRENGTH'), 'strength')
        getter = getattr(settings, f'get_tool_{channel}')
        setter = getattr(settings, f'set_tool_{channel}')
        value = getter(context, mode, force_global=force_global, button=btn)
        setter(context, mode, value + step, force_global=force_global, button=btn)
        settings.apply_tool_runtime_settings(context, mode, force_global=force_global)
        ctx.redraw()

    def _toggle_button(self, ctx, event):
        """Switch between editing the LMB and RMB settings."""
        state = ctx.state
        new_btn = 'RMB' if state.get('sub_edit_button', 'LMB') == 'LMB' else 'LMB'
        state['sub_edit_button'] = new_btn
        self._capture_originals(ctx, new_btn)  # so cancel restores the right button
        ctx.redraw()
