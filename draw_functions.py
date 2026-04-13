"""GPU drawing callbacks and pixel-write helpers."""
import colorsys
import math
import time

import blf
import gpu
import gpu_extras.batch
import numpy as np

from . import math_utils
from . import blender_utils


# ---------------------------------------------------------------------------
# Pixel writing with blend mode support
# ---------------------------------------------------------------------------

def _apply_blend(dst, src, blend, opacity):
    """Apply a blend mode between destination [N,3] and source [3] arrays.

    dst    — float32 array of shape [N, 3] (existing pixel RGB values)
    src    — float32 array of shape [3]    (brush color RGB)
    blend  — Blender BrushBlend identifier string
    opacity — float [0, 1], controls mix strength

    Returns blended float32 [N, 3]. Caller is responsible for clipping.
    """
    # Convenience: lerp(dst, x, opacity) = dst + (x - dst) * opacity
    if blend == 'MIX':
        out = dst + (src - dst) * opacity

    elif blend == 'ADD':
        out = dst + src * opacity

    elif blend == 'SUB':
        out = dst - src * opacity

    elif blend == 'MUL':
        # Lerp between dst and (dst * src) — darkens toward zero
        out = dst + (dst * src - dst) * opacity

    elif blend == 'DARKEN':
        out = dst + (np.minimum(dst, src) - dst) * opacity

    elif blend == 'LIGHTEN':
        out = dst + (np.maximum(dst, src) - dst) * opacity

    elif blend == 'SCREEN':
        screen = 1.0 - (1.0 - dst) * (1.0 - src)
        out = dst + (screen - dst) * opacity

    elif blend == 'OVERLAY':
        # Standard Overlay: 2*dst*src when dst<0.5, else 1-2*(1-dst)*(1-src)
        overlay = np.where(dst < 0.5,
                           2.0 * dst * src,
                           1.0 - 2.0 * (1.0 - dst) * (1.0 - src))
        out = dst + (overlay - dst) * opacity

    elif blend == 'HARDLIGHT':
        # Hard Light is Overlay with src/dst roles swapped
        hl = np.where(src < 0.5,
                      2.0 * dst * src,
                      1.0 - 2.0 * (1.0 - dst) * (1.0 - src))
        out = dst + (hl - dst) * opacity

    elif blend == 'SOFTLIGHT':
        # Pegtop / Photoshop soft light formula
        sl = (1.0 - 2.0 * src) * dst ** 2 + 2.0 * src * dst
        out = dst + (sl - dst) * opacity

    elif blend == 'DIFFERENCE':
        out = dst + (np.abs(dst - src) - dst) * opacity

    elif blend == 'EXCLUSION':
        excl = dst + src - 2.0 * dst * src
        out = dst + (excl - dst) * opacity

    elif blend == 'COLORDODGE':
        # Protect against division by zero when src approaches 1
        dodge = np.where(src >= 1.0, 1.0, dst / (1.0 - src + 1e-6))
        out = dst + (dodge - dst) * opacity

    elif blend == 'COLORBURN':
        # Protect against division by zero when src approaches 0
        burn = np.where(src <= 0.0, 0.0, 1.0 - (1.0 - dst) / (src + 1e-6))
        out = dst + (burn - dst) * opacity

    elif blend == 'COLOR':
        # Approximate "Color" by taking source hue/saturation and destination value.
        sh, ss, _ = colorsys.rgb_to_hsv(float(src[0]), float(src[1]), float(src[2]))
        color_rgb = np.empty_like(dst)
        for i in range(dst.shape[0]):
            _, _, dv = colorsys.rgb_to_hsv(float(dst[i, 0]), float(dst[i, 1]), float(dst[i, 2]))
            color_rgb[i] = colorsys.hsv_to_rgb(sh, ss, dv)
        out = dst + (color_rgb - dst) * opacity

    elif blend == 'HUE':
        sh, _, _ = colorsys.rgb_to_hsv(float(src[0]), float(src[1]), float(src[2]))
        hue_rgb = np.empty_like(dst)
        for i in range(dst.shape[0]):
            _, ds, dv = colorsys.rgb_to_hsv(float(dst[i, 0]), float(dst[i, 1]), float(dst[i, 2]))
            hue_rgb[i] = colorsys.hsv_to_rgb(sh, ds, dv)
        out = dst + (hue_rgb - dst) * opacity

    elif blend == 'SATURATION':
        _, ss, _ = colorsys.rgb_to_hsv(float(src[0]), float(src[1]), float(src[2]))
        sat_rgb = np.empty_like(dst)
        for i in range(dst.shape[0]):
            dh, _, dv = colorsys.rgb_to_hsv(float(dst[i, 0]), float(dst[i, 1]), float(dst[i, 2]))
            sat_rgb[i] = colorsys.hsv_to_rgb(dh, ss, dv)
        out = dst + (sat_rgb - dst) * opacity

    elif blend == 'VALUE':
        _, _, sv = colorsys.rgb_to_hsv(float(src[0]), float(src[1]), float(src[2]))
        val_rgb = np.empty_like(dst)
        for i in range(dst.shape[0]):
            dh, ds, _ = colorsys.rgb_to_hsv(float(dst[i, 0]), float(dst[i, 1]), float(dst[i, 2]))
            val_rgb[i] = colorsys.hsv_to_rgb(dh, ds, sv)
        out = dst + (val_rgb - dst) * opacity

    elif blend == 'LUMINOSITY':
        # HSV approximation: use source value (brightness) while preserving destination hue/saturation.
        _, _, sv = colorsys.rgb_to_hsv(float(src[0]), float(src[1]), float(src[2]))
        lum_rgb = np.empty_like(dst)
        for i in range(dst.shape[0]):
            dh, ds, _ = colorsys.rgb_to_hsv(float(dst[i, 0]), float(dst[i, 1]), float(dst[i, 2]))
            lum_rgb[i] = colorsys.hsv_to_rgb(dh, ds, sv)
        out = dst + (lum_rgb - dst) * opacity

    else:
        # Unknown mode — fall back to plain mix
        out = dst + (src - dst) * opacity

    return out


