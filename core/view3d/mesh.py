"""Mesh cache: the painted object's evaluated triangles (positions, UVs, a BVH tree),
rebuilt when the mesh, its UV map or the object changes.
"""


import numpy as np
from mathutils.bvhtree import BVHTree



# ---------------------------------------------------------------------------
# Mesh cache
# ---------------------------------------------------------------------------

class MeshCache:
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
_failed_key = None   # key whose build gave no mesh (no UV map, no faces): not retried per event


def invalidate():
    """Drop the cached mesh (call when a painting session starts)."""
    global _cache, _failed_key
    _cache = None
    _failed_key = None


def uv_layer_name(context, obj):
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

    return MeshCache(key, bvh, tri_verts, tri_loops, verts, uvs, density)


def mesh_cache(context):
    """Cached BVH + UV data of the active mesh object, or None."""
    global _cache, _failed_key
    obj = getattr(context, 'active_object', None)
    if obj is None or obj.type != 'MESH':
        return None
    uv_name = uv_layer_name(context, obj)
    key = (obj.name, obj.data.name, uv_name)
    if _cache is None or _cache.key != key:
        if key == _failed_key:
            return None   # evaluating the mesh again would fail again (until invalidate())
        try:
            _cache = _build(context, obj, uv_name, key)
        except Exception:
            import traceback
            traceback.print_exc()
            _cache = None
        _failed_key = key if _cache is None else None
    return _cache


def cached_mesh():
    """The current mesh cache without (re)building it (safe in draw callbacks)."""
    return _cache
