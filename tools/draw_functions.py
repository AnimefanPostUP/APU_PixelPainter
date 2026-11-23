"""GPU drawing callbacks and pixel-write helpers."""
import math
import time

import blf
import bpy
import gpu
import gpu_extras.batch
import numpy as np

from ..core.state import declare as declare_state
from ..utils import math_utils
from ..utils import blender_utils
from . import draw_blending


# Draw handler handles: survive a session end, removed explicitly.
declare_state({
    'draw_handler':      None,  # POST_PIXEL handler
    'draw_handler_view': None,  # POST_VIEW handler (3D Viewport surface outline)
    'draw_space':        None,
}, persistent=('draw_handler', 'draw_handler_view', 'draw_space'))


def write_pixels_to_image(img, pixels, color, base_buffer=None,
                          blend='MIX', opacity=1.0, alpha_opacity=1.0, pixel_weights=None,
                          protect_transparent=False):
    """Paint a set of (px, py) coordinates onto img.

    Parameters
    ----------
    img           — bpy.types.Image to modify
    pixels        — iterable of (px, py) integer image coordinates
    color         — RGB or RGBA sequence, brush foreground color
    base_buffer   — optional float32 pixel array to start from (line preview)
    blend         — Blender BrushBlend mode string (default 'MIX')
    opacity       — float [0, 1] brush strength / alpha (default 1.0)
    alpha_opacity — float [0, 1] absolute alpha written to affected pixels
    pixel_weights — optional list of float [0, 1], same length and order as
                    *pixels*, multiplied into opacity per pixel.  Used for
                    falloff on circle/spray brushes.  Requires *pixels* to be
                    an ordered sequence (list), not a set.
    """
    w, h = img.size
    arr  = base_buffer.copy() if base_buffer is not None else np.array(img.pixels, dtype=np.float32)

    # Build parallel lists of flat RGBA base-indices and per-pixel weights
    # for every coordinate that falls inside the image bounds.
    pixels = list(pixels)  # ensure indexable for weight lookup
    flat_indices  = []
    weight_values = []
    for i, (px, py) in enumerate(pixels):
        if 0 <= px < w and 0 <= py < h:
            flat_indices.append((py * w + px) * 4)
            weight_values.append(pixel_weights[i] if pixel_weights is not None else 1.0)

    if not flat_indices:
        return

    flat_idx = np.array(flat_indices, dtype=np.int32)
    weights = np.array(weight_values, dtype=np.float32)

    if protect_transparent:
        alpha_mask = arr[flat_idx + 3] > 1e-6
        if not np.any(alpha_mask):
            return
        flat_idx = flat_idx[alpha_mask]
        weights = weights[alpha_mask]

    src = np.array([color[0], color[1], color[2]], dtype=np.float32)

    # Destination RGB as [N, 3]
    dst = np.stack([arr[flat_idx], arr[flat_idx + 1], arr[flat_idx + 2]], axis=1)



    # Farbmischung: Stärke * Falloff (weight) pro Pixel
    per_pixel_opacity = opacity * weights
    per_pixel_opacity = np.clip(per_pixel_opacity, 0.0, 1.0)
    out = np.clip(draw_blending._apply_blend(dst, src, blend, per_pixel_opacity[:, None]), 0.0, 1.0)

    arr[flat_idx]     = out[:, 0]
    arr[flat_idx + 1] = out[:, 1]
    arr[flat_idx + 2] = out[:, 2]

    # Alpha blend wie gehabt: opacity * falloff (weight)
    alpha_target = float(max(0.0, min(1.0, alpha_opacity)))
    alpha_dst = arr[flat_idx + 3]
    alpha_mix = per_pixel_opacity
    arr[flat_idx + 3] = alpha_dst + (alpha_target - alpha_dst) * alpha_mix

    img.pixels.foreach_set(arr)
    img.update()

    # Tag all editors that display this image for redraw: VIEW_3D (texture
    # preview) and any IMAGE_EDITOR windows other than the one the operator
    # is running in (that one is covered by context.area.tag_redraw()).
    try:
        for screen in bpy.data.screens:
            for area in screen.areas:
                if area.type in {'VIEW_3D', 'IMAGE_EDITOR'}:
                    area.tag_redraw()
    except Exception:
        pass


