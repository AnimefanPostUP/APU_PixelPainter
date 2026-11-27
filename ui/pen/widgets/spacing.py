"""The pen menu's spacing (model/spacing.py), one capsule along the circle at the bottom
right: on the left the mode button (Once -> Fixed -> Time, its name written along the
arc), right of it the mode's value as an arc slider showing just the number and unit
(Once: pixels per stamp, Fixed: pixels between stamps, Time: ms between stamps; Time's
scale is two-part, model/spacing.slider_value). While dragged, a readout beside the
menu gives the value's full name.
"""

import math

from ...kit import RingSegment, draw
from ...kit.theme import with_alpha
from ....model import spacing as spacing_model
from ..windows.parts import FONT, ArcSlider


def _text_along_arc(segment, dc, text, alpha, size=FONT * 0.85):
    """``text`` centered on ``segment``'s middle, along the circle, kept upright."""
    theme = dc.theme
    px = theme.px(size)
    mx, my = segment.middle()
    angle = math.atan2(my - segment.cy, mx - segment.cx) - math.pi * 0.5
    if math.cos(angle) < 0.0:
        angle += math.pi
    ux, uy = math.cos(angle), math.sin(angle)
    w = draw.text_size(text, px, theme.font_id)[0]
    draw.text_along(text, mx - ux * w * 0.5, my - uy * w * 0.5, px, with_alpha(theme.text, alpha), angle,
                    theme.font_id)


class SpacingModeButton(RingSegment):
    """Once / Fixed / Time: a tap steps to the next (``actions.toggle_spacing``)."""

    def __init__(self, actions, **kwargs):
        self.actions = actions
        super().__init__("", on_click=actions.toggle_spacing, **kwargs)

    def draw_content(self, dc, alpha):
        try:
            text = spacing_model.MODE_LABELS.get(self.actions.spacing(), "Fixed")
        except Exception:
            text = "Fixed"
        _text_along_arc(self, dc, text, alpha)


class SpacingSlider(ArcSlider):
    """``actions``: the pen menu's actions (``spacing`` / ``spacing_label`` /
    ``spacing_value`` / ``set_spacing_value`` / ``spacing_range`` / ``spacing_text``)."""

    def __init__(self, actions, **kwargs):
        self.actions = actions
        super().__init__("Spacing", value=actions.spacing_value, on_value=actions.set_spacing_value,
                         value_range=actions.spacing_range, fmt=actions.spacing_text, **kwargs)

    _plain = False   # while ArcSlider draws the band: no text (the value is written along the arc)

    # The readout's name follows the mode (ArcSlider / RingSegment set ``label`` once: ignored).
    @property
    def label(self):
        if self._plain:
            return ""
        try:
            return self.actions.spacing_label()
        except Exception:
            return "Spacing"

    @label.setter
    def label(self, _value):
        pass

    # The slider's scale follows the mode (Time: the first 60 % up to 100 ms, model/spacing.py).
    def drag_update(self, x, y):
        self.on_value(int(round(spacing_model.slider_value(self.actions.spacing(), self.fraction_at(x, y)))))

    def _fraction(self):
        try:
            return spacing_model.slider_fraction(self.actions.spacing(), self.actions.spacing_value())
        except Exception:
            return super()._fraction()

    def value_text(self):
        return "" if self._plain else super().value_text()

    def draw_self(self, dc):
        """The band and its fill (ArcSlider), then only the value ("4 px", "100 ms") along the arc."""
        self._plain = True
        try:
            super().draw_self(dc)
        finally:
            self._plain = False
        alpha = dc.alpha * (1.0 if self.is_enabled else dc.theme.disabled_alpha)
        _text_along_arc(self, dc, self.value_text(), alpha)
