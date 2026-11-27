"""MaskTool: the global tool that picks mask elements on the canvas (while state
``mask_picking`` is on) and keeps the mask data fresh.
"""



from ...core.framework import Shortcut, ToolFrame
from ...core.view3d import elements
from ...overlays import element_outline
from ...overlays.cursor import draw_pick_cursor
from .. import pickers
from .data import active, element_at, is_chosen, refresh, selection, set_chosen
from .overlay import draw_edit_frame, draw_hint


# ---------------------------------------------------------------------------
# Picking tool
# ---------------------------------------------------------------------------

def redraw_editors(context):
    try:
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type in {'IMAGE_EDITOR', 'VIEW_3D'}:
                    area.tag_redraw()
    except Exception:
        pass


HOVER_COLOR = (1.0, 0.55, 0.15, 1.0)   # the edit frame's orange (ui/viewport_frame.MASK_EDIT_COLOR)


def _picking(state):
    return bool(state.get('mask_picking'))


def update_hover(ctx):
    """Outline the island / part under the cursor (the mask's source); True when it changed."""
    source = getattr(ctx.wm, 'pixel_painter_mask_source', 'UV_ISLAND')
    try:
        emap = elements.element_map(ctx.context, ctx.image, source)
    except Exception:
        import traceback
        traceback.print_exc()
        emap = None
    return element_outline.set_hover('MASK', _picking, emap, elements.label_under(ctx, emap), HOVER_COLOR)


def release(state):
    """Stop choosing elements (also when another canvas picker starts, tools/pickers.py)."""
    state['mask_picking'] = False
    state['mask_pick_value'] = None
    element_outline.clear('MASK')


pickers.register('MASK', release)


def set_picking(state, context, on):
    """Start / stop choosing elements on the canvas (starting also turns the mask on and
    stops the other canvas pickers)."""
    if not on:
        release(state)
    else:
        pickers.claim(state, 'MASK')
        state['mask_picking'] = True
        state['mask_pick_value'] = None
        wm = context.window_manager
        if not active(wm):
            wm.pixel_painter_mask_enabled = True
    redraw_editors(context)


class MaskTool(ToolFrame):
    """Global tool: element picking on the canvas, keeps the mask data fresh, draws the overlay."""

    label = "Mask"
    is_global = True
    priority = 150              # after the pen bar (its buttons win), before tool shortcuts

    state_defaults = {
        'mask_picking': False,     # canvas presses toggle islands / parts
        'mask_pick_value': None,   # True / False while a pick drag sets elements to it
    }

    def on_register(self):
        self.bind(Shortcut('LEFTMOUSE'), self._press)
        self.bind(Shortcut('LEFTMOUSE', 'RELEASE'), self._release)
        self.bind(Shortcut(('ESC', 'RIGHTMOUSE')), self._stop)

    def holds_mouse(self, ctx):
        return _picking(ctx.state)     # secondary tool while editing the mask

    def on_interrupt(self, ctx):
        ctx.state['mask_pick_value'] = None

    def on_session_end(self, ctx):
        release(ctx.state)

    def _apply(self, ctx, value=None):
        """Toggle (``value`` None) or set the element under the cursor; returns its new state."""
        img = ctx.image
        mask_data = refresh(ctx.context, img, force=value is None)
        element = element_at(mask_data, *ctx.cursor)
        if element is None:
            return None
        chosen = is_chosen(element, selection(ctx.context))
        target = (not chosen) if value is None else value
        if target != chosen:
            set_chosen(ctx.context, element, target)
            redraw_editors(ctx.context)
        return target

    def _press(self, ctx, event):
        if not ctx.state.get('mask_picking'):
            return False
        ctx.state['mask_pick_value'] = self._apply(ctx)
        return True

    def _release(self, ctx, event):
        if not ctx.state.get('mask_picking'):
            return False
        ctx.state['mask_pick_value'] = None
        return True

    def _stop(self, ctx, event):
        if not ctx.state.get('mask_picking') or not event.is_press:
            return False
        set_picking(ctx.state, ctx.context, False)
        return True

    def on_event(self, ctx, event):
        if event.type != 'MOUSEMOVE':
            return
        if ctx.state.get('mask_picking') and update_hover(ctx):
            ctx.redraw()
        value = ctx.state.get('mask_pick_value')
        if ctx.state.get('mask_picking') and value is not None:
            self._apply(ctx, value)
            event.consume()
        elif active(ctx.wm):
            refresh(ctx.context, ctx.image)

    def draw_overlay(self, ctx):
        # The shading itself is drawn by the core under all tool overlays (draw_2d / draw_3d).
        if not ctx.state.get('mask_picking'):
            return
        draw_pick_cursor(ctx.context, ctx.state, HOVER_COLOR)   # its own cursor (secondary tool)
        draw_edit_frame(ctx.context)
        if not getattr(ctx.wm, 'pixel_painter_pen_bar', False):
            draw_hint(ctx.context)
