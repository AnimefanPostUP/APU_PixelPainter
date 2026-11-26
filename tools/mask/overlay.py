"""Mask overlays: red stripes over the protected area (Image Editor: pixel runs,
3D Viewport: triangles), the picking hint and the edit frame. Draw callbacks only
read the cached mask data (:mod:`.data`).
"""


import blf
import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader

from . import geometry as geo
from . import data
from .data import active, allowed
# Protected area: diagonal stripes of red and lighter red, 15% visible.
STRIPE_DARK = (0.85, 0.08, 0.08, 0.15)
STRIPE_LIGHT = (1.00, 0.50, 0.50, 0.15)
STRIPE_WIDTH = 8.0             # screen px per stripe (times the UI scale)
PICK_HINT = "Mask: tap islands / parts to toggle them  ·  Esc: done"
VIEW_OFFSET = 0.002            # 3D overlay pulled towards the viewer (fraction of view distance)


# ---------------------------------------------------------------------------
# Overlays (draw callbacks: read the cached data only)
# ---------------------------------------------------------------------------

_batch2d = (None, None)
_local3d = (None, None)
_stripe_shader = None
_stripe_failed = False


def _stripes():
    """Shader filling triangles with diagonal stripes (screen space), or None if unsupported."""
    global _stripe_shader, _stripe_failed
    if _stripe_shader is None and not _stripe_failed:
        try:
            info = gpu.types.GPUShaderCreateInfo()
            info.push_constant('MAT4', 'mvp')
            info.push_constant('VEC4', 'color_a')
            info.push_constant('VEC4', 'color_b')
            info.push_constant('FLOAT', 'stripe')
            info.vertex_in(0, 'VEC3', 'pos')
            info.fragment_out(0, 'VEC4', 'FragColor')
            info.vertex_source("void main() { gl_Position = mvp * vec4(pos, 1.0); }")
            info.fragment_source(
                "void main() {"
                "  float t = mod((gl_FragCoord.x + gl_FragCoord.y) / stripe, 2.0);"
                "  FragColor = t < 1.0 ? color_a : color_b;"
                "}")
            _stripe_shader = gpu.shader.create_from_info(info)
        except Exception:
            import traceback
            traceback.print_exc()
            _stripe_failed = True
    return _stripe_shader


def _draw_striped(coords3, context):
    """Draw (N, 3) triangle vertices with the stripe pattern (fallback: plain red, 15%)."""
    shader = _stripes()
    if shader is not None:
        batch = batch_for_shader(shader, 'TRIS', {"pos": coords3})
        scale = getattr(context.preferences.system, 'ui_scale', 1.0)
        shader.bind()
        shader.uniform_float("mvp", gpu.matrix.get_projection_matrix() @ gpu.matrix.get_model_view_matrix())
        shader.uniform_float("color_a", STRIPE_DARK)
        shader.uniform_float("color_b", STRIPE_LIGHT)
        shader.uniform_float("stripe", STRIPE_WIDTH * scale)
        batch.draw(shader)
        return
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'TRIS', {"pos": coords3})
    shader.bind()
    shader.uniform_float("color", STRIPE_DARK)
    batch.draw(shader)


def _blocked_for_draw(context, image):
    """Cached paintable pixels for drawing (no mesh access), or None."""
    wm = context.window_manager
    if not active(wm) or not getattr(wm, 'pixel_painter_mask_show', True):
        return None
    return allowed(context, image, refresh_data=False)


