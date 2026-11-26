"""The Windows ring: Settings / Mask / View / Color / Palettes over the dial's inner ring.
"""

import math

from ..kit import Rect, Widget
from ..kit import draw
from ..kit.geometry import ring_segment_points
from ..kit.theme import with_alpha
from .metrics import WINDOW_RING_BACKDROP


class WindowRing(Widget):
    """The Windows popup: entries in a full ring over the dial's inner ring (``r0 .. r1``).

    The dial's last child, so it draws on top and is picked first. An opaque backdrop
    from ``r0`` out to ``cover`` hides the rings under it (inner and outer: the tools
    too) and blocks the pointer there: a press in a gap or on the backdrop does not reach
    the buttons under it. Entries confirm on release (``drag_release``): press Windows,
    drag onto an entry, lift.
    """

    blocks_pointer = True

    def __init__(self, r0, r1, cover=None, **kwargs):
        super().__init__(visible=False, **kwargs)
        self.r0, self.r1 = r0, r1
        self.cover = r1 if cover is None else max(r1, cover)
        self.cx = self.cy = 0.0
        self.pr0 = self.pr1 = self.pcover = 0.0
        self.gap = 0.0

    def add_entries(self, dial, entries, start):
        """Split the full circle from ``start`` (degrees, counter-clockwise) between ``entries``;
        the dial places them (its ``corners``), this ring owns them (drawing / picking)."""
        step = 360.0 / max(1, len(entries))
        for i, entry in enumerate(entries):
            entry.r0, entry.r1 = self.r0, self.r1
            entry.a0, entry.a1 = start + i * step, start + (i + 1) * step
            entry.drag_release = True
            self.add(entry)
            dial.corners.append(entry)
        dial.corners.append(self)

    def place_on(self, cx, cy, theme, gap):
        self.cx, self.cy = cx, cy
        self.pr0, self.pr1, self.pcover = theme.px(self.r0), theme.px(self.r1), theme.px(self.cover)
        self.gap = theme.px(gap)
        self.rect = Rect.from_center(cx, cy, self.pcover * 2.0, self.pcover * 2.0)

    def contains(self, x, y):
        return self.pr0 <= math.hypot(x - self.cx, y - self.cy) <= self.pcover + self.gap * 0.5

    def draw_self(self, dc):
        theme = dc.theme
        # Out past the covered rings' rims (half the gap on each side), so nothing shows through.
        r0, r1 = max(0.0, self.pr0 - self.gap * 0.5), self.pcover + self.gap * 0.5
        inner, outer = ring_segment_points(self.cx, self.cy, r0, r1, 0.0, math.tau)
        draw.ring_segment(inner, outer, with_alpha(WINDOW_RING_BACKDROP, dc.alpha))
        accent = with_alpha(theme.accent, 0.8 * dc.alpha)
        draw.circle_outline(self.cx, self.cy, r1, accent, width=max(1.0, theme.px(1.5)), segments=96)
        if self.pcover > self.pr1 + self.gap:   # a fainter line around the entries
            draw.circle_outline(self.cx, self.cy, self.pr1 + self.gap * 0.5,
                                with_alpha(theme.accent, 0.35 * dc.alpha), width=max(1.0, theme.px(1.0)), segments=96)
