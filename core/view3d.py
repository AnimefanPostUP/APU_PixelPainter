"""3D Viewport support: map the mouse to a texture pixel by ray-casting the mesh.

In the Image Editor the hovered pixel comes from ``view2d.region_to_view``.
In the 3D Viewport (Texture Paint mode) the mouse ray is cast against the
active object's evaluated mesh, and the UV at the hit point (barycentric
interpolation over the hit triangle) is turned into an image pixel.

Stroke interpolation also differs: neighbouring pixels on the screen can be
far apart in UV space (seams), so :func:`pixel_path` walks the *screen*
segment between two mouse positions and only connects consecutive samples in
UV space when they are continuous on the surface.
"""

import math

import bpy
import numpy as np
from bpy_extras import view3d_utils
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform

from ..utils import math_utils


SCREEN_STEP = 2.0      # screen pixels between ray-cast samples along a stroke
MAX_SAMPLES = 256      # cap per mouse event
SEAM_FACTOR = 3.0      # UV jump > SEAM_FACTOR * expected jump (+ slack) = seam
SEAM_SLACK = 2


def is_view3d(context):
    space = getattr(context, 'space_data', None)
    return space is not None and space.type == 'VIEW_3D'


# ---------------------------------------------------------------------------
# Mesh cache
# ---------------------------------------------------------------------------

class _MeshCache:
    __slots__ = ('key', 'bvh', 'tri_verts', 'tri_loops', 'verts', 'uvs', 'density',
                 'tri_uv', 'tri_pos', 'uv_min', 'uv_max', 'uv_sign', 'uv_ok', 'version', '_adj', '_nbrs', '_centroids')

    def __init__(self, key, bvh, tri_verts, tri_loops, verts, uvs, density):
        self.key = key
        self.bvh = bvh
        self.tri_verts = tri_verts   # (T, 3) vertex indices
        self.tri_loops = tri_loops   # (T, 3) loop indices
        self.verts = verts           # (V, 3) local positions
        self.uvs = uvs               # (L, 2) loop UVs
        self.density = density       # (T,) UV units per local unit (sqrt of area ratio)
        # UV -> surface lookup (outline projection)
        self.tri_uv = uvs[tri_loops].astype(np.float64)     # (T, 3, 2)
        self.tri_pos = verts[tri_verts].astype(np.float64)  # (T, 3, 3)
        self.uv_min = self.tri_uv.min(axis=1)                # (T, 2)
        self.uv_max = self.tri_uv.max(axis=1)
        e1 = self.tri_uv[:, 1] - self.tri_uv[:, 0]
        e2 = self.tri_uv[:, 2] - self.tri_uv[:, 0]
        cross = e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]
        self.uv_sign = np.sign(cross)                        # UV winding per triangle
        self.uv_ok = np.abs(cross) > 1e-14                   # skip degenerate UV triangles
        global _cache_version
        _cache_version += 1
        self.version = _cache_version
        self._adj = None
        self._nbrs = None
        self._centroids = None


_cache_version = 0


_cache = None


def invalidate():
    """Drop the cached mesh (call when a painting session starts)."""
    global _cache
    _cache = None


def _uv_layer_name(context, obj):
    """UV map Blender's texture paint would use for the active canvas."""
    try:
        ip = context.tool_settings.image_paint
        if ip.mode == 'MATERIAL':
            mat = obj.active_material
            if mat is not None:
                slots = mat.texture_paint_slots
                idx = mat.paint_active_slot
                if 0 <= idx < len(slots) and slots[idx].uv_layer:
                    return slots[idx].uv_layer
    except Exception:
        pass
    uv_layers = getattr(obj.data, 'uv_layers', None)
    if uv_layers is not None and uv_layers.active is not None:
        return uv_layers.active.name
    return None


