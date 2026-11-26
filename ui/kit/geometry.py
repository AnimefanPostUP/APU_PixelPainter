"""2D geometry helpers for the UI kit.

All coordinates are region pixels (origin bottom-left, as delivered by
``event.mouse_region_x/y`` and used by POST_PIXEL draw handlers).
This module has no Blender dependency.
"""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    """Axis-aligned rectangle. ``x0/y0`` is bottom-left, ``x1/y1`` top-right."""

    x0: float = 0.0
    y0: float = 0.0
    x1: float = 0.0
    y1: float = 0.0

    @classmethod
    def from_center(cls, cx, cy, width, height):
        hw = width * 0.5
        hh = height * 0.5
        return cls(cx - hw, cy - hh, cx + hw, cy + hh)

    @classmethod
    def from_size(cls, x, y, width, height):
        return cls(x, y, x + width, y + height)

    @property
    def width(self):
        return self.x1 - self.x0

    @property
    def height(self):
        return self.y1 - self.y0

    @property
    def cx(self):
        return (self.x0 + self.x1) * 0.5

    @property
    def cy(self):
        return (self.y0 + self.y1) * 0.5

    @property
    def is_empty(self):
        return self.width <= 0.0 or self.height <= 0.0

    def contains(self, x, y):
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1

    def offset(self, dx, dy):
        return Rect(self.x0 + dx, self.y0 + dy, self.x1 + dx, self.y1 + dy)

    def expand(self, margin):
        return Rect(self.x0 - margin, self.y0 - margin, self.x1 + margin, self.y1 + margin)

    def union(self, other):
        if other is None or other.is_empty:
            return self
        if self.is_empty:
            return other
        return Rect(min(self.x0, other.x0), min(self.y0, other.y0),
                    max(self.x1, other.x1), max(self.y1, other.y1))

    def scaled(self, factor):
        """Scale about the rect's own center."""
        return Rect.from_center(self.cx, self.cy, self.width * factor, self.height * factor)

    def as_tuple(self):
        return (self.x0, self.y0, self.x1, self.y1)


def clamp(value, lo, hi):
    return lo if value < lo else hi if value > hi else value


def lerp(a, b, t):
    return a + (b - a) * t


