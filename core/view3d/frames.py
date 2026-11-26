"""Triangle frames: triangles laid out in a 2D texture space -- the real UV layout (UV
mode) or the mesh unfolded around a seed triangle across UV seams (Edge mode).
"""


import numpy as np



# ---------------------------------------------------------------------------
# Triangle frames
# ---------------------------------------------------------------------------
#
# A *frame* is a set of triangles laid out in some 2D texture space:
#   tris   (N,)       loop-triangle indices
#   uv     (N, 3, 2)  where each triangle sits in the frame
#   actual (N, 3, 2)  the triangle's real UVs (where its pixels live)
#   pos    (N, 3, 3)  object-space corner positions
#
# UV mode uses the real UV layout (uv == actual). Edge mode *unfolds* the
# mesh around a seed triangle: across UV seams the neighbour face is hinged
# into the seed's texture space, so a brush shape laid out there continues
# over the seam and lands on the neighbour's real pixels.

MAX_PAIR_CELLS = 4_000_000   # segment x triangle pairs per chunk (memory bound)
MAX_UNFOLD_TRIS = 2000       # safety cap for one unfold
UV_EPS = 1e-6                # UVs closer than this count as connected


class Frame:
    __slots__ = ('tris', 'uv', 'actual', 'pos', 'identity')

    def __init__(self, tris, uv, actual, pos, identity):
        self.tris = tris
        self.uv = uv
        self.actual = actual
        self.pos = pos
        self.identity = identity  # (N,) True where uv == actual (seed's own UV island)

    def __len__(self):
        return len(self.tris)


def _bbox_candidates(cache, lo, hi):
    return np.nonzero(
        cache.uv_ok
        & (cache.uv_max[:, 0] >= lo[0]) & (cache.uv_min[:, 0] <= hi[0])
        & (cache.uv_max[:, 1] >= lo[1]) & (cache.uv_min[:, 1] <= hi[1])
    )[0]


def uv_frame(cache, lo, hi):
    """Real UV layout of every triangle overlapping the UV box ``lo``..``hi``."""
    tris = _bbox_candidates(cache, lo, hi)
    uv = cache.tri_uv[tris]
    return Frame(tris, uv, uv, cache.tri_pos[tris], np.ones(len(tris), dtype=bool))


# ---- point / triangle helpers ------------------------------------------------

def bary2d(tri_uv, q):
    """Barycentric weights (K, 3) of points ``q`` (K, 2) in 2D triangles ``tri_uv`` (K, 3, 2)."""
    v0 = tri_uv[:, 1] - tri_uv[:, 0]
    v1 = tri_uv[:, 2] - tri_uv[:, 0]
    v2 = q - tri_uv[:, 0]
    den = v0[:, 0] * v1[:, 1] - v1[:, 0] * v0[:, 1]
    with np.errstate(divide='ignore', invalid='ignore'):
        w1 = (v2[:, 0] * v1[:, 1] - v1[:, 0] * v2[:, 1]) / den
        w2 = (v0[:, 0] * v2[:, 1] - v2[:, 0] * v0[:, 1]) / den
    return np.stack((1.0 - w1 - w2, w1, w2), axis=1)


def apply_bary(w, corners):
    """``w`` (K, 3) applied to ``corners`` (K, 3, D)."""
    return (w[:, :, None] * corners).sum(axis=1)


def bary3d(p0, p1, p2, q):
    """Barycentric weights of ``q`` in the plane of triangle p0, p1, p2 (3D)."""
    v0, v1, v2 = p1 - p0, p2 - p0, q - p0
    d00, d01, d11 = v0 @ v0, v0 @ v1, v1 @ v1
    d20, d21 = v2 @ v0, v2 @ v1
    den = d00 * d11 - d01 * d01
    if abs(den) < 1e-30:
        return None
    b = (d11 * d20 - d01 * d21) / den
    c = (d00 * d21 - d01 * d20) / den
    return np.array((1.0 - b - c, b, c))


def find_triangle(cache, uv, prefer=None):
    """A triangle whose real UVs contain ``uv``; ``prefer`` wins when it does."""
    q = np.asarray(uv, dtype=np.float64)
    if prefer is not None and 0 <= prefer < len(cache.tri_uv):
        w = bary2d(cache.tri_uv[prefer][None], q[None])[0]
        if np.all(w >= -1e-6):
            return int(prefer)
    cand = _bbox_candidates(cache, q, q)
    if len(cand):
        w = bary2d(cache.tri_uv[cand], np.broadcast_to(q, (len(cand), 2)))
        inside = np.nonzero(np.all(w >= -1e-6, axis=1))[0]
        if len(inside):
            return int(cand[inside[0]])
    return prefer


