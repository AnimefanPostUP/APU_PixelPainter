"""UV islands (UV mode): a brush stamp is a shape in texture space, so near an island's
edge it also covers neighbouring islands or the padding. Every texel gets the label
of its UV island; each stamp is clipped to the island under its center.
"""


import numpy as np

from . import mesh


# ---------------------------------------------------------------------------
# UV islands (UV mode: brushes stay on the island they are drawn on)
# ---------------------------------------------------------------------------
#
# A brush stamp is a shape in texture space, so near an island's edge it also
# covers whatever lies next to it in the UV layout: other islands (far away on
# the mesh) and the empty padding. The island map labels every texel with its
# UV island; each stamp is clipped to the island under its center.

class IslandMap:
    """Texel -> UV island label for one mesh cache and image size.

    ``labels`` (w*h int32): island of the texel (center inside one of its
    triangles), texels bordering an island get its label too (they straddle the
    island's edge and show on the mesh); -1 = no island. Islands that overlap
    in texture space (mirrored / stacked UVs) share their pixels and are merged.
    """
    __slots__ = ('version', 'w', 'h', 'labels', 'tri_label', 'counts')

    def __init__(self, version, w, h, labels, tri_label, counts):
        self.version = version
        self.w = w
        self.h = h
        self.labels = labels
        self.tri_label = tri_label    # (T,) island per loop triangle (merged)
        self.counts = counts          # texels per label


_island_map = None


def _tri_island_labels(cache, precision=1e5):
    """Island per loop triangle: triangles sharing an edge with equal UVs on both sides."""
    from ...tools.mask import geometry as mask_geometry
    tv = cache.tri_verts.astype(np.int64)
    tl = cache.tri_loops
    q = np.round(cache.uvs.astype(np.float64) * precision).astype(np.int64)
    n = len(tv)
    keys = []
    for k in range(3):
        a, b = k, (k + 1) % 3
        va, vb = tv[:, a], tv[:, b]
        ua, ub = q[tl[:, a]], q[tl[:, b]]
        swap = va > vb
        keys.append(np.column_stack([np.where(swap, vb, va), np.where(swap, va, vb),
                                     np.where(swap[:, None], ub, ua), np.where(swap[:, None], ua, ub)]))
    keys = np.concatenate(keys)
    owner = np.tile(np.arange(n, dtype=np.int64), 3)
    _, edge = np.unique(keys, axis=0, return_inverse=True)
    edge = edge.ravel()
    order = np.argsort(edge, kind='stable')
    same = edge[order][1:] == edge[order][:-1]
    return mask_geometry.components(n, owner[order[:-1][same]], owner[order[1:][same]])


