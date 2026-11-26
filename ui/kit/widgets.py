"""Ready-made widgets: Label, Button, BubbleButton, RoundButton, DragBubble, ColorBubble, Panel."""

import math

from . import anim
from . import draw
from .geometry import Rect, point_on_circle_toward, point_on_rect_toward
from .theme import mix, with_alpha
from .widget import Widget, _resolve


class Label(Widget):
    def __init__(self, text, *, size=None, color=None, **kwargs):
        super().__init__(**kwargs)
        self.text = text
        self.size = size
        self.color = color

    def _font_size(self, theme):
        return theme.px(self.size if self.size is not None else theme.font_size)

    def measure(self, theme):
        w, h = draw.text_size(self.text, self._font_size(theme), theme.font_id)
        return w, max(h, self._font_size(theme))

    def draw_self(self, dc):
        cx, cy = dc.reveal(self.rect.cx, self.rect.cy)
        alpha = dc.alpha * (1.0 - dc.closing)
        color = with_alpha(self.color or dc.theme.text, 0.95 * alpha)
        draw.text_centered(self.text, cx, cy, self._font_size(dc.theme), color, dc.theme.font_id)


class Button(Widget):
    """Square/rectangular button with an optional icon above a label.
    ``outline`` (class attribute, unscaled px): the border width."""

    interactive = True
    outline = 1.5
    corner = 0.0

    def __init__(self, label="", *, icon=None, icons=None, size=(46.0, 46.0), icon_only=False, **kwargs):
        super().__init__(**kwargs)
        self.label = label
        self.icon = icon
        self.icons = icons
        self.size = size
        self.icon_only = icon_only   # small buttons: centered icon, label only if the icon is missing
        self._visual = None

    def measure(self, theme):
        return theme.px(self.size[0]), theme.px(self.size[1])

    def anchor_point(self, tx, ty):
        return None  # connectors attach to the containing panel

    def _colors(self, dc):
        theme = dc.theme
        pressed = dc.pressed is self and dc.hot is self
        if self.is_selected:
            return theme.accent, theme.accent_light, 1.0
        normal_fill, normal_border, normal_icon = theme.surface, theme.border, 0.78
        hover_fill = theme.surface_pressed if pressed else theme.surface_hover
        t = anim.ease_in_out(self.hover_t)
        fill = mix(normal_fill, hover_fill, t)
        border = mix(normal_border, theme.accent, t)
        return fill, border, normal_icon + (0.95 - normal_icon) * t

    def draw_frame(self, dc, rect, fill, border, alpha):
        """Background and border (override to restyle). ``corner`` (class attribute,
        unscaled px) rounds the corners."""
        theme = dc.theme
        if self.corner > 0.0:
            radius = theme.px(self.corner)
            draw.rounded_rect(rect, radius, with_alpha(fill, alpha))
            draw.rounded_rect_outline(rect, radius, with_alpha(border, alpha), width=theme.px(self.outline))
            return
        draw.rect(rect, with_alpha(fill, alpha))
        draw.rect_outline(rect, with_alpha(border, alpha), width=theme.px(self.outline))

    def draw_self(self, dc):
        theme = dc.theme
        cx, cy = dc.reveal(self.rect.cx, self.rect.cy)
        scale = dc.reveal_scale(0.6)
        if dc.closing > 0.0 and dc.chosen is not self:
            scale *= 1.0 - dc.closing
        w = self.rect.width * scale
        h = self.rect.height * scale
        if w <= 1.0 or h <= 1.0:
            self._visual = None
            return
        rect = Rect.from_center(cx, cy, w, h)
        self._visual = rect

        alpha = dc.alpha * (1.0 if self.is_enabled else theme.disabled_alpha)
        fill, border, icon_alpha = self._colors(dc)
        self.draw_frame(dc, rect, fill, border, alpha)

        icon_size = max(1.0, min(w, h) * (0.72 if self.icon_only else 0.62))
        icon_drawn = False
        if self.icons is not None and self.icon:
            icon_y = cy if self.icon_only else cy + icon_size * 0.2
            icon_drawn = self.icons.draw(self.icon, cx, icon_y, icon_size, icon_alpha * alpha)
        if icon_drawn and self.icon_only:
            return
        label_y = cy - h * 0.22 if icon_drawn else cy
        label_alpha = max(0.72, icon_alpha) * alpha
        draw.text_centered(self.label, cx, label_y, theme.px(theme.font_size_small) * scale,
                           with_alpha(theme.text, label_alpha), theme.font_id)


