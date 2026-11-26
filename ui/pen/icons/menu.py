"""Icon painters of the pen UI: ``paint_*(dc, x, y, size, alpha)`` draw one icon into a
square (``kit.RingSegment`` / ``PenButton`` painters); factories (``paint_save(unsaved)``,
``captioned(painter, text)``, ...) return such a painter.
"""

import colorsys
import math

from ...kit import Rect
from ...kit import draw
from ...kit.theme import with_alpha
from ...kit.widget import _resolve
from ..metrics import TINT_CUSTOM, TINT_MASK, TINT_SAVE


def paint_swap(dc, x, y, size, alpha):
    """Double arrow between the primary and the secondary color (along the top-left diagonal)."""
    theme = dc.theme
    r = min(size * 0.5, theme.px(12.0))
    color = with_alpha(theme.text, 0.9 * alpha)
    ux, uy = math.cos(math.radians(45.0)), math.sin(math.radians(45.0))
    length, head = r * 0.8, r * 0.4
    a = (x - ux * length, y - uy * length)
    b = (x + ux * length, y + uy * length)
    draw.polyline([a, b], color, max(1.0, theme.px(1.5)))
    for (tx, ty), d in ((a, -1.0), (b, 1.0)):
        bx, by = tx - ux * head * d, ty - uy * head * d
        draw.triangle((tx, ty), (bx - uy * head * 0.6, by + ux * head * 0.6),
                      (bx + uy * head * 0.6, by - ux * head * 0.6), color)


def thick_line(a, b, width, color):
    draw.gradient_line(a, b, color, color, width)


def paint_eyedropper(dc, x, y, size, alpha, color=None):
    """Picker icon: an eyedropper, bulb top right, tip bottom left."""
    theme = dc.theme
    s = min(size * 0.62, theme.px(24.0))
    color = with_alpha(theme.text, 0.92 * alpha) if color is None else color
    ux = uy = math.sqrt(0.5)
    tip = (x - ux * s * 0.5, y - uy * s * 0.5)
    neck = (x + ux * s * 0.12, y + uy * s * 0.12)
    thick_line(tip, neck, s * 0.16, color)
    thick_line((neck[0] + uy * s * 0.2, neck[1] - ux * s * 0.2),
                (neck[0] - uy * s * 0.2, neck[1] + ux * s * 0.2), s * 0.12, color)
    draw.circle(x + ux * s * 0.3, y + uy * s * 0.3, s * 0.17, color, segments=16)


def paint_target_picker(rgb, active):
    """Picker for one color (``rgb()``): bright while that color is the active one
    (``active()``), grey otherwise; a dot of the color at its tip."""
    def paint(dc, x, y, size, alpha):
        theme = dc.theme
        on = _resolve(active, False)
        ink = (1.0, 1.0, 1.0, alpha) if on else with_alpha(theme.text_muted, 0.55 * alpha)
        paint_eyedropper(dc, x, y, size, alpha, color=ink)
        c = _resolve(rgb, None)
        if c is not None:
            s = min(size * 0.62, theme.px(24.0))
            dx = dy = -math.sqrt(0.5) * s * 0.5     # the eyedropper's tip
            dx, dy = x + dx, y + dy
            dot = (c[0], c[1], c[2], alpha if on else 0.6 * alpha)
            draw.circle(dx, dy, max(2.0, s * 0.16), dot, rim=theme.edge_for(c, dot[3]), segments=16)
    return paint


def paint_color_wheel(rgb):
    """Color icon: a hue ring around the color the pen paints."""
    def paint(dc, x, y, size, alpha):
        theme = dc.theme
        r = min(size * 0.36, theme.px(13.0))
        steps = 24
        for i in range(steps):
            c = colorsys.hsv_to_rgb(i / steps, 0.85, 1.0)
            draw.sector(x, y, r, math.tau * i / steps, math.tau * (i + 1) / steps, (*c, alpha), segments=2)
        draw.circle(x, y, r * 0.6, with_alpha(theme.surface_dark, alpha), segments=24)
        cur = _resolve(rgb, (1.0, 1.0, 1.0))
        draw.circle(x, y, r * 0.42, (cur[0], cur[1], cur[2], alpha), segments=24)
    return paint


