"""Shortest paths over the surface (Edge-mode Line): the corridor of triangles between two
surface points, the funnel algorithm on the unfolded corridor, and :func:`edge_line`.
"""

import math

import numpy as np

from ...utils import math_utils
from .frames import adjacency, bary3d, frame_from, grow, place_neighbor
from . import mesh


# ---- shortest path across faces (Edge-mode Line) ---------------------------------

MAX_SEARCH_TRIS = 200_000


def _tri_neighbors(cache):
    """Per triangle: list of ``(neighbour, va, vb, edge_midpoint)`` (built once per mesh)."""
    nbrs = cache._nbrs
    if nbrs is None:
        adj = adjacency(cache)
        verts = cache.verts.tolist()
        nbrs = []
        for t, (a, b, c) in enumerate(cache.tri_verts.tolist()):
            row = []
            for u, v in ((a, b), (b, c), (c, a)):
                pu, pv = verts[u], verts[v]
                mid = ((pu[0] + pv[0]) * 0.5, (pu[1] + pv[1]) * 0.5, (pu[2] + pv[2]) * 0.5)
                for n in adj[(u, v) if u < v else (v, u)]:
                    if n != t:
                        row.append((n, u, v, mid))
            nbrs.append(row)
        cache._nbrs = nbrs
        cache._centroids = cache.tri_pos.mean(axis=1).tolist()
    return nbrs


def find_corridor(cache, start, goal):
    """Shortest chain of triangles from ``start`` to ``goal`` (A* over face adjacency).

    Moves between neighbouring faces cost centroid -> shared edge midpoint ->
    centroid (surface distance); the heuristic is the straight 3D distance.
    Returns ``[(tri, va, vb), ...]`` where ``va``-``vb`` is the edge entered
    through (``None`` for the start), or None when unreachable.
    """
    import heapq
    nbrs = _tri_neighbors(cache)
    cen = cache._centroids
    if start == goal:
        return [(start, None, None)]
    goal_c = cen[goal]
    g = {start: 0.0}
    came = {}
    heap = [(math.dist(cen[start], goal_c), start)]
    closed = set()
    while heap:
        _f, t = heapq.heappop(heap)
        if t in closed:
            continue
        if t == goal:
            break
        closed.add(t)
        if len(closed) > MAX_SEARCH_TRIS:
            return None
        ct = cen[t]
        gt = g[t]
        for n, u, v, mid in nbrs[t]:
            if n in closed:
                continue
            ng = gt + math.dist(ct, mid) + math.dist(mid, cen[n])
            if ng < g.get(n, math.inf):
                g[n] = ng
                came[n] = (t, u, v)
                heapq.heappush(heap, (ng + math.dist(cen[n], goal_c), n))
    if goal not in came:
        return None
    path = []
    t = goal
    while t != start:
        prev, u, v = came[t]
        path.append((t, u, v))
        t = prev
    path.append((start, None, None))
    path.reverse()
    return path


def _cross2(a, b):
    return a[0] * b[1] - a[1] * b[0]


def funnel(start, end, portals):
    """Shortest polyline from ``start`` to ``end`` through ``portals``.

    Simple stupid funnel algorithm (Mononen). ``portals`` is a list of
    ``(left, right)`` 2D points as seen walking from start to end.
    """
    pts = [(start, start)] + list(portals) + [(end, end)]
    out = [start]
    apex = left = right = start
    apex_i = left_i = right_i = 0
    i = 1
    n = len(pts)
    eq = lambda a, b: abs(a[0] - b[0]) < 1e-12 and abs(a[1] - b[1]) < 1e-12
    while i < n:
        pl, pr = pts[i]
        # tighten the right side
        if _cross2((right[0] - apex[0], right[1] - apex[1]), (pr[0] - apex[0], pr[1] - apex[1])) >= 0.0:
            if eq(apex, right) or _cross2((left[0] - apex[0], left[1] - apex[1]),
                                          (pr[0] - apex[0], pr[1] - apex[1])) < 0.0:
                right, right_i = pr, i
            else:  # right crossed over left: left corner becomes the apex
                out.append(left)
                apex, apex_i = left, left_i
                right, right_i = apex, apex_i
                i = apex_i + 1
                continue
        # tighten the left side
        if _cross2((left[0] - apex[0], left[1] - apex[1]), (pl[0] - apex[0], pl[1] - apex[1])) <= 0.0:
            if eq(apex, left) or _cross2((right[0] - apex[0], right[1] - apex[1]),
                                         (pl[0] - apex[0], pl[1] - apex[1])) > 0.0:
                left, left_i = pl, i
            else:  # left crossed over right: right corner becomes the apex
                out.append(right)
                apex, apex_i = right, right_i
                left, left_i = apex, apex_i
                i = apex_i + 1
                continue
        i += 1
    if not eq(out[-1], end):
        out.append(end)
    return out