def set_pixels_alpha(img, pixels, alpha_opacity, opacity=1.0, protect_transparent=False, pixel_weights=None):
    """Blend image alpha toward target alpha for the given pixel coordinates.

    ``pixel_weights`` (parallel to ``pixels``) scales the blend per pixel.
    """
    w, h = img.size
    arr = np.array(img.pixels, dtype=np.float32)
    alpha = float(max(0.0, min(1.0, alpha_opacity)))
    mix = float(max(0.0, min(1.0, opacity)))

    if pixel_weights is None:
        pixel_weights = [1.0] * len(pixels)

    for (px, py), weight in zip(pixels, pixel_weights):
        if 0 <= px < w and 0 <= py < h:
            idx = (py * w + px) * 4
            if protect_transparent and arr[idx + 3] <= 1e-6:
                continue
            curr = arr[idx + 3]
            arr[idx + 3] = curr + (alpha - curr) * mix * weight

    img.pixels.foreach_set(arr)
    img.update()


# ---------------------------------------------------------------------------
# Internal GPU helpers
# ---------------------------------------------------------------------------

def _gpu_draw_lines(vertices, color):
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')
    gpu.state.line_width_set(1.5)
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch  = gpu_extras.batch.batch_for_shader(shader, 'LINES', {"pos": vertices})
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('LESS_EQUAL')


def _edges_to_screen_verts(edges, v2d, w, h, offset_x=0.0, offset_y=0.0):
    """Convert image-space edges to screen coordinates with optional sub-pixel offset."""
    vertices = []
    for (px0, py0), (px1, py1) in edges:
        sx0, sy0 = v2d.view_to_region((px0 + offset_x) / w, (py0 + offset_y) / h)
        sx1, sy1 = v2d.view_to_region((px1 + offset_x) / w, (py1 + offset_y) / h)
        vertices.append((round(sx0), round(sy0)))
        vertices.append((round(sx1), round(sy1)))
    return vertices


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
    _gpu_draw_lines(vertices, (1.0, 1.0, 0.0, 1.0))


def _draw_precision_pixel_guide(context, px, py, color=(1.0, 1.0, 1.0, 0.85)):
    """Draw thin corner brackets for one image pixel.

    The middle 60% of each edge is intentionally omitted so only corner hints
    remain, making the exact pixel bounds easier to read without visual clutter.
    """
    space, img = blender_utils.get_space_img(context)
    if not space or not img:
        return

    w, h = img.size
    if w == 0 or h == 0:
        return

    _, v2d = blender_utils.get_window_region_and_v2d(context.area)
    if not v2d:
        return

    x0 = px / w
    y0 = py / h
    x1 = (px + 1) / w
    y1 = (py + 1) / h

    # Draw only 20% at each side of an edge: 40% visible, 60% omitted.
    t = 0.2
    sx0, sy0 = v2d.view_to_region(x0, y0)
    sx1, sy1 = v2d.view_to_region(x1, y1)
    if sx0 is None or sy0 is None or sx1 is None or sy1 is None:
        return

    # Screen-space rectangle corners (not rounded to keep sub-pixel smoothness).
    left = min(sx0, sx1)
    right = max(sx0, sx1)
    bot = min(sy0, sy1)
    top = max(sy0, sy1)

    dx = right - left
    dy = top - bot
    hx = dx * t
    hy = dy * t

    verts = [
        # Bottom edge corners
        (left, bot), (left + hx, bot),
        (right - hx, bot), (right, bot),
        # Top edge corners
        (left, top), (left + hx, top),
        (right - hx, top), (right, top),
        # Left edge corners
        (left, bot), (left, bot + hy),
        (left, top - hy), (left, top),
        # Right edge corners
        (right, bot), (right, bot + hy),
        (right, top - hy), (right, top),
    ]

    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')
    gpu.state.line_width_set(1.0)
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = gpu_extras.batch.batch_for_shader(shader, 'LINES', {"pos": verts})
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('LESS_EQUAL')


# ---------------------------------------------------------------------------
# TestTool — shaped brush outline
# ---------------------------------------------------------------------------

def draw_test_tool_shape_outline(context, state):
    """Draw the outer-contour outline of the current TestTool brush shape.

    *state* is the module-level _state dict from core.py, passed in to avoid
    a circular import.
    """
    from . import overlays

    overlays.draw_brush_outline(context, state)


# ---------------------------------------------------------------------------
# Sub-mode cursor overlay helpers
# ---------------------------------------------------------------------------

