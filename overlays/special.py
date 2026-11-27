"""Canvas markers of the special brushes: the Repair brush's source (Image Editor), the
Particles brush's flight paths and impacts (3D Viewport and Image Editor).
"""

from ..utils import blender_utils
from .gpu_prims import draw_filled_circle, draw_lines, draw_wide_circle_outline

ARM = 7.0      # cross arm length, region px
RING = 4.0     # the live copy point's circle, region px


def _pixel_center(v2d, x, y, w, h):
    return v2d.view_to_region((x + 0.5) / w, (y + 0.5) / h, clip=False)


def draw_source_marker(context, source, live, color):
    """A cross on the source pixel; while a stroke copies, a small circle where it reads."""
    _space, img = blender_utils.get_space_img(context)
    if img is None:
        return
    w, h = img.size
    if w == 0 or h == 0:
        return
    _region, v2d = blender_utils.get_window_region_and_v2d(context.area)
    if not v2d:
        return
    sx, sy = _pixel_center(v2d, source[0], source[1], w, h)
    shadow = (0.0, 0.0, 0.0, 0.6)
    for (ox, oy), rgba in (((1.0, -1.0), shadow), ((0.0, 0.0), color)):
        draw_lines([(sx - ARM + ox, sy + oy), (sx + ARM + ox, sy + oy),
                    (sx + ox, sy - ARM + oy), (sx + ox, sy + ARM + oy)], rgba)
    if live is not None:
        lx, ly = _pixel_center(v2d, live[0], live[1], w, h)
        draw_wide_circle_outline(lx, ly, RING, color, steps=16)


# ---- Particles: the bodies' paths and impacts --------------------------------------------

HIT_RADIUS = 2.5      # impact dots, region px


def _projector(context, space):
    """``point -> (x, y)`` region px (or None) for the trails' space ('3D' world / '2D' image)."""
    if space == '3D':
        from bpy_extras import view3d_utils
        region, rv3d = getattr(context, 'region', None), getattr(context, 'region_data', None)
        if region is None or rv3d is None:
            return None

        def project(p):
            q = view3d_utils.location_3d_to_region_2d(region, rv3d, p)
            return None if q is None else (q.x, q.y)
        return project
    _space, img = blender_utils.get_space_img(context)
    _region, v2d = blender_utils.get_window_region_and_v2d(context.area)
    if img is None or not v2d or img.size[0] == 0 or img.size[1] == 0:
        return None
    w, h = img.size
    return lambda p: v2d.view_to_region(p[0] / w, p[1] / h, clip=False)


def draw_particle_trails(context, space, live, trail_color, hit_color):
    """``live``: ``[(trail, fade), ...]`` (model/particle_trails.py) -- each path as a line
    fading with age, each impact as a dot."""
    project = _projector(context, space)
    if project is None:
        return
    for trail, fade in live:
        pts = [project(p) for p in trail.path]
        verts = []
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            if a is None or b is None:
                continue
            verts += [a, b]
        if verts:
            draw_lines(verts, (*trail_color, 0.55 * fade))
        for p in trail.hits:
            q = project(p)
            if q is not None:
                draw_filled_circle(q[0], q[1], HIT_RADIUS, (*hit_color, 0.9 * fade), segments=10)
