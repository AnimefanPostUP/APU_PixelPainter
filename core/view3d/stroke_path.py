"""Stroke interpolation in the 3D Viewport: neighbouring pixels on the screen can be far
apart in UV space (seams), so :func:`pixel_path` walks the *screen* segment between two
mouse positions and only connects consecutive samples where they are continuous on the
surface.
"""

import math


from ...utils import math_utils
from . import mesh
from .raycast import hit_to_pixel, ray_hit


SCREEN_STEP = 2.0      # screen pixels between ray-cast samples along a stroke
MAX_SAMPLES = 256      # cap per mouse event
SEAM_FACTOR = 3.0      # UV jump > SEAM_FACTOR * expected jump (+ slack) = seam
SEAM_SLACK = 2


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
    cache = mesh.mesh_cache(context)
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