def _draw_filled_half_circle(cx, cy, radius, rgba, top):
    """Draw a filled semicircle (top half when top=True, bottom when False)."""
    steps = 40
    verts = [(cx, cy)]
    if top:
        for i in range(steps + 1):
            a = math.pi * i / steps
            verts.append((cx + radius * math.cos(a), cy + radius * math.sin(a)))
    else:
        for i in range(steps + 1):
            a = math.pi + math.pi * i / steps
            verts.append((cx + radius * math.cos(a), cy + radius * math.sin(a)))
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch  = gpu_extras.batch.batch_for_shader(shader, 'TRI_FAN', {"pos": verts})
    shader.uniform_float("color", rgba)
    batch.draw(shader)


def _draw_filled_arc(cx, cy, radius, rgba, a0, a1, steps=24):
    """Draw a filled circular sector from angle a0 to a1 (radians)."""
    verts = [(cx, cy)]
    for i in range(steps + 1):
        t = i / steps
        a = a0 + (a1 - a0) * t
        verts.append((cx + radius * math.cos(a), cy + radius * math.sin(a)))
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = gpu_extras.batch.batch_for_shader(shader, 'TRI_FAN', {"pos": verts})
    shader.uniform_float("color", rgba)
    batch.draw(shader)


def _draw_filled_circle(cx, cy, radius, rgba):
    """Draw a filled circle."""
    steps = 40
    verts = [(cx, cy)]
    for i in range(steps + 1):
        a = 2 * math.pi * i / steps
        verts.append((cx + radius * math.cos(a), cy + radius * math.sin(a)))
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch  = gpu_extras.batch.batch_for_shader(shader, 'TRI_FAN', {"pos": verts})
    shader.uniform_float("color", rgba)
    batch.draw(shader)


def _draw_modifier_arc_ring(cx, cy, inner_r, outer_r, modifier):
    """Draw a clockwise-filling annulus arc from 12 o'clock based on modifier [0, 1]."""
    if modifier <= 0.0:
        return
    steps = max(2, int(64 * min(modifier, 1.0)))
    sweep = -2.0 * math.pi * min(modifier, 1.0)  # negative = clockwise (Y-up region coords)
    start = math.pi / 2.0  # 12 o'clock

    tris = []
    for i in range(steps):
        a0 = start + sweep * (i / steps)
        a1 = start + sweep * ((i + 1) / steps)
        xi0 = cx + inner_r * math.cos(a0)
        yi0 = cy + inner_r * math.sin(a0)
        xo0 = cx + outer_r * math.cos(a0)
        yo0 = cy + outer_r * math.sin(a0)
        xi1 = cx + inner_r * math.cos(a1)
        yi1 = cy + inner_r * math.sin(a1)
        xo1 = cx + outer_r * math.cos(a1)
        yo1 = cy + outer_r * math.sin(a1)
        tris += [(xi0, yi0), (xo0, yo0), (xo1, yo1),
                 (xi0, yi0), (xo1, yo1), (xi1, yi1)]

    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch  = gpu_extras.batch.batch_for_shader(shader, 'TRIS', {"pos": tris})
    shader.uniform_float("color", (1.0, 1.0, 1.0, 0.85))
    batch.draw(shader)
    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('LESS_EQUAL')


def _draw_ring_sector(cx, cy, inner_r, outer_r, a0, a1, rgba, steps=28):
    """Draw an annulus sector between angles a0..a1 (radians)."""
    if a1 < a0:
        a0, a1 = a1, a0
    steps = max(2, int(steps))
    tris = []
    for i in range(steps):
        t0 = i / steps
        t1 = (i + 1) / steps
        aa = a0 + (a1 - a0) * t0
        ab = a0 + (a1 - a0) * t1

        xi0 = cx + inner_r * math.cos(aa)
        yi0 = cy + inner_r * math.sin(aa)
        xo0 = cx + outer_r * math.cos(aa)
        yo0 = cy + outer_r * math.sin(aa)
        xi1 = cx + inner_r * math.cos(ab)
        yi1 = cy + inner_r * math.sin(ab)
        xo1 = cx + outer_r * math.cos(ab)
        yo1 = cy + outer_r * math.sin(ab)

        tris += [
            (xi0, yi0), (xo0, yo0), (xo1, yo1),
            (xi0, yi0), (xo1, yo1), (xi1, yi1),
        ]

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = gpu_extras.batch.batch_for_shader(shader, 'TRIS', {"pos": tris})
    shader.uniform_float("color", rgba)
    batch.draw(shader)


