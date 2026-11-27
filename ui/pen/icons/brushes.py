"""Icons of the Brushes window (the special brushes, tools/special/), drawn in the
brush's primary / secondary colors where they paint with them. ``colors()`` returns
``(primary, secondary)`` RGB.
"""

import math

from ...kit import Rect
from ...kit import draw
from ...kit.theme import with_alpha
from .extras import _icon, _line_color, _mix, _pair, _size
from .menu import draw_caption

# Fixed spots (unit square, -1 .. 1) so the icons do not flicker.
_RUST_SPOTS = ((-0.55, 0.45, 0.42, 0.0), (0.35, 0.55, 0.30, 0.7), (0.5, -0.35, 0.45, 0.35),
               (-0.25, -0.45, 0.33, 1.0), (0.0, 0.05, 0.28, 0.55), (-0.75, -0.1, 0.2, 0.85))
_NOISE_DOTS = ((-0.8, 0.6), (-0.3, 0.85), (0.25, 0.7), (0.75, 0.45), (-0.65, 0.05), (-0.1, 0.3),
               (0.45, 0.15), (0.85, -0.2), (-0.85, -0.45), (-0.35, -0.25), (0.15, -0.5), (0.6, -0.7),
               (-0.55, -0.85), (0.05, -0.05), (0.35, -0.95))


def _cy(y, s, caption):
    return y + (s * 0.25 if caption else 0.0)


def _caption(dc, x, y, size, alpha, caption, text):
    if caption:
        draw_caption(dc, x, y - size * 0.36, text, alpha)


def paint_rust(colors, caption=True):
    """Rust: a plate with blotches mixing the primary and secondary color."""
    def paint(dc, x, y, size, alpha):
        theme = dc.theme
        primary, secondary = _pair(colors)
        s = _size(dc, size, caption) * 0.5
        cy = _cy(y, s * 2.0, caption)
        plate = (0.45, 0.45, 0.47)
        draw.rounded_rect(Rect.from_center(x, cy, s * 2.0, s * 2.0), s * 0.3, (*plate, alpha),
                          rim=theme.edge_for(plate, alpha))
        for ox, oy, r, t in _RUST_SPOTS:
            color = _mix(primary, secondary, t)
            draw.circle(x + ox * s * 0.8, cy + oy * s * 0.8, r * s, (*color, alpha), segments=14)
        _caption(dc, x, y, size, alpha, caption, "Rust")
    return paint


def paint_particles(colors, caption=True):
    """Particles: a ball's bouncing path over a surface, dents where it hit."""
    def paint(dc, x, y, size, alpha):
        primary, _secondary = _pair(colors)
        c, w = _line_color(dc, alpha), max(1.0, dc.theme.px(1.0))
        s = _size(dc, size, caption) * 0.5
        cy = _cy(y, s * 2.0, caption)
        ground = cy - s * 0.75
        draw.polyline([(x - s * 1.1, ground), (x + s * 1.1, ground)], with_alpha(c, 0.6 * c[3]), w)
        # A fall from the top left, then two shrinking bounces (parabolas).
        pts = [(x + (-1.0 + 0.55 * t) * s, ground + (1.0 - t * t) * 1.4 * s) for t in (i / 6.0 for i in range(7))]
        for x0, x1, height in ((-0.45, 0.6, 0.8), (0.6, 1.1, 0.35)):
            pts += [(x + (x0 + (x1 - x0) * t) * s, ground + 4.0 * t * (1.0 - t) * height * s)
                    for t in (i / 6.0 for i in range(1, 7))]
        draw.polyline(pts, with_alpha(c, 0.45 * c[3]), w)
        for hx in (-0.45, 0.6, 1.1):
            draw.circle(x + hx * s, ground, s * 0.17, (*primary, alpha), segments=10)
        draw.circle(x - s, ground + s * 1.4, s * 0.26, (*c[:3], alpha), segments=14)
        _caption(dc, x, y, size, alpha, caption, "Particles")
    return paint


