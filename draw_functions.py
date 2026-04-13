"""GPU drawing callbacks and pixel-write helpers."""
import colorsys
import math

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


def _edges_to_screen_verts(edges, v2d, w, h):
    """Convert image-space edge corner pairs to rounded screen coordinates."""
    vertices = []
    for (px0, py0), (px1, py1) in edges:
        sx0, sy0 = v2d.view_to_region(px0 / w, py0 / h)
        sx1, sy1 = v2d.view_to_region(px1 / w, py1 / h)
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
        return

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

    if (mode == 'LINE' or state.get('ctrl_line_active')) and state['start_position'] is not None:
        shape = state['last_shape']
        # SPRAY uses a circle tip when drawing lines
        tip_shape = 'CIRCLE' if shape == 'SPRAY' else shape
        x0, y0 = state['start_position']
        pixels = set()
        for (lx, ly) in math_utils.get_line_pixels(x0, y0, cx, cy):
            pixels |= math_utils.get_pixels_in_shape(lx, ly, radius, tip_shape)
    else:
        # SPRAY shows full circle boundary as the outline (represents the spray area)
        outline_mode = 'CIRCLE' if mode == 'SPRAY' else mode
        pixels = math_utils.get_pixels_in_shape(cx, cy, radius, outline_mode)

    edges = math_utils.get_outline_edges(pixels)
    if not edges:
        return

    outline_color = {
        'SPRAY':  (1.0, 0.55, 0.0,  0.9),  # orange
        'SMEAR':  (1.0, 0.2,  0.2,  0.9),  # red
        'SMOOTH': (0.7, 0.3,  1.0,  0.9),  # purple
    }.get(mode, (1.0, 1.0, 0.0, 0.9))      # default yellow

    vertices = _edges_to_screen_verts(edges, v2d, w, h)
    _gpu_draw_lines(vertices, outline_color)


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