def _build(context, obj, uv_name, key):
    depsgraph = context.evaluated_depsgraph_get()
    obj_eval = obj.evaluated_get(depsgraph)
    mesh = obj_eval.to_mesh()
    try:
        uv_layer = mesh.uv_layers.get(uv_name) if uv_name else None
        if uv_layer is None:
            uv_layer = mesh.uv_layers.active
        if uv_layer is None:
            return None
        mesh.calc_loop_triangles()

        n_verts = len(mesh.vertices)
        n_loops = len(mesh.loops)
        n_tris = len(mesh.loop_triangles)
        if n_tris == 0:
            return None

        verts = np.empty(n_verts * 3, dtype=np.float32)
        mesh.vertices.foreach_get('co', verts)
        verts = verts.reshape(-1, 3)

        tri_verts = np.empty(n_tris * 3, dtype=np.int32)
        mesh.loop_triangles.foreach_get('vertices', tri_verts)
        tri_verts = tri_verts.reshape(-1, 3)

        tri_loops = np.empty(n_tris * 3, dtype=np.int32)
        mesh.loop_triangles.foreach_get('loops', tri_loops)
        tri_loops = tri_loops.reshape(-1, 3)

        uvs = np.empty(n_loops * 2, dtype=np.float32)
        uv_layer.data.foreach_get('uv', uvs)
        uvs = uvs.reshape(-1, 2)
    finally:
        obj_eval.to_mesh_clear()

    bvh = BVHTree.FromPolygons(verts.tolist(), tri_verts.tolist(), all_triangles=True)

    # Texel density per triangle, used to tell UV seams from fast strokes.
    p0, p1, p2 = (verts[tri_verts[:, i]] for i in range(3))
    area3d = 0.5 * np.linalg.norm(np.cross(p1 - p0, p2 - p0), axis=1)
    u0, u1, u2 = (uvs[tri_loops[:, i]] for i in range(3))
    e1, e2 = u1 - u0, u2 - u0
    area_uv = 0.5 * np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0])
    with np.errstate(divide='ignore', invalid='ignore'):
        density = np.sqrt(np.where(area3d > 1e-12, area_uv / area3d, 0.0))

    return _MeshCache(key, bvh, tri_verts, tri_loops, verts, uvs, density)


def _mesh_cache(context):
    """Cached BVH + UV data of the active mesh object, or None."""
    global _cache
    obj = getattr(context, 'active_object', None)
    if obj is None or obj.type != 'MESH':
        return None
    uv_name = _uv_layer_name(context, obj)
    key = (obj.name, obj.data.name, uv_name)
    if _cache is None or _cache.key != key:
        try:
            _cache = _build(context, obj, uv_name, key)
        except Exception:
            import traceback
            traceback.print_exc()
            _cache = None
    return _cache


# ---------------------------------------------------------------------------
# Ray casting
# ---------------------------------------------------------------------------

class Hit:
    __slots__ = ('uv', 'tri', 'local')

    def __init__(self, uv, tri, local):
        self.uv = uv        # (u, v), not wrapped
        self.tri = tri      # loop-triangle index
        self.local = local  # hit position in object space (Vector)


def _window_region(context):
    area = getattr(context, 'area', None)
    if area is None or area.type != 'VIEW_3D':
        return None, None
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    if region is None:
        return None, None
    rv3d = getattr(context, 'region_data', None)
    if rv3d is None or getattr(context, 'region', None) != region:
        rv3d = region.data
    return region, rv3d


def ray_hit(context, region_x, region_y):
    """Surface hit under region coordinates ``(x, y)``, or None."""
    region, rv3d = _window_region(context)
    if region is None or rv3d is None:
        return None
    cache = _mesh_cache(context)
    if cache is None:
        return None
    obj = context.active_object
    coord = (region_x, region_y)
    try:
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
    except Exception:
        return None
    inv = obj.matrix_world.inverted_safe()
    o_local = inv @ origin
    d_local = (inv.to_3x3() @ direction).normalized()
    loc, _normal, tri, _dist = cache.bvh.ray_cast(o_local, d_local)
    if loc is None or tri is None:
        return None

    vi = cache.tri_verts[tri]
    li = cache.tri_loops[tri]
    p0, p1, p2 = (Vector(cache.verts[i]) for i in vi)
    t0, t1, t2 = (Vector((cache.uvs[i][0], cache.uvs[i][1], 0.0)) for i in li)
    uv = barycentric_transform(loc, p0, p1, p2, t0, t1, t2)
    return Hit((uv.x, uv.y), int(tri), loc)