class BubbleButton(Widget):
    """Round button with icon + label; the classic radial-menu item."""

    interactive = True
    drag_release = True

    def __init__(self, label="", *, icon=None, icons=None, radius=28.0,
                 hover_grow=0.18, chosen_grow=1.6, **kwargs):
        super().__init__(**kwargs)
        self.label = label
        self.icon = icon
        self.icons = icons
        self.radius = radius
        self.hover_grow = hover_grow
        self.chosen_grow = chosen_grow
        self._visual = None   # (cx, cy, radius) as last drawn

    def measure(self, theme):
        d = theme.px(self.radius) * 2.0
        return d, d

    def contains(self, x, y):
        r = self.rect.width * 0.5
        return math.hypot(x - self.rect.cx, y - self.rect.cy) <= r

    def anchor_point(self, tx, ty):
        if self._visual is not None:
            cx, cy, r = self._visual
        else:
            cx, cy, r = self.rect.cx, self.rect.cy, self.rect.width * 0.5
        return point_on_circle_toward(cx, cy, r, tx, ty), (cx, cy)

    def draw_self(self, dc):
        theme = dc.theme
        item_r = self.rect.width * 0.5
        cx, cy = dc.reveal(self.rect.cx, self.rect.cy)
        base_scale = dc.reveal_scale(0.5)
        te = anim.ease_in_out(self.hover_t)
        radius = item_r * base_scale * (1.0 + self.hover_grow * te)
        content_scale = base_scale

        if dc.closing > 0.0:
            if dc.chosen is self:
                target = item_r * self.chosen_grow
                radius += (target - radius) * dc.closing
                content_scale = max(base_scale, radius / max(item_r, 1e-4))
            else:
                radius *= 1.0 - dc.closing
                content_scale *= 1.0 - dc.closing
        if radius <= 0.25 or dc.alpha <= 0.01:
            self._visual = None
            return
        self._visual = (cx, cy, radius)

        alpha = dc.alpha * (1.0 if self.is_enabled else theme.disabled_alpha)
        selected = self.is_selected
        if te > 0.0:
            draw.circle(cx, cy, radius + theme.px(1.9), with_alpha(theme.accent, te * alpha))
            if selected:
                fill = with_alpha(theme.accent, 0.95)
            else:
                g = 0.30 + 0.025 * te
                fill = (g, g, g, 0.94 + 0.02 * te)
        elif selected:
            fill = with_alpha(theme.accent, 0.95)
        else:
            fill = theme.surface
        draw.circle(cx, cy, radius, with_alpha(fill, alpha))

        # Content scales with the bubble's *unscaled* metrics so it stays crisp.
        s = content_scale * theme.scale
        y_off = self.radius * 0.2 * s
        icon_drawn = False
        if self.icons is not None and self.icon:
            icon_drawn = self.icons.draw(self.icon, cx, cy + y_off, max(1.0, 32.0 * s), alpha)
        text_color = with_alpha(theme.text, alpha)
        if icon_drawn:
            draw.text_centered(self.label, cx, cy - 20.0 * s + y_off, max(1.0, 10.0 * s), text_color, theme.font_id)
        else:
            draw.text_centered(self.label, cx, cy + y_off, max(1.0, 12.0 * s), text_color, theme.font_id)


class RoundButton(Widget):
    """Compact circular text button with an outline ring.

    Colors default to the theme; pass ``fill/border/active_fill/active_border``
    to restyle a single button. "Active" = hovered or selected.
    """

    interactive = True

    def __init__(self, label="", *, radius=17.0, font_size=10.0, fill=None, border=None,
                 active_fill=None, active_border=None, **kwargs):
        super().__init__(**kwargs)
        self.label = label
        self.radius = radius
        self.font_size = font_size
        self.fill = fill
        self.border = border
        self.active_fill = active_fill
        self.active_border = active_border

    def measure(self, theme):
        d = theme.px(self.radius) * 2.0
        return d, d

    def contains(self, x, y):
        return math.hypot(x - self.rect.cx, y - self.rect.cy) <= self.rect.width * 0.5

    def anchor_point(self, tx, ty):
        r = self.rect.width * 0.5
        return point_on_circle_toward(self.rect.cx, self.rect.cy, r, tx, ty), (self.rect.cx, self.rect.cy)

    def draw_self(self, dc):
        theme = dc.theme
        cx, cy = dc.reveal(self.rect.cx, self.rect.cy)
        radius = self.rect.width * 0.5 * dc.reveal_scale(0.6)
        active = 1.0 if self.is_selected else anim.ease_in_out(self.hover_t)
        fill = mix(self.fill or theme.surface, self.active_fill or theme.accent, active)
        border = mix(self.border or theme.border, self.active_border or theme.accent_light, active)
        alpha = dc.alpha * (1.0 if self.is_enabled else theme.disabled_alpha)
        draw.circle(cx, cy, radius, with_alpha(fill, alpha))
        draw.circle_outline(cx, cy, radius, with_alpha(border, alpha), width=theme.px(1.0))
        draw.text_centered(self.label, cx, cy, theme.px(self.font_size), with_alpha(theme.text, alpha), theme.font_id)


