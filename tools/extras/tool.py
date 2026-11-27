"""ExtrasTool: the global tool behind the Extras window. While one of its tools is
armed (state ``extras_mode``: 'FILL' / 'EDGES' / 'AO'), the island / part under the
cursor is outlined and a canvas press runs the tool on it (LMB: primary, RMB:
secondary color first). Esc ends it; the window's *All* runs it on every element.
"""

import traceback

from ...core.framework import Shortcut, ToolFrame
from ...core.view3d import elements
from ...overlays import element_outline
from ...overlays.cursor import draw_pick_cursor
from . import operations


HOVER_COLOR = (0.35, 0.95, 1.0, 1.0)
HINTS = {'FILL': "Fill", 'EDGES': "Edges", 'AO': "Ambient Occlusion"}


def armed(state):
    return state.get('extras_mode') in operations.MODES


def source(wm):
    return getattr(wm, 'pixel_painter_extras_source', 'UV_ISLAND')


def element_map(ctx):
    try:
        return elements.element_map(ctx.context, ctx.image, source(ctx.wm))
    except Exception:
        traceback.print_exc()
        return None


def set_mode(state, mode):
    """Arm ``mode`` (None: disarm). Arming ends mask editing (one canvas picker at a time)."""
    mode = mode if mode in operations.MODES else None
    state['extras_mode'] = mode
    if mode is None:
        element_outline.clear('EXTRAS')
    else:
        state['mask_picking'] = False
        state['mask_pick_value'] = None
        element_outline.clear('MASK')


def run(ctx, mode, label, secondary=False):
    """Run ``mode`` on element ``label`` (None: all); stores the status text."""
    try:
        status = operations.run(ctx, mode, element_map(ctx), label, secondary)
    except Exception:
        traceback.print_exc()
        status = f"{HINTS.get(mode, mode)}: failed (see the console)"
    if status is None:
        status = "No mesh with UVs for this image"
    ctx.state['extras_status'] = status
    ctx.redraw()
    return status


class ExtrasTool(ToolFrame):
    """Global tool: runs the armed Extras tool on the element under the cursor."""

    label = "Extras"
    is_global = True
    priority = 140              # after the pen bar and the mask picker, before tool shortcuts

    state_defaults = {
        'extras_mode': None,     # the armed Extras tool: 'FILL' / 'EDGES' / 'AO'
        'extras_status': None,   # result of the last run (shown in the window)
    }

    def on_register(self):
        self.bind(Shortcut('LEFTMOUSE'), lambda ctx, ev: self._press(ctx, ev, False))
        self.bind(Shortcut('RIGHTMOUSE'), lambda ctx, ev: self._press(ctx, ev, True))
        self.bind(Shortcut(('LEFTMOUSE', 'RIGHTMOUSE'), 'RELEASE'), self._release)
        self.bind(Shortcut('ESC'), self._stop)

    def holds_mouse(self, ctx):
        return armed(ctx.state)        # secondary tool while an Extras tool is armed

    def on_session_end(self, ctx):
        set_mode(ctx.state, None)

    def _press(self, ctx, event, secondary):
        mode = ctx.state.get('extras_mode')
        if mode not in operations.MODES:
            return False
        emap = element_map(ctx)
        label = elements.label_under(ctx, emap)
        if label is not None:
            run(ctx, mode, label, secondary)
        return True     # armed: a press never paints with the brush

    def _release(self, ctx, event):
        return armed(ctx.state)

    def _stop(self, ctx, event):
        if not armed(ctx.state) or not event.is_press:
            return False
        set_mode(ctx.state, None)
        ctx.redraw()
        return True

    def on_event(self, ctx, event):
        if event.type != 'MOUSEMOVE' or not armed(ctx.state):
            return
        emap = element_map(ctx)
        if element_outline.set_hover('EXTRAS', armed, emap, elements.label_under(ctx, emap), HOVER_COLOR):
            ctx.redraw()

    def draw_overlay(self, ctx):
        mode = ctx.state.get('extras_mode')
        if mode not in operations.MODES:
            return
        draw_pick_cursor(ctx.context, ctx.state, HOVER_COLOR)   # its own cursor (secondary tool)
        if getattr(ctx.wm, 'pixel_painter_pen_bar', False):
            return
        from ..mask.overlay import draw_hint
        draw_hint(ctx.context, f"{HINTS[mode]}: tap an island / part (RMB: secondary color)  ·  Esc: done")
