"""Element map: the painted mesh split into *elements* -- UV islands or connected mesh
parts -- with every texel labelled by its element (the Extras window's Fill / Edges /
Ambient Occlusion and the hover outline of Extras and Mask editing).

Built from the evaluated mesh cache (:mod:`.mesh`, the active object), so it matches
what the 3D Viewport shows (modifiers included). Elements that share texels (mirrored /
stacked UVs) are merged: painting one paints the other anyway. Texels next to an
element (the half-covered ones at its edge, which show on the mesh) get its label too.

* hover: :func:`label_under` -- the triangle under the 3D cursor, or the texel under
  the Image Editor cursor;
* :meth:`ElementMap.pixels` -- an element's texels;
* :meth:`ElementMap.outline_2d` / :meth:`ElementMap.outline_3d` -- its contour as
  pixel-corner segments / its border edges on the mesh (object space).
"""


import numpy as np

from . import islands, mesh


SOURCES = ('UV_ISLAND', 'MESH_PART')


class ElementMap:
    __slots__ = ('key', 'source', 'w', 'h', 'labels', 'tri_label', 'count', '_out2d', '_out3d')

    def __init__(self, key, source, w, h, labels, tri_label, count):
        self.key = key
        self.source = source
        self.w, self.h = w, h
        self.labels = labels          # (w*h,) int32 element per texel, -1 = none
        self.tri_label = tri_label    # (T,) element per loop triangle of the mesh cache
        self.count = count
        self._out2d = {}
        self._out3d = {}

    def valid(self, label):
        return label is not None and 0 <= int(label) < self.count

    def label_at(self, x, y):
        """Element of texel ``(x, y)`` or None."""
        if x is None or y is None or not (0 <= x < self.w and 0 <= y < self.h):
            return None
        label = int(self.labels[y * self.w + x])
        return label if label >= 0 else None

    def label_of_tri(self, tri):
        if tri is None or not (0 <= tri < len(self.tri_label)):
            return None
        label = int(self.tri_label[tri])
        return label if label >= 0 else None

    def pixels(self, label=None):
        """Flat texel indices of the element ``label`` (None: of every element)."""
        if label is None:
            return np.flatnonzero(self.labels >= 0)
        return np.flatnonzero(self.labels == int(label))

    def outline_2d(self, label):
        """Contour of the element's texels: ``(E, 2, 2)`` segments between pixel corners."""
        seg = self._out2d.get(label)
        if seg is None:
            from ...utils import math_utils
            idx = self.pixels(label)
            if len(idx) == 0:
                seg = np.empty((0, 2, 2), dtype=np.float64)
            else:
                ys, xs = np.divmod(idx, self.w)
                x0, y0 = int(xs.min()), int(ys.min())
                block = np.zeros((int(ys.max()) - y0 + 1, int(xs.max()) - x0 + 1), dtype=bool)
                block[ys - y0, xs - x0] = True
                seg = math_utils.mask_outline_segments(x0, y0, block)
            self._remember(self._out2d, label, seg)
        return seg

    def outline_3d(self, cache, label):
        """Border edges of the element's triangles: ``(K, 2, 3)`` object-space segments
        (edges used by exactly one of its triangles)."""
        seg = self._out3d.get(label)
        if seg is None:
            seg = border_segments(cache, self.tri_label == int(label))
            self._remember(self._out3d, label, seg)
        return seg

    @staticmethod
    def _remember(store, label, value):
        if len(store) > 64:
            store.clear()
        store[label] = value


def border_segments(cache, chosen):
    """``(K, 2, 3)`` object-space edges of the chosen triangles that only one of them uses."""
    tris = np.flatnonzero(chosen)
    if len(tris) == 0:
        return np.empty((0, 2, 3), dtype=np.float64)
    tv = cache.tri_verts[tris].astype(np.int64)
    a = tv.reshape(-1)
    b = tv[:, (1, 2, 0)].reshape(-1)
    keys = np.stack((np.minimum(a, b), np.maximum(a, b)), axis=1)
    uniq, count = np.unique(keys, axis=0, return_counts=True)
    border = uniq[count == 1]
    verts = cache.verts.astype(np.float64)
    return np.stack((verts[border[:, 0]], verts[border[:, 1]]), axis=1)


def tri_labels(cache, source):
    """Element per loop triangle: UV islands (shared edges with equal UVs) or mesh parts
    (triangles sharing vertices)."""
    if source == 'MESH_PART':
        from ...tools.mask import geometry as mask_geometry
        tv = cache.tri_verts.astype(np.int64)
        a = np.concatenate((tv[:, 0], tv[:, 1]))
        b = np.concatenate((tv[:, 1], tv[:, 2]))
        vert_label = mask_geometry.components(len(cache.verts), a, b)
        _, compact = np.unique(vert_label[tv[:, 0]], return_inverse=True)
        return compact.astype(np.int64)
    return islands._tri_island_labels(cache)


_maps = {}   # source -> ElementMap


def invalidate():
    _maps.clear()


def element_map(context, image, source):
    """:class:`ElementMap` of the active mesh for ``image``'s size (cached per source),
    or None (no mesh / UVs). Builds the mesh cache when needed: modal code only."""
    if image is None or source not in SOURCES:
        return None
    w, h = image.size
    cache = mesh.mesh_cache(context)
    if cache is None or w == 0 or h == 0:
        return None
    key = (cache.version, w, h)
    m = _maps.get(source)
    if m is not None and m.key == key:
        return m
    from ...utils import native
    tri_label = tri_labels(cache, source).astype(np.int32)
    count = int(tri_label.max()) + 1 if len(tri_label) else 0
    # UVs outside 0..1 wrap into the image (as for painting): move each triangle into
    # the 0..1 tile of its centroid.
    tri_uv = cache.tri_uv - np.floor(cache.tri_uv.mean(axis=1, keepdims=True))
    result = native.raster_labels(tri_uv, tri_label, count, w, h) if native.enabled() else None
    if result is None:
        result = islands._raster_labels_python(tri_uv, tri_label, count, w, h)
    labels, tri_label = result
    labels = islands._dilate_labels(labels, w, h).astype(np.int32)
    m = ElementMap(key, source, w, h, labels, np.asarray(tri_label, dtype=np.int32), max(count, 1))
    _maps[source] = m
    return m


def cached_map(source):
    """The last built map of ``source`` (draw callbacks: no building)."""
    return _maps.get(source)


def label_under(ctx, emap):
    """Element under the cursor: in the 3D Viewport the one of the hit triangle, in the
    Image Editor the one of the hovered texel; None when there is none."""
    if emap is None:
        return None
    cx, cy = ctx.cursor
    if cx is None:
        return None
    if ctx.is_3d:
        label = emap.label_of_tri(ctx.state.get('view3d_hit_tri'))
        if label is not None:
            return label
    return emap.label_at(cx, cy)
