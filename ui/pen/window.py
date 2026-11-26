"""Floating windows of the pen UI: :class:`Window` (move by the background, padlock,
X, resize triangle, help), its corner buttons, the menu layer.
"""

import math

from ..kit import Label, Panel, Rect, Widget
from ..kit import draw
from ..kit.geometry import clamp_box
from ..kit.theme import with_alpha
from ..kit.widget import _resolve
from .metrics import FLYOUT_GAP, CORNER_CAP, CORNER_HIT, CORNER_INSET, CORNER_RADIUS


class HintLabel(Label):
    """Label whose text comes from ``text_fn()``."""

    def __init__(self, text_fn, **kwargs):
        super().__init__("", **kwargs)
        self.text_fn = text_fn

    def measure(self, theme):
        self.text = str(_resolve(self.text_fn, ""))
        return super().measure(theme)


class CornerButton(Widget):
    """Small round button in an element's corner: ``glyph`` 'CLOSE' (X), 'HELP' (?) or 'LOCK'
    (padlock, closed while ``selected``). Its tap area is larger than the drawing (pens)."""

    interactive = True

    def __init__(self, glyph, *, radius=CORNER_RADIUS, hit=CORNER_HIT, **kwargs):
        super().__init__(**kwargs)
        self.glyph = glyph
        self.radius = radius
        self.hit = hit
        self._hit_px = 0.0

    def measure(self, theme):
        self._hit_px = theme.px(self.hit)
        d = theme.px(self.radius) * 2.0
        return d, d

    def contains(self, x, y):
        reach = self.rect.width * 0.5 + self._hit_px
        return math.hypot(x - self.rect.cx, y - self.rect.cy) <= reach

    def draw_self(self, dc):
        theme = dc.theme
        cx, cy, r = self.rect.cx, self.rect.cy, self.rect.width * 0.5
        hot = self.hover_t > 0.5
        on = self.is_selected
        fill = theme.accent if on else (theme.surface_pressed if hot else theme.surface)
        draw.circle(cx, cy, r, with_alpha(fill, dc.alpha))
        draw.circle_outline(cx, cy, r, with_alpha(theme.accent if hot else theme.border, dc.alpha),
                            width=theme.px(1.0))
        color = with_alpha(theme.text, 0.9 * dc.alpha)
        width = max(1.0, theme.px(1.2))
        if self.glyph == 'HELP':
            draw.text_centered("?", cx, cy, r * 1.35, color, theme.font_id)
            return
        if self.glyph == 'CLOSE':
            arm = r * 0.5
            draw.polyline([(cx - arm, cy - arm), (cx + arm, cy + arm)], color, width)
            draw.polyline([(cx - arm, cy + arm), (cx + arm, cy - arm)], color, width)
            return
        # Padlock; the shackle opens (lifts, one leg free) while unlocked.
        bw, bh = r * 0.95, r * 0.7
        body = Rect.from_size(cx - bw * 0.5, cy - r * 0.6, bw, bh)
        draw.rect(body, color)
        lift = 0.0 if on else r * 0.25
        sr = bw * 0.32
        sx = cx if on else cx + sr * 0.5
        draw.arc(sx, body.y1 + lift + sr * 0.2, sr, 0.0, math.pi, color, width=width, segments=12)
        draw.polyline([(sx - sr, body.y1 + lift + sr * 0.2), (sx - sr, body.y1 + (lift if not on else 0.0))],
                      color, width)
        draw.polyline([(sx + sr, body.y1 + lift + sr * 0.2), (sx + sr, body.y1)], color, width)


class ResizeHandle(Widget):
    """Triangle in an element's bottom-right corner; press and drag to resize.

    ``on_drag(dx, dy)`` gets the pointer offset from the press point.
    """

    interactive = True
    draggable = True

    def __init__(self, on_drag_begin, on_drag, on_drag_end, **kwargs):
        super().__init__(**kwargs)
        self.on_drag_begin = on_drag_begin
        self.on_drag = on_drag
        self.on_drag_end = on_drag_end
        self.drag_origin = None
        self.corner = 0.0               # screen px: the panel's corner radius (the triangle follows it)

    def drag_begin(self, x, y):
        self.drag_origin = (x, y)
        self.on_drag_begin()

    def drag_update(self, x, y):
        if self.drag_origin is not None:
            self.on_drag(x - self.drag_origin[0], y - self.drag_origin[1])

    def drag_end(self, x, y, cancelled=False):
        self.drag_origin = None
        self.on_drag_end(cancelled)

    def draw_self(self, dc):
        theme = dc.theme
        r = self.rect
        active = self.drag_origin is not None or self.hover_t > 0.5
        fill = with_alpha(theme.accent if active else theme.border, dc.alpha)
        rad = min(self.corner, r.width * 0.8, r.height * 0.8)
        if rad < 0.5:
            draw.triangle((r.x1, r.y0), (r.x0, r.y0), (r.x1, r.y1), fill)
            return
        # The triangle with its right angle rounded like the panel's corner.
        cx, cy = r.x1 - rad, r.y0 + rad
        arc = [(cx + math.cos(math.radians(a)) * rad, cy + math.sin(math.radians(a)) * rad)
               for a in range(-90, 1, 10)]
        draw._fill([(r.x0, r.y0)] + arc + [(r.x1, r.y1)], fill)


