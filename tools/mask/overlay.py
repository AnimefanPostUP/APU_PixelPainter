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

# Batches are built once per mask / mesh state (the vertex data can be large) and
# drawn with the view in the shader's matrices, so a frame uploads nothing.
_batch2d = (None, None)   # (allowed key, GPUBatch | None)
_batch3d = (None, None)   # ((mesh version, allowed key), GPUBatch | None)
_stripe_shader = None
_stripe_failed = False
_stripe3d_shader = None
_stripe3d_failed = False

_STRIPE_FRAGMENT = (
    "void main() {"
    "  float t = mod((gl_FragCoord.x + gl_FragCoord.y) / stripe, 2.0);"
    "  FragColor = t < 1.0 ? color_a : color_b;"
    "}")


def _stripe_info(push_constants):
    info = gpu.types.GPUShaderCreateInfo()
    for kind, name in push_constants:
        info.push_constant(kind, name)
    info.push_constant('VEC4', 'color_a')
    info.push_constant('VEC4', 'color_b')
    info.push_constant('FLOAT', 'stripe')
    info.vertex_in(0, 'VEC3', 'pos')
    info.fragment_out(0, 'VEC4', 'FragColor')
    info.fragment_source(_STRIPE_FRAGMENT)
    return info


def _stripes():
    """Shader filling triangles with diagonal stripes (screen space), or None if unsupported."""
    global _stripe_shader, _stripe_failed
    if _stripe_shader is None and not _stripe_failed:
        try:
            info = _stripe_info((('MAT4', 'mvp'),))
            info.vertex_source("void main() { gl_Position = mvp * vec4(pos, 1.0); }")
            _stripe_shader = gpu.shader.create_from_info(info)
        except Exception:
            import traceback
            traceback.print_exc()
            _stripe_failed = True
    return _stripe_shader


def _stripes_3d():
    """Stripe shader for object-space triangles, pulled towards the viewer in view space
    (``persp`` 1: towards the eye by ``pull`` of the distance; 0: ``pull`` units along
    view +Z) -- the same offset as ``overlays.view3d_outline._to_world_towards_view``."""
    global _stripe3d_shader, _stripe3d_failed
    if _stripe3d_shader is None and not _stripe3d_failed:
        try:
            info = _stripe_info((('MAT4', 'model_view'), ('MAT4', 'projection'),
                                 ('FLOAT', 'persp'), ('FLOAT', 'pull')))
            info.vertex_source(
                "void main() {"
                "  vec4 v = model_view * vec4(pos, 1.0);"
                "  if (persp > 0.5) { v.xyz *= 1.0 - pull; } else { v.z += pull; }"
                "  gl_Position = projection * v;"
                "}")
            _stripe3d_shader = gpu.shader.create_from_info(info)
        except Exception:
            import traceback
            traceback.print_exc()
            _stripe3d_failed = True
    return _stripe3d_shader


def _stripe_uniforms(shader, context):
    scale = getattr(context.preferences.system, 'ui_scale', 1.0)
    shader.uniform_float("color_a", STRIPE_DARK)
    shader.uniform_float("color_b", STRIPE_LIGHT)
    shader.uniform_float("stripe", STRIPE_WIDTH * scale)


def _flat_shader():
    """The 2D stripe shader, or plain UNIFORM_COLOR when custom shaders are unsupported."""
    return _stripes() or gpu.shader.from_builtin('UNIFORM_COLOR')


def _draw_flat(batch, shader, context):
    """Draw a batch made for :func:`_flat_shader` with the current matrices."""
    shader.bind()
    if shader is _stripe_shader:
        shader.uniform_float("mvp", gpu.matrix.get_projection_matrix() @ gpu.matrix.get_model_view_matrix())
        _stripe_uniforms(shader, context)
    else:
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
    shader = _flat_shader()
    if _batch2d[0] != data.allowed_key():
        rows, starts, ends = geo.blocked_runs(~allowed_pixels.reshape(h, w))
        verts = geo.run_triangles(rows, starts, ends)
        batch = None
        if len(verts):
            verts3 = np.zeros((len(verts), 3), dtype=np.float32)
            verts3[:, :2] = verts
            batch = batch_for_shader(shader, 'TRIS', {"pos": verts3})
        _batch2d = (data.allowed_key(), batch)
    batch = _batch2d[1]
    if batch is None:
        return
    x0, y0 = v2d.view_to_region(0.0, 0.0, clip=False)
    x1, y1 = v2d.view_to_region(1.0, 1.0, clip=False)
    gpu.state.blend_set('ALPHA')
    with gpu.matrix.push_pop():
        gpu.matrix.translate((x0, y0))
        gpu.matrix.scale(((x1 - x0) / w, (y1 - y0) / h))
        _draw_flat(batch, shader, context)
    gpu.state.blend_set('NONE')


def _blocked_triangles(cache, allowed_pixels, w, h):
    """Object-space corners (K, 3, 3) of the triangles whose UV center is protected."""
    center = cache.tri_uv.mean(axis=1)
    px = np.floor(center[:, 0] * w).astype(np.int64)
    py = np.floor(center[:, 1] * h).astype(np.int64)
    inside = (px >= 0) & (px < w) & (py >= 0) & (py < h)
    blocked = np.zeros(len(center), dtype=bool)
    blocked[inside] = ~allowed_pixels[py[inside] * w + px[inside]]
    return cache.tri_pos[blocked]


def draw_3d(context, image):
    """3D Viewport: red stripes over mesh triangles whose UV center is protected (POST_VIEW)."""
    global _batch3d
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
    shader = _stripes_3d()
    if shader is None:
        _draw_3d_fallback(cache, allowed_pixels, w, h, obj, rv3d)
        return
    key = (cache.version, data.allowed_key())
    if _batch3d[0] != key:
        local = _blocked_triangles(cache, allowed_pixels, w, h)
        batch = (batch_for_shader(shader, 'TRIS', {"pos": local.reshape(-1, 3).astype(np.float32)})
                 if len(local) else None)
        _batch3d = (key, batch)
    batch = _batch3d[1]
    if batch is None:
        return
    persp = bool(rv3d.is_perspective)
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_mask_set(False)
    gpu.state.depth_test_set('LESS_EQUAL')
    try:
        shader.bind()
        shader.uniform_float("model_view", gpu.matrix.get_model_view_matrix() @ obj.matrix_world)
        shader.uniform_float("projection", gpu.matrix.get_projection_matrix())
        shader.uniform_float("persp", 1.0 if persp else 0.0)
        shader.uniform_float("pull", VIEW_OFFSET if persp else rv3d.view_distance * VIEW_OFFSET)
        _stripe_uniforms(shader, context)
        batch.draw(shader)
    finally:
        gpu.state.depth_test_set('NONE')
        gpu.state.blend_set('NONE')


def _draw_3d_fallback(cache, allowed_pixels, w, h, obj, rv3d):
    """No custom shaders: plain red, offset towards the viewer on the CPU every frame."""
    from ...overlays.view3d_outline import _to_world_towards_view
    local = _blocked_triangles(cache, allowed_pixels, w, h)
    if len(local) == 0:
        return
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'TRIS', {"pos": _to_world_towards_view(local, obj, rv3d)})
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_mask_set(False)
    gpu.state.depth_test_set('LESS_EQUAL')
    try:
        shader.bind()
        shader.uniform_float("color", STRIPE_DARK)
        batch.draw(shader)
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
