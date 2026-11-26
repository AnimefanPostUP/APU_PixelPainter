"""Blend mode widgets: the favorite blend modes around Undo / Redo, the Blend button
and the favorite stars of the Blend flyout.
"""

import math

from ...kit import Rect, RingSegment, Widget
from ...kit import draw
from ...kit.theme import with_alpha
from ...kit.widget import _resolve
from ..style import PenButton
from ..metrics import BLEND_GRADIENT, DIAL_GAP, FAVORITE_CAPS_LETTERS, FAVORITE_ROWS, FAVORITE_SIZE_TEXTS, FAVORITE_TEXT_COLOR, FAVORITE_TEXT_PAD, STAR_COLOR


class StarButton(PenButton):
    """Favorite toggle beside a flyout entry: a star, filled (gold) while ``marked()``."""

    def __init__(self, *, marked, **kwargs):
        super().__init__("", layout='icon', **kwargs)
        self.marked = marked

    def draw_self(self, dc):
        super().draw_self(dc)
        r = self._visual
        if r is None:
            return
        theme = dc.theme
        alpha = dc.alpha * (1.0 if self.is_enabled else theme.disabled_alpha)
        on = bool(_resolve(self.marked, False))
        outer = min(r.width, r.height) * 0.34
        inner = outer * 0.45
        pts = [(r.cx + math.cos(math.radians(90.0 + 36.0 * k)) * (outer if k % 2 == 0 else inner),
                r.cy + math.sin(math.radians(90.0 + 36.0 * k)) * (outer if k % 2 == 0 else inner))
               for k in range(10)]
        if on:
            draw.star_polygon(r.cx, r.cy, pts, (*STAR_COLOR, alpha), rim=theme.edge_for(STAR_COLOR, alpha))
        else:
            draw.polyline(pts, with_alpha(theme.text_muted, 0.8 * alpha), max(1.0, theme.px(1.0)), closed=True)


class BlendFavorite(RingSegment):
    """A favorite blend mode in the bottom middle: its name across the segment (along the
    circle, upright), centered; names of several words on two lines. The text shrinks to
    fit the segment's depth and width."""

    def label_lines(self):
        words = self.label.split()
        if len(words) < 2:
            return [self.label]
        # Split at the space nearest the middle of the name.
        best = min(range(1, len(words)),
                   key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))))
        return [" ".join(words[:best]), " ".join(words[best:])]

    def draw_content(self, dc, alpha):
        theme = dc.theme
        lines = self.label_lines()
        pad = theme.px(FAVORITE_TEXT_PAD)
        depth = self.pr1 - self.pr0
        r = self.pr0 + depth * 0.35                      # the narrow (inner) part decides the width
        width = 2.0 * r * math.sin(math.radians(self.a1 - self.a0) * 0.5) - sum(self.insets) - 2.0 * pad
        line_gap = 1.1
        size = min(theme.px(self.font_size), depth * 0.62 / (len(lines) * line_gap))
        if size < 3.0 or width <= 4.0:
            return
        if max(len(line) for line in lines) <= FAVORITE_CAPS_LETTERS:
            lines = [line.upper() for line in lines]     # short names in capitals
        # One size for every name of a row: as large as a name of about five letters
        # (FAVORITE_SIZE_TEXTS) allows across the button.
        reference = max(draw.text_size(text, size, theme.font_id)[0] for text in FAVORITE_SIZE_TEXTS)
        if reference > width:
            size *= width / reference
        longest = max(draw.text_size(line, size, theme.font_id)[0] for line in lines)
        if longest > width:       # longer names than the reference still fit
            size *= width / longest
        # Direction: along the circle at the segment's (drawn) middle, kept upright.
        mx, my = self.middle()
        angle = math.atan2(my - self.cy, mx - self.cx) + math.pi * 0.5
        if math.cos(angle) < -1e-6:
            angle += math.pi
        ux, uy = math.cos(angle), math.sin(angle)
        up = (-uy, ux)                                   # "up" on screen for the reading direction
        color = (*FAVORITE_TEXT_COLOR, alpha)
        step = size * line_gap
        for i, line in enumerate(lines):
            off = ((len(lines) - 1) * 0.5 - i) * step   # first line on top
            w = draw.text_size(line, size, theme.font_id)[0]
            x = mx + up[0] * off - ux * w * 0.5
            y = my + up[1] * off - uy * w * 0.5
            draw.text_along(line, x, y, size, color, angle, theme.font_id)


