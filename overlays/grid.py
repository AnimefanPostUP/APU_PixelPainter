"""Pixel grid overlay drawing."""

import gpu
import gpu_extras.batch

from ..utils import blender_utils
from ..paint.pixels import _gpu_draw_lines


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

    # clip=False: with the default clip=True, off-screen corners return the
    # (12000, 12000) sentinel, which breaks the grid when zoomed past the edges.
    corner_00 = v2d.view_to_region(0.0, 0.0, clip=False)
    corner_11 = v2d.view_to_region(1.0, 1.0, clip=False)
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


# ---- 3D Viewport -------------------------------------------------------------------
# The mesh's triangles drawn with their UVs: the fragment shader puts a line on every
# texel border (anti-aliased, 1 px via fwidth) and fades the grid out where the texels
# get smaller than a few screen pixels. Clip-space depth is pulled toward the viewer
# a little so the lines win the depth test against the surface itself.

GRID_3D_DEPTH_BIAS = 2e-4
_grid3d_shader = None
_grid3d_failed = False
_grid3d_batch = (None, None)     # (cache.version, batch)


def _grid3d():
    global _grid3d_shader, _grid3d_failed
    if _grid3d_shader is None and not _grid3d_failed:
        try:
            info = gpu.types.GPUShaderCreateInfo()
            info.push_constant('MAT4', 'mvp')
            info.push_constant('VEC2', 'size')
            info.push_constant('VEC4', 'color')
            info.push_constant('FLOAT', 'bias')
            info.vertex_in(0, 'VEC3', 'pos')
            info.vertex_in(1, 'VEC2', 'uv')
            iface = gpu.types.GPUStageInterfaceInfo("pixel_painter_grid_iface")
            iface.smooth('VEC2', 'texel')
            info.vertex_out(iface)
            info.fragment_out(0, 'VEC4', 'FragColor')
            info.vertex_source(
                "void main() {"
                "  texel = uv * size;"
                "  gl_Position = mvp * vec4(pos, 1.0);"
                "  gl_Position.z -= bias * gl_Position.w;"
                "}")
            info.fragment_source(
                "void main() {"
                "  vec2 fw = max(fwidth(texel), vec2(1e-6));"
                "  vec2 d = abs(fract(texel - 0.5) - 0.5) / fw;"     # px to the nearest border
                "  float line = 1.0 - clamp(min(d.x, d.y) - 0.5, 0.0, 1.0);"
                "  float fade = 1.0 - smoothstep(0.2, 0.5, max(fw.x, fw.y));"  # texels < 2..5 px: fade out
                "  float a = color.a * line * fade;"
                "  if (a <= 0.0) discard;"
                "  FragColor = vec4(color.rgb, a);"
                "}")
            _grid3d_shader = gpu.shader.create_from_info(info)
        except Exception:
            import traceback
            traceback.print_exc()
            _grid3d_failed = True
    return _grid3d_shader


def draw_pixel_grid_overlay_3d(context, image, grid_opacity):
    """3D Viewport (POST_VIEW): the image's pixel grid on the painted mesh."""
    global _grid3d_batch
    if grid_opacity <= 0.0 or image is None:
        return
    w, h = image.size
    if w == 0 or h == 0:
        return
    from ..core import view3d
    cache = view3d.cached_mesh()
    if cache is None or len(cache.tri_pos) == 0:
        return
    import bpy
    obj = bpy.data.objects.get(cache.key[0])
    if obj is None:
        return
    shader = _grid3d()
    if shader is None:
        return
    if _grid3d_batch[0] != cache.version:
        pos = cache.tri_pos.reshape(-1, 3).astype('float32')
        uv = cache.tri_uv.reshape(-1, 2).astype('float32')
        _grid3d_batch = (cache.version, gpu_extras.batch.batch_for_shader(shader, 'TRIS', {"pos": pos, "uv": uv}))
    batch = _grid3d_batch[1]
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_mask_set(False)
    gpu.state.depth_test_set('LESS_EQUAL')
    try:
        shader.bind()
        shader.uniform_float("mvp", gpu.matrix.get_projection_matrix() @ gpu.matrix.get_model_view_matrix()
                             @ obj.matrix_world)
        shader.uniform_float("size", (float(w), float(h)))
        shader.uniform_float("color", (1.0, 1.0, 1.0, grid_opacity * 0.6))
        shader.uniform_float("bias", GRID_3D_DEPTH_BIAS)
        batch.draw(shader)
    finally:
        gpu.state.depth_test_set('NONE')
        gpu.state.blend_set('NONE')
