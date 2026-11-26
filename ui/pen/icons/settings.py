"""Icons of the pen settings window's tabs and rows.
"""

import colorsys
import math

from ...kit import Rect
from ...kit import draw
from ...kit.theme import with_alpha
from .menu import paint_curve, thick_line


# ---- icons: painter(dc, x, y, size, alpha) ------------------------------------------------

def _ink(dc, alpha, amount=0.92):
    return with_alpha(dc.theme.text, amount * alpha)


def icon_brush(dc, x, y, size, alpha):
    s = size * 0.6
    color = _ink(dc, alpha)
    thick_line((x + s * 0.45, y + s * 0.45), (x - s * 0.05, y - s * 0.05), s * 0.13, color)
    draw.circle(x - s * 0.22, y - s * 0.22, s * 0.24, color, segments=16)


def icon_blend(dc, x, y, size, alpha):
    r = size * 0.24
    draw.circle(x - r * 0.45, y, r, (0.15, 0.15, 0.15, alpha), segments=20)
    draw.circle(x + r * 0.45, y, r, (1.0, 1.0, 1.0, 0.7 * alpha), segments=20)
    draw.circle_outline(x - r * 0.45, y, r, _ink(dc, alpha, 0.6), width=1.0, segments=20)


def icon_falloff(dc, x, y, size, alpha):
    paint_curve(dc, x, y, size * 1.2, alpha)


def icon_pen(dc, x, y, size, alpha):
    s = size * 0.6
    color = _ink(dc, alpha)
    ux = uy = math.sqrt(0.5)
    tip = (x - ux * s * 0.5, y - uy * s * 0.5)
    base = (x - ux * s * 0.2, y - uy * s * 0.2)
    thick_line(base, (x + ux * s * 0.5, y + uy * s * 0.5), s * 0.22, color)
    draw.triangle(tip, (base[0] - uy * s * 0.11, base[1] + ux * s * 0.11),
                  (base[0] + uy * s * 0.11, base[1] - ux * s * 0.11), color)


def icon_eye(dc, x, y, size, alpha):
    w, h = size * 0.34, size * 0.2
    color = _ink(dc, alpha)
    top = [(x - w + 2 * w * i / 16, y + h * math.sin(math.pi * i / 16)) for i in range(17)]
    bottom = [(px, y - (py - y)) for px, py in top]
    draw.polyline(top, color, 1.5)
    draw.polyline(bottom, color, 1.5)
    draw.circle(x, y, h * 0.7, color, segments=16)


def icon_keyboard(dc, x, y, size, alpha):
    w, h = size * 0.36, size * 0.22
    color = _ink(dc, alpha)
    draw.rect_outline(Rect(x - w, y - h, x + w, y + h), color, width=1.5)
    k = w * 0.22
    for row, keys in ((0.35, 5), (-0.15, 5)):
        for i in range(keys):
            kx = x - w + w * 2.0 * (i + 0.5) / keys
            draw.rect(Rect.from_center(kx, y + h * row, k, k * 0.8), color)
    draw.rect(Rect.from_center(x, y - h * 0.6, w * 1.1, k * 0.7), color)


def icon_reset(dc, x, y, size, alpha):
    r = size * 0.28
    color = _ink(dc, alpha)
    draw.arc(x, y, r, math.radians(60), math.radians(360), color, width=max(1.0, size * 0.07), segments=24)
    hx, hy = x + math.cos(math.radians(60)) * r, y + math.sin(math.radians(60)) * r
    head = r * 0.5
    draw.triangle((hx + head * 0.9, hy + head * 0.1), (hx - head * 0.3, hy + head * 0.7),
                  (hx - head * 0.1, hy - head * 0.6), color)


def icon_pressure(dc, x, y, size, alpha):
    color = _ink(dc, alpha)
    w = size * 0.1
    for i, h in enumerate((0.25, 0.45, 0.65)):
        bx = x + (i - 1) * w * 1.7
        draw.rect(Rect(bx - w * 0.5, y - size * 0.3, bx + w * 0.5, y - size * 0.3 + size * h), color)


def icon_bolt(dc, x, y, size, alpha):
    s = size * 0.3
    color = _ink(dc, alpha)
    draw.triangle((x + s * 0.35, y + s * 1.05), (x - s * 0.55, y - s * 0.1), (x + s * 0.05, y - s * 0.1), color)
    draw.triangle((x - s * 0.35, y - s * 1.05), (x + s * 0.55, y + s * 0.1), (x - s * 0.05, y + s * 0.1), color)


def icon_grid(dc, x, y, size, alpha):
    w = size * 0.3
    color = _ink(dc, alpha, 0.8)
    for i in range(4):
        t = -w + 2.0 * w * i / 3.0
        draw.polyline([(x + t, y - w), (x + t, y + w)], color, 1.0)
        draw.polyline([(x - w, y + t), (x + w, y + t)], color, 1.0)


def icon_layout(kind):
    """Color selector layout glyphs: Sheet, Square, Triangle, Wheel."""
    def paint(dc, x, y, size, alpha):
        s = size * 0.36
        if kind == 'SHEET':
            steps = 12
            for i in range(steps):
                c = colorsys.hsv_to_rgb(i / steps, 1.0, 1.0)
                cell = Rect(x - s + 2 * s * i / steps, y - s * 0.7, x - s + 2 * s * (i + 1) / steps, y + s * 0.7)
                draw.gradient_quad(cell, (0, 0, 0, alpha), (0, 0, 0, alpha), (*c, alpha), (*c, alpha))
        elif kind == 'SQUARE':
            r = Rect(x - s * 0.8, y - s * 0.8, x + s * 0.8, y + s * 0.8)
            draw.gradient_quad(r, (0, 0, 0, alpha), (0, 0, 0, alpha), (1, 0.1, 0.1, alpha), (1, 1, 1, alpha))
        elif kind == 'TRIANGLE':
            for i in range(24):
                c = colorsys.hsv_to_rgb(i / 24, 1.0, 1.0)
                draw.sector(x, y, s, math.tau * i / 24, math.tau * (i + 1) / 24, (*c, alpha), segments=2)
            draw.circle(x, y, s * 0.75, with_alpha(dc.theme.surface_dark, alpha), segments=24)
            p = [(x + math.cos(a) * s * 0.7, y + math.sin(a) * s * 0.7)
                 for a in (math.radians(90), math.radians(210), math.radians(330))]
            draw.shaded_tris(p, [(1, 0.1, 0.1, alpha), (0, 0, 0, alpha), (1, 1, 1, alpha)])
        else:
            for i in range(24):
                c = colorsys.hsv_to_rgb(i / 24, 1.0, 1.0)
                draw.sector(x, y, s, math.tau * i / 24, math.tau * (i + 1) / 24, (*c, alpha), segments=2)
            draw.circle(x, y, s * 0.35, (1, 1, 1, 0.8 * alpha), segments=16)
    return paint