def _draw_rounded_arc_bar(cx, cy, mid_r, thickness, center_a, span_a, value, bg_rgba, fill_rgba, invert_fill=False):
    """Draw a rounded arc bar with a filled amount from bottom to top."""
    half = span_a * 0.5
    a0 = center_a - half
    a1 = center_a + half
    inner_r = max(1.0, mid_r - thickness * 0.5)
    outer_r = inner_r + thickness

    _draw_ring_sector(cx, cy, inner_r, outer_r, a0, a1, bg_rgba, steps=28)

    t = max(0.0, min(1.0, value))
    if t > 0.0:
        if invert_fill:
            fill_a0 = a1 - (a1 - a0) * t
            _draw_ring_sector(cx, cy, inner_r, outer_r, fill_a0, a1, fill_rgba, steps=28)
        else:
            fill_a1 = a0 + (a1 - a0) * t
            _draw_ring_sector(cx, cy, inner_r, outer_r, a0, fill_a1, fill_rgba, steps=28)

    cap_r = thickness * 0.5
    for aa in (a0, a1):
        mx = cx + mid_r * math.cos(aa)
        my = cy + mid_r * math.sin(aa)
        _draw_filled_circle(mx, my, cap_r, bg_rgba)

    if t > 0.0:
        if invert_fill:
            fill_cap = a1 - (a1 - a0) * t
        else:
            fill_cap = a0 + (a1 - a0) * t
        fx = cx + mid_r * math.cos(fill_cap)
        fy = cy + mid_r * math.sin(fill_cap)
        _draw_filled_circle(fx, fy, cap_r, fill_rgba)
        start_a = a1 if invert_fill else a0
        sx = cx + mid_r * math.cos(start_a)
        sy = cy + mid_r * math.sin(start_a)
        _draw_filled_circle(sx, sy, cap_r, fill_rgba)


def _draw_circle_outline(cx, cy, radius, rgba, width=2.0, steps=60):
    """Draw a thin circle outline."""
    steps = max(8, int(steps))
    verts = []
    for i in range(steps):
        a0 = 2 * math.pi * i / steps
        a1 = 2 * math.pi * (i + 1) / steps
        verts.append((cx + radius * math.cos(a0), cy + radius * math.sin(a0)))
        verts.append((cx + radius * math.cos(a1), cy + radius * math.sin(a1)))
    gpu.state.line_width_set(width)
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch  = gpu_extras.batch.batch_for_shader(shader, 'LINES', {"pos": verts})
    shader.uniform_float("color", rgba)
    batch.draw(shader)


def _draw_checker_circle(cx, cy, radius, cell=5):
    """Draw an opaque checkerboard pattern clipped to a circle."""
    light = (0.78, 0.78, 0.78, 1.0)
    dark  = (0.48, 0.48, 0.48, 1.0)

    x0 = int(cx - radius)
    y0 = int(cy - radius)
    r2 = radius * radius

    light_tris = []
    dark_tris  = []

    xi = 0
    x  = x0
    while x < cx + radius:
        yi = 0
        y  = y0
        while y < cy + radius:
            # Test the farthest corner of the cell from the circle centre so
            # no cell extends outside the circle boundary.
            fcx = x if abs(x - cx) > abs(x + cell - cx) else x + cell
            fcy = y if abs(y - cy) > abs(y + cell - cy) else y + cell
            if (fcx - cx) ** 2 + (fcy - cy) ** 2 <= r2:
                q = [(x, y), (x + cell, y), (x + cell, y + cell), (x, y + cell)]
                tris = [q[0], q[1], q[2], q[0], q[2], q[3]]
                if (xi + yi) % 2 == 0:
                    light_tris.extend(tris)
                else:
                    dark_tris.extend(tris)
            y  += cell
            yi += 1
        x  += cell
        xi += 1

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    for tris, rgba in ((light_tris, light), (dark_tris, dark)):
        if tris:
            batch = gpu_extras.batch.batch_for_shader(shader, 'TRIS', {"pos": tris})
            shader.uniform_float("color", rgba)
            batch.draw(shader)


