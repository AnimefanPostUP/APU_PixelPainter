"""Ambient occlusion per texel (the Extras window's AO tool).

Every target texel is placed on the mesh (the triangle whose UV covers its center:
object-space point + face normal); rays over the hemisphere around the normal are cast
against the mesh's BVH (the evaluated mesh cache, :mod:`core.view3d.mesh`). The
occlusion is the share of rays that hit something within ``distance``.

Only the painted object occludes. Cost: texels x samples ray casts. With the C# backend
(:mod:`utils.native`) the rays are traced natively against its own BVH of the triangles;
otherwise every ray is a Python call to the mesh's ``BVHTree`` and large textures take a
few seconds. The window manager's progress shows meanwhile.
"""

import math

import numpy as np

from ...utils import native


MAX_CANDIDATES = 1 << 22     # (triangle, texel) pairs tested per rasterization chunk
CHUNK = 2048                 # texels per progress update
NATIVE_CHUNK = 16384         # texels per progress update with the C# backend
OFFSET = 1e-4                # ray origins lifted off the surface (fraction of the mesh size)


def _face_normals(tri_pos):
    n = np.cross(tri_pos[:, 1] - tri_pos[:, 0], tri_pos[:, 2] - tri_pos[:, 0])
    length = np.linalg.norm(n, axis=1)
    return n / np.where(length > 1e-20, length, 1.0)[:, None]


def texel_surface(cache, w, h, targets):
    """Object-space point and face normal of each target texel (flat indices).

    Returns ``(pos (N, 3), normal (N, 3), ok (N,) bool)``; texels whose center no
    triangle covers (the half-covered ones at an island's edge) take a covered
    neighbour's values, ``ok`` is False where none was found."""
    targets = np.asarray(targets, dtype=np.int64)
    want = np.zeros(w * h, dtype=bool)
    want[targets] = True
    pos = np.zeros((w * h, 3), dtype=np.float64)
    nrm = np.zeros((w * h, 3), dtype=np.float64)
    has = np.zeros(w * h, dtype=bool)

    uv = cache.tri_uv - np.floor(cache.tri_uv.mean(axis=1, keepdims=True))
    pts = uv * np.array((w, h), dtype=np.float64)                  # (T, 3, 2) pixel units
    normals = _face_normals(cache.tri_pos)
    lo, hi = pts.min(axis=1), pts.max(axis=1)
    x0 = np.clip(np.ceil(lo[:, 0] - 0.5), 0, w).astype(np.int64)
    x1 = np.clip(np.floor(hi[:, 0] - 0.5), -1, w - 1).astype(np.int64)
    y0 = np.clip(np.ceil(lo[:, 1] - 0.5), 0, h).astype(np.int64)
    y1 = np.clip(np.floor(hi[:, 1] - 0.5), -1, h - 1).astype(np.int64)
    nx, ny = np.maximum(0, x1 - x0 + 1), np.maximum(0, y1 - y0 + 1)
    n = nx * ny
    e1, e2 = pts[:, 1] - pts[:, 0], pts[:, 2] - pts[:, 0]
    det = e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]
    tris = np.flatnonzero((n > 0) & (np.abs(det) > 1e-12))

    start = 0
    while start < len(tris):
        cum = np.cumsum(n[tris[start:]])
        stop = start + max(1, int(np.searchsorted(cum, MAX_CANDIDATES, side='right')))
        chunk = tris[start:stop]
        start = stop
        counts = n[chunk]
        t = np.repeat(chunk, counts)
        first = np.repeat(np.cumsum(counts) - counts, counts)
        i = np.arange(len(t), dtype=np.int64) - first
        px = x0[t] + i % nx[t]
        py = y0[t] + i // nx[t]
        flat = py * w + px
        dx = px + 0.5 - pts[t, 0, 0]
        dy = py + 0.5 - pts[t, 0, 1]
        b1 = (dx * e2[t, 1] - dy * e2[t, 0]) / det[t]
        b2 = (e1[t, 0] * dy - e1[t, 1] * dx) / det[t]
        b0 = 1.0 - b1 - b2
        eps = -1e-6
        inside = (b0 >= eps) & (b1 >= eps) & (b2 >= eps)
        t, flat = t[inside], flat[inside]
        bary = np.stack((b0[inside], b1[inside], b2[inside]), axis=1)
        pos[flat] = np.einsum('ij,ijk->ik', bary, cache.tri_pos[t])
        nrm[flat] = normals[t]
        has[flat] = True

    # Edge texels: take a covered neighbour's point (twice: two texels deep).
    for _ in range(2):
        if not (want & ~has).any():
            break
        missing = ~has
        grid_has = has.reshape(h, w)
        gpos, gnrm = pos.reshape(h, w, 3), nrm.reshape(h, w, 3)
        new_has = grid_has.copy()
        miss = missing.reshape(h, w)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                ty = slice(max(0, -dy), h - max(0, dy))
                tx = slice(max(0, -dx), w - max(0, dx))
                sy = slice(max(0, dy), h - max(0, -dy))
                sx = slice(max(0, dx), w - max(0, -dx))
                take = miss[ty, tx] & ~new_has[ty, tx] & grid_has[sy, sx]
                gpos[ty, tx][take] = gpos[sy, sx][take]
                gnrm[ty, tx][take] = gnrm[sy, sx][take]
                new_has[ty, tx] |= take
        has = new_has.reshape(-1)
    return pos[targets], nrm[targets], has[targets]