def paint_noise_blur(caption=True):
    """Noise Blur: scattered dots fading from a solid core."""
    def paint(dc, x, y, size, alpha):
        c = _line_color(dc, alpha)
        s = _size(dc, size, caption) * 0.5
        cy = _cy(y, s * 2.0, caption)
        draw.circle(x, cy, s * 0.45, with_alpha(c, 0.55 * c[3]), segments=16)
        dot = max(1.0, s * 0.18)
        for i, (ox, oy) in enumerate(_NOISE_DOTS):
            fade = 1.0 - 0.6 * math.hypot(ox, oy) / 1.3
            draw.rect(Rect.from_center(x + ox * s, cy + oy * s, dot, dot), with_alpha(c, fade * c[3]))
        _caption(dc, x, y, size, alpha, caption, "Noise Blur")
    return paint


def paint_pull(caption=True):
    """Pull: a grid line bent along with an arrow."""
    def paint(dc, x, y, size, alpha):
        c, w = _line_color(dc, alpha), max(1.0, dc.theme.px(1.2))
        s = _size(dc, size, caption) * 0.5
        cy = _cy(y, s * 2.0, caption)
        for row in (-0.6, 0.0, 0.6):
            pts = []
            for i in range(13):
                u = -1.0 + i / 6.0
                bump = math.exp(-(u * 2.2) ** 2) * 0.55 * (1.0 - abs(row) * 0.6)
                pts.append((x + (u + bump) * s, cy + row * s))
            draw.polyline(pts, with_alpha(c, 0.6 * c[3]), w)
        tip = (x + s * 1.05, cy)
        draw.polyline([(x - s * 0.2, cy), tip], c, w * 1.4)
        draw.triangle(tip, (tip[0] - s * 0.38, cy + s * 0.25), (tip[0] - s * 0.38, cy - s * 0.25), c)
        _caption(dc, x, y, size, alpha, caption, "Pull")
    return paint


def paint_repair(caption=True):
    """Repair: a bandage."""
    def paint(dc, x, y, size, alpha):
        theme = dc.theme
        s = _size(dc, size, caption) * 0.5
        cy = _cy(y, s * 2.0, caption)
        tan, pad = (0.93, 0.78, 0.62), (0.98, 0.94, 0.88)
        a = math.radians(35.0)
        ux, uy = math.cos(a), math.sin(a)
        vx, vy = -uy, ux
        L, H = s * 1.15, s * 0.42

        def quad(half_len, hh, color):
            pts = [(x + ux * px + vx * py, cy + uy * px + vy * py) for px, py in ((-half_len, -hh), (half_len, -hh), (half_len, hh), (-half_len, hh))]
            draw.triangle(pts[0], pts[1], pts[2], (*color, alpha))
            draw.triangle(pts[0], pts[2], pts[3], (*color, alpha))
            draw.polyline(pts, theme.edge_for(color, alpha), 1.0, closed=True)

        quad(L, H, tan)
        quad(L * 0.35, H * 0.8, pad)
        dot = with_alpha(theme.edge_for(tan, alpha), alpha)
        for k in (-0.7, 0.7):
            for j in (-0.4, 0.4):
                draw.circle(x + ux * L * k + vx * H * j, cy + uy * L * k + vy * H * j, max(0.8, s * 0.06), dot,
                            segments=6)
        _caption(dc, x, y, size, alpha, caption, "Repair")
    return paint


def paint_brushes_title(colors):
    def paint(dc, x, y, size, alpha):
        paint_rust(colors, caption=False)(dc, x, y, size * 1.4, alpha)
    return paint


def paint_brushes_menu(colors):
    """The Windows ring entry (outer ring)."""
    def paint(dc, x, y, size, alpha):
        paint_rust(colors, caption=False)(dc, x, y + size * 0.12, size * 0.8, alpha)
        draw_caption(dc, x, y - size * 0.36, "Brushes", alpha)
    return paint


