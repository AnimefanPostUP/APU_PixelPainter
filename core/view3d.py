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
                 'tri_uv', 'tri_pos', 'uv_min', 'uv_max', 'uv_sign', 'uv_ok', 'version')

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
# UV -> surface projection (brush outline)
# ---------------------------------------------------------------------------

MAX_PAIR_CELLS = 4_000_000   # edge x triangle pairs per chunk (memory bound)


def project_uv_segments(cache, segments):
    """Map UV-space line segments onto the mesh surface.

    ``segments`` is an ``(E, 2, 2)`` array of UV segments. Every segment is
    clipped against each UV triangle it crosses and the clipped pieces are
    mapped to object space with the triangle's barycentric coordinates, so a
    segment bends exactly where it crosses a mesh edge (around corners).
    Overlapping / mirrored UVs yield one copy per triangle.

    Returns ``(K, 2, 3)`` object-space segments.
    """
    empty = np.empty((0, 2, 3), dtype=np.float64)
    if cache is None or len(segments) == 0:
        return empty
    seg = np.asarray(segments, dtype=np.float64)
    p0 = seg[:, 0]
    d = seg[:, 1] - p0

    lo = seg.reshape(-1, 2).min(axis=0)
    hi = seg.reshape(-1, 2).max(axis=0)
    cand = np.nonzero(
        cache.uv_ok
        & (cache.uv_max[:, 0] >= lo[0]) & (cache.uv_min[:, 0] <= hi[0])
        & (cache.uv_max[:, 1] >= lo[1]) & (cache.uv_min[:, 1] <= hi[1])
    )[0]
    if len(cand) == 0:
        return empty

    out = []
    chunk = max(1, MAX_PAIR_CELLS // max(1, len(seg)))
    for start in range(0, len(cand), chunk):
        tris = cand[start:start + chunk]
        pieces = _clip_segments_to_triangles(cache, p0, d, tris)
        if pieces is not None:
            out.append(pieces)
    return np.concatenate(out) if out else empty


def _clip_segments_to_triangles(cache, p0, d, tris):
    uv = cache.tri_uv[tris]                 # (C, 3, 2)
    sign = cache.uv_sign[tris][None, :]     # (1, C)
    n_e, n_c = len(p0), len(tris)
    tmin = np.zeros((n_e, n_c))
    tmax = np.ones((n_e, n_c))
    eps = 1e-12
    for i in range(3):
        a = uv[:, i]                        # (C, 2)
        e = uv[:, (i + 1) % 3] - a          # (C, 2)
        rel_x = p0[:, None, 0] - a[None, :, 0]
        rel_y = p0[:, None, 1] - a[None, :, 1]
        # inside half-plane: sign * cross(e, p - a) >= 0, linear in t
        n0 = sign * (e[None, :, 0] * rel_y - e[None, :, 1] * rel_x)
        dn = sign * (e[None, :, 0] * d[:, None, 1] - e[None, :, 1] * d[:, None, 0])
        with np.errstate(divide='ignore', invalid='ignore'):
            t = -n0 / dn
        pos = dn > eps
        neg = dn < -eps
        tmin = np.where(pos, np.maximum(tmin, t), tmin)
        tmax = np.where(neg, np.minimum(tmax, t), tmax)
        tmax = np.where(~pos & ~neg & (n0 < -eps), -1.0, tmax)  # parallel and outside

    ei, ci = np.nonzero(tmax - tmin > 1e-9)
    if len(ei) == 0:
        return None
    tri = tris[ci]
    q0 = p0[ei] + d[ei] * tmin[ei, ci][:, None]
    q1 = p0[ei] + d[ei] * tmax[ei, ci][:, None]
    return np.stack((_uv_to_local(cache, tri, q0), _uv_to_local(cache, tri, q1)), axis=1)


def _uv_to_local(cache, tri, q):
    """Object-space positions of UV points ``q`` (K, 2) inside triangles ``tri`` (K,)."""
    uv = cache.tri_uv[tri]
    pos = cache.tri_pos[tri]
    v0 = uv[:, 1] - uv[:, 0]
    v1 = uv[:, 2] - uv[:, 0]
    v2 = q - uv[:, 0]
    den = v0[:, 0] * v1[:, 1] - v1[:, 0] * v0[:, 1]
    w1 = (v2[:, 0] * v1[:, 1] - v1[:, 0] * v2[:, 1]) / den
    w2 = (v0[:, 0] * v2[:, 1] - v2[:, 0] * v0[:, 1]) / den
    w0 = 1.0 - w1 - w2
    return w0[:, None] * pos[:, 0] + w1[:, None] * pos[:, 1] + w2[:, None] * pos[:, 2]
