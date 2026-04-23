def draw_bezier_curve(p0, p1, p2, p3, color=(0.66, 0.44, 0.92, 0.70), segments=20):
    verts = []
    for i in range(segments + 1):
        t = i / segments
        it = 1.0 - t
        x = (
            it * it * it * p0[0]
            + 3.0 * it * it * t * p1[0]
            + 3.0 * it * t * t * p2[0]
            + t * t * t * p3[0]
        )
        y = (
            it * it * it * p0[1]
            + 3.0 * it * it * t * p1[1]
            + 3.0 * it * t * t * p2[1]
            + t * t * t * p3[1]
        )
        verts.append((x, y))
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'LINE_STRIP', {'pos': verts})
    gpu.state.line_width_set(3.0)
    shader.bind()
    shader.uniform_float('color', color)
    batch.draw(shader)
    gpu.state.line_width_set(1.0)
import math
import gpu
from gpu_extras.batch import batch_for_shader

def draw_triangle_arrow(cx, cy, mx, my, color=(0.66, 0.44, 0.92, 0.92)):
    dx = mx - cx
    dy = my - cy
    d2 = dx * dx + dy * dy
    if d2 < 1e-4:
        return None
    d = math.sqrt(d2)
    ux = dx / d
    uy = dy / d
    px = -uy
    py = ux
    base_dist = 12.0
    tri_len = 22.0
    tri_half_w = 7.0
    bx = cx + ux * base_dist
    by = cy + uy * base_dist
    tx = bx + ux * tri_len
    ty = by + uy * tri_len
    lx = bx + px * tri_half_w
    ly = by + py * tri_half_w
    rx = bx - px * tri_half_w
    ry = by - py * tri_half_w
    verts = [(tx, ty), (lx, ly), (rx, ry)]
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'TRI_FAN', {'pos': verts})
    shader.bind()
    shader.uniform_float('color', color)
    batch.draw(shader)
    return {'tip': (tx, ty), 'dir': (ux, uy)}