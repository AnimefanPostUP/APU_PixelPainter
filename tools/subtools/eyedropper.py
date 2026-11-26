"""Hold-Ctrl eyedropper subtool: LMB picks primary, RMB picks secondary."""

import colorsys

from ...core.framework import HoldTool, Shortcut


class EyedropperTool(HoldTool):
    label = "Eyedropper"
    modifier = 'CTRL'
    exclusive = True  # no painting while Ctrl is held

    state_defaults = {
        'ctrl_pick_active':   False,
        'ctrl_hovered_color': None,
        'ctrl_region_x':      None,
        'ctrl_region_y':      None,
    }

    def on_register(self):
        self.bind(Shortcut('MOUSEMOVE', None), self._update_hover)
        self.bind(Shortcut('LEFTMOUSE'), lambda ctx, ev: self._pick(ctx, ev, secondary=False))
        self.bind(Shortcut('RIGHTMOUSE'), lambda ctx, ev: self._pick(ctx, ev, secondary=True))

    def on_activate(self, ctx, event):
        state = ctx.state
        state['ctrl_pick_active'] = True
        if event is not None:
            state['ctrl_region_x'] = event.mouse_region_x
            state['ctrl_region_y'] = event.mouse_region_y
        state['ctrl_hovered_color'] = ctx.image_color(*ctx.cursor)
        if event is not None and event.type in {'LEFTMOUSE', 'RIGHTMOUSE'} and event.is_press:
            self._pick(ctx, event, secondary=event.type == 'RIGHTMOUSE')
            event.consume()
        ctx.redraw()

    def on_deactivate(self, ctx):
        ctx.state['ctrl_pick_active'] = False
        ctx.state['ctrl_hovered_color'] = None
        ctx.redraw()

    def on_interrupt(self, ctx):
        self.deactivate(ctx)  # e.g. cursor left the image

    def draw_overlay(self, ctx):
        from ...overlays import sub_modes
        sub_modes.draw_ctrl_pick_overlay(ctx.context, ctx.state)

    def _update_hover(self, ctx, event):
        state = ctx.state
        state['ctrl_region_x'] = event.mouse_region_x
        state['ctrl_region_y'] = event.mouse_region_y
        state['ctrl_hovered_color'] = ctx.image_color(*ctx.cursor)
        ctx.redraw()

    def _pick(self, ctx, event, secondary):
        state = ctx.state
        if state.get('ctrl_hovered_color') is None and ctx.update_cursor(event) is not None:
            state['ctrl_hovered_color'] = ctx.image_color(*ctx.cursor)
        picked = state.get('ctrl_hovered_color')
        if picked is None:
            return
        if secondary:
            ctx.settings.set_brush_secondary_rgb(ctx.context, *picked)
        else:
            ctx.settings.set_brush_rgb(ctx.context, *picked)
            h, s, v = colorsys.rgb_to_hsv(*picked)
            state['sub_color_h'], state['sub_color_s'], state['sub_color_v'] = h, s, v
        ctx.redraw()