def _surface_to_placed(cache, tri, local, P):
    """Placement-frame position of object-space point ``local`` on triangle ``tri``."""
    corners = [cache.verts[i].astype(np.float64) for i in cache.tri_verts[tri]]
    w = bary3d(*corners, np.asarray(local, dtype=np.float64))
    return None if w is None else w @ P


def surface_path(cache, start, end):
    """Shortest surface path between two surface points.

    ``start`` / ``end`` are ``(tri, local_xyz)``. The triangle corridor from
    :func:`find_corridor` is unfolded isometrically into the start
    triangle's texture space (so straight = shortest on the surface) and
    straightened with :func:`funnel`.

    Returns ``(placed, identity, order, polyline)`` -- the corridor placement
    and the path as frame-UV points -- or None.
    """
    corridor = find_corridor(cache, start[0], end[0])
    if corridor is None:
        return None
    first = corridor[0][0]
    placed = {first: cache.tri_uv[first].copy()}
    identity = {first: True}
    order = [first]
    chain = [placed[first]]
    portals = []
    for (prev, _, _), (t, va, vb) in zip(corridor, corridor[1:]):
        if t in placed:
            return None  # corridor revisits a face (should not happen)
        Pn, _connected = place_neighbor(cache, prev, placed[prev], t, va, vb, isometric=True)
        if Pn is None:
            return None
        P = placed[prev]
        V = cache.tri_verts[prev].tolist()
        ka, kb = V.index(va), V.index(vb)
        a, b, c = P[ka], P[kb], P[3 - ka - kb]
        forward = (a + b) * 0.5 - c
        if _cross2(forward, a - c) > 0.0:
            portals.append((tuple(a), tuple(b)))
        else:
            portals.append((tuple(b), tuple(a)))
        placed[t] = Pn
        identity[t] = False
        order.append(t)
    s = _surface_to_placed(cache, start[0], start[1], placed[start[0]])
    e = _surface_to_placed(cache, end[0], end[1], placed[end[0]])
    if s is None or e is None:
        return None
    polyline = funnel(tuple(s), tuple(e), portals)
    return placed, identity, order, [np.array(p, dtype=np.float64) for p in polyline]


def _near_polyline(Pn, polyline, margin):
    """True when placed triangle ``Pn`` comes within ``margin`` of the polyline (conservative)."""
    c = Pn.mean(axis=0)
    reach = np.sqrt(((Pn - c) ** 2).sum(axis=1)).max() + margin
    for a, b in zip(polyline, polyline[1:] or polyline):
        d = b - a
        dd = d @ d
        t = 0.0 if dd < 1e-30 else max(0.0, min(1.0, ((c - a) @ d) / dd))
        if np.linalg.norm(c - (a + d * t)) <= reach:
            return True
    return False


_line_cache_key = None
_line_cache_val = None


def edge_line(context, img, start, end, radius):
    """Edge-mode line: shortest surface path from ``start`` to ``end``.

    Returns ``(frame, line_pixels)``: the frame (corridor plus the faces the
    brush tip can reach, laid out in the start face's texture space) and the
    path rasterised as frame-space texels (not wrapped; pair them with
    ``tile=(0, 0)`` in :func:`expand_footprint`). None when no path exists.
    Results are cached, so painting and the outline share one computation.
    """
    global _line_cache_key, _line_cache_val
    cache = mesh.mesh_cache(context)
    w, h = img.size
    if cache is None or w == 0 or h == 0 or start is None or end is None:
        return None
    key = (cache.version, w, h, radius, start[0], tuple(np.round(start[1], 6)),
           end[0], tuple(np.round(end[1], 6)))
    if key == _line_cache_key:
        return _line_cache_val

    result = None
    path = surface_path(cache, start, end)
    if path is not None:
        placed, identity, order, polyline = path
        size = np.array((w, h), dtype=np.float64)
        margin = (radius + 2.0) / min(w, h)
        grow(cache, placed, identity, order,
              lambda Pn: _near_polyline(Pn, polyline, margin), isometric=True)
        pix = [tuple(int(v) for v in np.floor(p * size)) for p in polyline]
        line = [pix[0]]
        for a, b in zip(pix, pix[1:]):
            line.extend(math_utils.get_line_pixels(a[0], a[1], b[0], b[1])[1:])
        result = (frame_from(cache, placed, identity, order), line)
    _line_cache_key, _line_cache_val = key, result
    return result
