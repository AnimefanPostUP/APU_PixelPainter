"""GPU drawing primitives for POST_PIXEL overlays.

The single place in the kit that talks to ``gpu``/``blf``. Imports are guarded
so the rest of the kit (layout, hit-testing, interaction) can be imported and
unit-tested outside Blender.
"""

import math

from . import aa

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
# Shapes -- every fill gets a soft edge and every line is a soft-edged strip
# (see .aa): overlays have no multisampling.
# ---------------------------------------------------------------------------

def _mesh(verts, colors):
    if verts:
        shaded_tris(verts, colors)


def _fill(points, color, rim=None):
    """Convex polygon (or a fan around its first point): the solid part EDGE px
    smaller, the coverage ramp across the edge, then the optional ``rim`` line."""
    if len(points) < 3:
        return
    _draw('TRI_FAN', aa.offset_points(points, -aa.EDGE), color)
    _mesh(*aa.fringe_mesh(points, color))
    if rim is not None:
        polyline(points, rim, 1.0, closed=True)


def _snap(r):
    """Rect on whole pixels: axis-aligned edges have no slopes to smooth, keep them crisp."""
    return round(r.x0), round(r.y0), round(r.x1), round(r.y1)


def shaded_tris(verts, colors):
    """Triangles with per-vertex colors (gradients): 3 verts / colors per triangle."""
    shader = gpu.shader.from_builtin('SMOOTH_COLOR')
    batch_for_shader(shader, 'TRIS', {'pos': verts, 'color': colors}).draw(shader)


def rect(r, color):
    """Filled rectangle (``r``: :class:`geometry.Rect`), snapped to whole pixels."""
    x0, y0, x1, y1 = _snap(r)
    if x1 > x0 and y1 > y0:
        _draw('TRI_FAN', [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], color)


def rect_outline(r, color, width=1.5):
    """Outline along the rect's edges; 1 px lines sit on pixel centers (crisp)."""
    x0, y0, x1, y1 = _snap(r)
    h = 0.5 if width <= 1.0 else 0.0
    polyline([(x0 + h, y0 + h), (x1 - h, y0 + h), (x1 - h, y1 - h), (x0 + h, y1 - h)], color, width, closed=True)


def circle(cx, cy, radius, color, segments=36, rim=None):
    _fill(aa.circle_points(cx, cy, radius, max(segments, aa.segments_for(radius))), color, rim)


def circle_outline(cx, cy, radius, color, width=1.5, segments=48):
    pts = aa.circle_points(cx, cy, radius, max(segments, aa.segments_for(radius)))
    polyline(pts, color, width, closed=True)


def arc(cx, cy, radius, a0, a1, color, width=1.5, segments=48):
    """Circular arc from angle ``a0`` to ``a1`` (radians, counter-clockwise positive)."""
    full = max(segments, aa.segments_for(radius))
    steps = max(2, int(full * abs(a1 - a0) / math.tau) + 1)
    verts = [
        (cx + math.cos(a0 + (a1 - a0) * i / steps) * radius,
         cy + math.sin(a0 + (a1 - a0) * i / steps) * radius)
        for i in range(steps + 1)
    ]
    polyline(verts, color, width)


def gradient_quad(r, c00, c10, c11, c01):
    """Rectangle ``r`` with corner colors (bottom-left, bottom-right, top-right, top-left).
    Not snapped: neighbouring gradient cells must meet exactly."""
    a, b, c, d = (r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)
    shaded_tris([a, b, c, a, c, d], [c00, c10, c11, c00, c11, c01])


def sector(cx, cy, radius, a0, a1, color, segments=24, rim=None):
    """Filled pie slice from angle ``a0`` to ``a1`` (radians, counter-clockwise from +x)."""
    full = aa.segments_for(radius)
    segments = max(segments, int(full * abs(a1 - a0) / math.tau) + 1)
    pts = [(cx, cy)] + [(cx + math.cos(a0 + (a1 - a0) * i / segments) * radius,
                         cy + math.sin(a0 + (a1 - a0) * i / segments) * radius) for i in range(segments + 1)]
    _fill(pts, color, rim)


def ring_segment(inner, outer, color, rim=None):
    """Filled ring segment from :func:`geometry.ring_segment_points` outlines
    (also corner segments); ``rim``: color of a 1 px line along its outline."""
    n = len(inner)
    if n < 2 or n != len(outer):
        return
    outline = list(inner) + list(reversed(outer))
    solid = aa.offset_points(outline, -aa.EDGE)
    inner_s, outer_s = solid[:n], list(reversed(solid[n:]))
    verts = []
    for i in range(n - 1):
        verts += [inner_s[i], outer_s[i], outer_s[i + 1], inner_s[i], outer_s[i + 1], inner_s[i + 1]]
    _draw('TRIS', verts, color)
    _mesh(*aa.fringe_mesh(outline, color))
    if rim is not None:
        polyline(outline, rim, 1.0, closed=True)


def ring_segment_outline(inner, outer, color, width=1.5):
    if len(inner) < 2:
        return
    polyline(list(inner) + list(reversed(outer)), color, width, closed=True)


def gradient_line(p0, p1, c0, c1, width=1.5):
    """Straight line ``width`` px wide, colored from ``c0`` at ``p0`` to ``c1`` at ``p1`` (e.g. a fade)."""
    _mesh(*aa.stroke_mesh([p0, p1], c0, width, colors=[c0, c1]))


def gradient_circle(cx, cy, radius, left, right, segments=36):
    """Disc shaded horizontally from color ``left`` to ``right`` (RGBA)."""
    def _at(x):
        t = (x - (cx - radius)) / max(2.0 * radius, 1e-6)
        return tuple(left[i] + (right[i] - left[i]) * t for i in range(4))

    pts = aa.circle_points(cx, cy, radius, max(segments, aa.segments_for(radius)))
    solid = aa.circle_points(cx, cy, max(0.0, radius - aa.EDGE), len(pts))
    verts, colors = [], []
    for i in range(len(solid)):
        for p in ((cx, cy), solid[i], solid[(i + 1) % len(solid)]):
            verts.append(p)
            colors.append(_at(p[0]))
    shaded_tris(verts, colors)
    _mesh(*aa.fringe_mesh(pts, [_at(p[0]) for p in pts]))


def triangle(p0, p1, p2, color, rim=None):
    _fill([p0, p1, p2], color, rim)


def polyline(points, color, width=1.0, closed=False):
    """Line through ``points`` (``closed``: back to the first), ``width`` px, soft edges."""
    _mesh(*aa.stroke_mesh(list(points), color, width, closed=closed))


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


def text_along(text, x, y, size, color, angle, font_id=0):
    """``text`` running in direction ``angle`` (radians, counter-clockwise from +x),
    starting at ``(x, y)``, centered on that line (its height straddles the point)."""
    if not text or size < 1.0 or color[3] <= 0.0:
        return
    blf.size(font_id, size)
    _w, h = blf.dimensions(font_id, text)
    # Baseline start: half the height "down" (perpendicular to the direction).
    ox, oy = x + math.sin(angle) * h * 0.5, y - math.cos(angle) * h * 0.5
    blf.enable(font_id, blf.ROTATION)
    try:
        blf.rotation(font_id, angle)
        blf.position(font_id, ox, oy, 0)
        blf.color(font_id, *color)
        blf.draw(font_id, text)
    finally:
        blf.rotation(font_id, 0.0)
        blf.disable(font_id, blf.ROTATION)
