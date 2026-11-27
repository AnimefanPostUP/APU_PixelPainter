"""Element map: the painted mesh split into *elements* -- UV islands, connected mesh
parts or sharp areas (faces joined across edges flatter than the Sharp Angle) -- with every texel labelled by its element (the Extras window's Fill / Edges /
Ambient Occlusion and the hover outline of Extras and Mask editing).

Built from the evaluated mesh cache (:mod:`.mesh`, the active object), so it matches
what the 3D Viewport shows (modifiers included). Elements that share texels (mirrored /
stacked UVs) are merged: painting one paints the other anyway. Texels next to an
element (the half-covered ones at its edge, which show on the mesh) get its label too.

* hover: :func:`label_under` -- the triangle under the 3D cursor, or the texel under
  the Image Editor cursor;
* :meth:`ElementMap.pixels` -- an element's texels;
* :meth:`ElementMap.outline_2d` / :meth:`ElementMap.outline_3d` -- its contour as
  pixel-corner segments / on the mesh (object space): its open border edges plus its
  silhouette from the current view, so closed mesh parts are outlined too.
"""


import numpy as np

from . import islands, mesh


SOURCES = ('UV_ISLAND', 'MESH_PART', 'SHARP')


class ElementMap:
    __slots__ = ('key', 'source', 'w', 'h', 'labels', 'tri_label', 'count', '_out2d', '_out3d',
                 '_bounds2d', '_bounds3d')

    def __init__(self, key, source, w, h, labels, tri_label, count):
        self.key = key
        self.source = source
        self.w, self.h = w, h
        self.labels = labels          # (w*h,) int32 element per texel, -1 = none
        self.tri_label = tri_label    # (T,) element per loop triangle of the mesh cache
        self.count = count
        self._out2d = {}
        self._out3d = {}
        self._bounds2d = None
        self._bounds3d = None

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

    def outline_3d(self, cache, label, eye=None, direction=None):
        """Outline of the element on the mesh: ``(K, 2, 3)`` object-space segments.

        Its open border edges (used by one of its triangles: UV seams, mesh borders)
        plus, given a view, its silhouette -- edges between a triangle facing the viewer
        and one facing away. ``eye``: the viewer's position (perspective), ``direction``:
        towards the viewer (orthographic), both in object space. Without a view only the
        border is returned (a closed mesh part has none)."""
        edges = self._out3d.get(label)
        if edges is None:
            edges = edge_sets(cache, self.tri_label == int(label))
            self._remember(self._out3d, label, edges)
        return outline_from(edges, eye, direction)

    def boundaries_2d(self):
        """Every element's border in the texture: ``(E, 2, 2)`` pixel-corner segments
        between texels of different elements (or an element and empty space)."""
        if self._bounds2d is None:
            self._bounds2d = label_boundaries_2d(self.labels.reshape(self.h, self.w))
        return self._bounds2d

    def boundaries_3d(self, cache):
        """Every element's border on the mesh: ``(K, 2, 3)`` object-space edges between
        triangles of different elements, plus open borders."""
        if self._bounds3d is None:
            self._bounds3d = label_boundaries_3d(cache, self.tri_label)
        return self._bounds3d

    @staticmethod
    def _remember(store, label, value):
        if len(store) > 64:
            store.clear()
        store[label] = value


def label_boundaries_2d(labels):
    """``labels`` (h, w), -1 = none -> ``(E, 2, 2)`` segments along texel sides where the
    label changes (the image border counts as -1)."""
    p = np.pad(np.asarray(labels), 1, constant_values=-1)
    vy, vx = np.nonzero(p[1:-1, :-1] != p[1:-1, 1:])      # side at x = vx, rows vy..vy+1
    hy, hx = np.nonzero(p[:-1, 1:-1] != p[1:, 1:-1])      # side at y = hy, columns hx..hx+1
    vertical = np.stack((np.c_[vx, vy], np.c_[vx, vy + 1]), axis=1)
    horizontal = np.stack((np.c_[hx, hy], np.c_[hx + 1, hy]), axis=1)
    return np.concatenate((vertical, horizontal)).astype(np.float64)


