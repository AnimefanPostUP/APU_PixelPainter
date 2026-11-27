"""Icons of the Mask and View windows.
"""

import math

from ...kit import Rect
from ...kit import draw
from ...kit.theme import with_alpha
from ...kit.widget import _resolve
from .menu import paint_mask, paint_mask_pick, paint_view, thick_line
from ..windows.parts import FONT, LINE


# ---- icons: painter(dc, x, y, size, alpha) ----------------------------------------------

def paint_edit(dc, x, y, size, alpha):
    """The Mask window's center: Edit (choose islands / parts on the canvas)."""
    paint_mask_pick(dc, x, y, size, alpha, caption=True)


SOURCE_NAMES = {'UV_ISLAND': "UV Islands", 'MESH_PART': "Mesh Parts", 'SHARP': "Sharp Areas"}


SOURCE_SHORT = {'UV_ISLAND': "UV", 'MESH_PART': "Mesh", 'SHARP': "Sharp"}


def paint_source_name(source_id):
    """One source's short name (the Extras window's UV / Mesh / Sharp buttons)."""
    def paint(dc, x, y, size, alpha):
        theme = dc.theme
        draw.text_centered(SOURCE_SHORT.get(source_id, source_id), x, y, theme.px(FONT * 0.9),
                           with_alpha(theme.text, alpha), theme.font_id)
    return paint


def source_options(source):
    """``(count, index)`` of ``source`` among the sources (the source arc's option dots;
    same order as the cycle a tap steps through)."""
    order = list(SOURCE_NAMES)
    return len(order), order.index(source) if source in order else 0


def paint_source_band(source):
    """The source arc: 'UV Islands' / 'Mesh Parts' / 'Sharp Areas' written on it."""
    def paint(dc, x, y, size, alpha):
        theme = dc.theme
        text = SOURCE_NAMES.get(_resolve(source, 'UV_ISLAND'), "UV Islands")
        draw.text_centered(text, x, y, theme.px(FONT * 0.9), with_alpha(theme.text, alpha), theme.font_id)
    return paint


def icon_compact(compact):
    """Compact View window: two dials, the right one dashed while it is hidden."""
    def paint(dc, x, y, size, alpha):
        theme = dc.theme
        r = min(size * 0.2, theme.px(6.0))
        color = with_alpha(theme.text, 0.92 * alpha)
        w = _stroke(theme)
        draw.circle_outline(x - r * 1.15, y, r, color, width=w * 1.4)
        draw.circle(x - r * 1.15, y, r * 0.35, color, segments=12)
        if _resolve(compact, False):
            for k in range(6):
                a0 = math.tau * k / 6.0
                draw.arc(x + r * 1.15, y, r, a0, a0 + math.tau / 12.0, with_alpha(color, 0.6), width=w)
        else:
            draw.circle_outline(x + r * 1.15, y, r, color, width=w * 1.4)
            draw.circle(x + r * 1.15, y, r * 0.35, color, segments=12)
    return paint


def _stroke(theme):
    return max(1.0, theme.px(LINE))


def icon_face(side):
    """A cube face (square) seen from ``side``: Front = filled; else the edge facing
    that side is a solid strip (Top: upper edge ...), like an unfolded cube."""
    def paint(dc, x, y, size, alpha):
        theme = dc.theme
        s = min(size * 0.62, theme.px(16.0))
        box = Rect.from_center(x, y, s, s)
        color = with_alpha(theme.text, 0.92 * alpha)
        if side == 'FRONT':
            draw.rect(box, with_alpha(theme.text, 0.75 * alpha))
            return
        draw.rect(box, with_alpha(theme.text, 0.12 * alpha))
        draw.rect_outline(box, with_alpha(theme.text, 0.6 * alpha), width=_stroke(theme))
        t = s * 0.3
        strip = {'TOP': Rect(box.x0, box.y1 - t, box.x1, box.y1),
                 'BOTTOM': Rect(box.x0, box.y0, box.x1, box.y0 + t),
                 'LEFT': Rect(box.x0, box.y0, box.x0 + t, box.y1),
                 'RIGHT': Rect(box.x1 - t, box.y0, box.x1, box.y1)}[side]
        draw.rect(strip, color)
    return paint


def icon_back(dc, x, y, size, alpha):
    """Back: a dashed square (the hidden face) with a turn-around arrow."""
    theme = dc.theme
    s = min(size * 0.62, theme.px(16.0)) * 0.5
    color = with_alpha(theme.text, 0.92 * alpha)
    w = _stroke(theme)
    dash = with_alpha(theme.text, 0.55 * alpha)
    corners = [(x - s, y - s), (x + s, y - s), (x + s, y + s), (x - s, y + s)]
    for (ax, ay), (bx, by) in zip(corners, corners[1:] + corners[:1]):
        for k in range(3):
            t0, t1 = (k * 2 + 0.3) / 6.0, (k * 2 + 1.3) / 6.0
            draw.polyline([(ax + (bx - ax) * t0, ay + (by - ay) * t0), (ax + (bx - ax) * t1, ay + (by - ay) * t1)],
                          dash, w)
    r = s * 0.55
    draw.arc(x, y, r, math.radians(200.0), math.radians(-20.0) + 2.0 * math.pi, color, width=w * 1.4, segments=20)
    end = math.radians(-20.0)
    px, py = x + math.cos(end) * r, y + math.sin(end) * r
    h = r * 0.75
    draw.triangle((px - h * 0.1, py - h * 0.9), (px + h * 0.6, py + h * 0.2), (px - h * 0.6, py + h * 0.2), color)


