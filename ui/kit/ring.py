"""Dial: a center widget surrounded by rings of pie segments (pen friendly, no hover needed).

* :class:`Dial` lays out a center widget (e.g. a :class:`~.widgets.DragBubble`)
  and :class:`RingSegment` children placed by radius / angle. ``add_arc`` splits
  an angular range evenly between segments.
* Every segment is drawn shrunk by half the dial's ``gap`` on its side edges,
  parallel to its radial line, and rings are separated by the same gap -- so all
  spacings between segments are equally wide at any radius.
* Each ``add_arc`` is a *group* (a category): neighbouring groups are separated
  by the wider ``group_gap`` with a thin divider line through its middle, and
  ``tint`` colors all of a group's segments slightly.
* ``add_corner`` fills the corners of the dial's enclosing square with
  :class:`CornerSegment` buttons: the inner edge follows the circle, the outer
  edges the square (its extreme corners cut off diagonally by ``chamfer``).
* Hit-testing uses the unshrunk segment, so the gaps still belong to a segment.
* :class:`RingSlider` is a radial slider: the value runs from the inner to the
  outer radius; press / drag sets it from the pointer's distance to the center.

Radii are unscaled px, angles degrees (counter-clockwise from +x, 90 = up).
"""

import math

from . import anim
from . import draw
from .geometry import (Rect, corner_contains, corner_room, corner_segment_points, polygon_centroid,
                       ring_contains, ring_segment_points)
from .theme import mix, with_alpha
from .widget import Widget, _resolve


class RingSegment(Widget):
    """One pie segment. Content: ``icon`` (from ``icons``), ``label`` text, or
    ``painter(dc, x, y, size, alpha)`` drawing custom content at the segment's
    middle (``size`` = room available there, screen px).

    ``fill``: base color (theme surface when None); ``tint`` (RGB) is mixed into
    it by ``tint_amount``. Selected segments get an accent tint and an accent
    band along the outer edge.
    """

    interactive = True

    def __init__(self, label="", *, icon=None, icons=None, painter=None, fill=None,
                 tint=None, tint_amount=0.16, font_size=10.0, **kwargs):
        super().__init__(**kwargs)
        self.label = label
        self.icon = icon
        self.icons = icons
        self.painter = painter
        self.fill = fill
        self.tint = tint
        self.tint_amount = tint_amount
        self.font_size = font_size
        # Unscaled ring position, set by Dial.add_arc / Dial.add_segment.
        self.r0 = self.r1 = 0.0
        self.a0 = self.a1 = 0.0
        self.edge_extra = (0.0, 0.0)   # extra unscaled inset at the a0 / a1 edge (group gaps)
        # Screen geometry, set by Dial.arrange.
        self.cx = self.cy = 0.0
        self.pr0 = self.pr1 = 0.0
        self.insets = (0.0, 0.0)

    # ---- geometry -----------------------------------------------------------------

    @property
    def angles(self):
        return math.radians(self.a0), math.radians(self.a1)

    def place_on(self, cx, cy, theme, gap):
        self.cx, self.cy = cx, cy
        self.pr0, self.pr1 = theme.px(self.r0), theme.px(self.r1)
        half = theme.px(gap) * 0.5
        self.insets = (half + theme.px(self.edge_extra[0]), half + theme.px(self.edge_extra[1]))
        inner, outer = ring_segment_points(cx, cy, self.pr0, self.pr1, *self.angles)
        pts = inner + outer
        if pts:
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            self.rect = Rect(min(xs), min(ys), max(xs), max(ys))

    def contains(self, x, y):
        return ring_contains(self.cx, self.cy, self.pr0, self.pr1, *self.angles, x, y)

    def points(self, r0=None, r1=None):
        return ring_segment_points(self.cx, self.cy, self.pr0 if r0 is None else r0,
                                   self.pr1 if r1 is None else r1, *self.angles,
                                   self.insets[0], inset1=self.insets[1])

    def middle(self, r=None):
        """Point in the middle of the drawn segment at radius ``r`` (default: mid radius)."""
        r = (self.pr0 + self.pr1) * 0.5 if r is None else r
        a = math.radians((self.a0 + self.a1) * 0.5)
        if r > max(self.insets):   # unequal insets: center between the drawn edges
            a += (math.asin(min(1.0, self.insets[0] / r)) - math.asin(min(1.0, self.insets[1] / r))) * 0.5
        return self.cx + math.cos(a) * r, self.cy + math.sin(a) * r

    def content_size(self):
        """Room for content at the middle: min(chord, depth) minus the gaps."""
        r = (self.pr0 + self.pr1) * 0.5
        chord = 2.0 * r * math.sin(math.radians(self.a1 - self.a0) * 0.5) - sum(self.insets)
        depth = self.pr1 - self.pr0 - min(self.insets) * 2.0
        return max(0.0, min(chord, depth))

    # ---- drawing ------------------------------------------------------------------

    def _fill(self, dc, active=None):
        theme = dc.theme
        t = anim.ease_in_out(self.hover_t) if active is None else active
        base = self.fill or theme.surface
        if self.tint is not None:
            base = mix(base, (*self.tint[:3], base[3]), self.tint_amount)
        pressed = dc.pressed is self and dc.hot is self
        fill = mix(base, theme.surface_pressed if pressed else theme.surface_hover, t * 0.8)
        if self.is_selected:
            fill = mix(fill, theme.accent, 0.4)
        return fill, t

    def _alpha(self, dc):
        return dc.alpha * (1.0 if self.is_enabled else dc.theme.disabled_alpha)

    def draw_frame(self, dc, active=None):
        """Background, selection band and hover outline; returns the alpha to draw content with."""
        theme = dc.theme
        alpha = self._alpha(dc)
        inner, outer = self.points()
        if not inner:
            return alpha
        fill, t = self._fill(dc, active)
        draw.ring_segment(inner, outer, with_alpha(fill, alpha), rim=theme.edge_for(fill, alpha))
        if self.is_selected:
            self.draw_selection(dc, alpha)
        if t > 0.01:
            draw.ring_segment_outline(inner, outer, with_alpha(theme.accent, t * alpha), width=theme.px(1.5))
        return alpha

    def draw_selection(self, dc, alpha):
        """Accent band along the outer edge."""
        band = dc.theme.px(3.0)
        draw.ring_segment(*self.points(self.pr1 - band, self.pr1), with_alpha(dc.theme.accent, alpha))

    def draw_self(self, dc):
        alpha = self.draw_frame(dc)
        self.draw_content(dc, alpha)

    def draw_content(self, dc, alpha):
        theme = dc.theme
        x, y = self.middle()
        size = self.content_size()
        if size <= 2.0:
            return
        if self.painter is not None:
            self.painter(dc, x, y, size, alpha)
            return
        if self.icons is not None and self.icon and self.icons.draw(self.icon, x, y, size * 0.8, alpha):
            return
        if self.label:
            draw.text_centered(self.label, x, y, theme.px(self.font_size),
                               with_alpha(theme.text, alpha), theme.font_id)