class DragBubble(Widget):
    """Round knob that edits a value by press-and-drag (no hover needed: pen friendly).

    The press calls ``on_drag_begin()``, every move ``on_drag(dx, dy)`` with
    the pointer offset (screen px) from the press point, the release
    ``on_drag_end(cancelled)``. ``value_text`` (str or zero-arg callable) is
    drawn under the label, ``fraction`` (0..1, or callable) as a ring.
    """

    interactive = True
    draggable = True

    def __init__(self, label="", *, value_text=None, fraction=None, radius=22.0,
                 font_size=10.0, value_font_size=None, on_drag_begin=None, on_drag=None,
                 on_drag_end=None, **kwargs):
        super().__init__(**kwargs)
        self.label = label
        self.value_text = value_text
        self.fraction = fraction
        self.radius = radius
        self.font_size = font_size
        self.value_font_size = value_font_size
        self.on_drag_begin = on_drag_begin
        self.on_drag = on_drag
        self.on_drag_end = on_drag_end
        self.drag_origin = None

    def measure(self, theme):
        d = theme.px(self.radius) * 2.0
        return d, d

    def contains(self, x, y):
        return math.hypot(x - self.rect.cx, y - self.rect.cy) <= self.rect.width * 0.5

    def anchor_point(self, tx, ty):
        r = self.rect.width * 0.5
        return point_on_circle_toward(self.rect.cx, self.rect.cy, r, tx, ty), (self.rect.cx, self.rect.cy)

    # ---- drag --------------------------------------------------------------

    def drag_begin(self, x, y):
        self.drag_origin = (x, y)
        if self.on_drag_begin is not None:
            self.on_drag_begin()

    def drag_update(self, x, y):
        if self.drag_origin is None or self.on_drag is None:
            return
        self.on_drag(x - self.drag_origin[0], y - self.drag_origin[1])

    def drag_end(self, x, y, cancelled=False):
        self.drag_origin = None
        if self.on_drag_end is not None:
            self.on_drag_end(cancelled)

    # ---- drawing -----------------------------------------------------------

    def draw_self(self, dc):
        theme = dc.theme
        cx, cy = dc.reveal(self.rect.cx, self.rect.cy)
        radius = self.rect.width * 0.5 * dc.reveal_scale(0.6)
        if radius <= 1.0:
            return
        active = 1.0 if self.drag_origin is not None else anim.ease_in_out(self.hover_t)
        alpha = dc.alpha * (1.0 if self.is_enabled else theme.disabled_alpha)
        fill = mix(theme.surface, theme.surface_pressed, active)
        border = mix(theme.border, theme.accent, active)
        draw.circle(cx, cy, radius, with_alpha(fill, alpha))
        draw.circle_outline(cx, cy, radius, with_alpha(border, alpha), width=theme.px(1.0))

        fraction = _resolve(self.fraction, None)
        if fraction is not None:
            fraction = max(0.0, min(1.0, float(fraction)))
            ring = radius - theme.px(3.0)
            draw.arc(cx, cy, ring, 0.0, math.tau, with_alpha(theme.surface_dark, alpha), width=theme.px(2.5))
            if fraction > 0.0:
                # Clockwise from 12 o'clock.
                draw.arc(cx, cy, ring, math.pi * 0.5, math.pi * 0.5 - math.tau * fraction,
                         with_alpha(theme.accent, alpha), width=theme.px(2.5))

        label_size = theme.px(self.font_size)
        value = _resolve(self.value_text, "")
        text = with_alpha(theme.text, alpha)
        if value:
            value_size = theme.px(self.value_font_size or self.font_size * 1.3)
            draw.text_centered(self.label, cx, cy + radius * 0.3, label_size,
                               with_alpha(theme.text_muted, alpha), theme.font_id)
            draw.text_centered(str(value), cx, cy - radius * 0.15, value_size, text, theme.font_id)
        else:
            draw.text_centered(self.label, cx, cy, label_size, text, theme.font_id)


