import gpu
import gpu_extras.batch
import numpy as np

from ..paint import blending as draw_blending
from ..utils import blender_utils, pixel_io
from .gpu_prims import (
    draw_precision_pixel_guide, draw_circle_outline, draw_fill, draw_filled_circle, draw_lines,
)


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

    arr = pixel_io.buffer(img).reshape(height, width, 4)   # read only
    src_y0 = clip_bottom - dest_bottom
    src_y1 = src_y0 + (clip_top - clip_bottom + 1)
    src_x0 = clip_left - dest_left
    src_x1 = src_x0 + (clip_right - clip_left + 1)
    dst_slice = arr[clip_bottom:clip_top + 1, clip_left:clip_right + 1, :]
    src_slice = source_region[src_y0:src_y1, src_x0:src_x1, :]
    scaled_src_slice = preview[src_y0:src_y1, src_x0:src_x1, :]
    blended = draw_blending.blend_region_pixels(dst_slice, scaled_src_slice, blend, strength)
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
    draw_lines([
        (left + inset_x, center_y), (right - inset_x, center_y),
        (center_x, bottom + inset_y), (center_x, top - inset_y),
    ], (1.0, 1.0, 1.0, 0.95))


def _selection_overlay_rect(context, state):
    """Screen rect of the selection box, or None when nothing should be drawn."""
    if context.window_manager.pixel_painter_mode != 'SELECT':
        return None
    if state.get('sub_mode') or state.get('ctrl_pick_active'):
        return None
    box = state.get('selection_box')
    if not box:
        return None
    space, img = blender_utils.get_space_img(context)
    if not space or not img:
        return None
    width, height = img.size
    if width == 0 or height == 0 or not context.area:
        return None
    region = next((r for r in context.area.regions if r.type == 'WINDOW'), None)
    if not region:
        return None
    return _selection_screen_rect(region.view2d, width, height, box, state)


def draw_selection_overlay(context, state, actions=None):
    """Draw the selection box, handles, preview and the action buttons layer.

    ``actions`` is the :class:`ui.selection_actions.SelectionActions` layer; it
    is hidden whenever there is no visible selection so it cannot be clicked.
    """
    rect = _selection_overlay_rect(context, state)
    if rect is None:
        if actions is not None:
            actions.hide()
        return
    box = state.get('selection_box')

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

    draw_fill([(left, bottom), (right, bottom), (right, top), (left, top)], (0.18, 0.52, 0.96, 0.10))
    draw_lines([
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

    if actions is not None:
        actions.show_below(rect)
        actions.draw()
    draw_precision_pixel_guide(context, state.get('current_cx'), state.get('current_cy'))


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

    draw_filled_circle(cx, cy, radius, fill, segments=32)
    draw_circle_outline(cx, cy, outline_radius, outline, segments=36)
    draw_filled_circle(cx, cy, inner_radius, inner, segments=24)