def lerp2(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def normalize(dx, dy, fallback=(0.0, 0.0)):
    """Return ``(ux, uy, length)``; ``fallback`` direction when degenerate."""
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return fallback[0], fallback[1], 0.0
    return dx / length, dy / length, length


def point_on_circle_toward(cx, cy, radius, tx, ty):
    ux, uy, _ = normalize(tx - cx, ty - cy)
    return cx + ux * radius, cy + uy * radius


def point_on_rect_toward(rect, tx, ty):
    """Point where the ray from the rect center toward ``(tx, ty)`` leaves the rect."""
    cx, cy = rect.cx, rect.cy
    half_w = rect.width * 0.5
    half_h = rect.height * 0.5
    dx = tx - cx
    dy = ty - cy
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return cx, cy
    scale = max(abs(dx) / max(half_w, 1e-6), abs(dy) / max(half_h, 1e-6))
    if scale <= 1e-6:
        return cx, cy
    return cx + dx / scale, cy + dy / scale


def fit_offset(bounds, width, height, margin=0.0):
    """Offset ``(dx, dy)`` that moves ``bounds`` inside a ``width x height`` area.

    When the bounds are larger than the area, they are aligned to the top/left
    edge so the most important (upper) part of a menu stays visible.
    """
    def _axis(lo, hi, size):
        avail_lo = margin
        avail_hi = size - margin
        if hi - lo > avail_hi - avail_lo:
            return avail_lo - lo if lo < avail_lo else 0.0
        if lo < avail_lo:
            return avail_lo - lo
        if hi > avail_hi:
            return avail_hi - hi
        return 0.0

    dx = _axis(bounds.x0, bounds.x1, width)
    # Vertically, prefer keeping the top visible when it does not fit.
    if bounds.height > height - 2.0 * margin:
        dy = (height - margin) - bounds.y1
    else:
        dy = _axis(bounds.y0, bounds.y1, height)
    return dx, dy


# ---------------------------------------------------------------------------
# Ring segments (annular sectors, e.g. the pen dial)
# ---------------------------------------------------------------------------

def normalize_angle(angle, start):
    """``angle`` (radians) shifted into ``[start, start + tau)``."""
    return start + (angle - start) % math.tau


def ring_contains(cx, cy, r0, r1, a0, a1, x, y):
    """Is ``(x, y)`` inside the ring segment ``r0..r1`` x ``a0..a1`` (radians, a0 < a1)?"""
    r = math.hypot(x - cx, y - cy)
    if not r0 <= r <= r1:
        return False
    return normalize_angle(math.atan2(y - cy, x - cx), a0) <= a1


def ring_edge_angles(r, a0, a1, inset, inset1=None):
    """Angles at radius ``r`` of the segment's side edges, each moved ``inset`` px
    (the ``a1`` edge: ``inset1`` px, default the same) inward *parallel* to its
    radial line -- so the gap between neighbours has the same width at every
    radius. ``None`` when nothing is left at that radius."""
    inset1 = inset if inset1 is None else inset1
    if r <= max(inset, inset1):
        return None
    b0 = a0 + math.asin(min(1.0, inset / r))
    b1 = a1 - math.asin(min(1.0, inset1 / r))
    return (b0, b1) if b1 > b0 else None


def ring_segment_points(cx, cy, r0, r1, a0, a1, inset=0.0, steps=None, inset1=None):
    """``(inner, outer)`` outline points of a ring segment shrunk by ``inset`` px on
    its side edges (``inset1``: the ``a1`` edge, default the same), both running
    from the ``a0`` side to the ``a1`` side. Empty lists when the segment vanishes."""
    inner_edges = ring_edge_angles(r0, a0, a1, inset, inset1) if r0 > 0.0 else (a0, a1)
    outer_edges = ring_edge_angles(r1, a0, a1, inset, inset1)
    if inner_edges is None or outer_edges is None:
        return [], []
    if steps is None:   # a vertex about every 3 px along the outer arc
        steps = max(2, int(abs(a1 - a0) * max(r0, r1) / 3.0) + 1)

    def _arc(r, b0, b1):
        return [(cx + math.cos(b0 + (b1 - b0) * i / steps) * r,
                 cy + math.sin(b0 + (b1 - b0) * i / steps) * r) for i in range(steps + 1)]

    return _arc(r0, *inner_edges), _arc(r1, *outer_edges)


def clamp_box(x0, y0, width, height, bounds):
    """Bottom-left ``(x0, y0)`` of a ``width x height`` box moved inside ``bounds``
    (x0, y0, x1, y1). A box larger than the bounds keeps its left / top edge inside."""
    bx0, by0, bx1, by1 = bounds
    x0 = max(bx0, min(x0, bx1 - width))
    y1 = min(by1, max(y0 + height, by0 + height))
    return x0, y1 - height


# ---------------------------------------------------------------------------
# Corner segments (between a circle and its enclosing square)
# ---------------------------------------------------------------------------
# Coordinates relative to the shared center. The square has half size ``half``;
# its corners are cut off diagonally by ``chamfer`` px (room for corner buttons).

def chamfered_square(half, chamfer):
    """Vertices (counter-clockwise) of the square with its corners cut by ``chamfer``."""
    k = max(0.0, min(chamfer, half))
    if k <= 0.0:
        return [(half, -half), (half, half), (-half, half), (-half, -half)]
    return [(half, -half + k), (half, half - k), (half - k, half), (-half + k, half),
            (-half, half - k), (-half, -half + k), (-half + k, -half), (half - k, -half)]


def _edges(poly):
    """``(nx, ny, c)`` per edge of a convex CCW polygon: inside where n . p <= c."""
    out = []
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        ex, ey = x1 - x0, y1 - y0
        length = math.hypot(ex, ey)
        if length < 1e-9:
            continue
        nx, ny = ey / length, -ex / length
        out.append((nx, ny, nx * x0 + ny * y0))
    return out


def _exit_distance(q, d, edges):
    t = math.inf
    for nx, ny, c in edges:
        nd = nx * d[0] + ny * d[1]
        if nd > 1e-9:
            t = min(t, (c - nx * q[0] - ny * q[1]) / nd)
    return t


def _resample(points, count):
    """``count`` points along the polyline, keeping its vertices."""
    legs = [math.dist(a, b) for a, b in zip(points, points[1:])]
    total = sum(legs)
    if total <= 1e-9 or count < len(points):
        return list(points)
    out = []
    remaining = count - 1
    for i, (a, b) in enumerate(zip(points, points[1:])):
        last = i == len(legs) - 1
        n = remaining if last else max(1, round(legs[i] / total * (count - 1)))
        n = min(n, remaining - (len(legs) - 1 - i))
        remaining -= n
        out += [(a[0] + (b[0] - a[0]) * j / n, a[1] + (b[1] - a[1]) * j / n) for j in range(n)]
    out.append(points[-1])
    return out


def corner_segment_points(r0, half, a0, a1, inset0=0.0, inset1=0.0, chamfer=0.0, steps=None):
    """``(inner, outer)`` outline (relative to the center) of the part of the square
    outside the circle ``r0`` between angles ``a0 < a1`` (radians), its side edges
    moved inward ``inset0`` / ``inset1`` px parallel to their rays. Both lists run
    from the ``a0`` side to the ``a1`` side with the same length (a triangle strip).
    Empty lists when nothing is left. ``steps`` (default: about one per 3 px of
    the outer edge) = points per edge - 1."""
    angles = ring_edge_angles(r0, a0, a1, inset0, inset1)
    if angles is None:
        return [], []
    b0, b1 = angles
    poly = chamfered_square(half, chamfer)
    edges = _edges(poly)
    i0 = (math.cos(b0) * r0, math.sin(b0) * r0)
    i1 = (math.cos(b1) * r0, math.sin(b1) * r0)
    d0, d1 = (math.cos(a0), math.sin(a0)), (math.cos(a1), math.sin(a1))
    t0, t1 = _exit_distance(i0, d0, edges), _exit_distance(i1, d1, edges)
    if not (0.0 < t0 < math.inf and 0.0 < t1 < math.inf):
        return [], []
    p0 = (i0[0] + d0[0] * t0, i0[1] + d0[1] * t0)
    p1 = (i1[0] + d1[0] * t1, i1[1] + d1[1] * t1)
    start = math.atan2(p0[1], p0[0])
    span = normalize_angle(math.atan2(p1[1], p1[0]), start) - start
    corners = sorted((normalize_angle(math.atan2(y, x), start) - start, (x, y)) for x, y in poly)
    outer = [p0] + [v for a, v in corners if 1e-9 < a < span - 1e-9] + [p1]
    if steps is None:
        length = sum(math.dist(a, b) for a, b in zip(outer, outer[1:]))
        steps = max(8, int(max(length, (b1 - b0) * r0) / 3.0))
    outer = _resample(outer, steps + 1)
    inner = [(math.cos(b0 + (b1 - b0) * i / (len(outer) - 1)) * r0,
              math.sin(b0 + (b1 - b0) * i / (len(outer) - 1)) * r0) for i in range(len(outer))]
    return inner, outer


def corner_contains(r0, half, a0, a1, chamfer, x, y):
    """Is ``(x, y)`` (relative to the center) in the corner segment (without insets)?"""
    if math.hypot(x, y) < r0:
        return False
    if any(nx * x + ny * y > c for nx, ny, c in _edges(chamfered_square(half, chamfer))):
        return False
    return normalize_angle(math.atan2(y, x), a0) <= a1


def polygon_centroid(points):
    """Area centroid of a simple polygon (vertex mean when degenerate)."""
    area = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1]):
        cross = x0 * y1 - x1 * y0
        area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(area) < 1e-9:
        n = max(1, len(points))
        return sum(p[0] for p in points) / n, sum(p[1] for p in points) / n
    return cx / (3.0 * area), cy / (3.0 * area)