def hemisphere(samples):
    """Cosine-weighted unit directions around +Z (Hammersley points): (K, 3)."""
    k = np.arange(samples, dtype=np.int64)
    u1 = (k + 0.5) / samples
    bits = k.copy()
    u2 = np.zeros(samples)
    scale = 0.5
    while bits.any():
        u2 += (bits & 1) * scale
        bits >>= 1
        scale *= 0.5
    r = np.sqrt(u1)
    phi = 2.0 * math.pi * u2
    return np.stack((r * np.cos(phi), r * np.sin(phi), np.sqrt(np.maximum(0.0, 1.0 - u1))), axis=1)


def _frames(normals, rng):
    """Tangent frames (N, 3, 3) -- rows: tangent, bitangent, normal -- spun around the
    normal by a random angle per texel (no banding between texels)."""
    n = normals
    helper = np.where(np.abs(n[:, 2:3]) < 0.9, np.array((0.0, 0.0, 1.0)), np.array((1.0, 0.0, 0.0)))
    t = np.cross(helper, n)
    t /= np.maximum(np.linalg.norm(t, axis=1), 1e-20)[:, None]
    b = np.cross(n, t)
    angle = rng.uniform(0.0, 2.0 * math.pi, len(n))
    c, s = np.cos(angle)[:, None], np.sin(angle)[:, None]
    return np.stack((t * c + b * s, b * c - t * s, n), axis=1)


def occlusion(cache, pos, normals, samples=32, distance=0.25, progress=None, seed=7):
    """Occlusion 0 (open) .. 1 (closed) per point: the share of ``samples`` hemisphere
    rays that hit the mesh within ``distance`` (a fraction of the mesh's bounding box
    diagonal). ``progress(done)`` is called every ``CHUNK`` points."""
    count = len(pos)
    out = np.zeros(count, dtype=np.float64)
    if count == 0:
        return out
    verts = cache.verts.astype(np.float64)
    size = float(np.linalg.norm(verts.max(axis=0) - verts.min(axis=0))) or 1.0
    reach = max(1e-6, float(distance) * size)
    lift = OFFSET * size
    local = hemisphere(max(1, int(samples)))
    rng = np.random.default_rng(seed)
    tree = _native_tree(cache)
    try:
        start = 0
        while start < count:
            stop = min(count, start + (NATIVE_CHUNK if tree is not None else CHUNK))
            frames = _frames(normals[start:stop], rng)
            origins = pos[start:stop] + normals[start:stop] * lift
            occ = tree.occlusion(origins, frames, local, reach) if tree is not None else None
            if occ is None:
                tree = _close(tree)            # native failure: the rest in Python
                occ = _occlusion_python(cache.bvh.ray_cast, origins, frames, local, reach)
            out[start:stop] = occ
            start = stop
            if progress is not None:
                progress(stop)
    finally:
        _close(tree)
    return out


def _native_tree(cache):
    if not native.enabled():
        return None
    try:
        return native.TriangleBVH(cache.tri_pos)
    except Exception:
        return None


def _close(tree):
    if tree is not None:
        tree.close()
    return None


def _occlusion_python(ray_cast, origins, frames, local, reach):
    """One chunk of :func:`occlusion` with ``BVHTree.ray_cast`` (Python calls)."""
    out = np.zeros(len(origins), dtype=np.float64)
    if len(origins) == 0:
        return out
    dirs = np.einsum('kj,njd->nkd', local, frames)            # (n, K, 3) object space
    for i, (origin, rays) in enumerate(zip(origins.tolist(), dirs.tolist())):
        hits = 0
        for d in rays:
            if ray_cast(origin, d, reach)[0] is not None:
                hits += 1
        out[i] = hits / len(rays)
    return out

