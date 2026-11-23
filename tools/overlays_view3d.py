"""3D Viewport brush outline, drawn on the mesh surface (POST_VIEW).

The outline is the same pixel contour as in the Image Editor
(``tool.outline_pixels`` -> ``get_outline_edges``), built in texture space and
projected onto the mesh with :func:`core.view3d.project_uv_segments`. Because
it is built from texels, its size always matches what a stamp paints, and it
follows the surface over mesh edges and corners.
"""

import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader

from ..core import view3d
from ..utils import blender_utils, math_utils


VIEW_OFFSET = 0.002   # pull lines towards the viewer (fraction of view distance) against z-fighting

# Projection is only recomputed when one of its inputs changes.
_cache_key = None
_cache_local = None   # (K, 2, 3) object-space segments


def _outline_local(state, tool, cache, img, cx, cy, radius):
    global _cache_key, _cache_local
    w, h = img.size
    tile = state.get('view3d_uv_tile') or (0, 0)
    key = (cache.version, tool.tool_id, cx, cy, radius, w, h, tile,
           state.get('start_position'), state.get('last_shape'))
    if key == _cache_key:
        return _cache_local

    edges = math_utils.get_outline_edges(tool.outline_pixels(state, cx, cy, radius))
    if edges:
        seg = np.array(edges, dtype=np.float64)                 # (E, 2, 2) pixel corners
        seg /= np.array((w, h), dtype=np.float64)
        seg += np.array(tile, dtype=np.float64)
        local = view3d.project_uv_segments(cache, seg)
    else:
        local = np.empty((0, 2, 3), dtype=np.float64)
    _cache_key, _cache_local = key, local
    return local


def _to_world_towards_view(local, obj, rv3d):
    pts = local.reshape(-1, 3)
    mat = np.array(obj.matrix_world, dtype=np.float64)
    world = pts @ mat[:3, :3].T + mat[:3, 3]
    view_inv = np.array(rv3d.view_matrix.inverted(), dtype=np.float64)
    if rv3d.is_perspective:
        eye = view_inv[:3, 3]
        world = world + (eye - world) * VIEW_OFFSET
    else:
        toward_viewer = view_inv[:3, 2]  # view-space +Z in world space
        world = world + toward_viewer * (rv3d.view_distance * VIEW_OFFSET)
    return world.astype(np.float32)


def _draw_lines(coords, color, width, viewport):
    shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'LINES', {"pos": coords})
    shader.bind()
    shader.uniform_float("viewportSize", viewport)
    shader.uniform_float("lineWidth", width)
    shader.uniform_float("color", color)
    batch.draw(shader)


def draw_brush_outline_3d(context, state):
    cx, cy = state.get('current_cx'), state.get('current_cy')
    if cx is None or cy is None:
        return
    cache = view3d.cached_mesh()
    if cache is None:
        return
    obj = bpy.data.objects.get(cache.key[0])
    rv3d = getattr(context, 'region_data', None)
    region = getattr(context, 'region', None)
    if obj is None or rv3d is None or region is None:
        return
    img = blender_utils.get_paint_image(context)
    if img is None or img.size[0] == 0 or img.size[1] == 0:
        return

    from .catalog import TOOLS
    tool = TOOLS.get(context.window_manager.pixel_painter_mode)
    if tool is None or not tool.shows_brush_outline:
        return
    radius = blender_utils.get_brush_image_radius(context)

    local = _outline_local(state, tool, cache, img, cx, cy, radius)
    if len(local) == 0:
        return
    coords = _to_world_towards_view(local, obj, rv3d)
    viewport = (float(region.width), float(region.height))

    gpu.state.blend_set('ALPHA')
    gpu.state.depth_mask_set(False)
    gpu.state.depth_test_set('LESS_EQUAL')
    try:
        _draw_lines(coords, (0.0, 0.0, 0.0, 0.7), 3.0, viewport)
        _draw_lines(coords, tuple(tool.outline_color), 1.5, viewport)
        # Faint see-through pass so the outline stays readable behind geometry.
        gpu.state.depth_test_set('NONE')
        c = tool.outline_color
        _draw_lines(coords, (c[0], c[1], c[2], 0.15), 1.0, viewport)
    finally:
        gpu.state.depth_test_set('NONE')
        gpu.state.blend_set('NONE')
