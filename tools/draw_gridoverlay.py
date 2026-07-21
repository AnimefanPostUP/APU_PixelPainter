"""Pixel grid overlay drawing."""

import gpu
import gpu_extras.batch

from ..utils import blender_utils
from .draw_functions import _gpu_draw_lines


def draw_pixel_grid_overlay(context, grid_opacity):
    """Draw a pixel-aligned grid overlay when opacity > 0."""
    if grid_opacity <= 0.0:
        return

    space, img = blender_utils.get_space_img(context)
    if not space or not img:
        return

    w, h = img.size
    if w == 0 or h == 0:
        return

    region = next((r for r in context.area.regions if r.type == 'WINDOW'), None)
    if not region:
        return

    region_width = region.width
    region_height = region.height

    _, v2d = blender_utils.get_window_region_and_v2d(context.area)
    if not v2d:
        return

    corner_00 = v2d.view_to_region(0.0, 0.0)
    corner_11 = v2d.view_to_region(1.0, 1.0)
    if corner_00 is None or corner_11 is None:
        return

    sx_min, sy_min = corner_00
    sx_max, sy_max = corner_11
    screen_left = max(min(sx_min, sx_max), 0.0)
    screen_right = min(max(sx_min, sx_max), float(region_width))
    screen_bot = max(min(sy_min, sy_max), 0.0)
    screen_top = min(max(sy_min, sy_max), float(region_height))

    if screen_left >= screen_right or screen_bot >= screen_top:
        return

    px_width = (sx_max - sx_min) / w if abs(sx_max - sx_min) > 1e-6 else 1.0
    py_height = (sy_max - sy_min) / h if abs(sy_max - sy_min) > 1e-6 else 1.0
    min_spacing = 2.0
    x_step = max(1, int((min_spacing / abs(px_width)) + 0.999999)) if px_width != 0 else 1
    y_step = max(1, int((min_spacing / abs(py_height)) + 0.999999)) if py_height != 0 else 1

    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')
    gpu.state.line_width_set(1.0)

    vertices = []
    for x in range(0, w + 1, x_step):
        sx = sx_min + x * px_width
        if screen_left <= sx <= screen_right:
            vertices.append((sx, screen_bot))
            vertices.append((sx, screen_top))
    for y in range(0, h + 1, y_step):
        sy = sy_min + y * py_height
        if screen_bot <= sy <= screen_top:
            vertices.append((screen_left, sy))
            vertices.append((screen_right, sy))

    if vertices:
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        batch = gpu_extras.batch.batch_for_shader(shader, 'LINES', {"pos": vertices})
        shader.uniform_float("color", (1.0, 1.0, 1.0, grid_opacity * 0.6))
        batch.draw(shader)

    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('LESS_EQUAL')