def corner_room(point, r0, half, a0, a1, inset0, inset1, chamfer):
    """Radius of the largest circle around ``point`` inside the (inset) corner segment."""
    x, y = point
    room = math.hypot(x, y) - r0
    room = min(room, min(c - nx * x - ny * y for nx, ny, c in _edges(chamfered_square(half, chamfer))))
    room = min(room, -math.sin(a0) * x + math.cos(a0) * y - inset0)
    room = min(room, math.sin(a1) * x - math.cos(a1) * y - inset1)
    return max(0.0, room)


# ---------------------------------------------------------------------------
# Rounded strips (ring / corner segments with round corners)
# ---------------------------------------------------------------------------

def _length(points):
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def _trim(points, start, end):
    """The part of the polyline between arc lengths ``start`` and ``end``."""
    out, travelled = [], 0.0
    for a, b in zip(points, points[1:]):
        leg = math.dist(a, b)
        lo, hi = travelled, travelled + leg
        if hi >= start and lo <= end and leg > 1e-9:
            if not out:
                t = max(0.0, (start - lo) / leg)
                out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            if hi <= end:
                out.append(b)
            else:
                t = (end - lo) / leg
                out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
                break
        travelled = hi
    return out


def _toward(p, q, distance):
    """The point ``distance`` from ``p`` toward ``q``."""
    d = math.dist(p, q)
    if d < 1e-9:
        return p
    return p[0] + (q[0] - p[0]) * distance / d, p[1] + (q[1] - p[1]) * distance / d


