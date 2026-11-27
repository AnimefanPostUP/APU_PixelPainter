"""Edge band math for the Extras window's Edges tool (pure NumPy, no bpy).

The tool paints a band along the model's edges (not the UV borders). Every texel
belongs to an element (UV island / mesh part; -1 = none); each model edge is drawn in
the UV space of each triangle beside it, onto that triangle's element only, so a band
never leaks into a neighbouring island and a seam edge gets a band on both islands.

The band is measured as the true distance from a texel's center to the edge, so it is
the same on both sides of the edge:

* ``'BETWEEN'`` (Symmetric): the edge runs where it lies; an edge on a texel border
  gets the same number of texels on each side (an even band).
* ``'ON'`` (Pixel Line): the edge is snapped onto texel centers first, so it becomes a
  one-texel line and the band spreads evenly from it (an odd band).

* :func:`model_edges` -- which triangle sides are model edges to draw.
* :func:`snap_segments` -- segments moved onto texel centers ('ON').
* :func:`segment_distance` -- per-texel distance to the edges of its own element.
* :func:`band` / :func:`ramp` -- distance -> painted texels; through the falloff curve
  -> gradient position, opacity.
"""

import numpy as np


EDGE_MODES = ('ANGLE', 'ALL', 'MARKED')
MAX_CANDIDATES = 1 << 22     # (segment piece, texel) pairs per chunk


def model_edges(tri_verts, tri_pos, mode='ANGLE', angle_deg=30.0, real_edges=None, marked=None):
    """Triangle sides lying on the chosen model edges: ``(tri, k)`` int arrays (side
    ``k`` runs from corner ``k`` to ``(k + 1) % 3``); an edge yields every triangle beside it.

    ``mode``: 'ANGLE' -- edges whose two faces meet at more than ``angle_deg``;
    'ALL' -- every edge (open borders included); 'MARKED' -- edges in ``marked``.
    ``real_edges`` (E, 2): the mesh's edges -- triangle sides not among them are
    triangulation diagonals and never drawn (None: every side is an edge);
    ``marked`` (E,) bool beside ``real_edges``."""
    tv = np.asarray(tri_verts, dtype=np.int64).reshape(-1, 3)
    n = len(tv)
    empty = np.zeros(0, dtype=np.int64)
    if n == 0:
        return empty, empty
    tri = np.tile(np.arange(n, dtype=np.int64), 3)
    k = np.repeat(np.arange(3, dtype=np.int64), n)
    a, b = tv[tri, k], tv[tri, (k + 1) % 3]
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    base = int(tv.max()) + 1
    side_key = lo * base + hi

    is_edge = np.ones(len(tri), dtype=bool)
    chosen_key = None
    if real_edges is not None:
        re = np.asarray(real_edges, dtype=np.int64).reshape(-1, 2)
        re_key = np.minimum(re[:, 0], re[:, 1]) * base + np.maximum(re[:, 0], re[:, 1])
        is_edge = np.isin(side_key, re_key)
        if marked is not None:
            chosen_key = re_key[np.asarray(marked, dtype=bool)]
    if mode == 'MARKED':
        if chosen_key is None:
            return empty, empty
        keep = is_edge & np.isin(side_key, chosen_key)
        return tri[keep], k[keep]
    if mode == 'ALL':
        return tri[is_edge], k[is_edge]

    # ANGLE: manifold edges whose two face normals differ by more than the angle.
    pos = np.asarray(tri_pos, dtype=np.float64).reshape(-1, 3, 3)
    normal = np.cross(pos[:, 1] - pos[:, 0], pos[:, 2] - pos[:, 0])
    length = np.linalg.norm(normal, axis=1)
    normal = normal / np.where(length > 1e-20, length, 1.0)[:, None]
    order = np.argsort(side_key, kind='stable')
    sk = side_key[order]
    start = np.flatnonzero(np.r_[True, sk[1:] != sk[:-1]])
    count = np.diff(np.r_[start, len(sk)])
    pair = start[count == 2]
    s0, s1 = order[pair], order[pair + 1]
    t0, t1 = tri[s0], tri[s1]
    cos = np.clip(np.einsum('ij,ij->i', normal[t0], normal[t1]), -1.0, 1.0)
    sharp = (cos < np.cos(np.radians(float(angle_deg)))) & (length[t0] > 1e-20) & (length[t1] > 1e-20)
    sharp &= is_edge[s0]
    sides = np.concatenate((s0[sharp], s1[sharp]))
    return tri[sides], k[sides]


def snap_segments(seg_px):
    """Segment ends (pixel units) moved onto the nearest texel centers."""
    seg = np.asarray(seg_px, dtype=np.float64)
    return np.floor(seg) + 0.5