def _draw_sub_mode_cursor_dot(context, state):
    """Draw a 50px circle at the sub-mode start position.

    COLOR_PICK: top half = current target color; bottom half = original
                color of the active target (primary or secondary).
    STRENGTH:   left arc = strength, right arc = modifier,
                center circle = canvas opacity.
    """
    sub = state.get('sub_mode')
    if not sub:
        return
    rx = state.get('sub_start_region_x')
    ry = state.get('sub_start_region_y')
    if rx is None or ry is None:
        return
    origin_rx = rx
    origin_ry = ry

    radius = 38  # ~75 px diameter (1.5×)

    try:
        brush = context.tool_settings.image_paint.brush
        ups   = context.tool_settings.unified_paint_settings
    except Exception:
        return

    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')

    if sub == 'COLOR_PICK':
        # Attach bubble to fake cursor with a slight upward offset.
        cx = state.get('sub_last_x')
        cy = state.get('sub_last_y')
        if cx is None or cy is None:
            cx, cy = origin_rx, origin_ry
        rx = cx
        ry = cy + 50

        try:
            target = state.get('sub_color_target') or 'PRIMARY'
            curr = (
                tuple(brush.secondary_color[:3]) if (brush and target == 'SECONDARY')
                else (tuple(brush.color[:3]) if brush else (1.0, 1.0, 1.0))
            )
            orig_target = (
                tuple(state.get('sub_orig_color_secondary') or curr)
                if target == 'SECONDARY'
                else tuple(state.get('sub_orig_color') or curr)
            )
        except Exception:
            curr = (1.0, 1.0, 1.0)
            orig_target = (1.0, 1.0, 1.0)

        _draw_filled_half_circle(rx, ry, radius, (*orig_target, 1.0), top=False)
        _draw_filled_half_circle(rx, ry, radius, (*curr, 1.0), top=True)

        # Label above bubble: which target is being edited.
        gpu.state.blend_set('NONE')
        font_id = 0
        label = "Secondary Color" if target == 'SECONDARY' else "Primary Color"
        blf.size(font_id, 12)
        tw, th = blf.dimensions(font_id, label)
        sheet_w = 500.0
        sheet_h = 300.0
        sheet_x0 = origin_rx - sheet_w * 0.5
        sheet_y0 = origin_ry - sheet_h * 0.5
        blf.color(font_id, 1.0, 1.0, 1.0, 0.95)
        blf.position(font_id, sheet_x0 + (sheet_w - tw) * 0.5, sheet_y0 + sheet_h + th + 6, 0)
        blf.draw(font_id, label)
        gpu.state.blend_set('ALPHA')

    elif sub == 'STRENGTH':
        try:
            edit_btn = state.get('sub_edit_button', 'LMB')
            suffix = '_rmb' if edit_btn == 'RMB' else ''
            wm = context.window_manager
            mode = wm.pixel_painter_mode
            # Strength
            use_global_str = getattr(wm, f'pixel_painter_{mode}_use_global_strength{suffix}', True)
            if use_global_str or not hasattr(wm, f'pixel_painter_{mode}_strength{suffix}'):
                curr_strength = getattr(wm, f'pixel_painter_global_strength{suffix}',
                                        ups.strength if ups.use_unified_strength else (brush.strength if brush else 1.0))
            else:
                curr_strength = getattr(wm, f'pixel_painter_{mode}_strength{suffix}', 1.0)
            # Modifier
            use_global_mod = getattr(wm, f'pixel_painter_{mode}_use_global_modifier{suffix}', True)
            if use_global_mod or not hasattr(wm, f'pixel_painter_{mode}_modifier{suffix}'):
                mod = getattr(wm, f'pixel_painter_global_modifier{suffix}', 0.5)
            else:
                mod = getattr(wm, f'pixel_painter_{mode}_modifier{suffix}', 0.5)
            # Alpha
            use_global_alp = getattr(wm, f'pixel_painter_{mode}_use_global_alpha{suffix}', True)
            if use_global_alp or not hasattr(wm, f'pixel_painter_{mode}_alpha{suffix}'):
                curr_alpha = getattr(wm, f'pixel_painter_global_alpha{suffix}', 1.0)
            else:
                curr_alpha = getattr(wm, f'pixel_painter_{mode}_alpha{suffix}', 1.0)
        except Exception:
            curr_strength, mod, curr_alpha = 1.0, 0.5, 1.0

        arc_mid_r = 156.0
        arc_thickness = 8.0
        arc_span = math.radians(50.0)
        hover_target = state.get('sub_strength_hover_target')

        left_bg = (0.26, 0.26, 0.26, 0.55)
        right_bg = (0.26, 0.26, 0.26, 0.55)
        if hover_target == 'STRENGTH':
            left_bg = (0.34, 0.34, 0.34, 0.70)
        elif hover_target == 'MODIFIER':
            right_bg = (0.34, 0.34, 0.34, 0.70)

        left_fill = (0.95, 0.84, 0.22, 0.95)
        right_fill = (0.66, 0.44, 0.92, 0.95)
        _draw_rounded_arc_bar(
            rx,
            ry,
            arc_mid_r,
            arc_thickness,
            math.pi,
            arc_span,
            curr_strength,
            left_bg,
            left_fill,
            invert_fill=True,
        )
        _draw_rounded_arc_bar(rx, ry, arc_mid_r, arc_thickness, 0.0, arc_span, mod, right_bg, right_fill)

        center_bg = (0.14, 0.14, 0.14, 0.72)
        center_fill = (0.2, 0.9, 0.95, 0.92)
        if hover_target == 'ALPHA':
            center_bg = (0.2, 0.2, 0.2, 0.85)
        _draw_filled_circle(rx, ry, 24.0, center_bg)
        _draw_filled_circle(rx, ry, max(2.0, 22.0 * curr_alpha), center_fill)
        _draw_circle_outline(rx, ry, 24.0, (0.0, 0.0, 0.0, 0.85), width=1.4, steps=42)

        _draw_circle_outline(rx, ry, arc_mid_r + arc_thickness * 0.9, (0.0, 0.0, 0.0, 0.35), width=1.2, steps=72)

        # Labels next to each arc and current percentages.
        gpu.state.blend_set('NONE')
        font_id = 0
        blf.size(font_id, 12)
        left_txt = f"Strength  {curr_strength * 100:.0f}%"
        right_txt = f"Modifier  {mod * 100:.0f}%"
        center_txt = f"Alpha  {curr_alpha * 100:.0f}%"

        lw, lh = blf.dimensions(font_id, left_txt)
        rw, rh = blf.dimensions(font_id, right_txt)

        blf.color(font_id, 1.0, 0.95, 0.5, 1.0)
        blf.position(font_id, rx - arc_mid_r - lw - 14, ry - lh * 0.5, 0)
        blf.draw(font_id, left_txt)

        blf.color(font_id, 0.86, 0.76, 0.98, 1.0)
        blf.position(font_id, rx + arc_mid_r + 14, ry - rh * 0.5, 0)
        blf.draw(font_id, right_txt)

        cw, ch = blf.dimensions(font_id, center_txt)
        blf.color(font_id, 0.55, 0.97, 1.0, 1.0)
        blf.position(font_id, rx - cw * 0.5, ry - 24 - ch - 8, 0)
        blf.draw(font_id, center_txt)
        gpu.state.blend_set('ALPHA')

    _draw_circle_outline(rx, ry, radius, (0.0, 0.0, 0.0, 0.85))

    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.line_width_set(1.0)


