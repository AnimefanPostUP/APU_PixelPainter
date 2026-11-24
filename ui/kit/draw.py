"""GPU drawing primitives for POST_PIXEL overlays.

The single place in the kit that talks to ``gpu``/``blf``. Imports are guarded
so the rest of the kit (layout, hit-testing, interaction) can be imported and
unit-tested outside Blender.
"""

import math

try:  # pragma: no cover - only unavailable outside Blender
    import blf
    import gpu
    from gpu_extras.batch import batch_for_shader
except ImportError:  # pragma: no cover
    blf = None
    gpu = None
    batch_for_shader = None


def _shader():
    return gpu.shader.from_builtin('UNIFORM_COLOR')


def _draw(prim, verts, color):
    shader = _shader()
    batch = batch_for_shader(shader, prim, {'pos': verts})
    shader.bind()
    shader.uniform_float('color', color)
    batch.draw(shader)


class blend_mode:
    """Context manager: ``with blend_mode('ALPHA'): ...`` restores 'NONE' after."""

    def __init__(self, mode='ALPHA', restore='NONE'):
        self.mode = mode
        self.restore = restore

    def __enter__(self):
        gpu.state.blend_set(self.mode)
        return self

    def __exit__(self, *exc):
        gpu.state.blend_set(self.restore)
        return False


# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------

def rect(r, color):
    """Filled rectangle; ``r`` is a :class:`geometry.Rect`."""
    _draw('TRI_FAN', [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)], color)


def rect_outline(r, color, width=1.5):
    verts = [
        (r.x0, r.y0), (r.x1, r.y0),
        (r.x1, r.y0), (r.x1, r.y1),
        (r.x1, r.y1), (r.x0, r.y1),
        (r.x0, r.y1), (r.x0, r.y0),
    ]
    gpu.state.line_width_set(width)
    _draw('LINES', verts, color)
    gpu.state.line_width_set(1.0)


def circle(cx, cy, radius, color, segments=36):
    verts = [
        (cx + math.cos(i / segments * math.tau) * radius,
         cy + math.sin(i / segments * math.tau) * radius)
        for i in range(segments)
    ]
    _draw('TRI_FAN', verts, color)


def circle_outline(cx, cy, radius, color, width=1.5, segments=48):
    verts = [
        (cx + math.cos(i / segments * math.tau) * radius,
         cy + math.sin(i / segments * math.tau) * radius)
        for i in range(segments + 1)
    ]
    gpu.state.line_width_set(width)
    _draw('LINE_STRIP', verts, color)
    gpu.state.line_width_set(1.0)


def arc(cx, cy, radius, a0, a1, color, width=1.5, segments=48):
    """Circular arc from angle ``a0`` to ``a1`` (radians, counter-clockwise positive)."""
    steps = max(2, int(segments * abs(a1 - a0) / math.tau) + 1)
    verts = [
        (cx + math.cos(a0 + (a1 - a0) * i / steps) * radius,
         cy + math.sin(a0 + (a1 - a0) * i / steps) * radius)
        for i in range(steps + 1)
    ]
    polyline(verts, color, width)


def shaded_tris(verts, colors):
    """Triangles with per-vertex colors (gradients): 3 verts / colors per triangle."""
    shader = gpu.shader.from_builtin('SMOOTH_COLOR')
    batch_for_shader(shader, 'TRIS', {'pos': verts, 'color': colors}).draw(shader)


def gradient_quad(r, c00, c10, c11, c01):
    """Rectangle ``r`` with corner colors (bottom-left, bottom-right, top-right, top-left)."""
    a, b, c, d = (r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)
    shaded_tris([a, b, c, a, c, d], [c00, c10, c11, c00, c11, c01])


def sector(cx, cy, radius, a0, a1, color, segments=24):
    """Filled pie slice from angle ``a0`` to ``a1`` (radians, counter-clockwise from +x)."""
    verts = []
    for i in range(segments):
        t0 = a0 + (a1 - a0) * i / segments
        t1 = a0 + (a1 - a0) * (i + 1) / segments
        verts += [(cx, cy),
                  (cx + math.cos(t0) * radius, cy + math.sin(t0) * radius),
                  (cx + math.cos(t1) * radius, cy + math.sin(t1) * radius)]
    _draw('TRIS', verts, color)


def ring_segment(inner, outer, color):
    """Filled ring segment from :func:`geometry.ring_segment_points` outlines."""
    if len(inner) < 2 or len(inner) != len(outer):
        return
    verts = []
    for i in range(len(inner) - 1):
        verts += [inner[i], outer[i], outer[i + 1], inner[i], outer[i + 1], inner[i + 1]]
    _draw('TRIS', verts, color)


def ring_segment_outline(inner, outer, color, width=1.5):
    if len(inner) < 2:
        return
    polyline(list(inner) + list(reversed(outer)) + [inner[0]], color, width)


def gradient_line(p0, p1, c0, c1, width=1.5):
    """Straight line ``width`` px wide, colored from ``c0`` at ``p0`` to ``c1`` at ``p1`` (e.g. a fade)."""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return
    nx, ny = -dy / length * width * 0.5, dx / length * width * 0.5
    a, b = (p0[0] + nx, p0[1] + ny), (p0[0] - nx, p0[1] - ny)
    c, d = (p1[0] - nx, p1[1] - ny), (p1[0] + nx, p1[1] + ny)
    shaded_tris([a, b, c, a, c, d], [c0, c0, c1, c0, c1, c1])


def gradient_circle(cx, cy, radius, left, right, segments=36):
    """Disc shaded horizontally from color ``left`` to ``right`` (RGBA)."""
    def _at(x):
        t = (x - (cx - radius)) / max(2.0 * radius, 1e-6)
        return tuple(left[i] + (right[i] - left[i]) * t for i in range(4))

    pts = [(cx + math.cos(i / segments * math.tau) * radius,
            cy + math.sin(i / segments * math.tau) * radius) for i in range(segments + 1)]
    verts, colors = [], []
    for i in range(segments):
        for p in ((cx, cy), pts[i], pts[i + 1]):
            verts.append(p)
            colors.append(_at(p[0]))
    shaded_tris(verts, colors)


def triangle(p0, p1, p2, color):
    _draw('TRIS', [p0, p1, p2], color)


def polyline(points, color, width=1.0):
    gpu.state.line_width_set(width)
    _draw('LINE_STRIP', list(points), color)
    gpu.state.line_width_set(1.0)


def bezier_points(p0, p1, p2, p3, segments=20):
    pts = []
    for i in range(segments + 1):
        t = i / segments
        it = 1.0 - t
        a = it * it * it
        b = 3.0 * it * it * t
        c = 3.0 * it * t * t
        d = t * t * t
        pts.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
                    a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return pts


def bezier(p0, p1, p2, p3, color, width=3.0, segments=20):
    polyline(bezier_points(p0, p1, p2, p3, segments), color, width)


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------

def text_size(text, size, font_id=0):
    """``(width, height)`` of ``text`` at ``size``; estimated outside Blender."""
    if blf is None:
        return len(text) * size * 0.55, size
    blf.size(font_id, size)
    return blf.dimensions(font_id, text)


def text_centered(text, x, y, size, color, font_id=0):
    if not text or size < 1.0 or color[3] <= 0.0:
        return
    blf.size(font_id, size)
    w, h = blf.dimensions(font_id, text)
    blf.position(font_id, x - w * 0.5, y - h * 0.5, 0)
    blf.color(font_id, *color)
    blf.draw(font_id, text)