def texel_screen_size(context, hit, image):
    """Screen pixels covered by one texel at ``hit`` (view-plane measure), or None.

    Uses the hit face's texel density (UV area / surface area), so the
    value follows the texture resolution on that face and the zoom.
    """
    cache = _mesh_cache(context)
    region, rv3d = _window_region(context)
    if cache is None or region is None or rv3d is None or image is None:
        return None
    w, h = image.size
    density = float(cache.density[hit.tri])   # UV units per object-space unit
    if w == 0 or h == 0 or density <= 0.0:
        return None
    obj = context.active_object
    mat = obj.matrix_world
    scale = sum(abs(c) for c in mat.to_scale()) / 3.0
    if scale <= 0.0:
        return None
    texel_world = (1.0 / math.sqrt(w * h)) / density * scale
    p = mat @ hit.local
    right = rv3d.view_rotation @ Vector((1.0, 0.0, 0.0))
    a = view3d_utils.location_3d_to_region_2d(region, rv3d, p)
    b = view3d_utils.location_3d_to_region_2d(region, rv3d, p + right * texel_world)
    if a is None or b is None:
        return None
    size = (b - a).length
    return size if size > 1e-6 else None


def cached_mesh():
    """The current mesh cache without (re)building it (safe in draw callbacks)."""
    return _cache


def hit_tile(hit):
    """Integer UV tile of a hit (UVs outside 0..1 wrap into the image)."""
    return int(math.floor(hit.uv[0])), int(math.floor(hit.uv[1]))


def hit_to_pixel(hit, w, h):
    """Image pixel for a hit; UVs outside 0..1 wrap (tiling)."""
    u = hit.uv[0] % 1.0
    v = hit.uv[1] % 1.0
    return min(w - 1, int(u * w)), min(h - 1, int(v * h))


def hovered_pixel(context, region_x, region_y, image):
    if image is None:
        return None
    w, h = image.size
    if w == 0 or h == 0:
        return None
    hit = ray_hit(context, region_x, region_y)
    if hit is None:
        return None
    return hit_to_pixel(hit, w, h)


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
    from ..tools import mask_geometry
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
    from ..tools import mask_geometry
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
    cache = _mesh_cache(context)
    if cache is None or w == 0 or h == 0:
        return None
    m = _island_map
    if m is not None and m.version == cache.version and (m.w, m.h) == (w, h):
        return m
    from ..utils import native
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


# ---------------------------------------------------------------------------
# Stroke path
# ---------------------------------------------------------------------------

def _is_continuous(cache, a, b, pa, pb, size):
    """True when samples ``a`` -> ``b`` lie on one UV island (no seam between)."""
    jump = max(abs(pb[0] - pa[0]), abs(pb[1] - pa[1]))
    if jump <= SEAM_SLACK:
        return True
    density = max(float(cache.density[a.tri]), float(cache.density[b.tri]))
    expected = (b.local - a.local).length * density * size
    return jump <= expected * SEAM_FACTOR + SEAM_SLACK