def write_pixels_to_image(img, pixels, color, base_buffer=None,
                          blend='MIX', opacity=1.0, pixel_weights=None):
    """Paint a set of (px, py) coordinates onto img.

    Parameters
    ----------
    img           — bpy.types.Image to modify
    pixels        — iterable of (px, py) integer image coordinates
    color         — RGB or RGBA sequence, brush foreground color
    base_buffer   — optional float32 pixel array to start from (line preview)
    blend         — Blender BrushBlend mode string (default 'MIX')
    opacity       — float [0, 1] brush strength / alpha (default 1.0)
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

    flat_idx = np.array(flat_indices,  dtype=np.int32)
    src      = np.array([color[0], color[1], color[2]], dtype=np.float32)

    # Destination RGB as [N, 3]
    dst = np.stack([arr[flat_idx], arr[flat_idx + 1], arr[flat_idx + 2]], axis=1)

    # Effective per-pixel opacity: scalar * weight → [N, 1] for broadcasting
    eff_opacity = opacity * np.array(weight_values, dtype=np.float32)[:, np.newaxis]

    out = np.clip(_apply_blend(dst, src, blend, eff_opacity), 0.0, 1.0)

    arr[flat_idx]     = out[:, 0]
    arr[flat_idx + 1] = out[:, 1]
    arr[flat_idx + 2] = out[:, 2]
    arr[flat_idx + 3] = 1.0  # always fully opaque image alpha

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
    if state.get('sub_mode') or state.get('shift_pick_active'):
        return

    cx = state['current_cx']
    cy = state['current_cy']
    if cx is None or cy is None:
        state['outline_display_cx'] = None
        state['outline_display_cy'] = None
        state['outline_from_cx'] = None
        state['outline_from_cy'] = None
        state['outline_to_cx'] = None
        state['outline_to_cy'] = None
        return

    if state.get('outline_immediate'):
        cx = float(cx)
        cy = float(cy)
        state['outline_display_cx'] = cx
        state['outline_display_cy'] = cy
        state['outline_from_cx'] = cx
        state['outline_from_cy'] = cy
        state['outline_to_cx'] = cx
        state['outline_to_cy'] = cy
        state['outline_anim_start'] = time.perf_counter()
    else:
        now = time.perf_counter()
        display_cx = state.get('outline_display_cx')
        display_cy = state.get('outline_display_cy')
        target_cx = state.get('outline_to_cx')
        target_cy = state.get('outline_to_cy')

        if display_cx is None or display_cy is None:
            display_cx = float(cx)
            display_cy = float(cy)
            state['outline_display_cx'] = display_cx
            state['outline_display_cy'] = display_cy
            state['outline_from_cx'] = display_cx
            state['outline_from_cy'] = display_cy
            state['outline_to_cx'] = float(cx)
            state['outline_to_cy'] = float(cy)
            state['outline_anim_start'] = now
        elif target_cx != float(cx) or target_cy != float(cy):
            nx = float(cx)
            ny = float(cy)
            dx = nx - display_cx
            dy = ny - display_cy
            if (dx * dx + dy * dy) < 4.0:
                state['outline_from_cx'] = display_cx
                state['outline_from_cy'] = display_cy
                state['outline_to_cx'] = nx
                state['outline_to_cy'] = ny
                state['outline_anim_start'] = now
            else:
                state['outline_from_cx'] = nx
                state['outline_from_cy'] = ny
                state['outline_to_cx'] = nx
                state['outline_to_cy'] = ny
                state['outline_display_cx'] = nx
                state['outline_display_cy'] = ny
                state['outline_anim_start'] = now

        from_cx = state.get('outline_from_cx', float(cx))
        from_cy = state.get('outline_from_cy', float(cy))
        to_cx = state.get('outline_to_cx', float(cx))
        to_cy = state.get('outline_to_cy', float(cy))
        t = min(1.0, max(0.0, (now - state.get('outline_anim_start', now)) / 0.018))
        te = t * t * (3.0 - 2.0 * t)
        cx = from_cx + (to_cx - from_cx) * te
        cy = from_cy + (to_cy - from_cy) * te
        state['outline_display_cx'] = cx
        state['outline_display_cy'] = cy

    space = context.space_data
    if not space or not space.image:
        return

    wm     = context.window_manager
    radius = blender_utils.get_brush_image_radius(context)
    mode   = wm.pixel_painter_mode
    w, h   = space.image.size
    if w == 0 or h == 0:
        return

    area = context.area
    if not area:
        return
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    if not region:
        return
    v2d = region.view2d

    outline_color = {
        'SPRAY':  (1.0, 0.55, 0.0,  0.9),  # orange
        'SMEAR':  (1.0, 0.2,  0.2,  0.9),  # red
        'SMOOTH': (0.7, 0.3,  1.0,  0.9),  # purple
    }.get(mode, (1.0, 1.0, 0.0, 0.9))      # default yellow

    def _outline_pixels_at(ix, iy):
        if (mode == 'LINE' or state.get('ctrl_line_active')) and state['start_position'] is not None:
            shape = state['last_shape']
            tip_shape = 'CIRCLE' if shape == 'SPRAY' else shape
            x0, y0 = state['start_position']
            pixels = set()
            for (lx, ly) in math_utils.get_line_pixels(x0, y0, ix, iy):
                pixels |= math_utils.get_pixels_in_shape(lx, ly, radius, tip_shape)
            return pixels

        outline_mode = 'CIRCLE' if mode == 'SPRAY' else mode
        return math_utils.get_pixels_in_shape(ix, iy, radius, outline_mode)

    if state.get('outline_immediate'):
        base_ix = round(cx)
        base_iy = round(cy)
        frac_x = 0.0
        frac_y = 0.0
    else:
        base_ix = math.floor(cx)
        base_iy = math.floor(cy)
        frac_x = cx - base_ix
        frac_y = cy - base_iy

    pixels = _outline_pixels_at(base_ix, base_iy)
    edges = math_utils.get_outline_edges(pixels)
    if not edges:
        return
    vertices = _edges_to_screen_verts(edges, v2d, w, h, offset_x=frac_x, offset_y=frac_y)
    _gpu_draw_lines(vertices, outline_color)

    # Precision guide is anchored to the true edited pixel, not the smoothed
    # display position, so users can always see exact pixel start/end bounds.
    _draw_precision_pixel_guide(context, state['current_cx'], state['current_cy'])


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


def _draw_color_pick_axes(rx, ry, h, s, v, radius):
    """Draw VALUE (left), SATURATION (right), and HUE (bottom) bars."""
    del radius  # kept for call compatibility

    # Must stay aligned with _draw_color_pick_sheet_overlay dimensions.
    sheet_w = 500.0
    sheet_h = 300.0
    side_gap = 6.0
    bar_w = 12.0
    hue_h = 12.0
    font_id = 0

    sheet_x0 = rx - sheet_w * 0.5
    sheet_y0 = ry - sheet_h * 0.5

    # Left: Value (brightness)
    val_x0 = sheet_x0 - side_gap - bar_w
    val_y0 = sheet_y0
    val_h = sheet_h

    # Right: Saturation
    sat_x0 = sheet_x0 + sheet_w + side_gap
    sat_y0 = sheet_y0
    sat_h = sheet_h

    # Bottom: Hue
    hue_x0 = sheet_x0
    hue_y0 = sheet_y0 - side_gap - hue_h
    hue_w = sheet_w

    su = gpu.shader.from_builtin('UNIFORM_COLOR')
    sc = gpu.shader.from_builtin('SMOOTH_COLOR')

    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')

    # ---- Left VALUE bar: black -> hsv(h, s, 1) ----
    steps = 20
    sh = val_h / steps
    verts_v, colors_v = [], []
    for i in range(steps):
        v0 = i / steps
        v1 = (i + 1) / steps
        r0, g0, b0 = colorsys.hsv_to_rgb(h, s, v0)
        r1, g1, b1 = colorsys.hsv_to_rgb(h, s, v1)
        y0_ = val_y0 + i * sh
        y1_ = y0_ + sh
        verts_v += [
            (val_x0, y0_), (val_x0 + bar_w, y0_), (val_x0 + bar_w, y1_),
            (val_x0, y0_), (val_x0 + bar_w, y1_), (val_x0, y1_),
        ]
        c0 = (r0, g0, b0, 1.0)
        c1 = (r1, g1, b1, 1.0)
        colors_v += [c0, c0, c1, c0, c1, c1]

    gpu_extras.batch.batch_for_shader(sc, 'TRIS', {"pos": verts_v, "color": colors_v}).draw(sc)

    cur_vy = val_y0 + v * val_h
    for lw, rgba in [(3.0, (0, 0, 0, 1)), (1.5, (1, 1, 1, 1))]:
        gpu.state.line_width_set(lw)
        su.uniform_float("color", rgba)
        gpu_extras.batch.batch_for_shader(su, 'LINES', {"pos": [
            (val_x0 - 4, cur_vy), (val_x0 + bar_w + 4, cur_vy)
        ]}).draw(su)

    # Border: value bar
    gpu.state.line_width_set(1.0)
    su.uniform_float("color", (0.0, 0.0, 0.0, 0.6))
    gpu_extras.batch.batch_for_shader(su, 'LINES', {"pos": [
        (val_x0, val_y0), (val_x0 + bar_w, val_y0),
        (val_x0 + bar_w, val_y0), (val_x0 + bar_w, val_y0 + val_h),
        (val_x0 + bar_w, val_y0 + val_h), (val_x0, val_y0 + val_h),
        (val_x0, val_y0 + val_h), (val_x0, val_y0),
    ]}).draw(su)

    # ---- Right SATURATION bar: hsv(h,0,v) -> hsv(h,1,v) ----
    verts_s, colors_s = [], []
    for i in range(steps):
        s0 = i / steps
        s1 = (i + 1) / steps
        r0, g0, b0 = colorsys.hsv_to_rgb(h, s0, v)
        r1, g1, b1 = colorsys.hsv_to_rgb(h, s1, v)
        y0_ = sat_y0 + i * sh
        y1_ = y0_ + sh
        verts_s += [
            (sat_x0, y0_), (sat_x0 + bar_w, y0_), (sat_x0 + bar_w, y1_),
            (sat_x0, y0_), (sat_x0 + bar_w, y1_), (sat_x0, y1_),
        ]
        c0 = (r0, g0, b0, 1.0)
        c1 = (r1, g1, b1, 1.0)
        colors_s += [c0, c0, c1, c0, c1, c1]

    gpu_extras.batch.batch_for_shader(sc, 'TRIS', {"pos": verts_s, "color": colors_s}).draw(sc)

    cur_sy = sat_y0 + s * sat_h
    for lw, rgba in [(3.0, (0, 0, 0, 1)), (1.5, (1, 1, 1, 1))]:
        gpu.state.line_width_set(lw)
        su.uniform_float("color", rgba)
        gpu_extras.batch.batch_for_shader(su, 'LINES', {"pos": [
            (sat_x0 - 4, cur_sy), (sat_x0 + bar_w + 4, cur_sy)
        ]}).draw(su)

    # Border: saturation bar
    gpu.state.line_width_set(1.0)
    su.uniform_float("color", (0.0, 0.0, 0.0, 0.6))
    gpu_extras.batch.batch_for_shader(su, 'LINES', {"pos": [
        (sat_x0, sat_y0), (sat_x0 + bar_w, sat_y0),
        (sat_x0 + bar_w, sat_y0), (sat_x0 + bar_w, sat_y0 + sat_h),
        (sat_x0 + bar_w, sat_y0 + sat_h), (sat_x0, sat_y0 + sat_h),
        (sat_x0, sat_y0 + sat_h), (sat_x0, sat_y0),
    ]}).draw(su)

    # ---- Bottom HUE bar: rainbow horizontal ----
    hsteps = 36
    sw = hue_w / hsteps
    verts_h, colors_h = [], []
    for i in range(hsteps):
        h0 = i / hsteps
        h1 = (i + 1) / hsteps
        r0, g0, b0 = colorsys.hsv_to_rgb(h0, 1.0, 1.0)
        r1, g1, b1 = colorsys.hsv_to_rgb(h1, 1.0, 1.0)
        x0_ = hue_x0 + i * sw
        x1_ = x0_ + sw
        verts_h += [
            (x0_, hue_y0), (x1_, hue_y0), (x1_, hue_y0 + hue_h),
            (x0_, hue_y0), (x1_, hue_y0 + hue_h), (x0_, hue_y0 + hue_h),
        ]
        c0 = (r0, g0, b0, 1.0)
        c1 = (r1, g1, b1, 1.0)
        colors_h += [c0, c1, c1, c0, c1, c0]

    gpu_extras.batch.batch_for_shader(sc, 'TRIS', {"pos": verts_h, "color": colors_h}).draw(sc)

    cur_hx = hue_x0 + h * hue_w
    for lw, rgba in [(3.0, (0, 0, 0, 1)), (1.5, (1, 1, 1, 1))]:
        gpu.state.line_width_set(lw)
        su.uniform_float("color", rgba)
        gpu_extras.batch.batch_for_shader(su, 'LINES', {"pos": [
            (cur_hx, hue_y0 - 4), (cur_hx, hue_y0 + hue_h + 4)
        ]}).draw(su)

    # Border: hue bar
    gpu.state.line_width_set(1.0)
    su.uniform_float("color", (0.0, 0.0, 0.0, 0.6))
    gpu_extras.batch.batch_for_shader(su, 'LINES', {"pos": [
        (hue_x0, hue_y0), (hue_x0 + hue_w, hue_y0),
        (hue_x0 + hue_w, hue_y0), (hue_x0 + hue_w, hue_y0 + hue_h),
        (hue_x0 + hue_w, hue_y0 + hue_h), (hue_x0, hue_y0 + hue_h),
        (hue_x0, hue_y0 + hue_h), (hue_x0, hue_y0),
    ]}).draw(su)

    # Labels
    blf.size(font_id, 11)
    val_str = f"Val  {v * 100:.0f}%"
    sat_str = f"Sat  {s * 100:.0f}%"
    hue_str = "Hue"
    _, lh = blf.dimensions(font_id, val_str)
    blf.color(font_id, 0.9, 0.9, 0.9, 0.85)
    blf.position(font_id, val_x0 - 8, val_y0 + val_h + lh + 4, 0)
    blf.draw(font_id, val_str)
    blf.position(font_id, sat_x0 - 8, sat_y0 + sat_h + lh + 4, 0)
    blf.draw(font_id, sat_str)
    blf.position(font_id, hue_x0, hue_y0 - lh - 4, 0)
    blf.draw(font_id, hue_str)

    # Value % ticks near left and saturation % ticks near right
    blf.size(font_id, 10)
    for pct in range(0, 101, 20):
        y_pos = val_y0 + (pct / 100) * val_h
        _, lh_ = blf.dimensions(font_id, "0%")
        blf.color(font_id, 1.0, 1.0, 1.0, 0.9)
        blf.position(font_id, val_x0 - 28, y_pos - lh_ * 0.5, 0)
        blf.draw(font_id, f"{pct}%")

        y_pos_s = sat_y0 + (pct / 100) * sat_h
        blf.position(font_id, sat_x0 + bar_w + 4, y_pos_s - lh_ * 0.5, 0)
        blf.draw(font_id, f"{pct}%")

    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.line_width_set(1.0)


def _draw_color_pick_sheet_overlay(state):
    """Draw a generated HSV sheet overlay centered at color-pick origin.

    The center position is treated as (H,V)=(0.5, 0.5), matching the modal
    mapping in core.py, so color under each position corresponds to that
    position's effective picked color.
    """
    rx = state.get('sub_start_region_x')
    ry = state.get('sub_start_region_y')
    if rx is None or ry is None:
        return

    s = state.get('sub_color_s')
    if s is None:
        s = 1.0

    # Must match COLOR_PICK mapping constants used in core.py.
    w = 500.0
    h = 300.0
    x0 = rx - w * 0.5
    y0 = ry - h * 0.5

    # Coarse grid for performance while keeping smooth-enough transitions.
    cols = 56
    rows = 34
    dx = w / cols
    dy = h / rows

    sc = gpu.shader.from_builtin('SMOOTH_COLOR')
    su = gpu.shader.from_builtin('UNIFORM_COLOR')

    verts = []
    cols_rgba = []

    def hv_at(px, py):
        h_val = (0.5 + (px - rx) / w) % 1.0
        v_val = max(0.0, min(1.0, 0.5 + (py - ry) / h))
        r, g, b = colorsys.hsv_to_rgb(h_val, s, v_val)
        return (r, g, b, 1.0)

    for yi in range(rows):
        y_a = y0 + yi * dy
        y_b = y_a + dy
        for xi in range(cols):
            x_a = x0 + xi * dx
            x_b = x_a + dx
            c00 = hv_at(x_a, y_a)
            c10 = hv_at(x_b, y_a)
            c11 = hv_at(x_b, y_b)
            c01 = hv_at(x_a, y_b)

            verts += [
                (x_a, y_a), (x_b, y_a), (x_b, y_b),
                (x_a, y_a), (x_b, y_b), (x_a, y_b),
            ]
            cols_rgba += [c00, c10, c11, c00, c11, c01]

    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')
    gpu_extras.batch.batch_for_shader(sc, 'TRIS', {"pos": verts, "color": cols_rgba}).draw(sc)

    # Border
    gpu.state.line_width_set(1.0)
    su.uniform_float("color", (0.0, 0.0, 0.0, 0.75))
    gpu_extras.batch.batch_for_shader(su, 'LINES', {"pos": [
        (x0, y0), (x0 + w, y0),
        (x0 + w, y0), (x0 + w, y0 + h),
        (x0 + w, y0 + h), (x0, y0 + h),
        (x0, y0 + h), (x0, y0),
    ]}).draw(su)

    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.line_width_set(1.0)


def _draw_sub_mode_cursor_dot(context, state):
    """Draw a 50px circle at the sub-mode start position.

    COLOR_PICK: top half = current target color; bottom half = original
                color of the active target (primary or secondary).
    OPACITY:    checker background circle showing brush color at current opacity,
                with percentage label to the right.
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

    elif sub == 'OPACITY':
        try:
            curr_op = ups.strength if ups.use_unified_strength else (brush.strength if brush else 1.0)
            color   = tuple(brush.color[:3]) if brush else (1.0, 1.0, 1.0)
        except Exception:
            curr_op, color = 1.0, (1.0, 1.0, 1.0)

        _draw_checker_circle(rx, ry, radius)
        _draw_filled_circle(rx, ry, radius, (*color, curr_op))

        # Modifier arc ring around the opacity circle
        try:
            mod = context.window_manager.pixel_painter_modifier
        except Exception:
            mod = 0.5
        _draw_modifier_arc_ring(rx, ry, radius + 5.0, radius + 10.0, mod)

        # Percentage label to the right of the circle
        gpu.state.blend_set('NONE')
        font_id = 0
        blf.size(font_id, 13)
        lx = rx + radius + 14
        for label, val in [("Opacity", curr_op), ("Modifier", mod)]:
            text = f"{label}  {val * 100:.1f}%"
            _, lh = blf.dimensions(font_id, text)
            blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
            blf.position(font_id, lx, ry + (lh + 3 if label == "Opacity" else -(lh + 3)), 0)
            blf.draw(font_id, text)
        gpu.state.blend_set('ALPHA')

    _draw_circle_outline(rx, ry, radius, (0.0, 0.0, 0.0, 0.85))

    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.line_width_set(1.0)