def paint_sliders(dc, x, y, size, alpha):
    """Channel sliders icon: three bars with knobs."""
    theme = dc.theme
    w = size * 0.34
    color = with_alpha(theme.text, 0.9 * alpha)
    for row, knob in ((1, 0.35), (0, -0.4), (-1, 0.1)):
        cy = y + row * size * 0.2
        draw.polyline([(x - w, cy), (x + w, cy)], color, max(1.0, size * 0.06))
        draw.circle(x + knob * w, cy, size * 0.08, color, segments=12)


def paint_gear(dc, x, y, size, alpha):
    """Settings icon: a gear."""
    theme = dc.theme
    r = min(size * 0.34, theme.px(12.0))
    color = with_alpha(theme.text, 0.92 * alpha)
    for k in range(8):
        a = k * math.pi / 4.0
        thick_line((x + math.cos(a) * r * 0.55, y + math.sin(a) * r * 0.55),
                    (x + math.cos(a) * r, y + math.sin(a) * r), r * 0.34, color)
    draw.circle(x, y, r * 0.74, color, segments=24)
    draw.circle(x, y, r * 0.32, with_alpha(theme.surface_dark, alpha), segments=16)


def paint_windows(dc, x, y, size, alpha):
    """Windows icon: two overlapping windows (title bars), the front one filled."""
    theme = dc.theme
    s = min(size * 0.3, theme.px(11.0))
    color = with_alpha(theme.text, 0.92 * alpha)
    width = max(1.0, theme.px(1.2))
    back = Rect.from_center(x - s * 0.35, y + s * 0.35, s * 1.5, s * 1.15)
    draw.rect_outline(back, color, width=width)
    draw.rect(Rect(back.x0, back.y1 - s * 0.25, back.x1, back.y1), color)
    front = Rect.from_center(x + s * 0.35, y - s * 0.35, s * 1.5, s * 1.15)
    draw.rect(front, with_alpha(theme.surface_dark, alpha))
    draw.rect_outline(front, color, width=width)
    draw.rect(Rect(front.x0, front.y1 - s * 0.25, front.x1, front.y1), color)


def captioned(painter, text):
    """``painter`` moved up and shrunk a bit, ``text`` under it (Windows popup entries)."""
    def paint(dc, x, y, size, alpha):
        painter(dc, x, y + size * 0.12, size * 0.8, alpha)
        draw_caption(dc, x, y - size * 0.36, text, alpha)
    return paint


def paint_save(unsaved, caption=True):
    """Save icon: a floppy disk; a dot in the accent color while ``unsaved()``."""
    def paint(dc, x, y, size, alpha):
        theme = dc.theme
        s = min(size * 0.5, theme.px(20.0 if caption else 14.0))
        color = with_alpha(theme.text, 0.92 * alpha)
        body = Rect.from_center(x, y, s, s)
        draw.rect(body, color)
        hole = with_alpha(theme.surface_dark, alpha)
        draw.rect(Rect(body.x0 + s * 0.22, body.y1 - s * 0.34, body.x1 - s * 0.22, body.y1 - s * 0.06), hole)
        draw.rect(Rect(body.x0 + s * 0.16, body.y0 + s * 0.1, body.x1 - s * 0.16, body.y0 + s * 0.48), hole)
        if _resolve(unsaved, False):
            dot = (*TINT_SAVE, alpha)
            draw.circle(body.x1, body.y1, max(2.5, s * 0.2), dot, rim=theme.edge_for(TINT_SAVE, alpha), segments=16)
        if caption:
            draw.text_centered("Save", x, body.y0 - theme.px(7.0), theme.px(8.0),
                               with_alpha(theme.text_muted, alpha), theme.font_id)
    return paint


def draw_caption(dc, x, y, text, alpha):
    theme = dc.theme
    draw.text_centered(text, x, y, theme.px(7.5), with_alpha(theme.text_muted, alpha), theme.font_id)


