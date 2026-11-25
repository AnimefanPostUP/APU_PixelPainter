"""Mask geometry (pure numpy, no bpy): group a mesh's faces into UV islands or
mesh parts and rasterize them into pixel sets.

* :func:`uv_island_labels` -- faces connected through an edge that has the same
  UV coordinates on both sides belong to one island (UV seams split islands).
* :func:`mesh_part_labels` -- faces connected through vertices / edges belong
  to one part (loose parts are separate).
* :func:`raster_triangles` -- texture pixels whose *center* lies inside UV
  triangles (optionally grown by a margin in pixels), as flat indices
  ``y * width + x``. With pixel-aligned UVs an island covers exactly its pixels.
* :func:`blocked_runs` / :func:`run_triangles` -- horizontal runs of blocked
  pixels, as triangles for the mask overlay.
"""

import numpy as np

from ..utils import native   # optional C# rasterizer (no bpy)


def components(n, a, b):
    """Connected-component labels (0..k-1) of ``n`` nodes joined by the pairs ``a[i]`` -- ``b[i]``."""
    labels = np.arange(n, dtype=np.int64)
    a = np.asarray(a, dtype=np.int64)
    b = np.asarray(b, dtype=np.int64)
    if n == 0:
        return labels
    if len(a):
        while True:
            la, lb = labels[a], labels[b]
            low = np.minimum(la, lb)
            new = labels.copy()
            np.minimum.at(new, la, low)     # hook each root onto the smaller root
            np.minimum.at(new, lb, low)
            while True:                     # pointer jumping: everyone points at its root
                nxt = new[new]
                if np.array_equal(nxt, new):
                    break
                new = nxt
            if np.array_equal(new, labels):
                break
            labels = new
    _, compact = np.unique(labels, return_inverse=True)
    return compact.astype(np.int64)


def _poly_of_loop(loop_start, loop_total, n_loops):
    poly = np.empty(n_loops, dtype=np.int64)
    for_poly = np.repeat(np.arange(len(loop_start), dtype=np.int64), loop_total)
    starts = np.repeat(np.asarray(loop_start, dtype=np.int64), loop_total)
    offsets = np.arange(len(for_poly), dtype=np.int64) - np.repeat(
        np.cumsum(loop_total) - loop_total, loop_total)
    poly[starts + offsets] = for_poly
    return poly


def uv_island_labels(loop_start, loop_total, loop_vert, loop_uv, precision=1e5):
    """Island label per polygon: polygons sharing an edge with equal UVs on both sides."""
    loop_start = np.asarray(loop_start, dtype=np.int64)
    loop_total = np.asarray(loop_total, dtype=np.int64)
    loop_vert = np.asarray(loop_vert, dtype=np.int64)
    n_polys, n_loops = len(loop_start), len(loop_vert)
    if n_polys == 0:
        return np.zeros(0, dtype=np.int64)
    poly = _poly_of_loop(loop_start, loop_total, n_loops)
    nxt = np.arange(n_loops, dtype=np.int64) + 1
    nxt[loop_start + loop_total - 1] = loop_start           # the last loop of a face wraps around
    q = np.round(np.asarray(loop_uv, dtype=np.float64).reshape(-1, 2) * precision).astype(np.int64)
    va, vb = loop_vert, loop_vert[nxt]
    ua, ub = q, q[nxt]
    swap = va > vb
    v0, v1 = np.where(swap, vb, va), np.where(swap, va, vb)
    u0, u1 = np.where(swap[:, None], ub, ua), np.where(swap[:, None], ua, ub)
    keys = np.column_stack([v0, v1, u0, u1])
    _, edge = np.unique(keys, axis=0, return_inverse=True)
    edge = edge.ravel()
    order = np.argsort(edge, kind='stable')
    sorted_edge = edge[order]
    same = sorted_edge[1:] == sorted_edge[:-1]
    return components(n_polys, poly[order[:-1][same]], poly[order[1:][same]])


