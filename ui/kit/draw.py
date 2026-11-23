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