def _draw_fake_color_pick_cursor(state):
    """Draw a circle-only fake cursor at the tracked COLOR_PICK position."""
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
        _draw_color_pick_sheet_overlay(state)
        rx = state.get('sub_start_region_x')
        ry = state.get('sub_start_region_y')
        if rx is not None and ry is not None:
            h = state.get('sub_color_h') or 0.0
            s = state.get('sub_color_s') or 0.0
            v = state.get('sub_color_v') or 0.0
            _draw_color_pick_axes(rx, ry, h, s, v, 0.0)

    _draw_sub_mode_cursor_dot(context, state)
    if sub == 'COLOR_PICK':
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

        if sub == 'OPACITY':
            val = ups.strength if ups.use_unified_strength else (brush.strength if brush else 0.0)
            try:
                mod = context.window_manager.pixel_painter_modifier
            except Exception:
                mod = 0.5
            line1 = f"Opacity  {val * 100:.1f}%    Modifier  {mod * 100:.1f}%"
            line2 = "Mouse Opacity   Scroll Modifier   Shift slow   LMB apply   RMB cancel"

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
# Shift eyedropper overlay
# ---------------------------------------------------------------------------

def draw_shift_pick_overlay(context, state):
    """Draw the split circle near the cursor while the shift eyedropper is active.

    Bottom half = primary (left) + secondary (right), top half = image color
    under cursor.
    Positioned 40 px above the cursor so it doesn't obscure the sampled pixel.
    """
    if not state.get('shift_pick_active'):
        return
    hovered = state.get('shift_hovered_color')
    if hovered is None:
        return
    rx = state.get('shift_region_x')
    ry = state.get('shift_region_y')
    if rx is None or ry is None:
        return

    try:
        brush = context.tool_settings.image_paint.brush
        prim  = tuple(brush.color[:3]) if brush else (1.0, 1.0, 1.0)
        sec   = tuple(brush.secondary_color[:3]) if brush else (0.0, 0.0, 0.0)
    except Exception:
        prim = (1.0, 1.0, 1.0)
        sec = (0.0, 0.0, 0.0)

    cx     = rx
    cy     = ry + 50   # offset above cursor
    radius = 38  # ~75 px diameter (1.5×)

    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')

    _draw_filled_arc(cx, cy, radius, (*prim, 1.0), math.pi, math.pi * 1.5)
    _draw_filled_arc(cx, cy, radius, (*sec, 1.0), math.pi * 1.5, math.tau)
    _draw_filled_half_circle(cx, cy, radius, (*hovered, 1.0), top=True)

    # Grid-snapped corner highlighter at the sampled image pixel.
    px = state.get('current_cx')
    py = state.get('current_cy')
    if px is not None and py is not None:
        _draw_precision_pixel_guide(context, px, py, color=(1.0, 1.0, 1.0, 0.95))

    _draw_circle_outline(cx, cy, radius, (0.0, 0.0, 0.0, 0.85))

    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.line_width_set(1.0)


