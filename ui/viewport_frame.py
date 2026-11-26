"""A frame around the editor: a colored line with rounded corners, a little inside the
region border, with a gap at the top where a small label sits.

Generic -- any mode can show one to say "you are in a special mode" (Mask editing does,
see ``tools/mask.py``). Call :func:`draw_frame` from a POST_PIXEL overlay of the region.
"""

from .kit import draw
from .kit.geometry import Rect
from .kit.theme import Theme, with_alpha

INSET = 6.0          # unscaled px: from the region border to the line
TOP_EXTRA = 14.0     # unscaled px: the top line sits this much lower still (clear of the
                     # editor's own overlays along the top edge), below any overlapping header
WIDTH = 2.0          # line width, unscaled px
ROUND = 10.0         # corner radius, unscaled px
LABEL_SIZE = 10.0    # label font size, unscaled px
LABEL_PAD = 6.0      # room on each side of the label inside the gap
_CORNER_STEPS = 8

MASK_EDIT_COLOR = (1.0, 0.55, 0.15)     # orange
MASK_EDIT_LABEL = "Pixelpainter - Editing Mask"


def frame_path(rect, radius, gap_width):
    """Points of the frame along ``rect`` (rounded by ``radius``), as one open line that
    leaves a gap ``gap_width`` px wide in the middle of the top edge (0: closed)."""
    steps = _CORNER_STEPS
    pts = draw.rounded_rect_points(rect, radius, steps=steps)
    if gap_width <= 0.0 or len(pts) < 4 * (steps + 1):
        return pts, True
    half = min(gap_width * 0.5, max(0.0, rect.width * 0.5 - radius))
    # rounded_rect_points runs counter-clockwise from the bottom-right corner: the
    # top-left corner's points start at index 2 * (steps + 1).
    n = 2 * (steps + 1)
    return [(rect.cx - half, rect.y1)] + pts[n:] + pts[:n] + [(rect.cx + half, rect.y1)], False


def top_cover(area, region):
    """Screen px at the top of ``region`` covered by overlapping header regions (the
    header and the tool settings bar with Region Overlap on); 0 when none overlap."""
    if area is None or region is None:
        return 0.0
    top = region.y + region.height
    cover = 0.0
    for other in area.regions:
        if other.type not in {'HEADER', 'TOOL_HEADER'} or other.width <= 1 or other.height <= 1:
            continue
        # A header at the region's top whose bottom edge reaches into the region.
        if region.y + region.height * 0.5 < other.y < top:
            cover = max(cover, top - other.y)
    return cover


def draw_frame(width, height, color, label=None, theme=None, alpha=1.0, top=0.0):
    """Frame around a ``width`` x ``height`` region in ``color`` (RGB / RGBA), with
    ``label`` (optional) in a gap at the top. ``top``: screen px covered at the top
    (overlapping headers, :func:`top_cover`) -- the frame starts below them."""
    theme = theme or Theme()
    rgba = (*color[:3], (color[3] if len(color) > 3 else 1.0) * alpha)
    inset = theme.px(INSET)
    top_inset = inset + max(0.0, top) + theme.px(TOP_EXTRA)
    rect = Rect(inset, inset, width - inset, height - top_inset)
    if rect.width <= 0.0 or rect.height <= 0.0:
        return
    size = theme.px(LABEL_SIZE)
    gap = 0.0
    if label:
        gap = draw.text_size(label, size, theme.font_id)[0] + 2.0 * theme.px(LABEL_PAD)
    points, closed = frame_path(rect, theme.px(ROUND), gap)
    with draw.blend_mode('ALPHA'):
        line = max(1.0, theme.px(WIDTH))
        draw.polyline(points, (0.0, 0.0, 0.0, 0.35 * rgba[3]), line + 2.0, closed=closed)   # readable on light
        draw.polyline(points, rgba, line, closed=closed)
        if label:
            shadow = max(1.0, theme.px(1.0))
            draw.text_centered(label, rect.cx + shadow, rect.y1 - shadow, size,
                               (0.0, 0.0, 0.0, 0.8 * rgba[3]), theme.font_id)
            draw.text_centered(label, rect.cx, rect.y1, size, with_alpha(rgba, 1.0), theme.font_id)