def pixel_path(context, start_xy, end_xy, image):
    """Pixels to paint when the mouse moves ``start_xy`` -> ``end_xy`` (region coords).

    The start sample is excluded (it was painted by the previous step).
    Consecutive surface samples are connected with Bresenham lines unless a
    UV seam (or empty space) lies between them.
    """
    w, h = image.size
    if w == 0 or h == 0:
        return []
    cache = _mesh_cache(context)
    if cache is None:
        return []
    size = max(w, h)

    sx, sy = start_xy
    ex, ey = end_xy
    length = math.hypot(ex - sx, ey - sy)
    n = max(1, min(MAX_SAMPLES, int(math.ceil(length / SCREEN_STEP))))

    path = []
    prev = ray_hit(context, sx, sy)
    prev_px = hit_to_pixel(prev, w, h) if prev is not None else None
    for i in range(1, n + 1):
        t = i / n
        cur = ray_hit(context, sx + (ex - sx) * t, sy + (ey - sy) * t)
        if cur is None:
            prev = prev_px = None
            continue
        cur_px = hit_to_pixel(cur, w, h)
        if prev is None:
            path.append(cur_px)
        elif cur_px != prev_px:
            if _is_continuous(cache, prev, cur, prev_px, cur_px, size):
                path.extend(math_utils.get_line_pixels(prev_px[0], prev_px[1], cur_px[0], cur_px[1])[1:])
            else:
                path.append(cur_px)  # seam: jump without connecting
        prev, prev_px = cur, cur_px
    return path


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

def _bary2d(tri_uv, q):
    """Barycentric weights (K, 3) of points ``q`` (K, 2) in 2D triangles ``tri_uv`` (K, 3, 2)."""
    v0 = tri_uv[:, 1] - tri_uv[:, 0]
    v1 = tri_uv[:, 2] - tri_uv[:, 0]
    v2 = q - tri_uv[:, 0]
    den = v0[:, 0] * v1[:, 1] - v1[:, 0] * v0[:, 1]
    with np.errstate(divide='ignore', invalid='ignore'):
        w1 = (v2[:, 0] * v1[:, 1] - v1[:, 0] * v2[:, 1]) / den
        w2 = (v0[:, 0] * v2[:, 1] - v2[:, 0] * v0[:, 1]) / den
    return np.stack((1.0 - w1 - w2, w1, w2), axis=1)


def _apply_bary(w, corners):
    """``w`` (K, 3) applied to ``corners`` (K, 3, D)."""
    return (w[:, :, None] * corners).sum(axis=1)


def _bary3d(p0, p1, p2, q):
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
        w = _bary2d(cache.tri_uv[prefer][None], q[None])[0]
        if np.all(w >= -1e-6):
            return int(prefer)
    cand = _bbox_candidates(cache, q, q)
    if len(cand):
        w = _bary2d(cache.tri_uv[cand], np.broadcast_to(q, (len(cand), 2)))
        inside = np.nonzero(np.all(w >= -1e-6, axis=1))[0]
        if len(inside):
            return int(cand[inside[0]])
    return prefer


# ---- unfolding ---------------------------------------------------------------------

def _adjacency(cache):
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


def _place_neighbor(cache, t, P, n, va, vb, isometric=False):
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
        w = _bary2d(A[None], An[ic][None])[0]
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
                w = _bary3d(*corners, q_unfolded)
                if w is not None:
                    pc = w @ P
    if pc is None or not np.all(np.isfinite(pc)):
        return None, connected
    Pn = np.empty((3, 2))
    Pn[ia], Pn[ib], Pn[ic] = P[ka], P[kb], pc
    return Pn, connected


def _grow(cache, placed, identity, order, accept, isometric=False):
    """Breadth-first placement from the already placed triangles in ``order``.

    ``accept(Pn)`` decides whether a newly placed neighbour is kept (and
    expanded further).
    """
    tri_verts = cache.tri_verts
    adj = _adjacency(cache)
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
                Pn, connected = _place_neighbor(cache, t, P, n, va, vb, isometric)
                if Pn is None or not accept(Pn):
                    continue
                placed[n] = Pn
                identity[n] = identity[t] and connected and not isometric
                order.append(n)
                queue.append(n)


def _frame_from(cache, placed, identity, order):
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
    _grow(cache, placed, identity, order, lambda Pn: _overlaps(Pn, lo, hi))
    return _frame_from(cache, placed, identity, order)