def paint_mask(dc, x, y, size, alpha, caption=True):
    """Mask on / off: a square, half texture (light) and half protected (dark)."""
    theme = dc.theme
    s = min(size * (0.42 if caption else 0.55), theme.px(16.0))
    box = Rect.from_center(x, y + (s * 0.2 if caption else 0.0), s, s)
    draw.rect(Rect(box.x0, box.y0, box.cx, box.y1), (0.85, 0.85, 0.85, alpha))
    draw.rect(Rect(box.cx, box.y0, box.x1, box.y1), (0.12, 0.12, 0.12, alpha))
    draw.rect_outline(box, with_alpha(theme.text, 0.9 * alpha), width=max(1.0, theme.px(1.0)))
    if caption:
        draw_caption(dc, x, box.y0 - theme.px(6.0), "Mask", alpha)


def paint_mask_menu(enabled):
    """Mask window button: the mask icon; a dot in the mask's tint while the mask is on."""
    def paint(dc, x, y, size, alpha):
        paint_mask(dc, x, y, size, alpha)
        if _resolve(enabled, False):
            theme = dc.theme
            s = min(size * 0.42, theme.px(16.0))
            draw.circle(x + s * 0.5, y + s * 0.7, max(2.5, s * 0.2), (*TINT_MASK, alpha),
                        rim=theme.edge_for(TINT_MASK, alpha), segments=16)
    return paint


def paint_view(dc, x, y, size, alpha):
    """View window button: a camera (body, lens, viewfinder) with a caption."""
    theme = dc.theme
    s = min(size * 0.42, theme.px(16.0))
    color = with_alpha(theme.text, 0.92 * alpha)
    cy = y + s * 0.2
    body = Rect.from_center(x, cy, s * 1.3, s * 0.85)
    draw.rect(body, color)
    draw.rect(Rect(body.x0 + s * 0.15, body.y1, body.x0 + s * 0.55, body.y1 + s * 0.18), color)
    draw.circle(x, cy, s * 0.3, with_alpha(theme.surface_dark, alpha), segments=16)
    draw.circle(x, cy, s * 0.15, color, segments=12)
    if size > theme.px(30.0):
        draw_caption(dc, x, body.y0 - theme.px(6.0), "View", alpha)


def paint_mask_source(source, caption=True):
    """UV Islands / Mesh Parts: the source in big letters."""
    def paint(dc, x, y, size, alpha):
        theme = dc.theme
        uv = _resolve(source, 'UV_ISLAND') != 'MESH_PART'
        draw.text_centered("UV" if uv else "Mesh", x, y + (size * 0.1 if caption else 0.0),
                           theme.px(11.0 if uv else 9.0), with_alpha(theme.text, alpha), theme.font_id)
        if caption:
            draw_caption(dc, x, y - size * 0.25, "Islands" if uv else "Parts", alpha)
    return paint


def paint_mask_invert(dc, x, y, size, alpha, caption=True):
    """Invert: a disc, half light and half dark."""
    theme = dc.theme
    r = min(size * (0.22 if caption else 0.3), theme.px(9.0))
    cy = y + (r * 0.45 if caption else 0.0)
    draw.sector(x, cy, r, math.pi * 0.5, math.pi * 1.5, (0.85, 0.85, 0.85, alpha), segments=12)
    draw.sector(x, cy, r, -math.pi * 0.5, math.pi * 0.5, (0.12, 0.12, 0.12, alpha), segments=12)
    draw.circle_outline(x, cy, r, with_alpha(theme.text, 0.9 * alpha), width=max(1.0, theme.px(1.0)))
    if caption:
        draw_caption(dc, x, cy - r - theme.px(6.0), "Invert", alpha)


def paint_mask_pick(dc, x, y, size, alpha, caption=True):
    """Edit (the mask): a target (tap islands)."""
    theme = dc.theme
    s = min(size * (0.4 if caption else 0.55), theme.px(15.0))
    color = with_alpha(theme.text, 0.92 * alpha)
    cy = y + (s * 0.25 if caption else 0.0)
    draw.circle_outline(x, cy, s * 0.5, color, width=max(1.0, theme.px(1.0)))
    draw.circle(x, cy, s * 0.16, color, segments=12)
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        draw.polyline([(x + dx * s * 0.55, cy + dy * s * 0.55), (x + dx * s * 0.8, cy + dy * s * 0.8)],
                      color, max(1.0, theme.px(1.0)))
    if caption:
        draw_caption(dc, x, cy - s * 0.8 - theme.px(5.0), "Edit", alpha)


