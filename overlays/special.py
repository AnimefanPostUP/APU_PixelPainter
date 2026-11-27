"""Canvas markers of the special brushes (Image Editor): the Repair brush's source.
"""

from ..utils import blender_utils
from .gpu_prims import draw_lines, draw_wide_circle_outline

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
