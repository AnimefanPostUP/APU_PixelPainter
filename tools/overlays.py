"""Outline and visual overlay primitives separated from paint core logic."""

import math
import time

import blf
import gpu
import numpy as np
import gpu_extras.batch

from ..tools import draw_functions
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


def _gpu_draw_filled_rect(x0, y0, x1, y1, color):
    verts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = gpu_extras.batch.batch_for_shader(shader, 'TRI_FAN', {"pos": verts})
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('LESS_EQUAL')


def _gpu_draw_filled_circle(cx, cy, radius, color, segments=40):
    verts = [(cx, cy)]
    for index in range(segments + 1):
        angle = (2.0 * math.pi * index) / segments
        verts.append((cx + math.cos(angle) * radius, cy + math.sin(angle) * radius))
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = gpu_extras.batch.batch_for_shader(shader, 'TRI_FAN', {"pos": verts})
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('LESS_EQUAL')


def _gpu_draw_circle_outline(cx, cy, radius, color, segments=40):
    verts = []
    for index in range(segments + 1):
        angle = (2.0 * math.pi * index) / segments
        verts.append((cx + math.cos(angle) * radius, cy + math.sin(angle) * radius))
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')
    gpu.state.line_width_set(1.5)
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = gpu_extras.batch.batch_for_shader(shader, 'LINE_STRIP', {"pos": verts})
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
    if mode == 'SELECT':
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

    outline_color = {
        'SPRAY': (1.0, 0.55, 0.0, 0.9),
        'SMEAR': (1.0, 0.3, 0.7, 0.9),   # pink
        'SMOOTH': (0.7, 0.3, 1.0, 0.9),
        'ERASER': (1.0, 0.1, 0.1, 0.9),  # red
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


def _gpu_draw_fill(vertices, color):
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = gpu_extras.batch.batch_for_shader(shader, 'TRI_FAN', {"pos": vertices})
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('LESS_EQUAL')


def _selection_screen_rect(v2d, width, height, box, state=None):
    left, bottom, right, top = box
    corners = [
        (left / width, bottom / height),
        ((right + 1) / width, bottom / height),
        ((right + 1) / width, (top + 1) / height),
        (left / width, (top + 1) / height),
    ]
    points = [v2d.view_to_region(u, v) for u, v in corners]
    if any(px is None or py is None for px, py in points):
        return None
    xs = [round(px) for px, _ in points]
    ys = [round(py) for _, py in points]
    return min(xs), min(ys), max(xs), max(ys)


def _draw_arrow_handle(cx, cy, handle_id, color, highlighted=False, active=False):
    is_move = handle_id == 'MOVE'
    radius = 9.5 if is_move else 8.0
    outline_radius = radius + 1.8
    inner_radius = max(2.5, radius * 0.38)

    fill = (0.13, 0.15, 0.18, 0.72)
    outline = color
    inner = (1.0, 1.0, 1.0, 0.18)

    if handle_id in {'N', 'S', 'E', 'W'}:
        fill = (0.12, 0.14, 0.17, 0.70)
    elif handle_id in {'NW', 'NE', 'SE', 'SW'}:
        fill = (0.10, 0.12, 0.16, 0.74)

    if highlighted:
        fill = (fill[0] + 0.12, fill[1] + 0.12, fill[2] + 0.12, min(0.92, fill[3] + 0.12))
        inner = (1.0, 1.0, 1.0, 0.32)

    if active:
        fill = (fill[0] + 0.10, fill[1] + 0.08, fill[2] + 0.04, min(0.96, fill[3] + 0.10))
        inner = (1.0, 0.98, 0.92, 0.40)

    _gpu_draw_filled_circle(cx, cy, radius, fill, segments=32)
    _gpu_draw_circle_outline(cx, cy, outline_radius, outline, segments=36)
    _gpu_draw_filled_circle(cx, cy, inner_radius, inner, segments=24)


def _draw_text_centered(text, x, y, size=12, alpha=1.0):
    font_id = 0
    blf.size(font_id, size)
    width, height = blf.dimensions(font_id, text)
    blf.position(font_id, x - width * 0.5, y - height * 0.5, 0)
    blf.color(font_id, 1.0, 1.0, 1.0, alpha)
    blf.draw(font_id, text)


def _draw_selection_pixel_preview(state, rect):
    region = state.get('selection_pending_region')
    if region is None:
        return
    region_h, region_w = region.shape[:2]
    if region_w <= 0 or region_h <= 0:
        return

    left, bottom, right, top = rect
    width = max(1.0, float(right - left))
    height = max(1.0, float(top - bottom))
    cell_w = width / float(region_w)
    cell_h = height / float(region_h)

    vertices = []
    colors = []
    for row in range(region_h):
        y0 = bottom + row * cell_h
        y1 = bottom + (row + 1) * cell_h
        for col in range(region_w):
            x0 = left + col * cell_w
            x1 = left + (col + 1) * cell_w
            rgba = region[row, col]
            color = (float(rgba[0]), float(rgba[1]), float(rgba[2]), float(rgba[3]))
            vertices += [(x0, y0), (x1, y0), (x1, y1), (x0, y0), (x1, y1), (x0, y1)]
            colors += [color, color, color, color, color, color]

    if not vertices:
        return

    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')
    shader = gpu.shader.from_builtin('SMOOTH_COLOR')
    batch = gpu_extras.batch.batch_for_shader(shader, 'TRIS', {"pos": vertices, "color": colors})
    batch.draw(shader)
    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('LESS_EQUAL')


def _selection_preview_composite_region(context, box, source_region):
    if source_region is None or box is None:
        return None

    space, img = blender_utils.get_space_img(context)
    if not space or not img:
        return source_region.copy()

    blend = blender_utils.get_brush_blend_mode(context)
    strength = float(getattr(context.window_manager, 'pixel_painter_active_strength', 1.0))
    width, height = img.size
    dest_left, dest_bottom, dest_right, dest_top = box
    region_h, region_w = source_region.shape[:2]
    target_w = max(1, dest_right - dest_left + 1)
    target_h = max(1, dest_top - dest_bottom + 1)
    clip_left = max(0, dest_left)
    clip_bottom = max(0, dest_bottom)
    clip_right = min(width - 1, dest_right)
    clip_top = min(height - 1, dest_top)

    if target_w == region_w and target_h == region_h:
        preview = source_region.copy()
    else:
        x_idx = np.rint(np.linspace(0, max(0, region_w - 1), target_w)).astype(np.int32)
        y_idx = np.rint(np.linspace(0, max(0, region_h - 1), target_h)).astype(np.int32)
        preview = source_region[np.ix_(y_idx, x_idx)].copy()

    if clip_right < clip_left or clip_top < clip_bottom:
        return preview

    arr = np.array(img.pixels, dtype=np.float32).reshape(height, width, 4)
    src_y0 = clip_bottom - dest_bottom
    src_y1 = src_y0 + (clip_top - clip_bottom + 1)
    src_x0 = clip_left - dest_left
    src_x1 = src_x0 + (clip_right - clip_left + 1)
    dst_slice = arr[clip_bottom:clip_top + 1, clip_left:clip_right + 1, :]
    src_slice = source_region[src_y0:src_y1, src_x0:src_x1, :]
    scaled_src_slice = preview[src_y0:src_y1, src_x0:src_x1, :]
    blended = draw_functions.blend_region_pixels(dst_slice, scaled_src_slice, blend, strength)
    preview[src_y0:src_y1, src_x0:src_x1, :] = blended
    return preview


def _selection_stencil_box_from_state(state):
    region = state.get('selection_stencil_region')
    if region is None:
        return None
    current_cx = state.get('current_cx')
    current_cy = state.get('current_cy')
    if current_cx is None or current_cy is None:
        return state.get('selection_box')
    region_h, region_w = region.shape[:2]
    if region_w <= 0 or region_h <= 0:
        return None
    left = int(round(current_cx - (region_w - 1) * 0.5))
    bottom = int(round(current_cy - (region_h - 1) * 0.5))
    return (left, bottom, left + region_w - 1, bottom + region_h - 1)


def _selection_button_layout(rect, state):
    left, bottom, right, top = rect
    gap = 10
    button_size = 34
    copy_w = button_size
    paste_w = button_size
    stencil_w = button_size
    center_x = (left + right) * 0.5
    row1_total = copy_w + gap + paste_w + gap + stencil_w
    row1_start = center_x - row1_total * 0.5
    y1 = bottom - 26
    y0 = y1 - button_size

    copy_rect = (row1_start, y0, row1_start + copy_w, y1)
    paste_rect = (row1_start + copy_w + gap, y0, row1_start + copy_w + gap + paste_w, y1)
    stencil_rect = (row1_start + copy_w + gap + paste_w + gap, y0, row1_start + row1_total, y1)
    return copy_rect, paste_rect, stencil_rect


def _draw_selection_button(rect, label, active=False):
    x0, y0, x1, y1 = rect
    cx = (x0 + x1) * 0.5
    cy = (y0 + y1) * 0.5
    radius = min(x1 - x0, y1 - y0) * 0.5
    fill = (0.16, 0.16, 0.16, 0.9)
    border = (0.75, 0.75, 0.75, 0.95)
    if active:
        fill = (0.22, 0.35, 0.22, 0.95)
        border = (0.4, 1.0, 0.5, 0.95)
    _gpu_draw_filled_circle(cx, cy, radius, fill)
    _gpu_draw_circle_outline(cx, cy, radius, border)
    _draw_text_centered(label, cx, cy, size=10, alpha=1.0)


def _draw_selection_cross_cursor(context, state):
    if state.get('sub_mode') or state.get('ctrl_pick_active'):
        return
    current_x = state.get('current_cx')
    current_y = state.get('current_cy')
    if current_x is None or current_y is None:
        return

    space, img = blender_utils.get_space_img(context)
    if not space or not img:
        return
    width, height = img.size
    if width == 0 or height == 0:
        return

    area = context.area
    if not area:
        return
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    if not region:
        return

    v2d = region.view2d
    left_top = v2d.view_to_region(current_x / width, (current_y + 1) / height)
    right_bottom = v2d.view_to_region((current_x + 1) / width, current_y / height)
    if left_top[0] is None or left_top[1] is None or right_bottom[0] is None or right_bottom[1] is None:
        return

    left = min(left_top[0], right_bottom[0])
    right = max(left_top[0], right_bottom[0])
    bottom = min(left_top[1], right_bottom[1])
    top = max(left_top[1], right_bottom[1])
    center_x = (left + right) * 0.5
    center_y = (bottom + top) * 0.5
    inset_x = max(1.0, (right - left) * 0.22)
    inset_y = max(1.0, (top - bottom) * 0.22)
    _gpu_draw_lines([
        (left + inset_x, center_y), (right - inset_x, center_y),
        (center_x, bottom + inset_y), (center_x, top - inset_y),
    ], (1.0, 1.0, 1.0, 0.95))


def draw_selection_overlay(context, state):
    if context.window_manager.pixel_painter_mode != 'SELECT':
        state['selection_apply_button_bounds'] = None
        state['selection_copy_button_bounds'] = None
        state['selection_stencil_button_bounds'] = None
        return
    if state.get('sub_mode') or state.get('ctrl_pick_active'):
        return

    box = state.get('selection_box')
    if not box:
        state['selection_apply_button_bounds'] = None
        state['selection_copy_button_bounds'] = None
        state['selection_stencil_button_bounds'] = None
        return

    space, img = blender_utils.get_space_img(context)
    if not space or not img:
        state['selection_apply_button_bounds'] = None
        state['selection_copy_button_bounds'] = None
        state['selection_stencil_button_bounds'] = None
        return
    width, height = img.size
    if width == 0 or height == 0:
        state['selection_apply_button_bounds'] = None
        state['selection_copy_button_bounds'] = None
        state['selection_stencil_button_bounds'] = None
        return

    area = context.area
    if not area:
        state['selection_apply_button_bounds'] = None
        state['selection_copy_button_bounds'] = None
        state['selection_stencil_button_bounds'] = None
        return
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    if not region:
        state['selection_apply_button_bounds'] = None
        state['selection_copy_button_bounds'] = None
        state['selection_stencil_button_bounds'] = None
        return

    rect = _selection_screen_rect(region.view2d, width, height, box, state)
    if rect is None:
        state['selection_apply_button_bounds'] = None
        state['selection_copy_button_bounds'] = None
        state['selection_stencil_button_bounds'] = None
        return

    left, bottom, right, top = rect
    preview_region = None
    if state.get('selection_stencil_mode') and state.get('selection_stencil_region') is not None:
        preview_region = _selection_preview_composite_region(context, box, state.get('selection_stencil_region'))
    elif state.get('selection_pending_region') is not None:
        preview_region = _selection_preview_composite_region(context, box, state.get('selection_pending_region'))
    state['selection_overlay_region'] = preview_region
    if preview_region is not None:
        preview_state = dict(state)
        preview_state['selection_pending_region'] = preview_region
        _draw_selection_pixel_preview(preview_state, rect)

    _gpu_draw_fill([(left, bottom), (right, bottom), (right, top), (left, top)], (0.18, 0.52, 0.96, 0.10))
    _gpu_draw_lines([
        (left, bottom), (right, bottom),
        (right, bottom), (right, top),
        (right, top), (left, top),
        (left, top), (left, bottom),
    ], (0.50, 0.82, 1.0, 0.95))

    center_x = (left + right) * 0.5
    center_y = (bottom + top) * 0.5
    handles = {
        'NW': (left, top),
        'N': (center_x, top),
        'NE': (right, top),
        'E': (right, center_y),
        'SE': (right, bottom),
        'S': (center_x, bottom),
        'SW': (left, bottom),
        'W': (left, center_y),
        'MOVE': (center_x, center_y),
    }
    hover = state.get('selection_hover_handle')
    active = state.get('selection_active_handle')
    if state.get('selection_stencil_mode'):
        hover = None
        active = None
    if state.get('selection_pending_action') is not None:
        hover = None
        active = None
    for handle_id, (hx, hy) in handles.items():
        color = (0.84, 0.92, 1.0, 0.72)
        highlighted = False
        active_state = False
        if handle_id == hover:
            color = (1.0, 0.88, 0.22, 0.98)
            highlighted = True
        if handle_id == active:
            color = (1.0, 0.56, 0.18, 1.0)
            highlighted = True
            active_state = True
        _draw_arrow_handle(hx, hy, handle_id, color, highlighted=highlighted, active=active_state)

    copy_rect, paste_rect, stencil_rect = _selection_button_layout(rect, state)
    state['selection_copy_button_bounds'] = copy_rect
    state['selection_apply_button_bounds'] = paste_rect
    state['selection_stencil_button_bounds'] = stencil_rect
    mouse_x = state.get('selection_mouse_region_x')
    mouse_y = state.get('selection_mouse_region_y')
    copy_hover = mouse_x is not None and mouse_y is not None and (
        copy_rect[0] <= mouse_x <= copy_rect[2] and copy_rect[1] <= mouse_y <= copy_rect[3]
    )
    paste_hover = paste_rect is not None and mouse_x is not None and mouse_y is not None and (
        paste_rect[0] <= mouse_x <= paste_rect[2] and paste_rect[1] <= mouse_y <= paste_rect[3]
    )
    stencil_hover = mouse_x is not None and mouse_y is not None and (
        stencil_rect[0] <= mouse_x <= stencil_rect[2] and stencil_rect[1] <= mouse_y <= stencil_rect[3]
    )
    _draw_selection_button(copy_rect, 'Copy', active=copy_hover)
    _draw_selection_button(paste_rect, 'Apply', active=paste_hover or (state.get('selection_pending_action') is not None))
    _draw_selection_button(stencil_rect, 'Stencil', active=stencil_hover or state.get('selection_stencil_mode'))
    _draw_precision_pixel_guide(context, state.get('current_cx'), state.get('current_cy'))