class BlendFavorites(Widget):
    """The favorite blend modes in ``rows`` rings stacked from ``r0`` out to ``r1``, each a
    band across ``arc``, equally deep and split as evenly as possible (the outer, longer
    rows take the extra ones; fewer favorites than rows: one per row). Rows read from
    ``a0`` (left at the bottom). Owns one segment per blend mode (only the favorites are
    shown) and re-places them when the favorites change. Added to the dial's
    ``corners`` so the dial places it."""

    def __init__(self, dial, entries, r0, r1, arc, favorites, rows=FAVORITE_ROWS, **kwargs):
        super().__init__(**kwargs)
        self.dial = dial
        self.entries = dict(entries)        # blend id -> BlendFavorite
        self.r0, self.r1 = r0, r1           # the dial's measure reads r1
        self.row_count = max(1, int(rows))
        self.arc = arc
        self.favorites = favorites          # () -> set of blend ids
        self._shown = None
        self._place = None
        for segment in self.entries.values():
            segment.visible = False
            self.add(segment)
        dial.add(self)
        dial.corners.append(self)

    def shown_ids(self):
        try:
            favorites = set(self.favorites())
        except Exception:
            favorites = set()
        return tuple(b for b in self.entries if b in favorites)

    def rows(self, count):
        """``[((r0, r1), buttons)]`` for ``count`` favorites, inner row first."""
        if count <= 0:
            return []
        n = min(self.row_count, count)
        depth = (self.r1 - self.r0 - (n - 1) * DIAL_GAP) / n
        bands = [(self.r0 + i * (depth + DIAL_GAP), self.r0 + i * (depth + DIAL_GAP) + depth) for i in range(n)]
        base, extra = divmod(count, n)
        counts = [base + (1 if i >= n - extra else 0) for i in range(n)]
        return list(zip(bands, counts))

    def _assign(self, ids):
        self._shown = ids
        for segment in self.entries.values():
            segment.visible = False
        start = 0
        for (r0, r1), count in self.rows(len(ids)):
            segments = [self.entries[b] for b in ids[start:start + count]]   # listed from a0 (left)
            start += count
            extra, spans = self.dial._split(len(segments), r0, r1, *self.arc)
            for i, (segment, (b0, b1)) in enumerate(zip(segments, spans)):
                segment.r0, segment.r1, segment.a0, segment.a1 = r0, r1, b0, b1
                segment.edge_extra = (extra if i == 0 else 0.0, extra if i == len(segments) - 1 else 0.0)
                segment.visible = True

    def place_on(self, cx, cy, theme, gap):
        self._place = (cx, cy, theme, gap)
        self.rect = Rect.from_center(cx, cy, 0.0, 0.0)
        self._assign(self.shown_ids())
        for segment in self.entries.values():
            if segment.visible:
                segment.place_on(cx, cy, theme, gap)

    def contains(self, x, y):
        return False

    def draw_self(self, dc):
        if self._place is not None and self.shown_ids() != self._shown:
            self.place_on(*self._place)


class BlendButton(RingSegment):
    """Blend (opens the flyout): filled with a gradient from dark to
    light gray along the circle (``BLEND_GRADIENT``), the active blend mode's name
    (``mode()``) on it."""

    def __init__(self, label="", *, mode, **kwargs):
        super().__init__(label, **kwargs)
        self.mode = mode

    def draw_self(self, dc):
        theme = dc.theme
        alpha = self._alpha(dc)
        inner, outer = self.points()
        if not inner:
            return
        lo, hi = BLEND_GRADIENT
        pressed = dc.pressed is self and dc.hot is self
        shade = 0.8 if pressed else 1.0
        last = max(1, len(inner) - 1)
        colors = []
        for i in range(len(inner)):
            t = i / last
            colors.append(tuple((lo[k] + (hi[k] - lo[k]) * t) * shade for k in range(3)) + (alpha,))
        draw.gradient_ring_segment(inner, outer, colors)
        draw.ring_segment_outline(inner, outer, theme.edge_for((0.45, 0.45, 0.45), alpha), width=1.0)
        if self.is_selected:
            self.draw_selection(dc, alpha)
        if self.hover_t > 0.01:
            draw.ring_segment_outline(inner, outer, with_alpha(theme.accent, self.hover_t * alpha),
                                      width=theme.px(1.5))
        text = str(_resolve(self.mode, ""))
        room = self.content_size()
        if room <= 4.0 or not text:
            return
        x, y = self.middle()
        font = min(theme.px(12.0), room * 0.45)
        width, _h = draw.text_size(text, font, theme.font_id)
        if width > room * 1.1:
            font *= room * 1.1 / width
        shadow = max(1.0, theme.px(1.0))
        draw.text_centered(text, x + shadow, y - shadow, font, (0.0, 0.0, 0.0, 0.85 * alpha), theme.font_id)
        draw.text_centered(text, x, y, font, (1.0, 1.0, 1.0, alpha), theme.font_id)
