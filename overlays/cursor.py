"""Cursors drawn on the canvas: the 3D Viewport's off-mesh ring, a single-pixel
outline, the element pickers' cursor (secondary tools: mask editing, Extras).
"""


import gpu

from ..utils import blender_utils
from .gpu_prims import draw_wide_circle_outline, draw_lines, draw_precision_pixel_guide


# ---------------------------------------------------------------------------
# PixelDotDrawer — single-pixel cursor outline
# ---------------------------------------------------------------------------

def draw_pixel_cursor_outline(context, current_x, current_y):
    """Draw a 1-pixel square outline at (current_x, current_y) in image space."""
    if current_x is None or current_y is None:
        return

    space, img = blender_utils.get_space_img(context)
    if not space or not img:
        return

    w, h = img.size
    cx, cy = current_x, current_y
    _, v2d = blender_utils.get_window_region_and_v2d(context.area)
    if not v2d:
        return

    corners = [
        (cx / w,       cy / h),
        ((cx + 1) / w, cy / h),
        ((cx + 1) / w, (cy + 1) / h),
        (cx / w,       (cy + 1) / h),
    ]
    sc = [(round(x), round(y)) for x, y in [v2d.view_to_region(u, v) for u, v in corners]]
    vertices = [sc[0], sc[1], sc[1], sc[2], sc[2], sc[3], sc[3], sc[0]]
    draw_lines(vertices, (1.0, 1.0, 0.0, 1.0))


def draw_view3d_offmesh_cursor(context, state):
    """3D Viewport cursor while the mouse is off the mesh: a dim ring."""
    mouse = state.get('mouse_region')
    if mouse is None:
        return
    from ..tools.catalog import TOOLS
    try:
        color = TOOLS.get(context.window_manager.pixel_painter_mode).outline_color
    except Exception:
        color = (1.0, 1.0, 0.0, 0.9)
    if state.get('current_cx') is not None:
        return  # on the mesh: the surface outline (overlays_view3d) is drawn instead
    rgba = (color[0], color[1], color[2], 0.3)
    gpu.state.blend_set('ALPHA')
    draw_wide_circle_outline(mouse[0], mouse[1], 10.0, (0.0, 0.0, 0.0, rgba[3] * 0.8), width=3.0, steps=32)
    draw_wide_circle_outline(mouse[0], mouse[1], 10.0, rgba, width=1.5, steps=32)
    gpu.state.blend_set('NONE')
    gpu.state.line_width_set(1.0)


def draw_pick_cursor(context, state, color):
    """Cursor of an element picker (a secondary tool -- the selected tool's outline is
    hidden meanwhile): a small ring in the picker's ``color`` at the mouse and, in the
    Image Editor, brackets around the pixel it reads. The element itself is outlined
    by ``overlays.element_outline``."""
    mouse = state.get('mouse_region')
    if mouse is None:
        return
    space = getattr(context, 'space_data', None)
    if getattr(space, 'type', None) != 'VIEW_3D':
        px, py = state.get('current_cx'), state.get('current_cy')
        if px is not None and py is not None:
            draw_precision_pixel_guide(context, px, py, color=color)
    gpu.state.blend_set('ALPHA')
    draw_wide_circle_outline(mouse[0], mouse[1], 7.0, (0.0, 0.0, 0.0, 0.8), width=3.0, steps=28)
    draw_wide_circle_outline(mouse[0], mouse[1], 7.0, color, width=1.5, steps=28)
    gpu.state.blend_set('NONE')
    gpu.state.line_width_set(1.0)
