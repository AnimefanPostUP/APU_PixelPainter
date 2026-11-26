"""Pen variant of the eyedropper, started from the pen bar (no shortcut).

Works with one continuous touch: the press that opens it is already on the
canvas, dragging aims, lifting the pen picks. (The pen's color selector is
the color pad on the pen bar, see ``ui.pen.bar``.)
"""

import colorsys

from ...core.framework import Shortcut, ToolFrame
from ..subtools.eyedropper import EyedropperTool


def _paints_secondary(ctx):
    """The color to pick: the pen bar's picker sets ``pen_pick_target``; without it
    the RMB lock decides (the pen tip paints, and picks, the secondary color)."""
    target = ctx.state.get('pen_pick_target')
    if target is not None:
        return target == 'SECONDARY'
    if ctx.state.get('pen_tertiary'):   # tertiary selected: the color the selector edits
        return ctx.state.get('pen_color_target') == 'SECONDARY'
    return bool(ctx.state.get('pen_rmb_lock'))


class PenEyedropperTool(ToolFrame):
    """Press shows the color under the pen, drag to aim, lift to pick. RMB / Esc cancel."""

    label = "Pen Eyedropper"
    exclusive = True
    captures_input = True
    triggers = ()  # started by the pen bar

    state_defaults = dict(EyedropperTool.state_defaults)  # shares the Ctrl-eyedropper overlay

    def on_register(self):
        self.bind(Shortcut('MOUSEMOVE', None), self._hover)
        self.bind(Shortcut('LEFTMOUSE', 'RELEASE'), self._pick)
        self.bind(Shortcut(('RIGHTMOUSE', 'ESC')), lambda ctx, ev: self.deactivate(ctx))

    def on_activate(self, ctx, event):
        ctx.state['ctrl_pick_active'] = True
        if event is not None:
            self._hover(ctx, event)

    def on_deactivate(self, ctx):
        ctx.state['pen_pick_target'] = None
        ctx.state['ctrl_pick_active'] = False
        ctx.state['ctrl_hovered_color'] = None
        ctx.redraw()

    def on_interrupt(self, ctx):
        self.deactivate(ctx)

    def draw_overlay(self, ctx):
        from ...overlays import sub_modes
        sub_modes.draw_ctrl_pick_overlay(ctx.context, ctx.state)

    def _hover(self, ctx, event):
        state = ctx.state
        ctx.update_cursor(event)  # captures input: the core does not track the cursor for us
        mouse = ctx.mouse_region(event)
        if mouse is not None:
            state['ctrl_region_x'], state['ctrl_region_y'] = mouse
        state['ctrl_hovered_color'] = ctx.image_color(*ctx.cursor)
        ctx.redraw()

    def _pick(self, ctx, event):
        # Use the color aimed at before lifting (the release position can jitter).
        picked = ctx.state.get('ctrl_hovered_color')
        if picked is not None:
            if _paints_secondary(ctx):
                ctx.settings.set_brush_secondary_rgb(ctx.context, *picked)
            else:
                ctx.settings.set_brush_rgb(ctx.context, *picked)
                h, s, v = colorsys.rgb_to_hsv(*picked)
                ctx.state['sub_color_h'], ctx.state['sub_color_s'], ctx.state['sub_color_v'] = h, s, v
        self.deactivate(ctx)