# ---------------------------------------------------------------------------
# Smooth and Smear helpers
# ---------------------------------------------------------------------------

def smooth_pixels_in_image(img, pixels, smooth_radius, opacity):
    """Blur *pixels* by averaging their neighbors within *smooth_radius*.

    smooth_radius — integer kernel half-size in image pixels
    opacity       — blend fraction [0, 1] between original and blurred value
    """
    w, h = img.size
    arr     = np.array(img.pixels, dtype=np.float32)
    arr_4ch = arr.reshape(h, w, 4)
    result  = arr_4ch.copy()

    for (px, py) in pixels:
        if not (0 <= px < w and 0 <= py < h):
            continue
        x0 = max(0, px - smooth_radius)
        x1 = min(w - 1, px + smooth_radius)
        y0 = max(0, py - smooth_radius)
        y1 = min(h - 1, py + smooth_radius)
        avg  = arr_4ch[y0:y1 + 1, x0:x1 + 1, :3].mean(axis=(0, 1))
        orig = arr_4ch[py, px, :3]
        result[py, px, :3] = orig + (avg - orig) * opacity

    img.pixels.foreach_set(result.ravel())
    img.update()

    try:
        import bpy
        for screen in bpy.data.screens:
            for area in screen.areas:
                if area.type in {'VIEW_3D', 'IMAGE_EDITOR'}:
                    area.tag_redraw()
    except Exception:
        pass