def _fillet(p0, corner, p1, steps):
    """Quadratic curve from ``p0`` to ``p1`` with ``corner`` as control point (a round corner)."""
    out = []
    for i in range(steps + 1):
        t = i / steps
        u = 1.0 - t
        out.append((u * u * p0[0] + 2.0 * u * t * corner[0] + t * t * p1[0],
                    u * u * p0[1] + 2.0 * u * t * corner[1] + t * t * p1[1]))
    return out


def round_strip(inner, outer, radius, steps=6):
    """``(inner, outer)`` strip outline (as from :func:`ring_segment_points` /
    :func:`corner_segment_points`) with its four corners rounded by ``radius`` px
    (less where the segment is too small). Still two lists of equal length running
    from the first side edge to the second, usable as a triangle strip."""
    if radius <= 0.0 or len(inner) < 2 or len(inner) != len(outer):
        return inner, outer
    li, lo = _length(inner), _length(outer)
    r = min(radius, 0.5 * math.dist(inner[0], outer[0]), 0.5 * math.dist(inner[-1], outer[-1]),
            0.5 * li, 0.5 * lo)
    if r < 0.5:
        return inner, outer
    mid_in, mid_out = _trim(inner, r, li - r), _trim(outer, r, lo - r)
    if len(mid_in) < 2 or len(mid_out) < 2:
        return inner, outer
    count = max(len(mid_in), len(mid_out))
    mid_in, mid_out = _resample(mid_in, count), _resample(mid_out, count)
    if len(mid_in) != len(mid_out):
        return inner, outer
    head_in = _fillet(_toward(inner[0], outer[0], r), inner[0], mid_in[0], steps)
    head_out = _fillet(_toward(outer[0], inner[0], r), outer[0], mid_out[0], steps)
    tail_in = _fillet(mid_in[-1], inner[-1], _toward(inner[-1], outer[-1], r), steps)
    tail_out = _fillet(mid_out[-1], outer[-1], _toward(outer[-1], inner[-1], r), steps)
    return (head_in[:-1] + mid_in + tail_in[1:], head_out[:-1] + mid_out + tail_out[1:])


def best_circle(r0, half, a0, a1, inset0, inset1, chamfer, samples=48):
    """``(center, radius)`` (relative to the dial center) of the largest circle on the
    middle ray of the corner segment ``a0 .. a1`` (radians) that fits inside it."""
    mid = (a0 + a1) * 0.5
    ux, uy = math.cos(mid), math.sin(mid)
    poly = chamfered_square(half, chamfer)
    far = _exit_distance((0.0, 0.0), (ux, uy), _edges(poly))
    if not (r0 < far < math.inf):
        return (ux * r0, uy * r0), 0.0
    best = ((ux * r0, uy * r0), 0.0)
    for i in range(1, samples):
        d = r0 + (far - r0) * i / samples
        p = (ux * d, uy * d)
        room = corner_room(p, r0, half, a0, a1, inset0, inset1, chamfer)
        if room > best[1]:
            best = (p, room)
    return best
