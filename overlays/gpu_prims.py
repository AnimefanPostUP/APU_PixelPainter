"""Small GPU drawing primitives shared by the canvas overlays (POST_PIXEL, screen space).
"""

import math

import blf
import gpu
import gpu_extras.batch

from ..utils import blender_utils


# ---------------------------------------------------------------------------
# Internal GPU helpers
# ---------------------------------------------------------------------------

def draw_lines(vertices, color):
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')
    gpu.state.line_width_set(1.5)
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch  = gpu_extras.batch.batch_for_shader(shader, 'LINES', {"pos": vertices})
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('LESS_EQUAL')


def edges_to_screen_verts(edges, v2d, w, h, offset_x=0.0, offset_y=0.0):
    """Convert image-space edges to screen coordinates with optional sub-pixel offset."""
    vertices = []
    for (px0, py0), (px1, py1) in edges:
        sx0, sy0 = v2d.view_to_region((px0 + offset_x) / w, (py0 + offset_y) / h)
        sx1, sy1 = v2d.view_to_region((px1 + offset_x) / w, (py1 + offset_y) / h)
        vertices.append((round(sx0), round(sy0)))
        vertices.append((round(sx1), round(sy1)))
    return vertices


def draw_precision_pixel_guide(context, px, py, color=(1.0, 1.0, 1.0, 0.85)):
    """Draw thin corner brackets for one image pixel.

    The middle 60% of each edge is intentionally omitted so only corner hints
    remain, making the exact pixel bounds easier to read without visual clutter.
    """
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

    # Draw only 20% at each side of an edge: 40% visible, 60% omitted.
    t = 0.2
    sx0, sy0 = v2d.view_to_region(x0, y0)
    sx1, sy1 = v2d.view_to_region(x1, y1)
    if sx0 is None or sy0 is None or sx1 is None or sy1 is None:
        return

    # Screen-space rectangle corners (not rounded to keep sub-pixel smoothness).
    left = min(sx0, sx1)
    right = max(sx0, sx1)
    bot = min(sy0, sy1)
    top = max(sy0, sy1)

    dx = right - left
    dy = top - bot
    hx = dx * t
    hy = dy * t

    verts = [
        # Bottom edge corners
        (left, bot), (left + hx, bot),
        (right - hx, bot), (right, bot),
        # Top edge corners
        (left, top), (left + hx, top),
        (right - hx, top), (right, top),
        # Left edge corners
        (left, bot), (left, bot + hy),
        (left, top - hy), (left, top),
        # Right edge corners
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


def draw_wide_circle_outline(cx, cy, radius, rgba, width=2.0, steps=60):
    """Draw a thin circle outline."""
    steps = max(8, int(steps))
    verts = []
    for i in range(steps):
        a0 = 2 * math.pi * i / steps
        a1 = 2 * math.pi * (i + 1) / steps
        verts.append((cx + radius * math.cos(a0), cy + radius * math.sin(a0)))
        verts.append((cx + radius * math.cos(a1), cy + radius * math.sin(a1)))
    gpu.state.line_width_set(width)
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch  = gpu_extras.batch.batch_for_shader(shader, 'LINES', {"pos": verts})
    shader.uniform_float("color", rgba)
    batch.draw(shader)


def draw_filled_rect(x0, y0, x1, y1, color):
    verts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = gpu_extras.batch.batch_for_shader(shader, 'TRI_FAN', {"pos": verts})
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('LESS_EQUAL')


def draw_filled_circle(cx, cy, radius, color, segments=40):
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


def draw_circle_outline(cx, cy, radius, color, segments=40):
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


def draw_fill(vertices, color):
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = gpu_extras.batch.batch_for_shader(shader, 'TRI_FAN', {"pos": vertices})
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('LESS_EQUAL')


def draw_text_centered(text, x, y, size=12, alpha=1.0):
    font_id = 0
    blf.size(font_id, size)
    width, height = blf.dimensions(font_id, text)
    blf.position(font_id, x - width * 0.5, y - height * 0.5, 0)
    blf.color(font_id, 1.0, 1.0, 1.0, alpha)
    blf.draw(font_id, text)
