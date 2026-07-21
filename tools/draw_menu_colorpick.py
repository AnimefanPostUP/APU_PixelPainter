"""Color-pick sheet overlay drawing."""

import colorsys

import blf
import gpu
import gpu_extras.batch

from .draw_functions import _draw_circle_outline, _draw_filled_circle


def draw_color_pick_axes(rx, ry, h, s, v, radius):
    """Draw VALUE, SATURATION, and HUE bars."""
    del radius

    sheet_w = 500.0
    sheet_h = 300.0
    side_gap = 6.0
    bar_w = 24.0
    hue_h = 24.0
    font_id = 0

    sheet_x0 = rx - sheet_w * 0.5
    sheet_y0 = ry - sheet_h * 0.5

    val_x0 = sheet_x0 - side_gap - bar_w
    val_y0 = sheet_y0
    val_h = sheet_h

    sat_x0 = sheet_x0 + sheet_w + side_gap
    sat_y0 = sheet_y0
    sat_h = sheet_h

    hue_x0 = sheet_x0
    hue_y0 = sheet_y0 - side_gap - hue_h
    hue_w = sheet_w

    su = gpu.shader.from_builtin('UNIFORM_COLOR')
    sc = gpu.shader.from_builtin('SMOOTH_COLOR')

    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')

    seam_overlap = 1.0
    val_r = bar_w * 0.5
    steps = 20
    sh = (val_h - 2.0 * val_r + 2.0 * seam_overlap) / steps
    verts_v, colors_v = [], []
    for i in range(steps):
        v0 = i / steps
        v1 = (i + 1) / steps
        r0, g0, b0 = colorsys.hsv_to_rgb(h, s, v0)
        r1, g1, b1 = colorsys.hsv_to_rgb(h, s, v1)
        y0_ = val_y0 + val_r - seam_overlap + i * sh
        y1_ = y0_ + sh
        verts_v += [(val_x0, y0_), (val_x0 + bar_w, y0_), (val_x0 + bar_w, y1_), (val_x0, y0_), (val_x0 + bar_w, y1_), (val_x0, y1_)]
        c0 = (r0, g0, b0, 1.0)
        c1 = (r1, g1, b1, 1.0)
        colors_v += [c0, c0, c1, c0, c1, c1]
    gpu_extras.batch.batch_for_shader(sc, 'TRIS', {"pos": verts_v, "color": colors_v}).draw(sc)
    _draw_filled_circle(val_x0 + val_r, val_y0 + val_r, val_r, (*colorsys.hsv_to_rgb(h, s, 0.0), 1.0))
    _draw_filled_circle(val_x0 + val_r, val_y0 + val_h - val_r, val_r, (*colorsys.hsv_to_rgb(h, s, 1.0), 1.0))

    cur_vy = val_y0 + v * val_h
    for lw, rgba in [(3.0, (0, 0, 0, 1)), (1.5, (1, 1, 1, 1))]:
        gpu.state.line_width_set(lw)
        su.uniform_float("color", rgba)
        gpu_extras.batch.batch_for_shader(su, 'LINES', {"pos": [(val_x0 - 4, cur_vy), (val_x0 + bar_w + 4, cur_vy)]}).draw(su)

    sat_r = bar_w * 0.5
    verts_s, colors_s = [], []
    for i in range(steps):
        s0 = i / steps
        s1 = (i + 1) / steps
        r0, g0, b0 = colorsys.hsv_to_rgb(h, s0, v)
        r1, g1, b1 = colorsys.hsv_to_rgb(h, s1, v)
        y0_ = sat_y0 + sat_r - seam_overlap + i * sh
        y1_ = y0_ + sh
        verts_s += [(sat_x0, y0_), (sat_x0 + bar_w, y0_), (sat_x0 + bar_w, y1_), (sat_x0, y0_), (sat_x0 + bar_w, y1_), (sat_x0, y1_)]
        c0 = (r0, g0, b0, 1.0)
        c1 = (r1, g1, b1, 1.0)
        colors_s += [c0, c0, c1, c0, c1, c1]
    gpu_extras.batch.batch_for_shader(sc, 'TRIS', {"pos": verts_s, "color": colors_s}).draw(sc)
    _draw_filled_circle(sat_x0 + sat_r, sat_y0 + sat_r, sat_r, (*colorsys.hsv_to_rgb(h, 0.0, v), 1.0))
    _draw_filled_circle(sat_x0 + sat_r, sat_y0 + sat_h - sat_r, sat_r, (*colorsys.hsv_to_rgb(h, 1.0, v), 1.0))

    cur_sy = sat_y0 + s * sat_h
    for lw, rgba in [(3.0, (0, 0, 0, 1)), (1.5, (1, 1, 1, 1))]:
        gpu.state.line_width_set(lw)
        su.uniform_float("color", rgba)
        gpu_extras.batch.batch_for_shader(su, 'LINES', {"pos": [(sat_x0 - 4, cur_sy), (sat_x0 + bar_w + 4, cur_sy)]}).draw(su)

    hue_r = hue_h * 0.5
    hsteps = 36
    sw = (hue_w - 2.0 * hue_r + 2.0 * seam_overlap) / hsteps
    verts_h, colors_h = [], []
    for i in range(hsteps):
        h0 = i / hsteps
        h1 = (i + 1) / hsteps
        r0, g0, b0 = colorsys.hsv_to_rgb(h0, 1.0, 1.0)
        r1, g1, b1 = colorsys.hsv_to_rgb(h1, 1.0, 1.0)
        x0_ = hue_x0 + hue_r - seam_overlap + i * sw
        x1_ = x0_ + sw
        verts_h += [(x0_, hue_y0), (x1_, hue_y0), (x1_, hue_y0 + hue_h), (x0_, hue_y0), (x1_, hue_y0 + hue_h), (x0_, hue_y0 + hue_h)]
        c0 = (r0, g0, b0, 1.0)
        c1 = (r1, g1, b1, 1.0)
        colors_h += [c0, c1, c1, c0, c1, c0]
    gpu_extras.batch.batch_for_shader(sc, 'TRIS', {"pos": verts_h, "color": colors_h}).draw(sc)
    _draw_filled_circle(hue_x0 + hue_r, hue_y0 + hue_r, hue_r, (*colorsys.hsv_to_rgb(0.0, 1.0, 1.0), 1.0))
    _draw_filled_circle(hue_x0 + hue_w - hue_r, hue_y0 + hue_r, hue_r, (*colorsys.hsv_to_rgb(1.0, 1.0, 1.0), 1.0))

    cur_hx = hue_x0 + h * hue_w
    for lw, rgba in [(3.0, (0, 0, 0, 1)), (1.5, (1, 1, 1, 1))]:
        gpu.state.line_width_set(lw)
        su.uniform_float("color", rgba)
        gpu_extras.batch.batch_for_shader(su, 'LINES', {"pos": [(cur_hx, hue_y0 - 4), (cur_hx, hue_y0 + hue_h + 4)]}).draw(su)

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


def draw_color_pick_sheet_overlay(state):
    """Draw a generated HSV sheet overlay centered at color-pick origin."""
    rx = state.get('sub_start_region_x')
    ry = state.get('sub_start_region_y')
    if rx is None or ry is None:
        return

    s = state.get('sub_color_s')
    if s is None:
        s = 1.0

    w = 500.0
    h = 300.0
    x0 = rx - w * 0.5
    y0 = ry - h * 0.5
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
            verts += [(x_a, y_a), (x_b, y_a), (x_b, y_b), (x_a, y_a), (x_b, y_b), (x_a, y_b)]
            cols_rgba += [c00, c10, c11, c00, c11, c01]

    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')
    gpu_extras.batch.batch_for_shader(sc, 'TRIS', {"pos": verts, "color": cols_rgba}).draw(sc)
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