def draw_2d(context, v2d, image):
    """Image Editor: red stripes over the protected pixels (POST_PIXEL)."""
    global _batch2d
    if v2d is None or image is None:
        return
    allowed_pixels = _blocked_for_draw(context, image)
    if allowed_pixels is None:
        return
    w, h = image.size
    if _batch2d[0] != data.allowed_key():
        rows, starts, ends = geo.blocked_runs(~allowed_pixels.reshape(h, w))
        verts = geo.run_triangles(rows, starts, ends)
        verts3 = np.zeros((len(verts), 3), dtype=np.float32)
        verts3[:, :2] = verts
        _batch2d = (data.allowed_key(), verts3 if len(verts3) else None)
    verts3 = _batch2d[1]
    if verts3 is None:
        return
    x0, y0 = v2d.view_to_region(0.0, 0.0, clip=False)
    x1, y1 = v2d.view_to_region(1.0, 1.0, clip=False)
    gpu.state.blend_set('ALPHA')
    with gpu.matrix.push_pop():
        gpu.matrix.translate((x0, y0))
        gpu.matrix.scale(((x1 - x0) / w, (y1 - y0) / h))
        _draw_striped(verts3, context)
    gpu.state.blend_set('NONE')


def draw_3d(context, image):
    """3D Viewport: red stripes over mesh triangles whose UV center is protected (POST_VIEW)."""
    global _local3d
    from ...core.view3d import mesh as v3d_mesh
    allowed_pixels = _blocked_for_draw(context, image)
    if allowed_pixels is None:
        return
    cache = v3d_mesh.cached_mesh()
    rv3d = getattr(context, 'region_data', None)
    if cache is None or rv3d is None:
        return
    obj = bpy.data.objects.get(cache.key[0])
    if obj is None:
        return
    w, h = image.size
    key = (cache.version, data.allowed_key())
    if _local3d[0] != key:
        center = cache.tri_uv.mean(axis=1)
        px = np.floor(center[:, 0] * w).astype(np.int64)
        py = np.floor(center[:, 1] * h).astype(np.int64)
        inside = (px >= 0) & (px < w) & (py >= 0) & (py < h)
        blocked = np.zeros(len(center), dtype=bool)
        blocked[inside] = ~allowed_pixels[py[inside] * w + px[inside]]
        _local3d = (key, cache.tri_pos[blocked])
    local = _local3d[1]
    if local is None or len(local) == 0:
        return
    from ...overlays.view3d_outline import _to_world_towards_view
    coords = _to_world_towards_view(local, obj, rv3d)
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_mask_set(False)
    gpu.state.depth_test_set('LESS_EQUAL')
    try:
        _draw_striped(coords, context)
    finally:
        gpu.state.depth_test_set('NONE')
        gpu.state.blend_set('NONE')


def draw_hint(context):
    region = getattr(context, 'region', None)
    if region is None:
        return
    font = 0
    size = int(13 * context.preferences.system.ui_scale)
    blf.size(font, size)
    tw, th = blf.dimensions(font, PICK_HINT)
    x, y = (region.width - tw) * 0.5, 40.0 * context.preferences.system.ui_scale
    pad = 6.0
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    box = [(x - pad, y - pad), (x + tw + pad, y - pad), (x + tw + pad, y + th + pad), (x - pad, y + th + pad)]
    gpu.state.blend_set('ALPHA')
    batch = batch_for_shader(shader, 'TRI_FAN', {"pos": box})
    shader.bind()
    shader.uniform_float("color", (0.1, 0.1, 0.1, 0.85))
    batch.draw(shader)
    blf.position(font, x, y, 0)
    blf.color(font, 1.0, 1.0, 1.0, 1.0)
    blf.draw(font, PICK_HINT)
    gpu.state.blend_set('NONE')


def draw_edit_frame(context):
    """While editing the mask: an orange frame around the editor, labelled at the top."""
    region = getattr(context, 'region', None)
    if region is None:
        return
    from ...ui import viewport_frame   # late import: ui imports the tools
    from ...ui.kit.theme import Theme
    viewport_frame.draw_frame(region.width, region.height, viewport_frame.MASK_EDIT_COLOR,
                              viewport_frame.MASK_EDIT_LABEL, Theme.for_context(context),
                              top=viewport_frame.top_cover(getattr(context, 'area', None), region))
