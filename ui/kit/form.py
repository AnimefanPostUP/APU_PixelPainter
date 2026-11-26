"""Form widgets for settings-style panels (pen friendly: press / drag / release only).

* :class:`Group`      titled block of related controls: tinted background, a
                       colored stripe on the left, optional icon before the title.
* :class:`Slider`     horizontal value slider: press sets the value from the
                       pointer, drag keeps setting it, ESC / right click restores.
* :class:`IconButton` button drawing ``painter(dc, x, y, size, alpha)`` as its
                       icon, with the label under it (``layout='column'``), beside
                       it (``'row'``) or hidden.
* :class:`TextBlock`  left-aligned muted lines (hints).
* :class:`Spacer`     fixed empty space.

Text, values, titles, ranges and enabled states may be callables (evaluated lazily).
"""

from . import draw
from .geometry import Rect
from .theme import mix, with_alpha
from .widget import Widget, _resolve
from .widgets import Button


def text_left(text, x, cy, size, color, font_id=0):
    """``text`` starting at ``x``, vertically centered on ``cy``."""
    if not text:
        return
    w, _h = draw.text_size(text, size, font_id)
    draw.text_centered(text, x + w * 0.5, cy, size, color, font_id)


class Spacer(Widget):
    def __init__(self, width=0.0, height=0.0, **kwargs):
        super().__init__(**kwargs)
        self.size = (width, height)

    def measure(self, theme):
        return theme.px(self.size[0]), theme.px(self.size[1])


class TextBlock(Widget):
    """Left-aligned lines; ``lines``: list of str (or a callable returning one)."""

    def __init__(self, lines, *, size=9.0, width=None, color=None, line_gap=1.35, **kwargs):
        super().__init__(**kwargs)
        self.lines = lines
        self.size = size
        self.width = width
        self.color = color
        self.line_gap = line_gap

    def _lines(self):
        lines = _resolve(self.lines, [])
        return [lines] if isinstance(lines, str) else list(lines or [])

    def measure(self, theme):
        size = theme.px(self.size)
        lines = self._lines()
        widest = max((draw.text_size(line, size, theme.font_id)[0] for line in lines), default=0.0)
        width = theme.px(self.width) if self.width else widest
        return width, size * self.line_gap * len(lines)

    def draw_self(self, dc):
        theme = dc.theme
        size = theme.px(self.size)
        step = size * self.line_gap
        color = with_alpha(self.color or theme.text_muted, dc.alpha)
        y = self.rect.y1 - step * 0.5
        for line in self._lines():
            text_left(line, self.rect.x0, y, size, color, theme.font_id)
            y -= step


class Group(Widget):
    """Titled block of related controls. ``tint`` (RGB) colors the stripe and the
    background; ``painter`` draws an icon before the title; ``width`` (unscaled)
    makes groups of a page equally wide; ``title_indent`` (unscaled) moves the title
    right (room for a corner button). The content is centered."""

    blocks_pointer = True

    def __init__(self, title, content, *, tint=(0.66, 0.44, 0.92), painter=None, width=None,
                 padding=7.0, title_size=10.5, title_indent=0.0, **kwargs):
        super().__init__(**kwargs)
        self.title = title
        self.title_indent = title_indent
        self.content = self.add(content)
        self.tint = tint
        self.painter = painter
        self.width = width
        self.padding = padding
        self.title_size = title_size

    def _title_h(self, theme):
        return theme.px(self.title_size) + theme.px(8.0)

    def measure(self, theme):
        cw, ch = self.content.measure(theme)
        pad = theme.px(self.padding)
        width = max(cw + pad * 2.0 + theme.px(3.0), theme.px(self.width) if self.width else 0.0)
        return width, ch + self._title_h(theme) + pad * 2.0

    def arrange(self, rect, theme):
        self.rect = rect
        cw, ch = self.content.measure(theme)
        pad = theme.px(self.padding)
        top = rect.y1 - pad - self._title_h(theme)
        cx = rect.cx + theme.px(1.5)   # centered right of the stripe
        self.content.arrange(Rect.from_size(cx - cw * 0.5, top - ch, cw, ch), theme)

    def draw_self(self, dc):
        theme = dc.theme
        r = self.rect
        tint = (*self.tint[:3], 1.0)
        alpha = dc.alpha
        draw.rect(r, with_alpha(mix(theme.surface_dark, tint, 0.10), alpha))
        draw.rect(Rect(r.x0, r.y0, r.x0 + theme.px(3.0), r.y1), with_alpha(tint, 0.9 * alpha))
        pad = theme.px(self.padding)
        size = theme.px(self.title_size)
        ty = r.y1 - pad - size * 0.5
        x = r.x0 + theme.px(3.0) + pad + theme.px(self.title_indent)
        if self.painter is not None:
            self.painter(dc, x + size * 0.6, ty, size * 1.4, alpha)
            x += size * 1.6
        text_left(str(_resolve(self.title, "")), x, ty, size, with_alpha(mix(theme.text, tint, 0.25), alpha),
                  theme.font_id)
        line_y = r.y1 - pad - self._title_h(theme) + theme.px(3.0)
        draw.rect(Rect(r.x0 + theme.px(3.0) + pad, line_y - 0.5, r.x1 - pad, line_y + 0.5),
                  with_alpha(tint, 0.35 * alpha))