def label_boundaries_3d(cache, tri_label):
    """``(K, 2, 3)`` object-space edges whose triangles carry different labels, plus
    edges used by one triangle only (open borders)."""
    tv = np.asarray(cache.tri_verts, dtype=np.int64).reshape(-1, 3)
    if len(tv) == 0:
        return np.empty((0, 2, 3), dtype=np.float64)
    a = tv.reshape(-1)
    b = tv[:, (1, 2, 0)].reshape(-1)
    base = int(tv.max()) + 1
    key = np.minimum(a, b) * base + np.maximum(a, b)
    lab = np.repeat(np.asarray(tri_label, dtype=np.int64).reshape(-1), 3)
    order = np.argsort(key, kind='stable')
    key_s, lab_s = key[order], lab[order]
    uniq, first, count = np.unique(key_s, return_index=True, return_counts=True)
    lo = np.minimum.reduceat(lab_s, first)
    hi = np.maximum.reduceat(lab_s, first)
    edge = uniq[(count == 1) | (lo != hi)]
    verts = np.asarray(cache.verts, dtype=np.float64)
    return np.stack((verts[edge // base], verts[edge % base]), axis=1)


def edge_sets(cache, chosen):
    """The chosen triangles' edges for :func:`outline_from`: ``(border, inner, n0, n1)``
    -- border edges ``(K, 2, 3)``, edges shared by exactly two of them ``(M, 2, 3)`` and
    the two triangles' normals ``(M, 3)`` (object space)."""
    empty = np.empty((0, 2, 3), dtype=np.float64)
    tris = np.flatnonzero(chosen)
    if len(tris) == 0:
        return empty, empty, np.empty((0, 3)), np.empty((0, 3))
    verts = cache.verts.astype(np.float64)
    tv = cache.tri_verts[tris].astype(np.int64)
    p = verts[tv]
    normals = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    a = tv.reshape(-1)
    b = tv[:, (1, 2, 0)].reshape(-1)
    keys = np.stack((np.minimum(a, b), np.maximum(a, b)), axis=1)
    uniq, inverse, count = np.unique(keys, axis=0, return_inverse=True, return_counts=True)
    inverse = inverse.reshape(-1)
    owner = np.repeat(np.arange(len(tris)), 3)          # triangle of each edge use
    order = np.argsort(inverse, kind='stable')
    first = np.searchsorted(inverse[order], np.arange(len(uniq)))
    border = uniq[count == 1]
    shared = np.flatnonzero(count == 2)                 # non-manifold edges are left out
    inner = uniq[shared]
    n0 = normals[owner[order[first[shared]]]]
    n1 = normals[owner[order[first[shared] + 1]]]

    def seg(e):
        return np.stack((verts[e[:, 0]], verts[e[:, 1]]), axis=1) if len(e) else empty

    return seg(border), seg(inner), n0, n1


def outline_from(edges, eye=None, direction=None):
    """Border edges plus the silhouette from ``eye`` / along ``direction`` (see
    :meth:`ElementMap.outline_3d`)."""
    border, inner, n0, n1 = edges
    if len(inner) == 0 or (eye is None and direction is None):
        return border
    if eye is not None:
        to_eye = np.asarray(eye, dtype=np.float64) - inner.mean(axis=1)
        f0 = np.einsum('ij,ij->i', n0, to_eye) > 0.0
        f1 = np.einsum('ij,ij->i', n1, to_eye) > 0.0
    else:
        d = np.asarray(direction, dtype=np.float64)
        f0 = n0 @ d > 0.0
        f1 = n1 @ d > 0.0
    silhouette = inner[f0 != f1]
    return np.concatenate((border, silhouette)) if len(silhouette) else border


def tri_labels(cache, source, angle=30.0):
    """Element per loop triangle: UV islands (shared edges with equal UVs), mesh parts
    (triangles sharing vertices) or sharp areas (joined across edges whose faces meet at
    no more than ``angle`` degrees)."""
    if source == 'SHARP':
        from ...tools.mask import geometry as mask_geometry
        return mask_geometry.sharp_labels(cache.tri_verts, cache.tri_pos, angle)
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
    angle = 30.0
    if source == 'SHARP':
        angle = round(float(getattr(context.window_manager, 'pixel_painter_sharp_angle', 30.0)), 3)
    key = (cache.version, w, h, angle if source == 'SHARP' else None)
    m = _maps.get(source)
    if m is not None and m.key == key:
        return m
    from ...utils import native
    tri_label = tri_labels(cache, source, angle).astype(np.int32)
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