def icon_arrow(angle_deg):
    """A straight arrow pointing at ``angle_deg`` (0 = right, 90 = up)."""
    def paint(dc, x, y, size, alpha):
        theme = dc.theme
        s = min(size * 0.32, theme.px(8.0))
        color = with_alpha(theme.text, 0.92 * alpha)
        a = math.radians(angle_deg)
        dx, dy = math.cos(a), math.sin(a)
        tip = (x + dx * s, y + dy * s)
        base = (x + dx * s * 0.05, y + dy * s * 0.05)
        thick_line((x - dx * s, y - dy * s), base, _stroke(theme) * 1.6, color)
        nx, ny = -dy, dx
        draw.triangle(tip, (base[0] + nx * s * 0.6, base[1] + ny * s * 0.6),
                      (base[0] - nx * s * 0.6, base[1] - ny * s * 0.6), color)
    return paint


def icon_roll(direction):
    """A curved arrow: ``direction`` +1 counter-clockwise, -1 clockwise."""
    def paint(dc, x, y, size, alpha):
        theme = dc.theme
        r = min(size * 0.26, theme.px(6.5))
        color = with_alpha(theme.text, 0.92 * alpha)
        a0, a1 = math.radians(-50.0), math.radians(210.0)
        draw.arc(x, y, r, a0, a1, color, width=_stroke(theme) * 1.4, segments=20)
        end = a1 if direction > 0 else a0
        px, py = x + math.cos(end) * r, y + math.sin(end) * r
        tx, ty = -math.sin(end) * direction, math.cos(end) * direction     # travel direction
        nx, ny = -ty, tx
        h = r * 0.75
        draw.triangle((px + tx * h, py + ty * h), (px + nx * h * 0.6, py + ny * h * 0.6),
                      (px - nx * h * 0.6, py - ny * h * 0.6), color)
    return paint


def icon_level(dc, x, y, size, alpha):
    """A spirit level: a bar with a bubble in the middle."""
    theme = dc.theme
    s = min(size * 0.34, theme.px(8.0))
    color = with_alpha(theme.text, 0.92 * alpha)
    tube = Rect.from_center(x, y, s * 2.0, s * 0.7)
    draw.rect_outline(tube, color, width=_stroke(theme))
    draw.circle(x, y, s * 0.22, color, segments=12)
    for sx in (-1, 1):
        draw.polyline([(x + sx * s * 0.45, tube.y0), (x + sx * s * 0.45, tube.y1)], color, _stroke(theme))


def icon_fit(dc, x, y, size, alpha):
    """Four corner brackets around a dot."""
    theme = dc.theme
    s = min(size * 0.3, theme.px(7.5))
    color = with_alpha(theme.text, 0.92 * alpha)
    w = _stroke(theme) * 1.4
    for sx in (-1, 1):
        for sy in (-1, 1):
            cx, cy = x + sx * s, y + sy * s
            thick_line((cx, cy), (cx - sx * s * 0.55, cy), w, color)
            thick_line((cx, cy), (cx, cy - sy * s * 0.55), w, color)
    draw.circle(x, y, s * 0.3, color, segments=12)


def icon_center(dc, x, y, size, alpha):
    """A crosshair."""
    theme = dc.theme
    s = min(size * 0.3, theme.px(7.5))
    color = with_alpha(theme.text, 0.92 * alpha)
    w = _stroke(theme)
    draw.circle_outline(x, y, s * 0.6, color, width=w)
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        thick_line((x + dx * s * 0.3, y + dy * s * 0.3), (x + dx * s, y + dy * s), w, color)


def icon_zoom(sign):
    """A magnifier with + / -."""
    def paint(dc, x, y, size, alpha):
        theme = dc.theme
        s = min(size * 0.28, theme.px(7.0))
        color = with_alpha(theme.text, 0.92 * alpha)
        w = _stroke(theme)
        gx, gy, gr = x - s * 0.2, y + s * 0.2, s * 0.72
        draw.circle_outline(gx, gy, gr, color, width=w)
        thick_line((gx + gr * 0.7, gy - gr * 0.7), (x + s, y - s), w * 2.0, color)
        thick_line((gx - gr * 0.5, gy), (gx + gr * 0.5, gy), w, color)
        if sign > 0:
            thick_line((gx, gy - gr * 0.5), (gx, gy + gr * 0.5), w, color)
    return paint


def icon_perspective(persp):
    """A trapezoid (perspective) or a square (orthographic) with a center line."""
    def paint(dc, x, y, size, alpha):
        theme = dc.theme
        s = min(size * 0.3, theme.px(7.5))
        color = with_alpha(theme.text, 0.92 * alpha)
        w = _stroke(theme)
        top = s * (0.45 if _resolve(persp, True) else 1.0)
        draw.polyline([(x - s, y - s), (x + s, y - s), (x + top, y + s), (x - top, y + s)], color, w, closed=True)
        draw.polyline([(x, y - s), (x, y + s)], color, w)
    return paint


def icon_mask_title(dc, x, y, size, alpha):
    paint_mask(dc, x, y, size * 1.4, alpha, caption=False)


def paint_view_title(dc, x, y, size, alpha):
    paint_view(dc, x, y - size * 0.15, size * 1.6, alpha)