def mesh_part_labels(loop_start, loop_vert, n_verts, edge_verts):
    """Part label per polygon: polygons connected through vertices (loose parts are separate)."""
    loop_start = np.asarray(loop_start, dtype=np.int64)
    if len(loop_start) == 0:
        return np.zeros(0, dtype=np.int64)
    edge_verts = np.asarray(edge_verts, dtype=np.int64).reshape(-1, 2)
    vert_label = components(n_verts, edge_verts[:, 0], edge_verts[:, 1])
    first_vert = np.asarray(loop_vert, dtype=np.int64)[loop_start]
    _, compact = np.unique(vert_label[first_vert], return_inverse=True)
    return compact.astype(np.int64)


def raster_triangles(tri_uv, width, height, grow=0.0):
    """Sorted flat pixel indices (``y * width + x``) whose center lies inside any of
    the UV triangles ``tri_uv`` (T, 3, 2), each edge pushed out by ``grow`` pixels."""
    if native.enabled():
        mask = native.raster_triangles(tri_uv, width, height, grow)
        if mask is not None:
            return np.flatnonzero(mask).astype(np.int64)
    pts = np.asarray(tri_uv, dtype=np.float64).reshape(-1, 3, 2) * (float(width), float(height))
    reach = float(grow) + 1e-6
    chunks = []
    for tri in pts:
        e1, e2 = tri[1] - tri[0], tri[2] - tri[0]
        cross = e1[0] * e2[1] - e1[1] * e2[0]
        if abs(cross) < 1e-12:
            continue
        lo = np.floor(tri.min(axis=0) - grow).astype(np.int64)
        hi = np.ceil(tri.max(axis=0) + grow).astype(np.int64)
        x0, y0 = max(0, int(lo[0])), max(0, int(lo[1]))
        x1, y1 = min(width, int(hi[0]) + 1), min(height, int(hi[1]) + 1)
        if x0 >= x1 or y0 >= y1:
            continue
        px = np.arange(x0, x1, dtype=np.float64)[None, :] + 0.5
        py = np.arange(y0, y1, dtype=np.float64)[:, None] + 0.5
        inside = np.ones((y1 - y0, x1 - x0), dtype=bool)
        sign = 1.0 if cross > 0 else -1.0
        for i in range(3):
            a, b = tri[i], tri[(i + 1) % 3]
            ex, ey = b - a
            length = float(np.hypot(ex, ey))
            if length < 1e-12:
                continue
            dist = sign * (ex * (py - a[1]) - ey * (px - a[0])) / length   # > 0: inside
            inside &= dist >= -reach
        ys, xs = np.nonzero(inside)
        if len(ys):
            chunks.append((ys + y0) * width + (xs + x0))
    if not chunks:
        return np.zeros(0, dtype=np.int64)
    return np.unique(np.concatenate(chunks).astype(np.int64))


def contains(sorted_pixels, pixel):
    """``pixel`` in the sorted array ``sorted_pixels``."""
    i = int(np.searchsorted(sorted_pixels, pixel))
    return i < len(sorted_pixels) and int(sorted_pixels[i]) == int(pixel)


def blocked_runs(blocked):
    """Horizontal runs of True in the (h, w) array: ``(rows, x_start, x_end)``, end exclusive."""
    blocked = np.asarray(blocked, dtype=bool)
    h, w = blocked.shape
    pad = np.zeros((h, w + 2), dtype=np.int8)
    pad[:, 1:-1] = blocked
    d = np.diff(pad, axis=1)
    rows, starts = np.nonzero(d == 1)
    _rows_end, ends = np.nonzero(d == -1)      # row-major: pairs up with the starts
    return rows, starts, ends


def run_triangles(rows, starts, ends):
    """Two triangles per run, (6 * N, 2) float32 vertices in pixel units."""
    y0 = rows.astype(np.float32)
    y1 = y0 + 1.0
    x0, x1 = starts.astype(np.float32), ends.astype(np.float32)
    verts = np.stack([x0, y0, x1, y0, x1, y1, x0, y0, x1, y1, x0, y1], axis=1)
    return verts.reshape(-1, 2)