# ---- shortest path across faces (Edge-mode Line) ---------------------------------

MAX_SEARCH_TRIS = 200_000


def _tri_neighbors(cache):
    """Per triangle: list of ``(neighbour, va, vb, edge_midpoint)`` (built once per mesh)."""
    nbrs = cache._nbrs
    if nbrs is None:
        adj = _adjacency(cache)
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
    w = _bary3d(*corners, np.asarray(local, dtype=np.float64))
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
        Pn, _connected = _place_neighbor(cache, prev, placed[prev], t, va, vb, isometric=True)
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
    cache = _mesh_cache(context)
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
        _grow(cache, placed, identity, order,
              lambda Pn: _near_polyline(Pn, polyline, margin), isometric=True)
        pix = [tuple(int(v) for v in np.floor(p * size)) for p in polyline]
        line = [pix[0]]
        for a, b in zip(pix, pix[1:]):
            line.extend(math_utils.get_line_pixels(a[0], a[1], b[0], b[1])[1:])
        result = (_frame_from(cache, placed, identity, order), line)
    _line_cache_key, _line_cache_val = key, result
    return result


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
    return np.stack((_apply_bary(_bary2d(tri_uv, q0), tri_pos),
                     _apply_bary(_bary2d(tri_uv, q1), tri_pos)), axis=1)


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
        bw = _bary2d(np.broadcast_to(tri_uv, (len(pts), 3, 2)), pts)
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
        uv = _apply_bary(bw[inside], np.broadcast_to(actual, (inside.sum(), 3, 2)))
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
    cache = _mesh_cache(context)
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


# ---- filter patches (Edge-mode Smooth / Smear) -------------------------------------

MAX_PATCH_TEXELS = 1 << 20


