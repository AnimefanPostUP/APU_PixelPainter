"""Radial (pie) menu widget."""

import math

from . import anim
from . import draw
from .events import number_key_index
from .geometry import Rect, lerp2, normalize
from .theme import with_alpha
from .widget import Widget


class Connector:
    """Animated curve endpoint that eases between targets when the hover changes."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.initialized = False
        self.key = None
        self.end = (0.0, 0.0)
        self.start = (0.0, 0.0)
        self.target = (0.0, 0.0)
        self.progress = 1.0
        self.last_time = None

    def update(self, now, target, key, duration):
        """Advance toward ``target``; returns ``(point, transition)``.

        ``transition`` is 1 right after the target changed and 0 when settled.
        A changed ``key`` (different hovered widget) restarts the ease; the
        same widget moving (e.g. growing on hover) snaps without easing.
        """
        dt = anim.frame_dt(now, self.last_time)
        self.last_time = now
        restart = key != self.key
        self.key = key

        if not self.initialized:
            self.initialized = True
            self.end = self.start = self.target = target
            self.progress = 1.0
            return target, 0.0

        if abs(target[0] - self.target[0]) > 1e-4 or abs(target[1] - self.target[1]) > 1e-4:
            if restart:
                self.start = self.end
                self.target = target
                self.progress = 0.0
            else:
                self.end = self.start = self.target = target
                self.progress = 1.0
                return target, 0.0

        if self.progress < 1.0 and dt > 0.0:
            self.progress = min(1.0, self.progress + dt / max(duration, 1e-4))
        self.end = lerp2(self.start, self.target, self.progress)
        return self.end, 1.0 - self.progress


class RadialMenu(Widget):
    """Items arranged on a circle around the cursor, picked by direction.

    * Items are placed on an arc (default: left -> top -> right) or on explicit
      ``directions``.
    * Pointing anywhere outside the dead zone selects the item whose direction
      is closest, unless another widget (e.g. an attached panel) is under the
      pointer.
    * Extra widgets can be attached below the ring with :meth:`attach_below`;
      they take part in layout, picking and connectors automatically.
    * Number keys 1..9 pick items directly.
    """

    def __init__(self, *, radius=120.0, dead_zone=16.0, arc=(180.0, 0.0), directions=None,
                 hub_radius=22.0, hub_dot=7.0, footer_gap=64.0, show_arrow=True,
                 show_connector=True, number_keys=True, **kwargs):
        super().__init__(**kwargs)
        self.radius = radius
        self.dead_zone = dead_zone
        self.arc = arc
        self.directions = directions
        self.hub_radius = hub_radius
        self.hub_dot = hub_dot
        self.footer_gap = footer_gap
        self.show_arrow = show_arrow
        self.show_connector = show_connector
        self.number_keys = number_keys
        self.items = []
        self._below = []
        self._connector = Connector()
        self._dead_zone_px = dead_zone

    # ---- building ----------------------------------------------------------

    def add_item(self, widget):
        self.items.append(widget)
        return self.add(widget)

    def attach_below(self, widget, gap=None):
        """Attach ``widget`` centered under the ring, ``gap`` px below the center."""
        self._below.append((widget, gap))
        return self.add(widget)

    def item_directions(self):
        n = len(self.items)
        if self.directions is not None:
            dirs = [normalize(dx, dy, (1.0, 0.0))[:2] for dx, dy in self.directions]
            return dirs[:n]
        start, end = (math.radians(a) for a in self.arc)
        if n == 1:
            angles = [(start + end) * 0.5]
        else:
            angles = [start + (end - start) * i / (n - 1) for i in range(n)]
        return [(math.cos(a), math.sin(a)) for a in angles]

    # ---- layout ------------------------------------------------------------

    @property
    def center(self):
        return self.rect.cx, self.rect.cy

    def place(self, origin, theme):
        cx, cy = origin
        hub = theme.px(self.hub_radius)
        self.rect = Rect.from_center(cx, cy, hub * 2.0, hub * 2.0)
        ring = theme.px(self.radius)
        for item, (dx, dy) in zip(self.items, self.item_directions()):
            w, h = item.measure(theme)
            item.arrange(Rect.from_center(cx + dx * ring, cy + dy * ring, w, h), theme)
        for widget, gap in self._below:
            w, h = widget.measure(theme)
            top = cy - theme.px(self.footer_gap if gap is None else gap)
            widget.arrange(Rect.from_size(cx - w * 0.5, top - h, w, h), theme)
        self._dead_zone_px = theme.px(self.dead_zone)

    # ---- picking -----------------------------------------------------------

    def pick(self, x, y):
        if not self.visible:
            return None
        # Attached widgets sit "above" the sectors.
        for widget, _gap in reversed(self._below):
            hit = widget.pick(x, y)
            if hit is not None:
                return hit
        cx, cy = self.center
        ux, uy, dist = normalize(x - cx, y - cy)
        if dist < self._dead_zone_px:
            return None
        best, best_dot = None, -2.0
        for item, (vx, vy) in zip(self.items, self.item_directions()):
            if not item.visible:
                continue
            dot = ux * vx + uy * vy
            if dot > best_dot:
                best, best_dot = item, dot
        return best

    def on_key(self, event, ui):
        if self.number_keys and event.is_press:
            index = number_key_index(event.type)
            if index is not None and index < len(self.items):
                ui.choose(self.items[index])
                return True
        return super().on_key(event, ui)

    # ---- drawing -----------------------------------------------------------

    def _arrow(self, dc):
        cx, cy = self.center
        ux, uy, dist = normalize(dc.pointer[0] - cx, dc.pointer[1] - cy)
        if dist < 1e-2:
            return None
        theme = dc.theme
        base = theme.px(12.0)
        length = theme.px(22.0)
        half_w = theme.px(7.0)
        px, py = -uy, ux
        bx, by = cx + ux * base, cy + uy * base
        tip = (bx + ux * length, by + uy * length)
        left = (bx + px * half_w, by + py * half_w)
        right = (bx - px * half_w, by - py * half_w)
        return tip, left, right, (ux, uy)

    def _draw_connector(self, dc, arrow):
        target_widget = dc.chosen if dc.chosen is not None else dc.pointer_widget
        anchor = target_widget.find_anchor(*arrow[0]) if (arrow and target_widget) else None
        if anchor is None:
            self._connector.reset()
            return
        theme = dc.theme
        (tx, ty), (ux, uy) = arrow[0], arrow[3]
        (ax, ay), (hx, hy) = anchor
        nx, ny, cd = normalize(tx - hx, ty - hy)
        if cd < 1e-3:
            return
        (ex, ey), transition = self._connector.update(
            dc.now, (ax, ay), id(target_widget), theme.connector_duration)

        cx, cy = self.center
        # Pull back toward the center only while easing to a new target.
        mix_c = 0.2 * transition
        ex = ex * (1.0 - mix_c) + cx * mix_c
        ey = ey * (1.0 - mix_c) + cy * mix_c

        enx, eny, _ = normalize(ex - hx, ey - hy, (nx, ny))
        tsx, tsy, _ = normalize(tx - ex, ty - ey, (enx, eny))
        efx, efy = enx * 0.55 + tsx * 0.45, eny * 0.55 + tsy * 0.45
        if transition > 0.0:
            ocx, ocy, ocl = normalize(ex - cx, ey - cy)
            if ocl > 0.0:
                m = 0.2 * transition
                efx = efx * (1.0 - m) + ocx * m
                efy = efy * (1.0 - m) + ocy * m
        efx, efy, _ = normalize(efx, efy, (enx, eny))

        tux, tuy, _ = normalize(ex - tx, ey - ty, (ux, uy))
        sux, suy, _ = normalize(ux * 0.55 + tux * 0.45, uy * 0.55 + tuy * 0.45, (ux, uy))

        p0 = (tx, ty)
        p1 = (tx + sux * theme.px(52.0), ty + suy * theme.px(52.0))
        p2 = (ex - efx * theme.px(4.0), ey - efy * theme.px(4.0))
        p3 = (ex, ey)
        draw.bezier(p0, p1, p2, p3, with_alpha(theme.accent, 0.70 * dc.alpha), width=theme.px(3.0))

    def draw_self(self, dc):
        theme = dc.theme
        cx, cy = self.center
        draw.circle(cx, cy, theme.px(self.hub_radius), with_alpha(theme.surface_dark, dc.alpha))
        draw.circle(cx, cy, theme.px(self.hub_dot), with_alpha(theme.accent, 0.95 * dc.alpha))
        arrow = self._arrow(dc) if self.show_arrow else None
        if arrow is not None:
            draw.triangle(arrow[0], arrow[1], arrow[2], with_alpha(theme.accent, 0.92 * dc.alpha))
        if self.show_connector:
            self._draw_connector(dc, arrow)
