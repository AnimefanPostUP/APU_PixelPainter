"""View window actions (pen menu > View): orient, orbit, roll, focus and fit the
3D Viewport on the painted object.

Works on the view (``RegionView3D``) directly, no operators: the view's rotation
is set, its pivot (``view_location``) moved to the object's center and its
distance chosen so every vertex of the object is inside the view
(:func:`fit_view`). A view looking through the scene camera is switched to a free
perspective view first (the camera object itself is not moved).

The math works on numpy 3x3 rotation matrices (columns: the view's right, up and
back axes in world space; the view looks down -back) and is unit tested without
Blender; :func:`_get_rot` / :func:`_set_rot` convert at the ``RegionView3D``.
"""

import math

import numpy as np

FIT_MARGIN = 0.92          # the object fills this much of the view's narrower side
ORBIT_STEP = 15.0          # degrees per orbit / roll tap

# View axes (right, up, back) of Blender's numpad views.
AXIS_VIEWS = {
    'FRONT': ((1, 0, 0), (0, 0, 1), (0, -1, 0)),
    'BACK': ((-1, 0, 0), (0, 0, 1), (0, 1, 0)),
    'RIGHT': ((0, 1, 0), (0, 0, 1), (1, 0, 0)),
    'LEFT': ((0, -1, 0), (0, 0, 1), (-1, 0, 0)),
    'TOP': ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
    'BOTTOM': ((1, 0, 0), (0, -1, 0), (0, 0, -1)),
}


def axis_rotation(axis):
    return np.array(AXIS_VIEWS[axis], dtype=np.float64).T


def axis_angle(axis, degrees):
    """Rotation matrix: ``degrees`` counter-clockwise around the unit vector ``axis``."""
    x, y, z = np.asarray(axis, dtype=np.float64) / np.linalg.norm(axis)
    a = math.radians(degrees)
    c, s, t = math.cos(a), math.sin(a), 1.0 - math.cos(a)
    return np.array([[t * x * x + c, t * x * y - s * z, t * x * z + s * y],
                     [t * x * y + s * z, t * y * y + c, t * y * z - s * x],
                     [t * x * z - s * y, t * y * z + s * x, t * z * z + c]])


def level_rotation(rot, up=(0.0, 0.0, 1.0)):
    """``rot`` with the same viewing direction but no roll: world ``up`` points up on
    screen. Looking (almost) straight along ``up``: world +Y / -Y is up instead,
    whichever is nearer the view's current up (like the Top / Bottom views)."""
    rot = np.asarray(rot, dtype=np.float64)
    back = rot[:, 2] / np.linalg.norm(rot[:, 2])
    up = np.asarray(up, dtype=np.float64)
    if abs(back @ up) > 0.999:
        up = np.array([0.0, 1.0, 0.0])
        if rot[:, 1] @ up < 0.0:
            up = -up
    right = np.cross(up, back)
    n = np.linalg.norm(right)
    if n < 1e-9:
        return rot.copy()
    right /= n
    return np.column_stack([right, np.cross(back, right), back])


def roll(rot, degrees):
    """Turn the view around its viewing axis (positive: the picture turns counter-clockwise)."""
    rot = np.asarray(rot, dtype=np.float64)
    return axis_angle(rot[:, 2], -degrees) @ rot


def orbit(rot, yaw_deg=0.0, pitch_deg=0.0):
    """Turntable orbit around the pivot: ``yaw`` around world Z (positive: the view moves
    to the right around the object), ``pitch`` around the view's right axis
    (positive: the view moves up, looking more from above)."""
    rot = np.asarray(rot, dtype=np.float64)
    if pitch_deg:
        rot = axis_angle(rot[:, 0], -pitch_deg) @ rot
    if yaw_deg:
        rot = axis_angle((0.0, 0.0, 1.0), yaw_deg) @ rot
    return rot


def fit_view(points, rot, tan_x, tan_y, perspective, margin=FIT_MARGIN):
    """``(center, distance)`` framing the world-space ``points`` (N, 3) for a view with
    rotation ``rot``. ``tan_x`` / ``tan_y``: half the view's width / height per unit of
    distance (perspective: tan of the half field of view; orthographic: half size /
    view distance, as in Blender). The center is the middle of the points' box in view
    space, so the object ends up centered on screen."""
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    rot = np.asarray(rot, dtype=np.float64)
    view = pts @ rot                                   # (N, 3): x right, y up, z toward the viewer
    lo, hi = view.min(axis=0), view.max(axis=0)
    mid = (lo + hi) * 0.5
    local = view - mid
    tx, ty = max(1e-9, tan_x * margin), max(1e-9, tan_y * margin)
    if perspective:
        # eye at +distance on the view's z axis: a point's depth = distance - z
        need = np.maximum(local[:, 2] + np.abs(local[:, 0]) / tx, local[:, 2] + np.abs(local[:, 1]) / ty)
        distance = float(need.max())
    else:
        distance = float(max(np.abs(local[:, 0]).max() / tx, np.abs(local[:, 1]).max() / ty))
    return rot @ mid, max(distance, 1e-3)


