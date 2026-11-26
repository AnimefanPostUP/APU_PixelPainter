"""The pen UI's look, shared by the windows and flyouts (Mask, View, Settings, Blend,
Palettes, Curve, the confirm dialog).

One design: neutral grays with a single accent color, soft round shapes, a darker
rim around filled shapes, an accent outline on hover and an accent band when
selected (like the pen menu's segments). Category tints are optional and light.

* :class:`PenButton` -- rounded button (icon and / or label).
* :class:`PenFlyoutButton` -- the same, confirming when the pen lifts over it.
* :class:`DangerButton` -- red-tinted (delete / replace).
* :class:`PlainGroup` -- a titled block on a soft neutral plate (no stripe, no tint).
* :class:`PenPanel` -- a flyout panel with its title on a plate at the top.
* :func:`pen_fill` -- a segment / button fill (hover, press, selection).
"""

from ..kit import Group, IconButton, Panel, Rect
from ..kit import anim, draw
from ..kit.form import text_left
from ..kit.theme import mix, with_alpha
from ..kit.widget import _resolve

BUTTON_ROUND = 7.0       # corner radius of buttons, unscaled px
TINT_AMOUNT = 0.16       # an optional category tint in a fill (as the pen menu's segments)
GROUP_ROUND = 9.0        # corner radius of a group's plate
GROUP_PLATE = (0.16, 0.16, 0.16, 0.6)  # a group's plate: a little lighter than the panel
TITLE_PLATE = (0.06, 0.06, 0.06, 0.75)  # a flyout's title plate
DANGER = (0.85, 0.22, 0.22, 1.0)


def pen_fill(dc, widget, tint=None, base=None, tint_amount=TINT_AMOUNT):
    """A pen-menu fill: the surface (``tint`` mixed in lightly), lighter while hovered /
    pressed, accent-tinted while selected (see ``RingSegment._fill``). ``(fill, hover)``."""
    theme = dc.theme
    base = base or theme.surface
    if tint is not None:
        base = mix(base, (*tint[:3], base[3]), tint_amount)
    pressed = dc.pressed is widget and dc.hot is widget
    t = anim.ease_in_out(widget.hover_t)
    fill = mix(base, theme.surface_pressed if pressed else theme.surface_hover, t * 0.8)
    if widget.is_selected:
        fill = mix(fill, theme.accent, 0.4)
    return fill, t


class PenButton(IconButton):
    """Rounded button in the pen menu's style: a filled shape with a darker rim, an
    accent outline while hovered, an accent band along the bottom while selected.
    ``tint`` (RGB, optional) colors the fill lightly. Text-only by default
    (``layout='row'``); ``icon_only`` buttons show just their icon."""

    outline = 1.0
    corner = BUTTON_ROUND

    def __init__(self, label="", *, tint=None, tint_amount=TINT_AMOUNT, layout='row', **kwargs):
        if kwargs.get('icon_only'):
            layout = 'icon'
        super().__init__(label, layout=layout, **kwargs)
        self.tint = tint
        self.tint_amount = tint_amount

    def _colors(self, dc):
        fill, border, icon = super()._colors(dc)
        return fill, border, max(icon, 0.9)

    def draw_frame(self, dc, rect, fill, border, alpha):
        theme = dc.theme
        radius = min(theme.px(self.corner), rect.height * 0.5)
        fill, t = pen_fill(dc, self, self.tint, tint_amount=self.tint_amount)
        draw.rounded_rect(rect, radius, with_alpha(fill, alpha), rim=theme.edge_for(fill, alpha))
        if self.is_selected:
            band = theme.px(3.0)
            inset = max(radius * 0.6, band)
            draw.rounded_rect(Rect(rect.x0 + inset, rect.y0 + band * 0.7, rect.x1 - inset, rect.y0 + band * 1.7),
                              band, with_alpha(theme.accent, alpha))
        if t > 0.01:
            draw.rounded_rect_outline(rect, radius, with_alpha(theme.accent, t * alpha), width=theme.px(1.5))


class PenFlyoutButton(PenButton):
    """Flyout entry: also confirms when the pen is lifted over it after dragging in."""

    drag_release = True


class DangerButton(PenButton):
    """Red-tinted action button (delete / replace)."""

    def __init__(self, label="", **kwargs):
        kwargs.setdefault('tint', DANGER[:3])
        kwargs.setdefault('tint_amount', 0.55)
        super().__init__(label, **kwargs)


class PlainGroup(Group):
    """Titled block on a soft neutral plate: the title (with its icon) in plain text,
    no stripe, divider or category color. Accepts ``tint`` and ignores it."""

    def draw_self(self, dc):
        theme = dc.theme
        r = self.rect
        alpha = dc.alpha
        draw.rounded_rect(r, theme.px(GROUP_ROUND), with_alpha(GROUP_PLATE, alpha))
        pad = theme.px(self.padding)
        size = theme.px(self.title_size)
        ty = r.y1 - pad - size * 0.5
        x = r.x0 + pad + theme.px(self.title_indent)
        if self.painter is not None:
            self.painter(dc, x + size * 0.6, ty, size * 1.4, alpha)
            x += size * 1.6
        text_left(str(_resolve(self.title, "")), x, ty, size, with_alpha(theme.text_muted, alpha), theme.font_id)


class PenPanel(Panel):
    """A flyout panel: rounded background, the title on a dark plate centered at the top."""

    def draw_self(self, dc):
        title, self.title = self.title, None
        try:
            super().draw_self(dc)          # the background only
        finally:
            self.title = title
        if not title:
            return
        theme = dc.theme
        alpha = dc.alpha * (1.0 - dc.closing)
        size = theme.px(theme.font_size)
        tx, ty = dc.reveal(self.rect.cx, self._title_y)
        tw = draw.text_size(title, size, theme.font_id)[0]
        h = size + theme.px(8.0)
        plate = Rect.from_center(tx, ty, tw + theme.px(24.0), h)
        draw.rounded_rect(plate, h * 0.5, with_alpha(TITLE_PLATE, alpha))
        draw.text_centered(title, tx, ty, size, with_alpha(theme.text, 0.95 * alpha), theme.font_id)
