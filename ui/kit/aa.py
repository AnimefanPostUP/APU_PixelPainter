"""Geometric anti-aliasing for overlay drawing (pure Python; :mod:`.draw` renders the meshes).

POST_PIXEL overlays have no multisampling, so edges of filled triangles and GL
lines come out jagged (and GL line widths above 1 px are not supported on
every GPU backend). Instead:

* Coverage: a pixel should get the share of the shape covering it. For an edge
  that is a ramp from 0.5 px inside the edge (full color) to 0.5 px outside
  (transparent), sampled at the pixel centers. Sloped edges get smooth
  in-between pixels where they would otherwise stair-step, while an edge lying
  on the pixel grid stays perfectly crisp.
* :func:`fringe_mesh` -- that ramp around a filled polygon; the solid fill is
  drawn :data:`EDGE` px smaller (:func:`offset_points`) so the two meet.
* :func:`stroke_mesh` -- lines as triangle strips: a solid core and a fading
  ``AA`` px rim on both sides, with mitred joins. Any width, any backend.
* :func:`segments_for` -- enough vertices for a curve's on-screen size, so big
  circles and arcs do not look faceted.

Meshes are ``(verts, colors)``: flat triangle lists with per-vertex RGBA colors.
Both builders are memoized (most overlay shapes repeat frame after frame); the
returned lists are shared, so callers must not modify them.
"""

import math
from functools import lru_cache

AA = 1.0                  # px: width of the soft edge (a coverage ramp across one pixel)
EDGE = AA * 0.5           # the ramp reaches this far inside and outside the true edge
_MAX_MITER = 3.0          # sharper corners are bevelled to this length (x half width)


def segments_for(radius, minimum=12, spacing=3.0, maximum=256):
    """Vertices for a full circle of ``radius`` px: one about every ``spacing`` px."""
    return max(minimum, min(maximum, int(math.tau * max(0.0, radius) / spacing)))


def circle_points(cx, cy, radius, segments=None):
    n = segments or segments_for(radius)
    return [(cx + math.cos(i / n * math.tau) * radius, cy + math.sin(i / n * math.tau) * radius)
            for i in range(n)]


def _dedupe(points, closed):
    """``(points, kept indices)`` without repeated consecutive points (nor a repeated
    closing point for ``closed`` outlines)."""
    out, kept = [], []
    for i, p in enumerate(points):
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > 1e-6:
            out.append((float(p[0]), float(p[1])))
            kept.append(i)
    if closed and len(out) > 1 and math.hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) <= 1e-6:
        out.pop()
        kept.pop()
    return out, kept


def _signed_area(points):
    return 0.5 * sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1]))


def _left_normal(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy) or 1e-9
    return -dy / length, dx / length


def _miter(n0, n1):
    """Vertex offset direction between edge normals ``n0`` / ``n1``, scaled so the
    offset edges stay at distance 1 (limited at sharp corners)."""
    mx, my = n0[0] + n1[0], n0[1] + n1[1]
    length = math.hypot(mx, my)
    if length < 1e-6:
        return n1
    mx, my = mx / length, my / length
    scale = 1.0 / max(1.0 / _MAX_MITER, mx * n1[0] + my * n1[1])
    return mx * scale, my * scale


def _vertex_normals(points, closed):
    """Left-side miter normal per vertex."""
    n = len(points)
    if closed:
        edges = [_left_normal(points[i], points[(i + 1) % n]) for i in range(n)]
        return [_miter(edges[i - 1], edges[i]) for i in range(n)]
    edges = [_left_normal(points[i], points[i + 1]) for i in range(n - 1)]
    out = [edges[0]]
    out += [_miter(edges[i - 1], edges[i]) for i in range(1, n - 1)]
    out.append(edges[-1])
    return out


def _transparent(color):
    return (color[0], color[1], color[2], 0.0)


def _key(points):
    return tuple((float(x), float(y)) for x, y in points)


def _color_key(colors):
    if colors and isinstance(colors[0], (tuple, list)):
        return tuple(tuple(c) for c in colors)
    return tuple(colors)


def fringe_mesh(points, colors, width=AA):
    """Soft edge around the closed polygon ``points`` (see :func:`_fringe_mesh`)."""
    return _fringe_mesh(_key(points), _color_key(colors), width)


def offset_points(points, distance):
    """The closed polygon ``points`` moved ``distance`` px outward (negative:
    inward) along mitred normals; same length and order as ``points``, so it can
    replace them in a strip / fan (e.g. the solid fill inside a fringe)."""
    return _offset_points(_key(points), distance)