class MovePanel(Panel):
    """Panel whose empty background moves its element when dragged (unless ``locked``).

    ``shape(panel, theme)`` (optional) returns the background as shapes fitted to the
    content (``ui/window_shapes.py``) instead of one rectangle; presses outside them
    fall through."""

    interactive = True

    def __init__(self, content, *, locked, on_move_begin, on_move, on_move_end, shape=None, **kwargs):
        super().__init__(content, **kwargs)
        self.locked = locked
        self.on_move_begin = on_move_begin
        self.on_move = on_move
        self.on_move_end = on_move_end
        self.drag_origin = None
        self.shape = shape
        self._theme = None

    def arrange(self, rect, theme):
        super().arrange(rect, theme)
        self._theme = theme

    def shapes(self):
        if self.shape is None or self._theme is None:
            return None
        return self.shape(self, self._theme)

    def contains(self, x, y):
        if not self.rect.contains(x, y):
            return False
        shapes = self.shapes()
        return shapes is None or any(s.contains(x, y) for s in shapes)

    def draw_self(self, dc):
        shapes = self.shapes()
        if shapes is None:
            super().draw_self(dc)
            return
        from .shapes import draw_shapes   # late import: it imports the kit only
        draw_shapes(shapes, with_alpha(dc.theme.panel_background, dc.alpha))

    @property
    def draggable(self):
        return not _resolve(self.locked, False)

    def drag_begin(self, x, y):
        self.drag_origin = (x, y)
        self.on_move_begin()

    def drag_update(self, x, y):
        if self.drag_origin is not None:
            self.on_move(x - self.drag_origin[0], y - self.drag_origin[1])

    def drag_end(self, x, y, cancelled=False):
        self.drag_origin = None
        self.on_move_end(cancelled)