class CornerSegment(RingSegment):
    """A button filling (part of) a corner of the dial's enclosing square: from the
    circle ``r0`` out to the square ``half`` (unscaled), between angles ``a0 .. a1``;
    the square's corner is cut off by ``chamfer``. Set by :meth:`Dial.add_corner`."""

    def __init__(self, label="", **kwargs):
        super().__init__(label, **kwargs)
        self.half = 0.0
        self.chamfer = 0.0
        self._geo = None        # (r0, half, chamfer) screen px
        self._inner = self._outer = []
        self._center = (0.0, 0.0)
        self._room = 0.0

    def place_on(self, cx, cy, theme, gap):
        self.cx, self.cy = cx, cy
        self.pr0 = theme.px(self.r0)
        self.pr1 = half = theme.px(self.half)
        chamfer = theme.px(self.chamfer)
        self._geo = (self.pr0, half, chamfer)
        g = theme.px(gap) * 0.5
        self.insets = (g + theme.px(self.edge_extra[0]), g + theme.px(self.edge_extra[1]))
        a0, a1 = self.angles
        inner, outer = corner_segment_points(self.pr0, half, a0, a1, *self.insets, chamfer)
        self._inner = [(cx + x, cy + y) for x, y in inner]
        self._outer = [(cx + x, cy + y) for x, y in outer]
        if not inner:
            self._room = 0.0
            return
        center = polygon_centroid(inner + list(reversed(outer)))
        self._center = (cx + center[0], cy + center[1])
        self._room = 2.0 * corner_room(center, self.pr0, half, a0, a1, *self.insets, chamfer)
        pts = self._inner + self._outer
        self.rect = Rect(min(p[0] for p in pts), min(p[1] for p in pts),
                         max(p[0] for p in pts), max(p[1] for p in pts))

    def contains(self, x, y):
        if self._geo is None:
            return False
        r0, half, chamfer = self._geo
        return corner_contains(r0, half, *self.angles, chamfer, x - self.cx, y - self.cy)

    def points(self, r0=None, r1=None):
        return self._inner, self._outer

    def middle(self, r=None):
        return self._center

    def content_size(self):
        return self._room

    def draw_selection(self, dc, alpha):
        """Accent line along the square edges."""
        draw.polyline(self._outer, with_alpha(dc.theme.accent, alpha), dc.theme.px(3.0))