def paint_curve(dc, x, y, size, alpha):
    """Curve button icon: a falloff curve with anchors."""
    theme = dc.theme
    s = min(size * 0.6, theme.px(24.0))
    color = with_alpha((*TINT_CUSTOM, 1.0), alpha)
    x0, y0 = x - s * 0.5, y - s * 0.4
    pts = []
    for i in range(17):
        t = i / 16.0
        pts.append((x0 + s * t, y0 + s * 0.8 * (1.0 - t * t * (3.0 - 2.0 * t))))
    draw.polyline([(x0, y0), (x0 + s, y0)], with_alpha(theme.text_muted, alpha), 1.0)
    draw.polyline(pts, color, max(1.0, theme.px(2.0)))
    for i in (0, 8, 16):
        draw.circle(pts[i][0], pts[i][1], max(1.5, s * 0.08), with_alpha(theme.text, alpha), segments=12)


# ---- dial segment content: painter(dc, x, y, size, alpha) --------------------------------

def paint_arrow(direction, caption):
    """Undo / Redo: a horizontal arrow with a caption under it."""
    def paint(dc, x, y, size, alpha):
        theme = dc.theme
        s = min(size * 0.55, theme.px(22.0))
        color = with_alpha(theme.text, 0.92 * alpha)
        d = 1.0 if direction == 'RIGHT' else -1.0
        ay = y + s * 0.15
        tip, tail = x + d * s * 0.5, x - d * s * 0.5
        base = tip - d * s * 0.45
        shaft = s * 0.13
        draw.rect(Rect(min(tail, base), ay - shaft, max(tail, base), ay + shaft), color)
        draw.triangle((tip, ay), (base, ay + s * 0.36), (base, ay - s * 0.36), color)
        draw.text_centered(caption, x, ay - s * 0.75, theme.px(8.0),
                           with_alpha(theme.text_muted, alpha), theme.font_id)
    return paint


def paint_alpha_lock(dc, x, y, size, alpha):
    """Checkerboard (transparency) with a padlock on it."""
    theme = dc.theme
    s = size * 0.62
    half = s * 0.5
    light, dark = (0.78, 0.78, 0.78, alpha), (0.48, 0.48, 0.48, alpha)
    for i in range(2):
        for j in range(2):
            draw.rect(Rect.from_size(x - half + i * half, y - half + j * half, half, half),
                      light if (i + j) % 2 else dark)
    lock = (0.07, 0.07, 0.07, alpha)
    bw, bh = s * 0.5, s * 0.36
    body = Rect.from_size(x - bw * 0.5, y - s * 0.32, bw, bh)
    draw.rect(body, lock)
    draw.arc(x, body.y1, bw * 0.3, 0.0, math.pi, lock, width=max(1.0, theme.px(2.0)), segments=16)


def paint_spacing(mode):
    """Pixel / Free: the initial with a small square (solid for Pixel, fading for Free)."""
    def paint(dc, x, y, size, alpha):
        theme = dc.theme
        pixel = _resolve(mode, 'FREE') == 'PIXEL'
        letter = theme.px(15.0)
        draw.text_centered("P" if pixel else "F", x - letter * 0.12, y + size * 0.12, letter,
                           with_alpha(theme.text, alpha), theme.font_id)
        sq = letter * 0.32
        box = Rect.from_size(x + letter * 0.22, y + size * 0.12 - letter * 0.42, sq, sq)
        if pixel:
            draw.rect(box, (1.0, 1.0, 1.0, alpha))
        else:
            draw.gradient_quad(box, (1.0, 1.0, 1.0, alpha), (1.0, 1.0, 1.0, 0.1 * alpha),
                               (1.0, 1.0, 1.0, 0.1 * alpha), (1.0, 1.0, 1.0, alpha))
        draw.text_centered("Pixel" if pixel else "Free", x, y - size * 0.3, theme.px(7.5),
                           with_alpha(theme.text_muted, alpha), theme.font_id)
    return paint