# ---- unfolding ---------------------------------------------------------------------

def adjacency(cache):
    """Edge (v_lo, v_hi) -> triangles sharing it (built once per mesh)."""
    adj = getattr(cache, '_adj', None)
    if adj is None:
        adj = {}
        for t, (a, b, c) in enumerate(cache.tri_verts.tolist()):
            for u, v in ((a, b), (b, c), (c, a)):
                adj.setdefault((u, v) if u < v else (v, u), []).append(t)
        cache._adj = adj
    return adj


def _overlaps(tri_uv, lo, hi):
    mn = tri_uv.min(axis=0)
    mx = tri_uv.max(axis=0)
    return mx[0] >= lo[0] and mn[0] <= hi[0] and mx[1] >= lo[1] and mn[1] <= hi[1]


def place_neighbor(cache, t, P, n, va, vb, isometric=False):
    """Place triangle ``n`` (sharing edge ``va``-``vb`` with ``t``) next to ``t``.

    ``P`` is ``t``'s placement. Across a UV-connected edge (and unless
    ``isometric``) ``n`` keeps its UV shape (same affine map as ``t``);
    otherwise it is hinged about the shared 3D edge into ``t``'s plane, which
    preserves surface distances. Returns ``(Pn, connected)`` or ``(None, _)``.
    """
    tri_verts = cache.tri_verts
    tri_uv = cache.tri_uv
    verts = cache.verts
    V = tri_verts[t].tolist()
    Vn = tri_verts[n].tolist()
    ka, kb = V.index(va), V.index(vb)
    kc = 3 - ka - kb
    ia, ib = Vn.index(va), Vn.index(vb)
    ic = 3 - ia - ib
    A = tri_uv[t]
    An = tri_uv[n]
    connected = (np.abs(An[ia] - A[ka]).max() < UV_EPS
                 and np.abs(An[ib] - A[kb]).max() < UV_EPS)
    pc = None
    if connected and not isometric and cache.uv_ok[t]:
        w = bary2d(A[None], An[ic][None])[0]
        pc = w @ P
    else:
        pa = verts[va].astype(np.float64)
        pb = verts[vb].astype(np.float64)
        pt = verts[V[kc]].astype(np.float64)
        q = verts[Vn[ic]].astype(np.float64)
        e = pb - pa
        le = np.linalg.norm(e)
        if le > 1e-12:
            e /= le
            s = (q - pa) @ e
            h = np.linalg.norm((q - pa) - s * e)
            perp = (pt - pa) - ((pt - pa) @ e) * e
            lp = np.linalg.norm(perp)
            if lp > 1e-12:
                q_unfolded = pa + s * e - h * perp / lp
                corners = [verts[i].astype(np.float64) for i in V]
                w = bary3d(*corners, q_unfolded)
                if w is not None:
                    pc = w @ P
    if pc is None or not np.all(np.isfinite(pc)):
        return None, connected
    Pn = np.empty((3, 2))
    Pn[ia], Pn[ib], Pn[ic] = P[ka], P[kb], pc
    return Pn, connected


def grow(cache, placed, identity, order, accept, isometric=False):
    """Breadth-first placement from the already placed triangles in ``order``.

    ``accept(Pn)`` decides whether a newly placed neighbour is kept (and
    expanded further).
    """
    tri_verts = cache.tri_verts
    adj = adjacency(cache)
    queue = list(order)
    head = 0
    while head < len(queue) and len(order) < MAX_UNFOLD_TRIS:
        t = queue[head]
        head += 1
        P = placed[t]
        V = tri_verts[t]
        for k in range(3):
            va, vb = int(V[k]), int(V[(k + 1) % 3])
            for n in adj.get((va, vb) if va < vb else (vb, va), ()):
                if n in placed:
                    continue
                Pn, connected = place_neighbor(cache, t, P, n, va, vb, isometric)
                if Pn is None or not accept(Pn):
                    continue
                placed[n] = Pn
                identity[n] = identity[t] and connected and not isometric
                order.append(n)
                queue.append(n)