BRUSH_PAINTERS = {
    'RUST': paint_rust,
    'PARTICLES': paint_particles,
    'NOISE_BLUR': lambda colors, caption=True: paint_noise_blur(caption),
    'PULL': lambda colors, caption=True: paint_pull(caption),
    'REPAIR': lambda colors, caption=True: paint_repair(caption),
}


# ---- setting buttons (icon + caption) -----------------------------------------------------

def icon_auto(dc, x, y, size, alpha):
    """Auto: a four-pointed sparkle."""
    s, c = _icon(size, dc), _line_color(dc, alpha)
    k = s * 0.28
    for (ax, ay) in ((0, 1), (1, 0), (0, -1), (-1, 0)):
        draw.triangle((x + ax * s, y + ay * s), (x + ay * k, y - ax * k), (x - ay * k, y + ax * k), c)


def icon_source(dc, x, y, size, alpha):
    """Source: a crosshair."""
    s, c, w = _icon(size, dc), _line_color(dc, alpha), max(1.0, dc.theme.px(1.3))
    draw.circle_outline(x, y, s * 0.6, c, width=w, segments=20)
    draw.polyline([(x - s, y), (x - s * 0.3, y)], c, w)
    draw.polyline([(x + s * 0.3, y), (x + s, y)], c, w)
    draw.polyline([(x, y - s), (x, y - s * 0.3)], c, w)
    draw.polyline([(x, y + s * 0.3), (x, y + s)], c, w)


def icon_pixels(dc, x, y, size, alpha):
    """Pixel: crisp squares."""
    s, c = _icon(size, dc), _line_color(dc, alpha)
    cell = s * 0.9
    for i, j in ((-1, -1), (0, 0), (1, 1), (-1, 1), (1, -1)):
        draw.rect(Rect.from_center(x + i * cell, y + j * cell, cell * 0.9, cell * 0.9), c)


def icon_drag(dc, x, y, size, alpha):
    """Drag: an arrow to the right."""
    s, c, w = _icon(size, dc), _line_color(dc, alpha), max(1.0, dc.theme.px(1.4))
    draw.polyline([(x - s, y), (x + s * 0.4, y)], c, w)
    draw.triangle((x + s, y), (x + s * 0.3, y + s * 0.45), (x + s * 0.3, y - s * 0.45), c)


def _radial_arrows(dc, x, y, size, alpha, inward):
    """Four diagonal arrows pointing into the center (``inward``) or out of it."""
    s, c, w = _icon(size, dc), _line_color(dc, alpha), max(1.0, dc.theme.px(1.3))
    draw.circle(x, y, s * 0.18, c, segments=10)
    for k in range(4):
        a = math.pi * 0.25 + k * math.pi * 0.5
        ux, uy = math.cos(a), math.sin(a)
        r_tail, r_tip = (s * 1.05, s * 0.45) if inward else (s * 0.4, s * 1.05)
        dx, dy = (-ux, -uy) if inward else (ux, uy)          # the arrow's direction
        tip = (x + ux * r_tip, y + uy * r_tip)
        draw.polyline([(x + ux * r_tail, y + uy * r_tail), tip], c, w)
        bx, by = tip[0] - dx * s * 0.3, tip[1] - dy * s * 0.3
        draw.triangle(tip, (bx - dy * s * 0.18, by + dx * s * 0.18), (bx + dy * s * 0.18, by - dx * s * 0.18), c)


def icon_pinch(dc, x, y, size, alpha):
    """Pinch: arrows pointing into the center."""
    _radial_arrows(dc, x, y, size, alpha, inward=True)


def icon_push(dc, x, y, size, alpha):
    """Push: arrows pointing out of the center."""
    _radial_arrows(dc, x, y, size, alpha, inward=False)


def icon_smooth(dc, x, y, size, alpha):
    """Smooth: soft rings."""
    s, c = _icon(size, dc), _line_color(dc, alpha)
    for k, a in ((1.0, 0.25), (0.7, 0.5), (0.4, 0.95)):
        draw.circle(x, y, s * k, with_alpha(c, a * c[3]), segments=20)
