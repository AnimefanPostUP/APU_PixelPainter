"""FalloffField: the swipeable field setting the *Shape* falloff (hardness along the
radius, sharpness along the circle).
"""

import math

from ..kit import RingSegment
from ..kit import anim, draw
from ..kit.theme import mix, with_alpha
from ..kit.widget import _resolve
from ...utils.math_utils import shape_falloff
from .metrics import (
    DRAG_THRESHOLD, FIELD_CROSS_ARM, FIELD_CURVE_FILL, FIELD_CURVE_SAMPLES, FIELD_EDGE_MARGIN,
    FIELD_GUIDE_ALPHA, FIELD_GUIDE_GRAY, FIELD_MARKER_RADIUS, FIELD_PREVIEW_SCALE,
)


class FalloffField(RingSegment):
    """The Shape falloff as a 2D field (a pie segment), swiped like the color selector.

    Radially (relative to the menu's center) it runs from hard (inner edge: full strength
    out to the brush edge) to soft (outer edge); along the circle from linear (top) to
    sharp (bottom). ``value()`` / ``on_value(hardness, sharpness)`` read / set the two
    values (setting them selects the Shape falloff); ``active()``: Shape is in use.

    A drag moves the marker by the pointer's motion (``gain``), not under the pen; a tap
    jumps to the tapped spot; ESC / RMB restore the values from before the drag. While
    pressed the OS cursor is hidden (``on_drag_state(True / False)``) and, once swiping,
    kept on the marker (``warp(x, y)``, region px), so the marker is the pointer. Each
    corner shows a quarter of a preview disc (``previews``: ``((hardness, sharpness),
    icon key)`` listed hard-linear, soft-linear, hard-sharp, soft-sharp); the marker is a
    cross, and the current falloff curve runs through the field (:meth:`curve_points`).
    The field is plain gray; only the accent band along its outer edge shows that the
    Shape falloff is selected. (``marker_icon`` is accepted but no longer drawn.)"""

    draggable = True

    def __init__(self, label="", *, value, on_value, active, previews=(), marker_icon=None,
                 gain=0.5, on_drag_state=None, warp=None, **kwargs):
        super().__init__(label, selected=active, **kwargs)
        self.value = value
        self.on_value = on_value
        self.active = active
        self.previews = tuple(previews)
        self.marker_icon = marker_icon
        self.gain = gain
        self.on_drag_state = on_drag_state
        self.warp = warp
        self.dragging = False
        self._drag = None
        self._theme = None

    # ---- field coordinates ---------------------------------------------------------

    def _track(self):
        """Screen radii of the hard (0) and soft (1) ends; angles (degrees) of the sharp
        (bottom) and linear (top) ends -- the drawn area minus a margin (part of the
        marker may reach over the edge: ``FIELD_EDGE_MARGIN``)."""
        edge = self._marker_radius() * FIELD_EDGE_MARGIN
        margin = edge + min(self.insets)
        r0, r1 = self.pr0 + margin, max(self.pr0 + margin + 1.0, self.pr1 - margin)
        mid = max(1.0, (self.pr0 + self.pr1) * 0.5)
        pad = [math.degrees(min(1.0, (inset + edge) / mid)) for inset in self.insets]
        a0, a1 = self.a0 + pad[0], self.a1 - pad[1]
        if a1 <= a0:
            a0 = a1 = (self.a0 + self.a1) * 0.5
        return r0, r1, a0, a1

    def _marker_radius(self):
        theme = self._theme
        return theme.px(FIELD_MARKER_RADIUS) if theme is not None else FIELD_MARKER_RADIUS

    def _tap_travel(self):
        return self._theme.px(DRAG_THRESHOLD) if self._theme is not None else DRAG_THRESHOLD

    def _polar(self, x, y):
        """``(radius, angle in degrees)`` of a screen point, the angle unwrapped around the field."""
        r = math.hypot(x - self.cx, y - self.cy)
        a = math.degrees(math.atan2(y - self.cy, x - self.cx))
        mid = (self.a0 + self.a1) * 0.5
        a = mid + (a - mid + 180.0) % 360.0 - 180.0
        return r, a

    def field_at(self, x, y):
        """``(hardness, sharpness)`` of a screen point, unclamped."""
        r0, r1, a0, a1 = self._track()
        r, a = self._polar(x, y)
        hardness = 1.0 - (r - r0) / max(1e-6, r1 - r0)
        sharpness = (a1 - a) / max(1e-6, a1 - a0)
        return hardness, sharpness

    def point_at(self, hardness, sharpness):
        """Screen point of field values."""
        r0, r1, a0, a1 = self._track()
        r = r0 + (1.0 - hardness) * (r1 - r0)
        a = math.radians(a1 - sharpness * (a1 - a0))
        return self.cx + math.cos(a) * r, self.cy + math.sin(a) * r

    def motion_delta(self, dx, dy):
        """``(d hardness, d sharpness)`` of a pointer motion ``(dx, dy)`` (unscaled by
        ``gain``). Two fixed straight axes, a cross through the field's middle: along its
        middle ray = hardness (outward: softer), across it = sharpness -- the same wherever
        the marker is, so a straight swipe changes one value without following the arc."""
        r0, r1, a0, a1 = self._track()
        am = math.radians((a0 + a1) * 0.5)
        ux, uy = math.cos(am), math.sin(am)             # outward along the middle ray
        along = dx * ux + dy * uy
        across = -dx * uy + dy * ux                     # toward the higher angle (linear end)
        rm = max(1.0, (r0 + r1) * 0.5)
        span = max(1e-6, math.radians(a1 - a0) * rm)    # the arc's length at the middle radius
        return -along / max(1e-6, r1 - r0), -across / span

    def _current(self):
        value = _resolve(self.value, None) or (0.0, 0.0)
        return float(value[0]), float(value[1])

    # ---- drag ----------------------------------------------------------------------

    def drag_begin(self, x, y):
        start = self._current()
        self._drag = {'start': start, 'value': start, 'press': (x, y), 'last': (x, y), 'travel': 0.0,
                      'was_active': bool(_resolve(self.active, False))}
        self.dragging = True
        if self.on_drag_state is not None:
            self.on_drag_state(True)

    def drag_update(self, x, y):
        drag = self._drag
        if drag is None:
            return
        lx, ly = drag['last']
        drag['last'] = (x, y)
        drag['travel'] += math.hypot(x - lx, y - ly)
        if drag['travel'] < self._tap_travel():
            return    # might still be a tap
        dh, ds = self.motion_delta(x - lx, y - ly)
        h, s = drag['value']
        drag['value'] = (max(0.0, min(1.0, h + dh * self.gain)),
                         max(0.0, min(1.0, s + ds * self.gain)))
        self.on_value(*drag['value'])
        if self.warp is not None:
            # The cursor stays on the marker: the next motion is measured from there.
            drag['last'] = self.point_at(*drag['value'])
            self.warp(*drag['last'])

    def drag_end(self, x, y, cancelled=False):
        drag, self._drag = self._drag, None
        self.dragging = False
        if self.on_drag_state is not None:
            self.on_drag_state(False)
        if drag is None:
            return
        if cancelled:
            if drag['travel'] >= self._tap_travel():
                self.on_value(*drag['start'])
        elif drag['travel'] < self._tap_travel():
            if not drag['was_active']:
                # Another falloff was in use: the first tap only switches back to Shape,
                # keeping its values (the marker stays where it was).
                self.on_value(*drag['start'])
                return
            h, s = self.field_at(*drag['press'])
            self.on_value(max(0.0, min(1.0, h)), max(0.0, min(1.0, s)))

    # ---- drawing -------------------------------------------------------------------

    def corners(self):
        """``(corner, unit vector into the field radially, unit vector into it along the
        circle)`` of the drawn shape, ordered hard-linear, soft-linear, hard-sharp, soft-sharp."""
        inner, outer = self.points()
        if not inner:
            return []
        out = []
        for index, side in ((-1, -1.0), (0, 1.0)):      # top (a1) side first, then bottom (a0)
            p_in, p_out = inner[index], outer[index]
            dx, dy = p_out[0] - p_in[0], p_out[1] - p_in[1]
            d = math.hypot(dx, dy) or 1.0
            ux, uy = dx / d, dy / d                       # outward
            tx, ty = -uy * side, ux * side                # toward the other side edge
            out.append((p_in, (ux, uy), (tx, ty)))
            out.append((p_out, (-ux, -uy), (tx, ty)))
        return out

    def preview_radius(self):
        r0, r1, a0, a1 = self._track()
        rm = (r0 + r1) * 0.5
        cell = min((r1 - r0) * 0.5, rm * math.radians(a1 - a0) * 0.5)
        return cell * 0.62 * FIELD_PREVIEW_SCALE * 0.5

    def _draw_previews(self, alpha):
        """A quarter of each preview disc in its corner (the disc's center on the corner)."""
        radius = self.preview_radius()
        for ((_hs, key), (c, e1, e2)) in zip(self.previews, self.corners()):
            quad = [c, (c[0] + e1[0] * radius, c[1] + e1[1] * radius),
                    (c[0] + (e1[0] + e2[0]) * radius, c[1] + (e1[1] + e2[1]) * radius),
                    (c[0] + e2[0] * radius, c[1] + e2[1] * radius)]
            self.icons.draw_quad(key, quad, ((0.5, 0.5), (1.0, 0.5), (1.0, 1.0), (0.5, 1.0)), 0.45 * alpha)

    def _fill(self, dc, active=None):
        """Plain gray (no category tint, no accent while selected: only the outer band
        marks the selection), lighter while hovered / pressed."""
        theme = dc.theme
        t = anim.ease_in_out(self.hover_t) if active is None else active
        pressed = dc.pressed is self and dc.hot is self
        base = self.fill or theme.surface
        return mix(base, theme.surface_pressed if pressed else theme.surface_hover, t * 0.8), t

    def curve_points(self, samples=FIELD_CURVE_SAMPLES):
        """The current Shape falloff drawn in the field: distance from the brush center
        along the circle (center at the linear / top end), the weight radially -- 1 on
        the outer line, 0 at the inner side."""
        r0, r1, a0, a1 = self._track()
        h, s = self._current()
        pts = []
        for i in range(samples + 1):
            t = i / samples
            weight = max(0.0, min(1.0, shape_falloff(t, h, s)))
            r = r0 + weight * (r1 - r0)
            a = math.radians(a1 - t * (a1 - a0))
            pts.append((self.cx + math.cos(a) * r, self.cy + math.sin(a) * r))
        return pts

    def draw_self(self, dc):
        self._theme = theme = dc.theme
        alpha = self.draw_frame(dc, active=1.0 if self.dragging else None)
        inner, _outer = self.points()
        if not inner:
            return
        # The inner side of the falloff curve (between it and the inner edge): a lighter gray.
        curve = self.curve_points()
        base = []
        for x, y in curve:   # the same angle, on the inner edge
            k = self.pr0 / max(1e-6, math.hypot(x - self.cx, y - self.cy))
            base.append((self.cx + (x - self.cx) * k, self.cy + (y - self.cy) * k))
        draw.ring_segment(base, curve, (*FIELD_CURVE_FILL, alpha))
        if self.icons is not None:
            self._draw_previews(alpha)
        r0, r1, a0, a1 = self._track()
        guide = (*FIELD_GUIDE_GRAY, FIELD_GUIDE_ALPHA * alpha)
        width = max(1.0, theme.px(1.0))
        # 2 x 2: the middle along the circle and across it.
        rm, am = (r0 + r1) * 0.5, math.radians((a0 + a1) * 0.5)
        draw.arc(self.cx, self.cy, rm, math.radians(a0), math.radians(a1), guide, width=width)
        draw.polyline([(self.cx + math.cos(am) * r0, self.cy + math.sin(am) * r0),
                       (self.cx + math.cos(am) * r1, self.cy + math.sin(am) * r1)], guide, width)
        on = bool(_resolve(self.active, False))
        # The falloff curve: from the outer line (full strength) in toward the inner side.
        draw.polyline(curve, with_alpha(theme.text, (0.8 if on else 0.45) * alpha),
                      max(1.0, theme.px(1.5)))
        # Marker: a cross (dimmed while another falloff is in use); black under white,
        # readable on the field, the curve and the previews.
        mx, my = self.point_at(*self._current())
        arm = self._marker_radius() * FIELD_CROSS_ARM
        marker_alpha = alpha if on else 0.55 * alpha
        lines = ([(mx - arm, my), (mx + arm, my)], [(mx, my - arm), (mx, my + arm)])
        for w, color in ((3.0, (0.0, 0.0, 0.0, 0.8)),
                         (1.5, theme.accent_light if on else theme.text)):
            for line in lines:
                draw.polyline(line, with_alpha(color, marker_alpha), max(1.0, theme.px(w)))