class Window(Widget):
    """A floating element: a movable panel with a lock (top left, or bottom left with
    ``lock_bottom``), an optional X (top right) and a resize triangle (bottom right,
    hidden while locked). ``tab`` (optional) replaces it while ``collapsed``. Placed
    by its top-left corner."""

    def __init__(self, panel, lock, grip, *, locked, close=None, tab=None, lock_bottom=False, help=None):
        super().__init__()
        self.lock_bottom = lock_bottom
        self.panel = self.add(panel)
        self.tab = self.add(tab) if tab is not None else None
        self.lock = self.add(lock)
        self.close = self.add(close) if close is not None else None
        self.help = self.add(help) if help is not None else None    # '?' left of the X
        self.grip = self.add(grip)      # last: picked before the panel under it
        self.locked = locked
        self.collapsed = False
        self.grip_size = 0.0            # screen px, set by the PenBar

    @property
    def grip_size(self):
        return self._grip_size

    @grip_size.setter
    def grip_size(self, value):
        """The resize triangle's legs (screen px); the panel's rounded corners stay
        smaller, so the triangle keeps a visible body in the bottom-right corner."""
        self._grip_size = value
        self.panel.corner_cap = value * CORNER_CAP if value > 0.0 else None

    @property
    def shown(self):
        return self.tab if (self.collapsed and self.tab is not None) else self.panel

    def measure(self, theme):
        return self.shown.measure(theme)

    def place(self, origin, theme):
        """``origin`` = (x0, y1): the top-left corner."""
        x0, y1 = origin
        shown = self.shown
        w, h = shown.measure(theme)
        shown.arrange(Rect.from_size(x0, y1 - h, w, h), theme)
        self.rect = shown.rect
        expanded = shown is self.panel
        self.panel.visible = expanded
        if self.tab is not None:
            self.tab.visible = not expanded
        for corner in (self.lock, self.close, self.help):
            if corner is not None:
                corner.visible = expanded
        self.grip.visible = expanded and not _resolve(self.locked, False)
        if not expanded:
            return
        plate = getattr(self.panel.content, 'plate', None)
        if plate is not None:
            self._place_on_plate(plate, theme)
            return
        r = self.panel.rect
        inset = theme.px(CORNER_INSET)
        lw, lh = self.lock.measure(theme)
        ly = r.y0 + inset if self.lock_bottom else r.y1 - inset - lh
        self.lock.arrange(Rect.from_size(r.x0 + inset, ly, lw, lh), theme)
        right = r.x1 - inset
        for corner in (self.close, self.help):
            if corner is not None:
                cw, ch = corner.measure(theme)
                corner.arrange(Rect.from_size(right - cw, r.y1 - inset - ch, cw, ch), theme)
                right -= cw + inset * 1.5
        g = self.grip_size
        self.grip.corner = self.panel.corner_px(theme)
        self.grip.arrange(Rect.from_size(r.x1 - g, r.y0, g, g), theme)

    def _place_on_plate(self, plate, theme):
        """The title plate on top (``content.plate``, see ``ui/pen_windows.py``): the lock
        at its left end, the resize triangle in its bottom-right corner, X and '?' left of it."""
        inset = theme.px(CORNER_INSET)
        lw, lh = self.lock.measure(theme)
        self.lock.arrange(Rect.from_size(plate.x0 + inset * 1.5, plate.cy - lh * 0.5, lw, lh), theme)
        g = min(self.grip_size, plate.height)
        self.grip.corner = getattr(self.panel.content, 'plate_round_px', 0.0)
        self.grip.arrange(Rect.from_size(plate.x1 - g, plate.y0, g, g), theme)
        right = plate.x1 - g - inset
        for corner in (self.close, self.help):
            if corner is not None:
                cw, ch = corner.measure(theme)
                corner.arrange(Rect.from_size(right - cw, plate.cy - ch * 0.5, cw, ch), theme)
                right -= cw + inset * 1.5


class MenuLayer(Widget):
    """Root of the pen menu's layer: the menu window and its flyouts (beside it, toward the canvas)."""

    def __init__(self, window, flyouts, dialog=None):
        super().__init__()
        self.window = self.add(window)
        self.flyouts = [self.add(flyout) for flyout in flyouts]
        self.dialog = self.add(dialog) if dialog is not None else None   # last: drawn / picked on top
        self.openers = {}          # flyout -> the widget that opened it
        self.region = (0.0, 0.0)

    def measure(self, theme):
        return self.window.measure(theme)

    def place(self, origin, theme):
        self.window.place(origin, theme)
        self.rect = win = self.window.rect
        gap = theme.px(FLYOUT_GAP)
        margin = theme.px(theme.region_margin)
        width, height = self.region
        for flyout in self.flyouts:
            if not flyout.visible:
                continue
            fw, fh = flyout.measure(theme)
            opener = self.openers.get(flyout)
            if opener is not None and getattr(flyout, 'below_opener', False):
                # A popup of another window (the color selector's shapes): under its button.
                o = opener.rect
                fy0 = o.y0 - gap - fh
                if fy0 < margin:
                    fy0 = o.y1 + gap
                fx, y0 = clamp_box(o.cx - fw * 0.5, fy0, fw, fh, (margin, margin, width - margin, height - margin))
                flyout.arrange(Rect.from_size(fx, y0, fw, fh), theme)
                continue
            fy = opener.rect.cy if opener is not None else win.cy
            right = win.cx < width * 0.5
            fx = win.x1 + gap if right else win.x0 - gap - fw
            anchor = getattr(flyout, 'anchor_bottom', None)   # bottom-anchored: height changes grow upward
            fy0 = fy - theme.px(anchor) if anchor is not None else fy - fh * 0.5
            fx, y0 = clamp_box(fx, fy0, fw, fh, (margin, margin, width - margin, height - margin))
            flyout.arrange(Rect.from_size(fx, y0, fw, fh), theme)
        if self.dialog is not None and self.dialog.visible:   # centered over the menu
            dw, dh = self.dialog.measure(theme)
            dx, dy = clamp_box(win.cx - dw * 0.5, win.cy - dh * 0.5, dw, dh,
                               (margin, margin, width - margin, height - margin))
            self.dialog.arrange(Rect.from_size(dx, dy, dw, dh), theme)