class RingSlider(RingSegment):
    """Radial slider: 0 at the inner radius, 1 at the bottom of the label cap.

    ``value`` (0..1, or callable) is shown as a band of ``fill_color`` from the
    inner edge; ``label`` sits in the cap at the outer end. A press sets the value
    from the pointer's distance to the center, dragging keeps setting it:
    ``on_drag_begin()``, ``on_value(v)`` per change, ``on_drag_end(cancelled)``.
    """

    draggable = True

    def __init__(self, label="", *, value=0.0, fill_color=(0.66, 0.44, 0.92, 1.0), cap=16.0,
                 on_drag_begin=None, on_value=None, on_drag_end=None, **kwargs):
        super().__init__(label, **kwargs)
        self.value = value
        self.fill_color = fill_color
        self.cap = cap
        self.on_drag_begin = on_drag_begin
        self.on_value = on_value
        self.on_drag_end = on_drag_end
        self.dragging = False
        self._cap_px = 0.0

    def place_on(self, cx, cy, theme, gap):
        super().place_on(cx, cy, theme, gap)
        self._cap_px = theme.px(self.cap)

    def _track(self):
        """Screen radii where the value is 0 and 1."""
        start = self.pr0 + min(self.insets)
        return start, max(start + 1.0, self.pr1 - self._cap_px)

    def value_at(self, x, y):
        t0, t1 = self._track()
        return max(0.0, min(1.0, (math.hypot(x - self.cx, y - self.cy) - t0) / (t1 - t0)))

    def drag_begin(self, x, y):
        self.dragging = True
        if self.on_drag_begin is not None:
            self.on_drag_begin()
        self.drag_update(x, y)

    def drag_update(self, x, y):
        if self.dragging and self.on_value is not None:
            self.on_value(self.value_at(x, y))

    def drag_end(self, x, y, cancelled=False):
        self.dragging = False
        if self.on_drag_end is not None:
            self.on_drag_end(cancelled)

    def draw_self(self, dc):
        theme = dc.theme
        alpha = self.draw_frame(dc, active=1.0 if self.dragging else None)
        value = max(0.0, min(1.0, float(_resolve(self.value, 0.0) or 0.0)))
        t0, t1 = self._track()
        if value > 0.0:
            draw.ring_segment(*self.points(self.pr0, t0 + (t1 - t0) * value), with_alpha(self.fill_color, alpha))
        # Cap: darker, with the label.
        draw.ring_segment(*self.points(t1, self.pr1), with_alpha(theme.surface_dark, 0.6 * alpha))
        x, y = self.middle((t1 + self.pr1) * 0.5)
        draw.text_centered(self.label, x, y, theme.px(self.font_size), with_alpha(theme.text, alpha), theme.font_id)


