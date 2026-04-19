"""Outline and visual overlay primitives separated from paint core logic."""

import math
import time

import gpu
import gpu_extras.batch

from ..utils import blender_utils
from ..utils import math_utils


def _gpu_draw_lines(vertices, color):
    """Render GPU lines with alpha blending in screen space."""
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')
    gpu.state.line_width_set(1.5)
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = gpu_extras.batch.batch_for_shader(shader, 'LINES', {"pos": vertices})
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('LESS_EQUAL')


def _edges_to_screen_verts(edges, v2d, w, h, offset_x=0.0, offset_y=0.0):
    """Convert image-space edge pairs to rounded screen-space vertices."""
    vertices = []
    for (px0, py0), (px1, py1) in edges:
        sx0, sy0 = v2d.view_to_region((px0 + offset_x) / w, (py0 + offset_y) / h)
        sx1, sy1 = v2d.view_to_region((px1 + offset_x) / w, (py1 + offset_y) / h)
        vertices.append((round(sx0), round(sy0)))
        vertices.append((round(sx1), round(sy1)))
    return vertices


def _draw_precision_pixel_guide(context, px, py, color=(1.0, 1.0, 1.0, 0.85)):
    """Draw corner brackets around one image pixel for precise targeting."""
    space, img = blender_utils.get_space_img(context)
    if not space or not img:
        return

    w, h = img.size
    if w == 0 or h == 0:
        return

    _, v2d = blender_utils.get_window_region_and_v2d(context.area)
    if not v2d:
        return

    x0 = px / w
    y0 = py / h
    x1 = (px + 1) / w
    y1 = (py + 1) / h

    t = 0.2
    sx0, sy0 = v2d.view_to_region(x0, y0)
    sx1, sy1 = v2d.view_to_region(x1, y1)
    if sx0 is None or sy0 is None or sx1 is None or sy1 is None:
        return

    left = min(sx0, sx1)
    right = max(sx0, sx1)
    bot = min(sy0, sy1)
    top = max(sy0, sy1)

    dx = right - left
    dy = top - bot
    hx = dx * t
    hy = dy * t

    verts = [
        (left, bot), (left + hx, bot),
        (right - hx, bot), (right, bot),
        (left, top), (left + hx, top),
        (right - hx, top), (right, top),
        (left, bot), (left, bot + hy),
        (left, top - hy), (left, top),
        (right, bot), (right, bot + hy),
        (right, top - hy), (right, top),
    ]

    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')
    gpu.state.line_width_set(1.0)
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = gpu_extras.batch.batch_for_shader(shader, 'LINES', {"pos": verts})
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('LESS_EQUAL')


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
        te = t * t * (3.0 - 2.0 * t)
        cx = from_cx + (to_cx - from_cx) * te
        cy = from_cy + (to_cy - from_cy) * te
        state['outline_display_cx'] = cx
        state['outline_display_cy'] = cy

    space = context.space_data
    if not space or not space.image:
        return

    wm = context.window_manager
    radius = blender_utils.get_brush_image_radius(context)
    mode = wm.pixel_painter_mode
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

    outline_color = {
        'SPRAY': (1.0, 0.55, 0.0, 0.9),
        'SMEAR': (1.0, 0.2, 0.2, 0.9),
        'SMOOTH': (0.7, 0.3, 1.0, 0.9),
    }.get(mode, (1.0, 1.0, 0.0, 0.9))

    def _outline_pixels_at(ix, iy):
        if mode == 'LINE':
            shape = state.get('last_shape') or 'SQUARE'
            tip_shape = 'CIRCLE' if shape == 'SPRAY' else shape
            if state['start_position'] is None:
                return math_utils.get_pixels_in_shape(ix, iy, radius, tip_shape)

            x0, y0 = state['start_position']
            pixels = set()
            for (lx, ly) in math_utils.get_line_pixels(x0, y0, ix, iy):
                pixels |= math_utils.get_pixels_in_shape(lx, ly, radius, tip_shape)
            return pixels

        outline_mode = 'CIRCLE' if mode == 'SPRAY' else mode
        return math_utils.get_pixels_in_shape(ix, iy, radius, outline_mode)

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

    vertices = _edges_to_screen_verts(edges, v2d, w, h, offset_x=frac_x, offset_y=frac_y)
    _gpu_draw_lines(vertices, outline_color)

    _draw_precision_pixel_guide(context, state['current_cx'], state['current_cy'])