def _raster_labels_python(tri_uv, tri_label, count, w, h):
    """Python version of native.raster_labels (merge overlapping labels)."""
    from ...tools.mask import geometry as mask_geometry
    out = np.full(w * h, -1, dtype=np.int64)
    parent = list(range(max(1, count)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for tri, label in zip(tri_uv, tri_label.tolist()):
        idx = mask_geometry.raster_triangles(tri[None], w, h)
        if not len(idx):
            continue
        cur = out[idx]
        for other in np.unique(cur[(cur >= 0) & (cur != label)]).tolist():
            ra, rb = find(other), find(label)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
        out[idx[cur < 0]] = label
    roots = np.array([find(i) for i in range(len(parent))], dtype=np.int64)
    hit = out >= 0
    out[hit] = roots[out[hit]]
    return out.astype(np.int32), roots[tri_label].astype(np.int32)


def _dilate_labels(labels, w, h):
    """Unlabelled texels next to a labelled one (8-neighbourhood) take its label."""
    src = labels.reshape(h, w)
    out = src.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            ty = slice(max(0, -dy), h - max(0, dy))
            tx = slice(max(0, -dx), w - max(0, dx))
            sy = slice(max(0, dy), h - max(0, -dy))
            sx = slice(max(0, dx), w - max(0, -dx))
            target = out[ty, tx]
            nb = src[sy, sx]
            fill = (target < 0) & (nb >= 0)
            target[fill] = nb[fill]
    return out.reshape(-1)


def island_map(context, image):
    """:class:`IslandMap` of the active mesh for ``image``'s size (cached), or None."""
    global _island_map
    if image is None:
        return None
    w, h = image.size
    cache = mesh.mesh_cache(context)
    if cache is None or w == 0 or h == 0:
        return None
    m = _island_map
    if m is not None and m.version == cache.version and (m.w, m.h) == (w, h):
        return m
    from ...utils import native
    tri_label = _tri_island_labels(cache).astype(np.int32)
    count = int(tri_label.max()) + 1 if len(tri_label) else 0
    # UVs outside 0..1 wrap into the image (like hit_to_pixel): move each
    # triangle into the 0..1 tile of its centroid.
    tri_uv = cache.tri_uv - np.floor(cache.tri_uv.mean(axis=1, keepdims=True))
    result = native.raster_labels(tri_uv, tri_label, count, w, h) if native.enabled() else None
    if result is None:
        result = _raster_labels_python(tri_uv, tri_label, count, w, h)
    labels, tri_label = result
    counts = np.bincount(labels[labels >= 0], minlength=max(count, 1))
    labels = _dilate_labels(labels, w, h).astype(np.int32)
    _island_map = IslandMap(cache.version, w, h, labels, tri_label, counts)
    return _island_map


class IslandClip:
    """Clips brush stamps to the UV island under their center (``DrawEnvironment.islands``).

    The stamp at the cursor uses the island of the triangle actually hit;
    other stamps (stroke interpolation, line pixels) the island of their
    center texel -- a stamp centered outside every island paints nothing.
    """
    NONE = -2   # = native.CLIP_NONE: no clipping
    SKIP = -1   # = native.CLIP_SKIP: stamp paints nothing

    def __init__(self, islands, cursor, cursor_tri):
        self.labels = islands.labels
        self.w, self.h = islands.w, islands.h
        self.cursor = tuple(cursor)
        self.cursor_label = None
        if cursor_tri is not None and 0 <= cursor_tri < len(islands.tri_label):
            label = int(islands.tri_label[cursor_tri])
            # an island without texels (degenerate UVs) must not block the brush
            self.cursor_label = label if islands.counts[label] > 0 else self.NONE

    def label_at(self, x, y):
        if self.cursor_label is not None and (x, y) == self.cursor:
            return self.cursor_label
        if 0 <= x < self.w and 0 <= y < self.h:
            return int(self.labels[y * self.w + x])   # -1 = SKIP
        return self.SKIP

    def center_labels(self, centers):
        """Label per center of an (N, 2) int array (for the C# stamps)."""
        c = np.asarray(centers, dtype=np.int64).reshape(-1, 2)
        x, y = c[:, 0], c[:, 1]
        inside = (x >= 0) & (x < self.w) & (y >= 0) & (y < self.h)
        out = np.full(len(c), self.SKIP, dtype=np.int32)
        out[inside] = self.labels[y[inside] * self.w + x[inside]]
        if self.cursor_label is not None:
            out[(x == self.cursor[0]) & (y == self.cursor[1])] = self.cursor_label
        return out

    def filter(self, x, y, pixels, weights=None):
        """``(pixels, weights)`` lists of one stamp at ``(x, y)`` reduced to its island."""
        pixels = list(pixels)
        weights = list(weights) if weights is not None else [1.0] * len(pixels)
        label = self.label_at(x, y)
        if label == self.NONE:
            return pixels, weights
        if label == self.SKIP or not pixels:
            return [], []
        w, h, labels = self.w, self.h, self.labels
        keep_p, keep_w = [], []
        for (px, py), wt in zip(pixels, weights):
            if 0 <= px < w and 0 <= py < h and labels[py * w + px] == label:
                keep_p.append((px, py))
                keep_w.append(wt)
        return keep_p, keep_w