class Dial(Widget):
    """A center widget surrounded by :class:`RingSegment` rings (see the module docs).

    ``gap`` (unscaled px): the spacing between segments of a group and between rings.
    ``group_gap``: the spacing between groups (``add_arc`` calls), with a divider
    line (``divider_overhang`` px past the outer ring) through its middle.
    """

    def __init__(self, center=None, *, gap=4.0, group_gap=None, divider_overhang=6.0, **kwargs):
        super().__init__(**kwargs)
        self.gap = gap
        self.group_gap = gap if group_gap is None else group_gap
        self.divider_overhang = divider_overhang
        self.center = self.add(center) if center is not None else None
        self.segments = []
        self.corners = []     # segments outside the rings: corner segments, bands
        self.dividers = []    # angles (degrees) between groups
        self._divider_lines = []

    def add_segment(self, segment, r0, r1, a0, a1):
        segment.r0, segment.r1, segment.a0, segment.a1 = r0, r1, a0, a1
        self.segments.append(self.add(segment))
        return segment

    def _split(self, count, r0, r1, a0, a1):
        """``(extra, spans)``: ``a0 .. a1`` split between ``count`` segments of one
        group so all of them are *drawn* equally wide. The two end segments lose
        ``extra`` px more to the group gap than the others lose to the normal gap,
        so they get that much more angle (measured at the middle radius)."""
        extra = max(0.0, self.group_gap - self.gap) * 0.5
        count = max(1, count)
        mid = max(1e-6, (r0 + r1) * 0.5)
        extra_deg = math.degrees(extra / mid) if count > 1 else 0.0
        step = (a1 - a0 - 2.0 * extra_deg) / count
        if step <= 0.0:              # not enough room: plain even split
            step, extra_deg = (a1 - a0) / count, 0.0
        edges = [a0]
        for i in range(count):
            edges.append(edges[-1] + step + (extra_deg if i in (0, count - 1) else 0.0))
        edges[-1] = a1
        return extra, list(zip(edges, edges[1:]))

    def add_band(self, segments, r0, r1, a0, a1, *, tint=None):
        """Like :meth:`add_arc`, but outside the rings (e.g. in the corners): no
        dividers, not counted in :attr:`radius`."""
        segments = list(segments)
        extra, spans = self._split(len(segments), r0, r1, a0, a1)
        for i, (segment, (b0, b1)) in enumerate(zip(segments, spans)):
            segment.r0, segment.r1 = r0, r1
            segment.a0, segment.a1 = b0, b1
            segment.edge_extra = (extra if i == 0 else 0.0, extra if i == len(segments) - 1 else 0.0)
            if tint is not None and segment.tint is None:
                segment.tint = tint
            self.corners.append(self.add(segment))
        return segments

    def add_arc(self, segments, r0, r1, a0, a1, *, tint=None):
        """A group: split ``a0 .. a1`` between ``segments`` (listed from ``a0``) so
        they are drawn equally wide, with the group gap and a divider at both ends."""
        segments = list(segments)
        extra, spans = self._split(len(segments), r0, r1, a0, a1)
        for i, (segment, (b0, b1)) in enumerate(zip(segments, spans)):
            self.add_segment(segment, r0, r1, b0, b1)
            segment.edge_extra = (extra if i == 0 else 0.0, extra if i == len(segments) - 1 else 0.0)
            if tint is not None and segment.tint is None:
                segment.tint = tint
        for angle in (a0, a1):
            if all(abs((angle - d + 180.0) % 360.0 - 180.0) > 1e-6 for d in self.dividers):
                self.dividers.append(angle % 360.0)
        return segments

    def add_corner(self, segments, r0, half, a0, a1, *, chamfer=0.0, weights=None, tint=None):
        """Corner buttons: split ``a0 .. a1`` between ``segments`` (listed from ``a0``;
        ``weights``: relative angular sizes) in the region between the circle ``r0`` and
        the square of half size ``half``. The ends get the group gap; no dividers."""
        segments = list(segments)
        weights = list(weights) if weights else [1.0] * len(segments)
        total = float(sum(weights))
        extra = max(0.0, self.group_gap - self.gap) * 0.5
        angle = a0
        for i, (segment, weight) in enumerate(zip(segments, weights)):
            end = a1 if i == len(segments) - 1 else angle + (a1 - a0) * weight / total
            segment.r0, segment.r1, segment.a0, segment.a1 = r0, half, angle, end
            segment.half, segment.chamfer = half, chamfer
            segment.edge_extra = (extra if i == 0 else 0.0, extra if i == len(segments) - 1 else 0.0)
            if tint is not None and segment.tint is None:
                segment.tint = tint
            self.corners.append(self.add(segment))
            angle = end
        return segments

    @property
    def radius(self):
        """Outer radius of the rings (corner segments excluded)."""
        return max((s.r1 for s in self.segments), default=0.0)

    def measure(self, theme):
        d = theme.px(self.radius + (self.divider_overhang if self.dividers else 0.0)) * 2.0
        d = max([d] + [theme.px(getattr(c, 'half', c.r1)) * 2.0 for c in self.corners])
        if self.center is not None:
            cw, ch = self.center.measure(theme)
            d = max(d, cw, ch)
        return d, d

    def arrange(self, rect, theme):
        self.rect = rect
        cx, cy = rect.cx, rect.cy
        if self.center is not None:
            w, h = self.center.measure(theme)
            self.center.arrange(Rect.from_center(cx, cy, w, h), theme)
        for segment in self.segments + self.corners:
            segment.place_on(cx, cy, theme, self.gap)
        r0 = theme.px(min((s.r0 for s in self.segments), default=0.0))
        r1 = theme.px(self.radius + self.divider_overhang)
        self._divider_lines = []
        for angle in self.dividers:
            ux, uy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
            self._divider_lines.append(((cx + ux * r0, cy + uy * r0), (cx + ux * r1, cy + uy * r1)))

    def draw_self(self, dc):
        theme = dc.theme
        # Fades out toward the outer end.
        inner = with_alpha(theme.text_muted, 0.6 * dc.alpha)
        outer = with_alpha(theme.text_muted, 0.0)
        for start, end in self._divider_lines:
            draw.gradient_line(start, end, inner, outer, max(1.0, theme.px(1.5)))