# ---- Blender side -------------------------------------------------------------------

def _rv3d(area):
    if area is None or area.type != 'VIEW_3D':
        return None
    return getattr(area.spaces.active, 'region_3d', None)


def _get_rot(rv3d):
    return np.array(rv3d.view_rotation.to_matrix(), dtype=np.float64)


def _set_rot(rv3d, rot):
    from mathutils import Matrix
    rv3d.view_rotation = Matrix(np.asarray(rot).tolist()).to_quaternion()


def target_object(context):
    """The painted object (the 3D paint session's mesh), else the active object."""
    import bpy
    from ...core import view3d
    cache = view3d.cached_mesh()
    if cache is not None:
        obj = bpy.data.objects.get(cache.key[0])
        if obj is not None:
            return obj
    return getattr(context, 'active_object', None)


def object_points(obj):
    """World-space points to frame: the cached paint mesh's vertices, else the bounding box."""
    from ...core import view3d
    cache = view3d.cached_mesh()
    if cache is not None and cache.key[0] == obj.name and len(cache.tri_pos):
        local = cache.tri_pos.reshape(-1, 3)
    else:
        local = np.array([tuple(c) for c in obj.bound_box], dtype=np.float64)
    mat = np.array(obj.matrix_world, dtype=np.float64)
    return local @ mat[:3, :3].T + mat[:3, 3]


def _view_tangents(rv3d):
    """Half width / height of the view per unit of distance (see :func:`fit_view`)."""
    wm = rv3d.window_matrix
    sx, sy = abs(wm[0][0]), abs(wm[1][1])
    if rv3d.is_perspective:
        return 1.0 / max(sx, 1e-9), 1.0 / max(sy, 1e-9)
    d = max(rv3d.view_distance, 1e-9)
    return 1.0 / max(sx * d, 1e-9), 1.0 / max(sy * d, 1e-9)


def _apply(context, area, rot=None, fit=False, center=False):
    from mathutils import Vector
    rv3d = _rv3d(area)
    if rv3d is None:
        return False
    if rv3d.view_perspective == 'CAMERA':
        rv3d.view_perspective = 'PERSP'
    if rot is not None:
        _set_rot(rv3d, rot)
    if fit or center:
        obj = target_object(context)
        if obj is not None:
            pts = object_points(obj)
            if fit:
                rv3d.update()    # window_matrix for the current lens / perspective
                tx, ty = _view_tangents(rv3d)
                c, d = fit_view(pts, _get_rot(rv3d), tx, ty, rv3d.is_perspective)
                rv3d.view_location = Vector(c)
                rv3d.view_distance = d
            else:
                lo, hi = pts.min(axis=0), pts.max(axis=0)
                rv3d.view_location = Vector((lo + hi) * 0.5)
    area.tag_redraw()
    return True


def view_axis(context, area, axis, fit):
    return _apply(context, area, rot=axis_rotation(axis), fit=fit, center=True)


def view_orbit(context, area, yaw, pitch, fit):
    rv3d = _rv3d(area)
    return rv3d is not None and _apply(context, area, rot=orbit(_get_rot(rv3d), yaw, pitch), fit=fit, center=True)


def view_roll(context, area, degrees, fit):
    rv3d = _rv3d(area)
    return rv3d is not None and _apply(context, area, rot=roll(_get_rot(rv3d), degrees), fit=fit)


def view_level(context, area, fit):
    rv3d = _rv3d(area)
    return rv3d is not None and _apply(context, area, rot=level_rotation(_get_rot(rv3d)), fit=fit)


def view_fit(context, area):
    return _apply(context, area, fit=True)


def view_center(context, area):
    return _apply(context, area, center=True)


def is_perspective(area):
    rv3d = _rv3d(area)
    return rv3d is not None and rv3d.view_perspective != 'ORTHO'


def toggle_perspective(context, area, fit):
    rv3d = _rv3d(area)
    if rv3d is None:
        return False
    rv3d.view_perspective = 'PERSP' if rv3d.view_perspective == 'ORTHO' else 'ORTHO'
    return _apply(context, area, fit=fit)
