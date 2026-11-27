"""Icons of the Extras window (Fill / Edges / Ambient Occlusion), drawn in the brush's
primary / secondary colors. ``colors()`` returns ``(primary, secondary)`` RGB.
"""

from ...kit import Rect
from ...kit import draw
from ...kit.theme import with_alpha
from ...kit.widget import _resolve
from .menu import draw_caption


def _pair(colors):
    try:
        a, b = _resolve(colors, ((0.9, 0.9, 0.9), (0.2, 0.2, 0.2)))
        return tuple(a)[:3], tuple(b)[:3]
    except Exception:
        return (0.9, 0.9, 0.9), (0.2, 0.2, 0.2)


def _mix(a, b, t):
    return tuple(a[k] + (b[k] - a[k]) * t for k in range(3))


def _size(dc, size, caption):
    return min(size * (0.42 if caption else 0.55), dc.theme.px(16.0))


def paint_fill(colors, caption=True):
    """Fill: a block in the primary color with a drop running off its corner."""
    def paint(dc, x, y, size, alpha):
        theme = dc.theme
        primary, _secondary = _pair(colors)
        s = _size(dc, size, caption)
        cy = y + (s * 0.25 if caption else 0.0)
        box = Rect.from_center(x - s * 0.1, cy, s, s)
        draw.rounded_rect(box, s * 0.15, (*primary, alpha), rim=theme.edge_for(primary, alpha))
        draw.circle(box.x1 + s * 0.12, box.y0 - s * 0.02, s * 0.16, (*primary, alpha),
                    rim=theme.edge_for(primary, alpha), segments=16)
        if caption:
            draw_caption(dc, x, y - size * 0.36, "Fill", alpha)
    return paint


def paint_edges(colors, caption=True):
    """Edges: a frame in the primary color running into the secondary one inside."""
    def paint(dc, x, y, size, alpha):
        theme = dc.theme
        primary, secondary = _pair(colors)
        s = _size(dc, size, caption)
        cy = y + (s * 0.25 if caption else 0.0)
        steps = 4
        for i in range(steps):
            k = s * (1.0 - i / steps * 0.75)
            color = _mix(primary, secondary, i / (steps - 1))
            box = Rect.from_center(x, cy, k, k)
            if i == 0:
                draw.rounded_rect(box, s * 0.12, (*color, alpha), rim=theme.edge_for(color, alpha))
            else:
                draw.rect(box, (*color, alpha))
        if caption:
            draw_caption(dc, x, y - size * 0.36, "Edges", alpha)
    return paint


def paint_ao(colors, caption=True):
    """Ambient Occlusion: a ball, the primary color in its shade, the secondary in its light."""
    def paint(dc, x, y, size, alpha):
        theme = dc.theme
        primary, secondary = _pair(colors)
        s = _size(dc, size, caption) * 0.55
        cy = y + (s * 0.45 if caption else 0.0)
        draw.circle(x, cy, s, (*primary, alpha), rim=theme.edge_for(primary, alpha), segments=32)
        for i, (k, off) in enumerate(((0.75, 0.15), (0.5, 0.3), (0.28, 0.42))):
            color = _mix(primary, secondary, (i + 1) / 3.0)
            draw.circle(x + s * off * 0.7, cy + s * off * 0.7, s * k, (*color, alpha), segments=28)
        if caption:
            draw_caption(dc, x, y - size * 0.36, "AO", alpha)
    return paint


def paint_all(dc, x, y, size, alpha):
    """The window's center: run the armed tool on every island / part."""
    theme = dc.theme
    s = min(size * 0.22, theme.px(8.0))
    color = with_alpha(theme.text, 0.92 * alpha)
    for dx, dy in ((-1, 1), (1, 1), (-1, -1), (1, -1)):
        draw.rect(Rect.from_center(x + dx * s * 0.62, y + s * 0.55 + dy * s * 0.62, s, s), color)
    draw_caption(dc, x, y - size * 0.3, "All", alpha)


def paint_extras_title(colors):
    def paint(dc, x, y, size, alpha):
        paint_edges(colors, caption=False)(dc, x, y, size * 1.4, alpha)
    return paint


def paint_extras_menu(colors):
    """The Windows ring entry."""
    def paint(dc, x, y, size, alpha):
        paint_ao(colors, caption=False)(dc, x, y + size * 0.12, size * 0.8, alpha)
        draw_caption(dc, x, y - size * 0.36, "Extras", alpha)
    return paint