def smear_pixels_in_image(img, pixels, dx, dy, smear_reach, opacity):
    """Smear *pixels* by sampling color from upstream along (dx, dy).

    dx, dy       — movement delta in image pixels (direction of travel)
    smear_reach  — how many pixels upstream to sample (float, from modifier)
    opacity      — blend fraction [0, 1]
    """
    w, h = img.size
    arr     = np.array(img.pixels, dtype=np.float32)
    arr_4ch = arr.reshape(h, w, 4)
    result  = arr_4ch.copy()

    for (px, py) in pixels:
        if not (0 <= px < w and 0 <= py < h):
            continue
        # Sample from upstream: opposite to direction of travel
        src_x = int(round(px - dx * smear_reach))
        src_y = int(round(py - dy * smear_reach))
        src_x = max(0, min(w - 1, src_x))
        src_y = max(0, min(h - 1, src_y))
        src_color = arr_4ch[src_y, src_x, :3]
        orig      = arr_4ch[py, px, :3]
        result[py, px, :3] = orig + (src_color - orig) * opacity

    img.pixels.foreach_set(result.ravel())
    img.update()

    try:
        import bpy
        for screen in bpy.data.screens:
            for area in screen.areas:
                if area.type in {'VIEW_3D', 'IMAGE_EDITOR'}:
                    area.tag_redraw()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Draw handler management
# ---------------------------------------------------------------------------

def register_draw_handler(state, space, context, callback):
    """Register a POST_PIXEL draw callback and store handles in *state*."""
    state['draw_handler'] = space.draw_handler_add(callback, (context,), 'WINDOW', 'POST_PIXEL')
    state['draw_space']   = space


def remove_draw_handler(state):
    """Remove the registered draw handler stored in *state*, if any."""
    handler = state.get('draw_handler')
    space   = state.get('draw_space')
    if handler is not None and space is not None:
        try:
            space.draw_handler_remove(handler, 'WINDOW')
        except Exception:
            pass
    state['draw_handler'] = None
    state['draw_space']   = None