def _draw_fake_color_pick_cursor(state):
    """Draw a circle-only fake cursor at the tracked sub-mode position."""
    x = state.get('sub_fake_cursor_x')
    y = state.get('sub_fake_cursor_y')
    if x is None or y is None:
        x = state.get('sub_last_x')
        y = state.get('sub_last_y')
    if x is None or y is None:
        return

    su = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')

    _draw_circle_outline(x, y, 6.0, (0.0, 0.0, 0.0, 0.92), width=2.5, steps=24)
    _draw_circle_outline(x, y, 4.5, (1.0, 1.0, 1.0, 0.95), width=1.4, steps=24)

    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.line_width_set(1.0)


# ---------------------------------------------------------------------------
# Sub-mode HUD overlay
# ---------------------------------------------------------------------------

def draw_sub_mode_overlay(context, state):
    """Draw a text HUD at the bottom of the editor when a sub-mode is active,
    plus the split-circle cursor dot at the start position."""
    sub = state.get('sub_mode')
    if not sub:
        return

    if sub == 'COLOR_PICK':
        from . import draw_menu_colorpick

        draw_menu_colorpick.draw_color_pick_sheet_overlay(state)
        rx = state.get('sub_start_region_x')
        ry = state.get('sub_start_region_y')
        if rx is not None and ry is not None:
            h = state.get('sub_color_h') or 0.0
            s = state.get('sub_color_s') or 0.0
            v = state.get('sub_color_v') or 0.0
            draw_menu_colorpick.draw_color_pick_axes(rx, ry, h, s, v, 0.0)

    _draw_sub_mode_cursor_dot(context, state)
    if sub in {'COLOR_PICK', 'STRENGTH'}:
        _draw_fake_color_pick_cursor(state)

    area = context.area
    if not area:
        return
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    if not region:
        return

    try:
        ups   = context.tool_settings.unified_paint_settings
        brush = context.tool_settings.image_paint.brush

        if sub == 'STRENGTH':
            edit_btn = state.get('sub_edit_button', 'LMB')
            try:
                wm = context.window_manager
                mode = wm.pixel_painter_mode
                suffix = '_rmb' if edit_btn == 'RMB' else ''
                # Strength
                use_global_str = getattr(wm, f'pixel_painter_{mode}_use_global_strength{suffix}', True)
                global_str_key = f'pixel_painter_global_strength{suffix}'
                if use_global_str or not hasattr(wm, f'pixel_painter_{mode}_strength{suffix}'):
                    val = getattr(wm, global_str_key, ups.strength if ups.use_unified_strength else (brush.strength if brush else 0.0))
                else:
                    val = getattr(wm, f'pixel_painter_{mode}_strength{suffix}', 1.0)
                # Modifier
                use_global_mod = getattr(wm, f'pixel_painter_{mode}_use_global_modifier{suffix}', True)
                global_mod_key = f'pixel_painter_global_modifier{suffix}'
                if use_global_mod or not hasattr(wm, f'pixel_painter_{mode}_modifier{suffix}'):
                    mod = getattr(wm, global_mod_key, 0.5)
                else:
                    mod = getattr(wm, f'pixel_painter_{mode}_modifier{suffix}', 0.5)
                # Alpha
                use_global_alp = getattr(wm, f'pixel_painter_{mode}_use_global_alpha{suffix}', True)
                global_alp_key = f'pixel_painter_global_alpha{suffix}'
                if use_global_alp or not hasattr(wm, f'pixel_painter_{mode}_alpha{suffix}'):
                    alpha = getattr(wm, global_alp_key, 1.0)
                else:
                    alpha = getattr(wm, f'pixel_painter_{mode}_alpha{suffix}', 1.0)
            except Exception:
                val, mod, alpha = 1.0, 0.5, 1.0
            line1 = f"[{edit_btn}]  Strength  {val * 100:.1f}%    Alpha  {alpha * 100:.1f}%    Modifier  {mod * 100:.1f}%"
            line2 = "Left arc Strength + right arc Modifier: mouse height   Center Alpha: scroll   E toggle LMB/RMB   LMB apply   RMB cancel"

        elif sub == 'COLOR_PICK':
            target = state.get('sub_color_target') or 'PRIMARY'
            if brush and target == 'SECONDARY':
                r, g, b = brush.secondary_color[:3]
            else:
                r, g, b = (brush.color if brush else (0, 0, 0))[:3]
            h, s, v = colorsys.rgb_to_hsv(r, g, b)
            line1 = f"Target {target}   H {h:.3f}   S {s:.3f}   V {v:.3f}"
            line2 = "Mouse X Hue   Mouse Y Value   Scroll Sat   E toggle target   LMB apply   RMB cancel"
        else:
            return
    except Exception:
        return

    font_id = 0
    blf.size(font_id, 17)

    # Background pill
    pad_x, pad_y = 14, 8
    w1, h1 = blf.dimensions(font_id, line1)
    w2, h2 = blf.dimensions(font_id, line2)
    box_w  = max(w1, w2) + pad_x * 2
    box_h  = h1 + h2 + pad_y * 3
    x0, y0 = 20, 20

    gpu.state.blend_set('ALPHA')
    verts  = [(x0, y0), (x0 + box_w, y0),
              (x0 + box_w, y0 + box_h), (x0, y0 + box_h)]
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch  = gpu_extras.batch.batch_for_shader(shader, 'TRI_FAN', {"pos": verts})
    shader.uniform_float("color", (0.1, 0.1, 0.1, 0.75))
    batch.draw(shader)
    gpu.state.blend_set('NONE')

    blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
    blf.position(font_id, x0 + pad_x, y0 + pad_y, 0)
    blf.draw(font_id, line2)
    blf.color(font_id, 1.0, 0.85, 0.2, 1.0)
    blf.position(font_id, x0 + pad_x, y0 + pad_y + h2 + pad_y, 0)
    blf.draw(font_id, line1)