def _draw_circle_outline(cx, cy, radius, rgba, width=2.0):
    """Draw a thin circle outline."""
    steps = 60
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
    """Draw hue (horizontal) and value (vertical) reference bars around the circle."""
    gap     = 16        # gap between circle edge and bar
    hue_w   = 200       # width of hue bar
    hue_h   = 12        # height of hue bar
    val_w   = 12        # width of value bar
    val_h   = 150       # height of value bar
    font_id = 0

    hue_x0    = rx - hue_w // 2
    hue_y_top = ry - radius - gap          # top edge of hue bar
    hue_y0    = hue_y_top - hue_h          # bottom edge

    val_x0   = rx + radius + gap + 20
    val_trim = int(val_h * 0.25)   # trim 25% from the bottom
    val_y0   = ry - val_h // 2 + val_trim
    val_h   -= val_trim

    su = gpu.shader.from_builtin('UNIFORM_COLOR')
    sc = gpu.shader.from_builtin('SMOOTH_COLOR')

    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')

    # ---- Hue bar: rainbow gradient ----
    steps  = 36
    sw     = hue_w / steps
    verts_h, colors_h = [], []
    for i in range(steps):
        h0 = i / steps
        h1 = (i + 1) / steps
        r0, g0, b0 = colorsys.hsv_to_rgb(h0, 1.0, 1.0)
        r1, g1, b1 = colorsys.hsv_to_rgb(h1, 1.0, 1.0)
        x0_ = hue_x0 + i * sw
        x1_ = x0_ + sw
        verts_h  += [(x0_, hue_y0), (x1_, hue_y0), (x1_, hue_y_top),
                     (x0_, hue_y0), (x1_, hue_y_top), (x0_, hue_y_top)]
        c0 = (r0, g0, b0, 1.0)
        c1 = (r1, g1, b1, 1.0)
        colors_h += [c0, c1, c1, c0, c1, c0]

    gpu_extras.batch.batch_for_shader(sc, 'TRIS',
        {"pos": verts_h, "color": colors_h}).draw(sc)

    # Hue cursor (black outline then white)
    cur_hx = hue_x0 + h * hue_w
    for lw, rgba in [(3.0, (0, 0, 0, 1)), (1.5, (1, 1, 1, 1))]:
        gpu.state.line_width_set(lw)
        su.uniform_float("color", rgba)
        gpu_extras.batch.batch_for_shader(su, 'LINES', {"pos": [
            (cur_hx, hue_y0 - 4), (cur_hx, hue_y_top + 4)
        ]}).draw(su)

    # Thin border around hue bar
    gpu.state.line_width_set(1.0)
    su.uniform_float("color", (0.0, 0.0, 0.0, 0.6))
    gpu_extras.batch.batch_for_shader(su, 'LINES', {"pos": [
        (hue_x0, hue_y0), (hue_x0 + hue_w, hue_y0),
        (hue_x0 + hue_w, hue_y0), (hue_x0 + hue_w, hue_y_top),
        (hue_x0 + hue_w, hue_y_top), (hue_x0, hue_y_top),
        (hue_x0, hue_y_top), (hue_x0, hue_y0),
    ]}).draw(su)

    # R / G / B labels below hue bar
    blf.size(font_id, 11)
    for label, frac in [("R", 0.0), ("G", 1 / 3), ("B", 2 / 3)]:
        lw_, lh_ = blf.dimensions(font_id, label)
        blf.color(font_id, 1.0, 1.0, 1.0, 0.9)
        blf.position(font_id, hue_x0 + frac * hue_w - lw_ * 0.5, hue_y0 - lh_ - 3, 0)
        blf.draw(font_id, label)

    # Saturation text below labels
    blf.size(font_id, 11)
    sat_str = f"Sat  {s * 100:.0f}%"
    _, lh_s = blf.dimensions(font_id, sat_str)
    _, lh_l = blf.dimensions(font_id, "R")
    blf.color(font_id, 0.9, 0.9, 0.9, 0.85)
    blf.position(font_id, hue_x0, hue_y0 - lh_l - 3 - lh_s - 4, 0)
    blf.draw(font_id, sat_str)

    # ---- Value bar: gradient from black → full-chroma color ----
    vsteps = 20
    sh_    = val_h / vsteps
    verts_v, colors_v = [], []
    for i in range(vsteps):
        v0_ = i / vsteps
        v1_ = (i + 1) / vsteps
        r0, g0, b0 = colorsys.hsv_to_rgb(h, s, v0_)
        r1, g1, b1 = colorsys.hsv_to_rgb(h, s, v1_)
        y0_ = val_y0 + i * sh_
        y1_ = y0_ + sh_
        verts_v  += [(val_x0, y0_), (val_x0 + val_w, y0_), (val_x0 + val_w, y1_),
                     (val_x0, y0_), (val_x0 + val_w, y1_), (val_x0, y1_)]
        c0 = (r0, g0, b0, 1.0)
        c1 = (r1, g1, b1, 1.0)
        colors_v += [c0, c0, c1, c0, c1, c1]

    gpu.state.blend_set('ALPHA')
    gpu_extras.batch.batch_for_shader(sc, 'TRIS',
        {"pos": verts_v, "color": colors_v}).draw(sc)

    # Value cursor
    cur_vy = val_y0 + v * val_h
    for lw, rgba in [(3.0, (0, 0, 0, 1)), (1.5, (1, 1, 1, 1))]:
        gpu.state.line_width_set(lw)
        su.uniform_float("color", rgba)
        gpu_extras.batch.batch_for_shader(su, 'LINES', {"pos": [
            (val_x0 - 4, cur_vy), (val_x0 + val_w + 4, cur_vy)
        ]}).draw(su)

    # Thin border around value bar
    gpu.state.line_width_set(1.0)
    su.uniform_float("color", (0.0, 0.0, 0.0, 0.6))
    gpu_extras.batch.batch_for_shader(su, 'LINES', {"pos": [
        (val_x0, val_y0), (val_x0 + val_w, val_y0),
        (val_x0 + val_w, val_y0), (val_x0 + val_w, val_y0 + val_h),
        (val_x0 + val_w, val_y0 + val_h), (val_x0, val_y0 + val_h),
        (val_x0, val_y0 + val_h), (val_x0, val_y0),
    ]}).draw(su)

    # Brightness % labels to the right of value bar
    blf.size(font_id, 10)
    for pct in range(0, 101, 20):
        y_pos = val_y0 + (pct / 100) * val_h
        _, lh_ = blf.dimensions(font_id, "0%")
        blf.color(font_id, 1.0, 1.0, 1.0, 0.9)
        blf.position(font_id, val_x0 + val_w + 4, y_pos - lh_ * 0.5, 0)
        blf.draw(font_id, f"{pct}%")

    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.line_width_set(1.0)