# ---- setting buttons (icon + caption, like Undo / Redo) ------------------------------------

def _line_color(dc, alpha):
    return with_alpha(dc.theme.text, 0.92 * alpha)


def _icon(size, dc):
    return min(size * 0.3, dc.theme.px(9.0))


def icon_angle(dc, x, y, size, alpha):
    """Edges by angle: two faces meeting at a corner, an arc between them."""
    s, c, w = _icon(size, dc), _line_color(dc, alpha), max(1.0, dc.theme.px(1.5))
    draw.polyline([(x - s, y - s * 0.6), (x, y + s * 0.6), (x + s, y - s * 0.6)], c, w)
    draw.arc(x, y + s * 0.6, s * 0.55, -2.2, -0.94, with_alpha(c, 0.7 * c[3]), width=w * 0.8, segments=12)


def icon_all_edges(dc, x, y, size, alpha):
    """Every edge: a cube's outline."""
    s, c, w = _icon(size, dc), _line_color(dc, alpha), max(1.0, dc.theme.px(1.5))
    o = s * 0.4
    draw.polyline([(x - s, y - s), (x + s - o, y - s), (x + s - o, y + s - o), (x - s, y + s - o)], c, w, closed=True)
    draw.polyline([(x - s, y + s - o), (x - s + o, y + s), (x + s, y + s), (x + s, y - s + o), (x + s - o, y - s)], c, w)
    draw.polyline([(x + s - o, y + s - o), (x + s, y + s)], c, w)


def icon_marked(dc, x, y, size, alpha):
    """Marked sharp: a square with one edge highlighted."""
    s, c, w = _icon(size, dc), _line_color(dc, alpha), max(1.0, dc.theme.px(1.5))
    draw.polyline([(x - s, y - s), (x + s, y - s), (x + s, y + s), (x - s, y + s)], with_alpha(c, 0.5 * c[3]), w,
                  closed=True)
    draw.polyline([(x - s, y + s), (x + s, y + s)], with_alpha(dc.theme.accent, alpha), w * 2.2)


def icon_symmetric(dc, x, y, size, alpha):
    """Symmetric: the edge between texels, the same texels on both sides."""
    s, c = _icon(size, dc), _line_color(dc, alpha)
    cell = s * 0.62
    for k in (-1.5, -0.5, 0.5, 1.5):
        draw.rect(Rect.from_center(x + k * cell * 1.15, y, cell, cell * 2.4),
                  with_alpha(c, (0.9 if abs(k) < 1 else 0.45) * c[3]))
    draw.polyline([(x, y - s * 1.2), (x, y + s * 1.2)], with_alpha(dc.theme.accent, alpha), max(1.0, dc.theme.px(1.5)))


def icon_pixel_line(dc, x, y, size, alpha):
    """Pixel line: one texel column on the edge, fainter ones beside it."""
    s, c = _icon(size, dc), _line_color(dc, alpha)
    cell = s * 0.62
    for k in (-1, 0, 1):
        draw.rect(Rect.from_center(x + k * cell * 1.15, y, cell, cell * 2.4),
                  with_alpha(c, (0.95 if k == 0 else 0.4) * c[3]))
    draw.polyline([(x, y - s * 1.2), (x, y + s * 1.2)], with_alpha(dc.theme.accent, alpha), max(1.0, dc.theme.px(1.5)))


def icon_fade(dc, x, y, size, alpha):
    """Fade: texels getting fainter."""
    s, c = _icon(size, dc), _line_color(dc, alpha)
    cell = s * 0.55
    for i in range(4):
        draw.rect(Rect.from_center(x - s + cell * 0.5 + i * cell * 1.2, y, cell, cell * 2.2),
                  with_alpha(c, (1.0 - i * 0.28) * c[3]))


def icon_curve(dc, x, y, size, alpha):
    """Curve: a falloff curve in a box."""
    s, c, w = _icon(size, dc), _line_color(dc, alpha), max(1.0, dc.theme.px(1.5))
    draw.polyline([(x - s, y - s), (x + s, y - s), (x + s, y + s), (x - s, y + s)], with_alpha(c, 0.4 * c[3]), 1.0,
                  closed=True)
    pts = [(x - s + 2 * s * i / 12.0, y - s + 2 * s * (1.0 - (i / 12.0) ** 2) ** 2) for i in range(13)]
    draw.polyline(pts[::-1], c, w)