# ---------------------------------------------------------------------------
# Hold-Ctrl eyedropper overlay
# ---------------------------------------------------------------------------

def draw_ctrl_pick_overlay(context, state):
    """Draw the split circle near the cursor while the hold-Ctrl eyedropper is active.

    Bottom half = primary (left) + secondary (right), top half = image color
    under cursor.
    Positioned above the cursor so it doesn't obscure the sampled pixel.
    """
    if not state.get('ctrl_pick_active'):
        return
    hovered = state.get('ctrl_hovered_color')
    if hovered is None:
        return
    rx = state.get('ctrl_region_x')
    ry = state.get('ctrl_region_y')
    if rx is None or ry is None:
        return

    try:
        brush = context.tool_settings.image_paint.brush
        prim = tuple(brush.color[:3]) if brush else (1.0, 1.0, 1.0)
        sec = tuple(brush.secondary_color[:3]) if brush else (0.0, 0.0, 0.0)
    except Exception:
        prim = (1.0, 1.0, 1.0)
        sec = (0.0, 0.0, 0.0)

    cx = rx
    cy = ry + 50
    radius = 38

    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')

    _draw_filled_arc(cx, cy, radius, (*prim, 1.0), math.pi, math.pi * 1.5)
    _draw_filled_arc(cx, cy, radius, (*sec, 1.0), math.pi * 1.5, math.tau)
    _draw_filled_half_circle(cx, cy, radius, (*hovered, 1.0), top=True)

    px = state.get('current_cx')
    py = state.get('current_cy')
    if px is not None and py is not None:
        _draw_precision_pixel_guide(context, px, py, color=(1.0, 1.0, 1.0, 0.95))

    _draw_circle_outline(cx, cy, radius, (0.0, 0.0, 0.0, 0.85))

    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.line_width_set(1.0)