def _draw_sub_mode_cursor_dot(context, state):
    """Draw a 50px circle at the sub-mode start position.

    COLOR_PICK: bottom half = original color, top half = current color.
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

    radius = 38  # ~75 px diameter (1.5×)

    try:
        brush = context.tool_settings.image_paint.brush
        ups   = context.tool_settings.unified_paint_settings
    except Exception:
        return

    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')

    if sub == 'COLOR_PICK':
        orig = state.get('sub_orig_color') or (1.0, 1.0, 1.0)
        try:
            curr = tuple(brush.color[:3]) if brush else (1.0, 1.0, 1.0)
        except Exception:
            curr = (1.0, 1.0, 1.0)

        _draw_filled_half_circle(rx, ry, radius, (*orig, 1.0), top=False)
        _draw_filled_half_circle(rx, ry, radius, (*curr, 1.0), top=True)

        # Dividing line
        gpu.state.line_width_set(1.5)
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        batch  = gpu_extras.batch.batch_for_shader(
            shader, 'LINES', {"pos": [(rx - radius, ry), (rx + radius, ry)]})
        shader.uniform_float("color", (0.0, 0.0, 0.0, 0.7))
        batch.draw(shader)

        h = state.get('sub_color_h') or 0.0
        s = state.get('sub_color_s') or 0.0
        v = state.get('sub_color_v') or 0.0
        _draw_color_pick_axes(rx, ry, h, s, v, radius)

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


# ---------------------------------------------------------------------------
# Sub-mode HUD overlay
# ---------------------------------------------------------------------------

def draw_sub_mode_overlay(context, state):
    """Draw a text HUD at the bottom of the editor when a sub-mode is active,
    plus the split-circle cursor dot at the start position."""
    sub = state.get('sub_mode')
    if not sub:
        return

    _draw_sub_mode_cursor_dot(context, state)

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
            r, g, b = (brush.color if brush else (0, 0, 0))[:3]
            h, s, v = colorsys.rgb_to_hsv(r, g, b)
            line1 = f"H {h:.3f}   S {s:.3f}   V {v:.3f}"
            line2 = "← → Hue   ↑ ↓ Value   Scroll Sat   LMB apply   RMB cancel"
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

    Bottom half = current brush color, top half = image color under cursor.
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
        curr  = tuple(brush.color[:3]) if brush else (1.0, 1.0, 1.0)
    except Exception:
        curr = (1.0, 1.0, 1.0)

    cx     = rx
    cy     = ry + 40   # offset above cursor
    radius = 38  # ~75 px diameter (1.5×)

    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')

    _draw_filled_half_circle(cx, cy, radius, (*curr,    1.0), top=False)
    _draw_filled_half_circle(cx, cy, radius, (*hovered, 1.0), top=True)

    gpu.state.line_width_set(1.5)
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch  = gpu_extras.batch.batch_for_shader(
        shader, 'LINES', {"pos": [(cx - radius, cy), (cx + radius, cy)]})
    shader.uniform_float("color", (0.0, 0.0, 0.0, 0.7))
    batch.draw(shader)

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
