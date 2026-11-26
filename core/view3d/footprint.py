"""Edge mode: map a stamp's footprint, laid out on the unfolded surface around it, back
onto real texels across the UV seams.
"""


import numpy as np

from .frames import apply_bary, bary2d, find_triangle, unfold
from . import mesh


# ---- footprint expansion (painting) ------------------------------------------

MAX_SUPERSAMPLE = 4


def expand_footprint(frame, pixels, weights, w, h, tile, drop_uncovered=True):
    """Edge mode: carry a brush footprint over UV seams.

    ``pixels`` are texel coords in the seed's texture space (they may lie
    outside its UV island). Texels covered by the seed's own island are
    painted as they are. Texels covered by an unfolded neighbour are written
    to that neighbour's real pixels (supersampled when the neighbour has a
    higher texel density, so no holes appear). Texels covered by nothing are
    dropped (except the ones bordering the seed island) -- painting them in
    place would spill onto whatever lies next to the island in the UV layout --
    unless ``drop_uncovered`` is False.

    Returns ``(pixels, weights)`` lists with duplicates merged (max weight).
    """
    n = len(pixels)
    if n == 0:
        return [], []
    pix = np.asarray(list(pixels), dtype=np.int64).reshape(-1, 2)
    wts = np.ones(n) if weights is None else np.asarray(weights, dtype=np.float64)
    size = np.array((w, h), dtype=np.float64)
    centers = (pix + 0.5) / size + np.asarray(tile, dtype=np.float64)

    in_island = np.zeros(n, dtype=bool)
    claimed = np.zeros(n, dtype=bool)
    out = {}

    def _inside(tri_uv, idx, pts):
        bw = bary2d(np.broadcast_to(tri_uv, (len(pts), 3, 2)), pts)
        return np.all(bw >= -1e-9, axis=1), bw

    # 1. the seed's own island
    for j in np.nonzero(frame.identity)[0]:
        tri = frame.uv[j]
        mn, mx = tri.min(axis=0), tri.max(axis=0)
        idx = np.nonzero(~in_island
                         & (centers[:, 0] >= mn[0]) & (centers[:, 0] <= mx[0])
                         & (centers[:, 1] >= mn[1]) & (centers[:, 1] <= mx[1]))[0]
        if len(idx):
            inside, _ = _inside(tri, idx, centers[idx])
            in_island[idx[inside]] = True

    # 2. unfolded neighbours, nearest first
    for j in np.nonzero(~frame.identity)[0]:
        tri = frame.uv[j]
        mn, mx = tri.min(axis=0), tri.max(axis=0)
        half = 0.5 / size
        idx = np.nonzero(~in_island & ~claimed
                         & (centers[:, 0] >= mn[0] - half[0]) & (centers[:, 0] <= mx[0] + half[0])
                         & (centers[:, 1] >= mn[1] - half[1]) & (centers[:, 1] <= mx[1] + half[1]))[0]
        if not len(idx):
            continue
        actual = frame.actual[j]
        a_placed = abs(np.cross(tri[1] - tri[0], tri[2] - tri[0]))
        a_actual = abs(np.cross(actual[1] - actual[0], actual[2] - actual[0]))
        if a_placed < 1e-18:
            continue
        k = int(min(MAX_SUPERSAMPLE, max(1, np.ceil(np.sqrt(a_actual / a_placed)))))
        offs = ((np.arange(k) + 0.5) / k - 0.5)
        sub = np.stack(np.meshgrid(offs, offs), axis=-1).reshape(-1, 2) / size   # (k*k, 2)
        pts = (centers[idx][:, None, :] + sub[None, :, :]).reshape(-1, 2)
        inside, bw = _inside(tri, None, pts)
        if not inside.any():
            continue
        owner = np.repeat(idx, len(sub))[inside]
        uv = apply_bary(bw[inside], np.broadcast_to(actual, (inside.sum(), 3, 2)))
        target = np.floor((uv % 1.0) * size).astype(np.int64)
        target[:, 0] = np.minimum(target[:, 0], w - 1)
        target[:, 1] = np.minimum(target[:, 1], h - 1)
        claimed[owner] = True
        for (tx, ty), o in zip(target.tolist(), owner.tolist()):
            key = (tx, ty)
            wt = float(wts[o])
            if wt > out.get(key, -1.0):
                out[key] = wt

    # 3. in-place texels: the island, texels covered by nothing, and texels
    #    bordering the island (they straddle the seam and show on both sides)
    island = {tuple(p) for p in pix[in_island].tolist()}
    for i, (px, py) in enumerate(pix.tolist()):
        if (claimed[i] or drop_uncovered) and not in_island[i]:
            if not any((px + dx, py + dy) in island
                       for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
                continue
        wt = float(wts[i])
        key = (px % w, py % h)
        if wt > out.get(key, -1.0):
            out[key] = wt

    keys = list(out)
    return keys, [out[k] for k in keys]


def footprint_box(pixels, w, h, tile, pad=1.0):
    """Frame-UV bounding box of a pixel set (padded by ``pad`` texels)."""
    pix = np.asarray(list(pixels), dtype=np.float64).reshape(-1, 2)
    size = np.array((w, h), dtype=np.float64)
    tile = np.asarray(tile, dtype=np.float64)
    lo = (pix.min(axis=0) - pad) / size + tile
    hi = (pix.max(axis=0) + 1.0 + pad) / size + tile
    return lo, hi


def edge_expand(context, img, cx, cy, pixels, weights, tile, prefer_tri=None):
    """Edge mode expansion of one stamp centred on texel ``(cx, cy)``."""
    pixels = list(pixels)
    if not pixels:
        return [], []
    cache = mesh.mesh_cache(context)
    w, h = img.size
    if cache is None or w == 0 or h == 0:
        return pixels, (list(weights) if weights is not None else [1.0] * len(pixels))
    center_uv = ((cx + 0.5) / w + tile[0], (cy + 0.5) / h + tile[1])
    seed = find_triangle(cache, center_uv, prefer=prefer_tri)
    if seed is None:
        return pixels, (list(weights) if weights is not None else [1.0] * len(pixels))
    lo, hi = footprint_box(pixels, w, h, tile)
    frame = unfold(cache, seed, lo, hi)
    return expand_footprint(frame, pixels, weights, w, h, tile)