def draw_view3d_offmesh_cursor(context, state):
    """3D Viewport cursor while the mouse is off the mesh: a dim ring."""
    mouse = state.get('mouse_region')
    if mouse is None:
        return
    from .catalog import TOOLS
    try:
        color = TOOLS.get(context.window_manager.pixel_painter_mode).outline_color
    except Exception:
        color = (1.0, 1.0, 0.0, 0.9)
    if state.get('current_cx') is not None:
        return  # on the mesh: the surface outline (overlays_view3d) is drawn instead
    rgba = (color[0], color[1], color[2], 0.3)
    gpu.state.blend_set('ALPHA')
    _draw_circle_outline(mouse[0], mouse[1], 10.0, (0.0, 0.0, 0.0, rgba[3] * 0.8), width=3.0, steps=32)
    _draw_circle_outline(mouse[0], mouse[1], 10.0, rgba, width=1.5, steps=32)
    gpu.state.blend_set('NONE')
    gpu.state.line_width_set(1.0)


def draw_test_corner_label(context, text="test"):
    """Draw a small text label in the top-left corner of the active editor region."""
    area = context.area
    if not area:
        return
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    if not region:
        return

    font_id = 0
    blf.size(font_id, 18)
    text_width, text_height = blf.dimensions(font_id, text)
    pos_x = 20
    pos_y = max(20, region.height - text_height - 20)

    gpu.state.blend_set('ALPHA')
    blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
    blf.position(font_id, pos_x, pos_y, 0)
    blf.draw(font_id, text)
    gpu.state.blend_set('NONE')



# ---------------------------------------------------------------------------
# Draw handler management
# ---------------------------------------------------------------------------

def register_draw_handler(state, space, context, callback, view_callback=None):
    """Register a POST_PIXEL draw callback (and optionally a POST_VIEW one) in *state*."""
    state['draw_handler'] = space.draw_handler_add(callback, (context,), 'WINDOW', 'POST_PIXEL')
    state['draw_handler_view'] = (
        space.draw_handler_add(view_callback, (context,), 'WINDOW', 'POST_VIEW')
        if view_callback is not None else None)
    state['draw_space']   = space


def remove_draw_handler(state):
    """Remove the registered draw handler stored in *state*, if any."""
    space   = state.get('draw_space')
    for key in ('draw_handler', 'draw_handler_view'):
        handler = state.get(key)
        if handler is not None and space is not None:
            try:
                space.draw_handler_remove(handler, 'WINDOW')
            except Exception:
                pass
        state[key] = None
    state['draw_space']   = None