class Slider(Widget):
    """Horizontal slider. ``value()`` / ``on_value(v)``; ``value_range`` (lo, hi) or a
    callable returning it; ``step`` rounds (1 for integers); ``fmt(v) -> str`` the
    value text (default: percent for 0..1, else the number)."""

    interactive = True

    def __init__(self, label, value, on_value, *, value_range=(0.0, 1.0), step=None, fmt=None,
                 size=(200.0, 24.0), fill_color=None, font_size=9.5, corner=0.0, **kwargs):
        super().__init__(**kwargs)
        self.corner = corner          # unscaled px: rounded track (0 = square)
        self.label = label
        self.value = value
        self.on_value = on_value
        self.value_range = value_range
        self.step = step
        self.fmt = fmt
        self.size = size
        self.fill_color = fill_color
        self.font_size = font_size
        self._original = None
        self._dragging = False

    @property
    def draggable(self):
        return self.is_enabled

    def measure(self, theme):
        return theme.px(self.size[0]), theme.px(self.size[1])

    def _range(self):
        lo, hi = _resolve(self.value_range, (0.0, 1.0))
        return float(lo), float(hi)

    def _value(self):
        try:
            return float(_resolve(self.value, 0.0))
        except (TypeError, ValueError):
            return 0.0

    def value_at(self, x):
        lo, hi = self._range()
        t = (x - self.rect.x0) / max(1.0, self.rect.width)
        v = lo + max(0.0, min(1.0, t)) * (hi - lo)
        if self.step:
            v = round(v / self.step) * self.step
        return v

    def drag_begin(self, x, y):
        self._original = self._value()
        self._dragging = True
        self.on_value(self.value_at(x))

    def drag_update(self, x, y):
        if self._dragging:
            self.on_value(self.value_at(x))

    def drag_end(self, x, y, cancelled=False):
        if cancelled and self._original is not None:
            self.on_value(self._original)
        self._original = None
        self._dragging = False

    def _text(self, v):
        if self.fmt is not None:
            return self.fmt(v)
        lo, hi = self._range()
        if self.step == 1:
            return str(int(round(v)))
        if lo == 0.0 and hi == 1.0:
            return f"{v * 100:.0f}%"
        return f"{v:.2f}"

    def draw_self(self, dc):
        theme = dc.theme
        r = self.rect
        alpha = dc.alpha * (1.0 if self.is_enabled else theme.disabled_alpha)
        active = self._dragging or self.hover_t > 0.5
        lo, hi = self._range()
        v = self._value()
        t = 0.0 if hi <= lo else max(0.0, min(1.0, (v - lo) / (hi - lo)))
        fill = self.fill_color or theme.accent
        border = with_alpha(theme.accent if active else theme.border, alpha)
        if self.corner > 0.0:
            # Rounded track; the value fill is a slight gradient (darker at the start).
            radius = theme.px(self.corner)
            draw.rounded_rect(r, radius, with_alpha(theme.surface_dark, alpha))
            if t > 0.0:
                dark = tuple(c * 0.62 for c in fill[:3])

                def shade(fx, _fy):
                    return (*(dark[i] + (fill[i] - dark[i]) * fx * t for i in range(3)), 0.85 * alpha)

                draw.rounded_grid(Rect(r.x0, r.y0, r.x0 + max(r.width * t, 2.0 * radius), r.y1), radius,
                                  shade, 6, 1)
            draw.rounded_rect_outline(r, radius, border, width=theme.px(1.0))
        else:
            draw.rect(r, with_alpha(theme.surface_dark, alpha))
            if t > 0.0:
                draw.rect(Rect(r.x0, r.y0, r.x0 + r.width * t, r.y1), with_alpha(fill, 0.75 * alpha))
            draw.rect_outline(r, border, width=theme.px(1.0))
        size = theme.px(self.font_size)
        pad = theme.px(7.0)
        text_left(str(_resolve(self.label, "")), r.x0 + pad, r.cy, size, with_alpha(theme.text, alpha), theme.font_id)
        value = self._text(v)
        w, _h = draw.text_size(value, size, theme.font_id)
        draw.text_centered(value, r.x1 - pad - w * 0.5, r.cy, size, with_alpha(theme.text, alpha), theme.font_id)


class IconButton(Button):
    """Button with a painted icon. ``layout``: 'column' (icon over the label),
    'row' (icon left of the label) or 'icon' (no label)."""

    def __init__(self, label="", *, painter=None, layout='column', font_size=9.0, **kwargs):
        super().__init__(label, **kwargs)
        self.painter = painter
        self.layout = layout
        self.font_size = font_size

    def draw_self(self, dc):
        label, self.label = self.label, ""
        try:
            super().draw_self(dc)          # frame (and an IconSet icon, if any)
        finally:
            self.label = label
        r = self._visual
        if r is None:
            return
        theme = dc.theme
        alpha = dc.alpha * (1.0 if self.is_enabled else theme.disabled_alpha)
        color = with_alpha(theme.text, alpha)
        size = theme.px(self.font_size)
        text = str(_resolve(label, ""))
        if self.layout == 'icon' or not text:
            if self.painter is not None:
                self.painter(dc, r.cx, r.cy, min(r.width, r.height) * 0.9, alpha)
            return
        if self.layout == 'row':
            icon = r.height * 0.8
            tw, _th = draw.text_size(text, size, theme.font_id)
            total = (icon + theme.px(4.0) if self.painter else 0.0) + tw
            x = r.cx - total * 0.5
            if self.painter is not None:
                self.painter(dc, x + icon * 0.5, r.cy, icon, alpha)
                x += icon + theme.px(4.0)
            text_left(text, x, r.cy, size, color, theme.font_id)
            return
        icon = min(r.width, r.height - size * 1.4)
        if self.painter is not None:
            self.painter(dc, r.cx, r.y1 - icon * 0.5 - theme.px(2.0), icon, alpha)
        draw.text_centered(text, r.cx, r.y0 + size * 0.75, size, color, theme.font_id)