def _patch_samples(frame, x0, y0, pw, ph, w, h, tile, k, mask=None):
    """Map the ``k * k`` subsamples of the patch texels onto the image.

    The patch is the texel box ``x0, y0`` .. ``x0 + pw - 1, y0 + ph - 1`` of the
    frame (seed texture space). Seed-island triangles come first, then the
    unfolded neighbours in unfold order (nearest first); every subsample goes
    to the first triangle covering it. ``mask`` (pw * ph bools) limits the
    texels mapped. Works triangle by triangle on the subsample grid inside the
    triangle's box, so the cost follows the patch area, not texels x triangles.

    Returns ``(owner, target, on_island)`` arrays, one entry per covered
    subsample: patch flat index, flat image pixel index, from the seed island.
    """
    size = np.array((w, h), dtype=np.float64)
    tile = np.asarray(tile, dtype=np.float64)
    gw, gh = pw * k, ph * k
    claimed = np.zeros(gw * gh, dtype=bool)
    if mask is not None:
        grid = np.asarray(mask, dtype=bool).reshape(ph, pw)
        claimed |= ~np.repeat(np.repeat(grid, k, axis=0), k, axis=1).ravel()
    owners, targets, islands = [], [], []
    order = np.concatenate((np.nonzero(frame.identity)[0], np.nonzero(~frame.identity)[0]))
    for j in order:
        tri = frame.uv[j]
        tp = (tri - tile) * size                      # frame texel coords
        mn, mx = tp.min(axis=0), tp.max(axis=0)
        gx0 = max(0, int(np.ceil((mn[0] - x0) * k - 0.5)))
        gx1 = min(gw - 1, int(np.floor((mx[0] - x0) * k - 0.5)))
        gy0 = max(0, int(np.ceil((mn[1] - y0) * k - 0.5)))
        gy1 = min(gh - 1, int(np.floor((mx[1] - y0) * k - 0.5)))
        if gx0 > gx1 or gy0 > gy1:
            continue
        gx, gy = np.meshgrid(np.arange(gx0, gx1 + 1), np.arange(gy0, gy1 + 1))
        flat = (gy * gw + gx).ravel()
        flat = flat[~claimed[flat]]
        if not len(flat):
            continue
        sx, sy = flat % gw, flat // gw
        q = (np.stack((x0 + (sx + 0.5) / k, y0 + (sy + 0.5) / k), axis=1)) / size + tile
        bw = _bary2d(np.broadcast_to(tri, (len(q), 3, 2)), q)
        inside = np.all(bw >= -1e-9, axis=1)
        if not inside.any():
            continue
        flat, sx, sy, bw = flat[inside], sx[inside], sy[inside], bw[inside]
        claimed[flat] = True
        uv = bw @ frame.actual[j]
        t = np.floor((uv % 1.0) * size).astype(np.int64)
        tx = np.minimum(t[:, 0], w - 1)
        ty = np.minimum(t[:, 1], h - 1)
        owners.append((sy // k) * pw + sx // k)
        targets.append(ty * w + tx)
        islands.append(np.full(len(flat), bool(frame.identity[j])))
    if not owners:
        empty = np.zeros(0, dtype=np.int64)
        return empty, empty, np.zeros(0, dtype=bool)
    return np.concatenate(owners), np.concatenate(targets), np.concatenate(islands)


def _area2(tri):
    """Twice the area of 2D triangle ``tri`` (3, 2)."""
    (ax, ay), (bx, by), (cx, cy) = tri
    return abs((bx - ax) * (cy - ay) - (by - ay) * (cx - ax))


def _supersample(frame):
    """Subsamples per texel side so no neighbour with a higher texel density gets holes."""
    k = 1
    for j in np.nonzero(~frame.identity)[0]:
        a_placed = _area2(frame.uv[j])
        a_actual = _area2(frame.actual[j])
        if a_placed >= 1e-18:
            k = max(k, int(min(MAX_SUPERSAMPLE, np.ceil(np.sqrt(a_actual / a_placed)))))
    return k


class EdgePatch:
    """The texels around one Edge-mode stamp, laid out in the stamp's texture space.

    Smooth and Smear read neighbouring pixels, which in texture space would
    pull in whatever lies beside the UV island. A patch unfolds the surface
    around the stamp (like :func:`edge_expand`), so a filter runs on the
    surface: gather the patch from the image, filter it, scatter the result.

    ``x0, y0`` / ``pw, ph``: the patch box in the seed's texel coords (it may
    leave the image). Per patch texel (flat ``ly * pw + lx``):

    * ``source``: flat image pixel it reads from (-1 = none);
    * ``valid``: it lies on the surface (seed island or an unfolded
      neighbour) -- the only texels a filter may sample;
    * texels off every triangle but next to the seed island read and write
      in place (they straddle the seam, see :func:`expand_footprint`) without
      being sampled.
    """

    def __init__(self, frame, x0, y0, pw, ph, w, h, tile, source, valid):
        self.frame = frame
        self.x0, self.y0, self.pw, self.ph = x0, y0, pw, ph
        self.w, self.h = w, h
        self.tile = tile
        self.source = source
        self.valid = valid

    def flat(self, pixels):
        """Patch flat indices of image-texel ``pixels`` (they must lie in the patch box)."""
        pix = np.asarray(pixels, dtype=np.int64).reshape(-1, 2)
        return (pix[:, 1] - self.y0) * self.pw + (pix[:, 0] - self.x0)

    def local(self, flat):
        """``(N, 2)`` patch coords of flat indices."""
        flat = np.asarray(flat, dtype=np.int64)
        return np.stack((flat % self.pw, flat // self.pw), axis=1)

    def gather(self, arr):
        """The patch as a flat float32 RGBA buffer read from image buffer ``arr``."""
        out = np.zeros((self.pw * self.ph, 4), dtype=np.float32)
        has = self.source >= 0
        out[has] = np.asarray(arr).reshape(-1, 4)[self.source[has]]
        return out.reshape(-1)

    def scatter(self, flat):
        """Where patch texels ``flat`` are written: ``(index into flat, flat image pixel)``.

        Supersampled, so neighbours with a higher texel density get no holes.
        """
        flat = np.asarray(flat, dtype=np.int64)
        if not len(flat):
            empty = np.zeros(0, dtype=np.int64)
            return empty, empty
        mask = np.zeros(self.pw * self.ph, dtype=bool)
        mask[flat] = True
        owner, target, _ = _patch_samples(self.frame, self.x0, self.y0, self.pw, self.ph,
                                          self.w, self.h, self.tile, _supersample(self.frame), mask)
        border = flat[(self.source[flat] >= 0) & ~self.valid[flat]]
        owner = np.concatenate((owner, border))
        target = np.concatenate((target, self.source[border]))
        pairs = np.unique(owner * (self.w * self.h) + target)
        owner, target = pairs // (self.w * self.h), pairs % (self.w * self.h)
        position = np.full(self.pw * self.ph, -1, dtype=np.int64)
        position[flat] = np.arange(len(flat))
        return position[owner], target

    def locate(self, x, y):
        """Patch coords (float) of image texel ``(x, y)`` on the unfolded surface, or None."""
        frame = self.frame
        if not len(frame):
            return None
        size = np.array((self.w, self.h), dtype=np.float64)
        tile = np.asarray(self.tile, dtype=np.float64)
        q = (np.array((x, y), dtype=np.float64) + 0.5) / size + tile
        bw = _bary2d(frame.actual, np.broadcast_to(q, (len(frame), 2)))
        inside = np.all(bw >= -1e-6, axis=1)
        if not inside.any():
            return None
        # the seed island first, then the nearest unfolded neighbour
        hits = np.nonzero(inside & frame.identity)[0]
        j = int(hits[0] if len(hits) else np.nonzero(inside)[0][0])
        p = (bw[j] @ frame.uv[j] - tile) * size - 0.5
        return float(p[0] - self.x0), float(p[1] - self.y0)


def edge_patch(context, img, cx, cy, pixels, pad, tile, prefer_tri=None):
    """:class:`EdgePatch` around the stamp ``pixels`` centred on texel ``(cx, cy)``,
    padded by ``pad`` texels; None without a mesh / seed triangle or when too large."""
    pixels = list(pixels)
    w, h = img.size
    if not pixels or w == 0 or h == 0:
        return None
    cache = _mesh_cache(context)
    if cache is None:
        return None
    center_uv = ((cx + 0.5) / w + tile[0], (cy + 0.5) / h + tile[1])
    seed = find_triangle(cache, center_uv, prefer=prefer_tri)
    if seed is None:
        return None
    pix = np.asarray(pixels, dtype=np.int64).reshape(-1, 2)
    pad = max(0, int(np.ceil(pad)))
    x0, y0 = (int(v) - pad for v in pix.min(axis=0))
    x1, y1 = (int(v) + pad for v in pix.max(axis=0))
    pw, ph = x1 - x0 + 1, y1 - y0 + 1
    if pw * ph > MAX_PATCH_TEXELS:
        return None
    lo, hi = footprint_box(((x0, y0), (x1, y1)), w, h, tile)
    frame = unfold(cache, seed, lo, hi)

    owner, target, on_island = _patch_samples(frame, x0, y0, pw, ph, w, h, tile, 1)
    source = np.full(pw * ph, -1, dtype=np.int64)
    source[owner] = target
    valid = source >= 0
    island = np.zeros(pw * ph, dtype=bool)
    island[owner[on_island]] = True

    # texels off every triangle that border the seed island: in place, never sampled
    grid = np.pad(island.reshape(ph, pw), 1)
    near = np.zeros((ph, pw), dtype=bool)
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            near |= grid[dy:dy + ph, dx:dx + pw]
    border = np.nonzero(near.ravel() & ~valid)[0]
    bx = (x0 + border % pw) % w
    by = (y0 + border // pw) % h
    source[border] = by * w + bx
    return EdgePatch(frame, x0, y0, pw, ph, w, h, tile, source, valid)
