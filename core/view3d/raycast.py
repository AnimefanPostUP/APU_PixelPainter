"""Mouse -> texture pixel: cast the mouse ray against the mesh and turn the UV at the
hit point (barycentric over the hit triangle) into an image pixel.
"""

import math

from bpy_extras import view3d_utils
from mathutils import Vector
from mathutils.geometry import barycentric_transform

from . import mesh


def is_view3d(context):
    space = getattr(context, 'space_data', None)
    return space is not None and space.type == 'VIEW_3D'


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
    cache = mesh.mesh_cache(context)
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

    return hit_at(cache, loc, tri)


def hit_at(cache, loc, tri):
    """A :class:`Hit` for the object-space point ``loc`` on loop triangle ``tri``."""
    vi = cache.tri_verts[tri]
    li = cache.tri_loops[tri]
    p0, p1, p2 = (Vector(cache.verts[i]) for i in vi)
    t0, t1, t2 = (Vector((cache.uvs[i][0], cache.uvs[i][1], 0.0)) for i in li)
    uv = barycentric_transform(loc, p0, p1, p2, t0, t1, t2)
    return Hit((uv.x, uv.y), int(tri), loc)


def view_frame(context):
    """``(region, rv3d)`` of the 3D Viewport's main region, or ``(None, None)``."""
    return _window_region(context)


def texel_screen_size(context, hit, image):
    """Screen pixels covered by one texel at ``hit`` (view-plane measure), or None.

    Uses the hit face's texel density (UV area / surface area), so the
    value follows the texture resolution on that face and the zoom.
    """
    cache = mesh.mesh_cache(context)
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
