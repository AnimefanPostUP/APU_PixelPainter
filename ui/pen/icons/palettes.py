"""Icons of the palette library flyout.
"""

from ...kit import Rect
from ...kit import draw
from ...kit.theme import mix, with_alpha
from ..style import DANGER


# ---- icons: painter(dc, x, y, size, alpha) ------------------------------------------------

def _ink(dc, alpha, amount=0.92):
    return with_alpha(dc.theme.text, amount * alpha)


def paint_palettes(dc, x, y, size, alpha):
    """Palette view icon: three fanned color cards."""
    s = size * 0.3
    for i, color in enumerate(((0.95, 0.35, 0.35), (0.35, 0.8, 0.4), (0.35, 0.55, 0.95))):
        dx = (i - 1) * s * 0.45
        dy = (1 - abs(i - 1)) * s * 0.15
        card = Rect.from_center(x + dx, y + dy, s * 0.9, s * 1.3)
        draw.rect(card, (*color, alpha))
        draw.rect_outline(card, _ink(dc, alpha, 0.7), width=1.0)


def paint_library(dc, x, y, size, alpha):
    """Library icon: a shelf with books."""
    s = size * 0.32
    color = _ink(dc, alpha)
    for i, (h, c) in enumerate(((1.0, (0.95, 0.55, 0.3)), (0.8, (0.45, 0.75, 0.95)), (0.95, (0.6, 0.85, 0.4)))):
        bx = x - s * 0.7 + i * s * 0.55
        draw.rect(Rect(bx, y - s * 0.75, bx + s * 0.42, y - s * 0.75 + s * 1.5 * h), (*c, alpha))
    draw.rect(Rect(x - s, y - s * 0.95, x + s, y - s * 0.78), color)


def paint_copy(dc, x, y, size, alpha):
    s = size * 0.22
    color = _ink(dc, alpha)
    draw.rect_outline(Rect.from_center(x - s * 0.35, y + s * 0.35, s * 1.4, s * 1.6), color, width=1.5)
    draw.rect(Rect.from_center(x + s * 0.35, y - s * 0.35, s * 1.4, s * 1.6), color)


def paint_paste(dc, x, y, size, alpha):
    s = size * 0.24
    color = _ink(dc, alpha)
    draw.rect_outline(Rect.from_center(x, y - s * 0.1, s * 1.6, s * 1.9), color, width=1.5)
    draw.rect(Rect.from_center(x, y + s * 0.85, s * 0.8, s * 0.35), color)


def paint_trash(dc, x, y, size, alpha):
    s = size * 0.22
    color = with_alpha(mix(dc.theme.text, DANGER, 0.5), alpha)
    draw.rect(Rect(x - s * 0.7, y - s, x + s * 0.7, y + s * 0.55), color)
    draw.rect(Rect(x - s, y + s * 0.7, x + s, y + s * 0.9), color)
    draw.rect(Rect(x - s * 0.3, y + s * 0.9, x + s * 0.3, y + s * 1.1), color)


def paint_save(dc, x, y, size, alpha):
    """Save to library: an arrow into a tray."""
    s = size * 0.24
    color = _ink(dc, alpha)
    draw.rect(Rect(x - s * 0.12, y - s * 0.1, x + s * 0.12, y + s), color)
    draw.triangle((x, y - s * 0.55), (x - s * 0.5, y), (x + s * 0.5, y), color)
    draw.rect(Rect(x - s, y - s, x + s, y - s * 0.8), color)


def paint_image(dc, x, y, size, alpha):
    """From image: a framed picture with a mountain and a sun."""
    s = size * 0.26
    frame = Rect.from_center(x, y, s * 2.2, s * 1.7)
    draw.rect_outline(frame, _ink(dc, alpha), width=1.5)
    draw.triangle((frame.x0 + s * 0.2, frame.y0 + s * 0.2), (x - s * 0.1, y + s * 0.45),
                  (x + s * 0.5, frame.y0 + s * 0.2), (0.45, 0.8, 0.5, alpha))
    draw.circle(x + s * 0.55, y + s * 0.35, s * 0.22, (1.0, 0.85, 0.3, alpha), segments=12)


def library_arrow(direction):
    def paint(dc, x, y, size, alpha):
        s = size * 0.2 * direction
        draw.triangle((x + s, y), (x - s, y + abs(s)), (x - s, y - abs(s)), _ink(dc, alpha))
    return paint
