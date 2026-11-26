"""Outline and visual overlay primitives separated from paint core logic."""

import math
import time


from ..core.state import declare as declare_state
from ..ui.kit import anim
from ..utils import blender_utils
from ..utils import math_utils
from .gpu_prims import draw_lines, draw_precision_pixel_guide, edges_to_screen_verts


# Brush outline position tween.
declare_state({
    'outline_display_cx': None,
    'outline_display_cy': None,
    'outline_from_cx':    None,
    'outline_from_cy':    None,
    'outline_to_cx':      None,
    'outline_to_cy':      None,
    'outline_anim_start': 0.0,
})


def draw_brush_outline(context, state):
    """Draw animated brush outline and precision guide from shared state.

    This function mirrors the old inline implementation while living in its
    own module so future overlays can be added independently.
    """
    if state.get('sub_mode') or state.get('ctrl_pick_active'):
        return

    cx = state['current_cx']
    cy = state['current_cy']
    if cx is None or cy is None:
        state['outline_display_cx'] = None
        state['outline_display_cy'] = None
        state['outline_from_cx'] = None
        state['outline_from_cy'] = None
        state['outline_to_cx'] = None
        state['outline_to_cy'] = None
        return

    if state.get('outline_immediate'):
        cx = float(cx)
        cy = float(cy)
        state['outline_display_cx'] = cx
        state['outline_display_cy'] = cy
        state['outline_from_cx'] = cx
        state['outline_from_cy'] = cy
        state['outline_to_cx'] = cx
        state['outline_to_cy'] = cy
        state['outline_anim_start'] = time.perf_counter()
    else:
        now = time.perf_counter()
        display_cx = state.get('outline_display_cx')
        display_cy = state.get('outline_display_cy')
        target_cx = state.get('outline_to_cx')
        target_cy = state.get('outline_to_cy')

        if display_cx is None or display_cy is None:
            display_cx = float(cx)
            display_cy = float(cy)
            state['outline_display_cx'] = display_cx
            state['outline_display_cy'] = display_cy
            state['outline_from_cx'] = display_cx
            state['outline_from_cy'] = display_cy
            state['outline_to_cx'] = float(cx)
            state['outline_to_cy'] = float(cy)
            state['outline_anim_start'] = now
        elif target_cx != float(cx) or target_cy != float(cy):
            nx = float(cx)
            ny = float(cy)
            dx = nx - display_cx
            dy = ny - display_cy
            if (dx * dx + dy * dy) < 4.0:
                state['outline_from_cx'] = display_cx
                state['outline_from_cy'] = display_cy
                state['outline_to_cx'] = nx
                state['outline_to_cy'] = ny
                state['outline_anim_start'] = now
            else:
                state['outline_from_cx'] = nx
                state['outline_from_cy'] = ny
                state['outline_to_cx'] = nx
                state['outline_to_cy'] = ny
                state['outline_display_cx'] = nx
                state['outline_display_cy'] = ny
                state['outline_anim_start'] = now

        from_cx = state.get('outline_from_cx', float(cx))
        from_cy = state.get('outline_from_cy', float(cy))
        to_cx = state.get('outline_to_cx', float(cx))
        to_cy = state.get('outline_to_cy', float(cy))
        t = min(1.0, max(0.0, (now - state.get('outline_anim_start', now)) / 0.018))
        if t < 1.0:
            anim.request_frame()   # the tween still runs: the session timer redraws
        te = t * t * (3.0 - 2.0 * t)
        cx = from_cx + (to_cx - from_cx) * te
        cy = from_cy + (to_cy - from_cy) * te
        state['outline_display_cx'] = cx
        state['outline_display_cy'] = cy

    space = context.space_data
    if not space or not space.image:
        return

    from ..tools.catalog import TOOLS

    wm = context.window_manager
    radius = blender_utils.get_brush_image_radius(context)
    tool = TOOLS.get(wm.pixel_painter_mode)
    if not tool.shows_brush_outline:
        return
    w, h = space.image.size
    if w == 0 or h == 0:
        return

    area = context.area
    if not area:
        return
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    if not region:
        return
    v2d = region.view2d

    outline_color = tool.outline_color

    def _outline_pixels_at(ix, iy):
        return tool.outline_pixels(state, ix, iy, radius)

    if state.get('outline_immediate'):
        base_ix = round(cx)
        base_iy = round(cy)
        frac_x = 0.0
        frac_y = 0.0
    else:
        base_ix = math.floor(cx)
        base_iy = math.floor(cy)
        frac_x = cx - base_ix
        frac_y = cy - base_iy

    pixels = _outline_pixels_at(base_ix, base_iy)
    edges = math_utils.get_outline_edges(pixels)
    if not edges:
        return

    vertices = edges_to_screen_verts(edges, v2d, w, h, offset_x=frac_x, offset_y=frac_y)
    draw_lines(vertices, outline_color)

    draw_precision_pixel_guide(context, state['current_cx'], state['current_cy'])