@lru_cache(maxsize=4096)
def _offset_points(points, distance):
    pts, kept = _dedupe(points, closed=True)
    if len(pts) < 3 or not distance:
        return list(points)
    outward = -1.0 if _signed_area(pts) > 0.0 else 1.0
    d = distance * outward
    moved = [(x + nx * d, y + ny * d) for (x, y), (nx, ny) in zip(pts, _vertex_normals(pts, closed=True))]
    out, k = [], 0
    first = points[0]
    for i, p in enumerate(points):
        while k + 1 < len(kept) and kept[k + 1] <= i:
            k += 1
        if i > kept[-1] and math.hypot(p[0] - first[0], p[1] - first[1]) <= 1e-6:
            out.append(moved[0])          # a repeated closing point
        else:
            out.append(moved[k])
    return out


def stroke_mesh(points, color, width=1.0, closed=False, colors=None):
    """Soft-edged line through ``points`` (see :func:`_stroke_mesh`)."""
    return _stroke_mesh(_key(points), tuple(color), width, closed,
                        None if colors is None else _color_key(colors))


@lru_cache(maxsize=4096)
def _fringe_mesh(points, colors, width=AA):
    """Coverage ramp across the edge of the closed polygon ``points``: full color
    ``width / 2`` px inside, transparent ``width / 2`` px outside. ``colors``: one
    RGBA, or one per point (gradients). Convex or concave, either winding."""
    pts, kept = _dedupe(points, closed=True)
    if len(pts) < 3:
        return [], []
    if colors and isinstance(colors[0], (tuple, list)):
        cols = [tuple(colors[i]) for i in kept]
    else:
        cols = [tuple(colors)] * len(pts)
    outward = -1.0 if _signed_area(pts) > 0.0 else 1.0   # left normals point inward on a CCW polygon
    normals = _vertex_normals(pts, closed=True)
    half = width * 0.5 * outward
    inner = [(x - nx * half, y - ny * half) for (x, y), (nx, ny) in zip(pts, normals)]
    outer = [(x + nx * half, y + ny * half) for (x, y), (nx, ny) in zip(pts, normals)]
    verts, out_colors = [], []
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        ci, cj = cols[i], cols[j]
        verts += [inner[i], inner[j], outer[j], inner[i], outer[j], outer[i]]
        out_colors += [ci, cj, _transparent(cj), ci, _transparent(cj), _transparent(ci)]
    return verts, out_colors


@lru_cache(maxsize=4096)
def _stroke_mesh(points, color, width=1.0, closed=False, colors=None):
    """A line through ``points``, ``width`` px wide overall, with soft edges.
    ``colors`` (one per point) overrides ``color`` (e.g. a fading line). Lines
    thinner than 1 px keep a 1 px footprint and get fainter instead."""
    pts, kept = _dedupe(points, closed)
    if len(pts) < 2:
        return [], []
    cols = [tuple(colors[i]) for i in kept] if colors is not None else [tuple(color)] * len(pts)
    fade = min(1.0, max(0.0, width))
    if fade < 1.0:
        cols = [(c[0], c[1], c[2], c[3] * fade) for c in cols]
    core = max(0.0, width - AA) * 0.5
    edge = core + AA
    normals = _vertex_normals(pts, closed)

    def rail(offset):
        return [(x + nx * offset, y + ny * offset) for (x, y), (nx, ny) in zip(pts, normals)]

    left_out, left_in, right_in, right_out = rail(edge), rail(core), rail(-core), rail(-edge)
    n = len(pts)
    seg = range(n) if closed else range(n - 1)
    verts, out_colors = [], []

    def quad(a0, a1, b0, b1, ca0, ca1, cb0, cb1):
        verts.extend([a0, a1, b1, a0, b1, b0])
        out_colors.extend([ca0, ca1, cb1, ca0, cb1, cb0])

    for i in seg:
        j = (i + 1) % n
        ci, cj = cols[i], cols[j]
        ti, tj = _transparent(ci), _transparent(cj)
        quad(left_out[i], left_out[j], left_in[i], left_in[j], ti, tj, ci, cj)
        if core > 0.0:
            quad(left_in[i], left_in[j], right_in[i], right_in[j], ci, cj, ci, cj)
        quad(right_in[i], right_in[j], right_out[i], right_out[j], ci, cj, ti, tj)
    return verts, out_colors