class Panel(Widget):
    """Titled container around a single content widget.

    Panels block the pointer: hovering empty panel space does not fall
    through to widgets behind (e.g. radial sectors), and connectors attach
    to the panel's outline.
    """

    blocks_pointer = True
    corner_cap = None   # screen px: the background's corner radius never exceeds this

    def __init__(self, content=None, *, title=None, padding=10.0, title_gap=6.0,
                 min_width=0.0, background=True, corner=10.0, **kwargs):
        super().__init__(**kwargs)
        self.corner = corner        # unscaled px: corner radius of the background
        self.title = title
        self.padding = padding
        self.title_gap = title_gap
        self.min_width = min_width
        self.background = background
        self.content = self.add(content) if content is not None else None
        self._title_y = 0.0
        self._visual = None

    def _title_height(self, theme):
        if not self.title:
            return 0.0
        return theme.px(theme.font_size) + theme.px(self.title_gap)

    def measure(self, theme):
        cw, ch = self.content.measure(theme) if self.content is not None else (0.0, 0.0)
        tw = draw.text_size(self.title, theme.px(theme.font_size), theme.font_id)[0] if self.title else 0.0
        pad = theme.px(self.padding)
        width = max(cw, tw, theme.px(self.min_width)) + pad * 2.0
        height = ch + self._title_height(theme) + pad * 2.0
        return width, height

    def arrange(self, rect, theme):
        self.rect = rect
        pad = theme.px(self.padding)
        top = rect.y1 - pad
        if self.title:
            self._title_y = top - theme.px(theme.font_size) * 0.5
            top -= self._title_height(theme)
        if self.content is not None:
            cw, ch = self.content.measure(theme)
            self.content.arrange(Rect.from_size(rect.cx - cw * 0.5, top - ch, cw, ch), theme)

    def corner_px(self, theme):
        """Screen corner radius of the background."""
        radius = theme.px(self.corner)
        return radius if self.corner_cap is None else min(radius, self.corner_cap)

    def anchor_point(self, tx, ty):
        rect = self._visual or self.rect
        return point_on_rect_toward(rect, tx, ty), (rect.cx, rect.cy)

    def draw_self(self, dc):
        theme = dc.theme
        cx, cy = dc.reveal(self.rect.cx, self.rect.cy)
        k = dc.opened * (1.0 - dc.closing)
        self._visual = Rect.from_center(cx, cy, self.rect.width * k, self.rect.height * k)
        alpha = dc.alpha * (1.0 - dc.closing)
        if self.background and k > 0.01:
            draw.rounded_rect(self._visual, self.corner_px(theme) * k, with_alpha(theme.panel_background, alpha))
        if self.title:
            tx, ty = dc.reveal(self.rect.cx, self._title_y)
            draw.text_centered(self.title, tx, ty, theme.px(theme.font_size),
                               with_alpha(theme.text, 0.95 * alpha), theme.font_id)


class ColorBubble(Widget):
    """Old / new color bubble (new on top). Tap accepts the new color as reference.

    Keeps its size while hidden (``shown`` false) so its row does not shift.
    """

    interactive = True

    def __init__(self, colors, shown, changed, *, radius=19.0, **kwargs):
        super().__init__(**kwargs)
        self.colors = colors      # () -> (old_rgb, new_rgb)
        self.shown = shown        # () -> bool
        self.changed = changed    # () -> bool: new differs from old
        self.radius = radius

    @property
    def is_shown(self):
        return bool(_resolve(self.shown, False))

    def measure(self, theme):
        d = theme.px(self.radius) * 2.0
        return d, d

    def contains(self, x, y):
        return self.is_shown and math.hypot(x - self.rect.cx, y - self.rect.cy) <= self.rect.width * 0.5

    def draw_self(self, dc):
        if not self.is_shown:
            return
        theme = dc.theme
        cx, cy = self.rect.cx, self.rect.cy
        r = self.rect.width * 0.5
        alpha = dc.alpha
        old, new = _resolve(self.colors, ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)))
        draw.sector(cx, cy, r, 0.0, math.pi, (new[0], new[1], new[2], alpha))
        draw.sector(cx, cy, r, math.pi, math.tau, (old[0], old[1], old[2], alpha))
        if bool(_resolve(self.changed, False)):
            draw.circle_outline(cx, cy, r, with_alpha(theme.accent_light, alpha), width=theme.px(2.0))
        else:
            draw.circle_outline(cx, cy, r, with_alpha(theme.border, alpha), width=theme.px(1.0))