def _split(seg, labels, piece):
    """Long segments cut into pieces no longer than ``piece`` (small bounding boxes)."""
    d = seg[:, 1] - seg[:, 0]
    parts = np.maximum(1, np.ceil(np.linalg.norm(d, axis=1) / piece).astype(np.int64))
    owner = np.repeat(np.arange(len(seg), dtype=np.int64), parts)
    first = np.repeat(np.cumsum(parts) - parts, parts)
    i = np.arange(len(owner), dtype=np.int64) - first
    f0 = (i / np.repeat(parts, parts))[:, None]
    f1 = ((i + 1) / np.repeat(parts, parts))[:, None]
    out = np.stack((seg[owner, 0] + d[owner] * f0, seg[owner, 0] + d[owner] * f1), axis=1)
    return out, labels[owner]


def segment_distance(seg_px, seg_label, labels, w, h, reach):
    """Distance (float64, w*h; inf = farther than ``reach``) from every texel center to
    the nearest segment ``(S, 2, 2)`` (pixel units) carrying the texel's own label."""
    lab = np.asarray(labels).reshape(-1)
    out = np.full(w * h, np.inf)
    seg = np.asarray(seg_px, dtype=np.float64).reshape(-1, 2, 2)
    seg_label = np.asarray(seg_label, dtype=np.int64).reshape(-1)
    if len(seg) == 0:
        return out
    reach = float(reach)
    seg, seg_label = _split(seg, seg_label, max(4.0, 2.0 * reach))
    lo = np.minimum(seg[:, 0], seg[:, 1]) - reach
    hi = np.maximum(seg[:, 0], seg[:, 1]) + reach
    x0 = np.clip(np.ceil(lo[:, 0] - 0.5), 0, w).astype(np.int64)
    x1 = np.clip(np.floor(hi[:, 0] - 0.5), -1, w - 1).astype(np.int64)
    y0 = np.clip(np.ceil(lo[:, 1] - 0.5), 0, h).astype(np.int64)
    y1 = np.clip(np.floor(hi[:, 1] - 0.5), -1, h - 1).astype(np.int64)
    nx, ny = np.maximum(0, x1 - x0 + 1), np.maximum(0, y1 - y0 + 1)
    n = nx * ny
    todo = np.flatnonzero(n > 0)
    start = 0
    while start < len(todo):
        cum = np.cumsum(n[todo[start:]])
        stop = start + max(1, int(np.searchsorted(cum, MAX_CANDIDATES, side='right')))
        chunk = todo[start:stop]
        start = stop
        counts = n[chunk]
        s = np.repeat(chunk, counts)
        first = np.repeat(np.cumsum(counts) - counts, counts)
        i = np.arange(len(s), dtype=np.int64) - first
        px = x0[s] + i % nx[s]
        py = y0[s] + i // nx[s]
        flat = py * w + px
        own = lab[flat] == seg_label[s]
        s, px, py, flat = s[own], px[own], py[own], flat[own]
        if len(s) == 0:
            continue
        a, b = seg[s, 0], seg[s, 1]
        ab = b - a
        p = np.stack((px + 0.5, py + 0.5), axis=1)
        denom = np.einsum('ij,ij->i', ab, ab)
        t = np.clip(np.einsum('ij,ij->i', p - a, ab) / np.where(denom > 1e-12, denom, 1.0), 0.0, 1.0)
        d = np.linalg.norm(a + ab * t[:, None] - p, axis=1)
        np.minimum.at(out, flat, d)
    return out


def band(dist, width, center='BETWEEN'):
    """Texels in the band and their distance in texel steps from the edge's texels.

    Returns ``(inside (bool), steps (float))``: 'BETWEEN' -- the texels touching the
    edge are step 0 (an edge on a texel border: both columns beside it), ``width``
    texels per side; 'ON' -- the texels on the (snapped) edge are step 0, the band
    reaches ``width - 1`` texels to each side of that line."""
    d = np.asarray(dist, dtype=np.float64)
    width = max(1, int(width))
    steps = np.maximum(0.0, d - 0.5) if center == 'BETWEEN' else d
    return steps < width - 0.5, steps


def ramp(steps, width, fade=True, curve=None):
    """``(t, opacity)`` for texels ``steps`` from the edge in a band ``width`` texels
    wide. The falloff ``curve(x)`` (x = steps / width, 0 = on the edge; default a
    linear fade ``1 - x``) gives the edge's weight ``f``: the color runs from the
    primary (``t = 1 - f = 0``) toward the secondary color, and with ``fade`` the
    opacity is ``f`` (else 1)."""
    width = max(1, int(width))
    x = np.clip(np.asarray(steps, dtype=np.float64) / width, 0.0, 1.0)
    f = (1.0 - x) if curve is None else np.clip(np.asarray(curve(x), dtype=np.float64), 0.0, 1.0)
    f = np.broadcast_to(f, x.shape)
    opacity = f.copy() if fade else np.ones_like(x)
    return 1.0 - f, opacity