def frame_from(cache, placed, identity, order):
    tris = np.array(order, dtype=np.int64)
    return Frame(
        tris,
        np.array([placed[t] for t in order]),
        cache.tri_uv[tris],
        cache.tri_pos[tris],
        np.array([identity[t] for t in order], dtype=bool),
    )


def unfold(cache, seed, lo, hi):
    """Lay the mesh around ``seed`` out in the seed's texture space.

    Breadth-first over mesh edges. Across a UV-connected edge a neighbour
    keeps its UV shape (same affine map as its parent); across a seam it is
    hinged about the shared 3D edge into the parent's plane, so the layout
    stays continuous on the surface. Only triangles overlapping the box
    ``lo``..``hi`` (frame UV) are placed.
    """
    placed = {seed: cache.tri_uv[seed].copy()}
    identity = {seed: True}
    order = [seed]
    grow(cache, placed, identity, order, lambda Pn: _overlaps(Pn, lo, hi))
    return frame_from(cache, placed, identity, order)


# ---- projection (outline) -------------------------------------------------------

def project_segments(frame, segments):
    """Map frame-space line segments ``(E, 2, 2)`` onto the mesh surface.

    Every segment is clipped against each frame triangle it crosses and the
    pieces are mapped to object space with the triangle's barycentric
    coordinates, so lines bend exactly over mesh edges and corners.
    Returns ``(K, 2, 3)`` object-space segments.
    """
    empty = np.empty((0, 2, 3), dtype=np.float64)
    if frame is None or len(frame) == 0 or len(segments) == 0:
        return empty
    seg = np.asarray(segments, dtype=np.float64)
    p0 = seg[:, 0]
    d = seg[:, 1] - p0
    e1 = frame.uv[:, 1] - frame.uv[:, 0]
    e2 = frame.uv[:, 2] - frame.uv[:, 0]
    cross = e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]
    usable = np.nonzero(np.abs(cross) > 1e-14)[0]

    out = []
    chunk = max(1, MAX_PAIR_CELLS // max(1, len(seg)))
    for start in range(0, len(usable), chunk):
        idx = usable[start:start + chunk]
        pieces = _clip_segments(frame.uv[idx], np.sign(cross[idx]), frame.pos[idx], p0, d)
        if pieces is not None:
            out.append(pieces)
    return np.concatenate(out) if out else empty


def project_uv_segments(cache, segments):
    """UV mode: project real-UV segments using the real UV layout."""
    if cache is None or len(segments) == 0:
        return np.empty((0, 2, 3), dtype=np.float64)
    flat = np.asarray(segments, dtype=np.float64).reshape(-1, 2)
    return project_segments(uv_frame(cache, flat.min(axis=0), flat.max(axis=0)), segments)


def _clip_segments(uv, sign, pos, p0, d):
    n_e, n_c = len(p0), len(uv)
    sign = sign[None, :]
    tmin = np.zeros((n_e, n_c))
    tmax = np.ones((n_e, n_c))
    eps = 1e-12
    for i in range(3):
        a = uv[:, i]
        e = uv[:, (i + 1) % 3] - a
        rel_x = p0[:, None, 0] - a[None, :, 0]
        rel_y = p0[:, None, 1] - a[None, :, 1]
        # inside half-plane: sign * cross(e, p - a) >= 0, linear in t
        n0 = sign * (e[None, :, 0] * rel_y - e[None, :, 1] * rel_x)
        dn = sign * (e[None, :, 0] * d[:, None, 1] - e[None, :, 1] * d[:, None, 0])
        with np.errstate(divide='ignore', invalid='ignore'):
            t = -n0 / dn
        pos_ = dn > eps
        neg = dn < -eps
        tmin = np.where(pos_, np.maximum(tmin, t), tmin)
        tmax = np.where(neg, np.minimum(tmax, t), tmax)
        tmax = np.where(~pos_ & ~neg & (n0 < -eps), -1.0, tmax)  # parallel and outside

    ei, ci = np.nonzero(tmax - tmin > 1e-9)
    if len(ei) == 0:
        return None
    q0 = p0[ei] + d[ei] * tmin[ei, ci][:, None]
    q1 = p0[ei] + d[ei] * tmax[ei, ci][:, None]
    tri_uv, tri_pos = uv[ci], pos[ci]
    return np.stack((apply_bary(bary2d(tri_uv, q0), tri_pos),
                     apply_bary(bary2d(tri_uv, q1), tri_pos)), axis=1)
