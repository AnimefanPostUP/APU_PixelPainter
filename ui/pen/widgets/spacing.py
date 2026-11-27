"""The spacing value under the Pixel / Free / Time button: an arc slider whose name, range
and unit follow the active tool's spacing mode (model/spacing.py) -- Pixel: Step (pixels
per stamp), Free: Spacing (pixels between stamps), Time: Interval (ms between stamps).
"""

import math

from ...kit import draw
from ...kit.theme import with_alpha
from ....model import spacing as spacing_model
from ..windows.parts import FONT, ArcSlider


class SpacingSlider(ArcSlider):
    """``actions``: the pen menu's actions (``spacing_label`` / ``spacing_value`` /
    ``set_spacing_value`` / ``spacing_range`` / ``spacing_text``)."""

    def __init__(self, actions, **kwargs):
        self.actions = actions
        super().__init__("Spacing", value=actions.spacing_value, on_value=actions.set_spacing_value,
                         value_range=actions.spacing_range, fmt=actions.spacing_text, **kwargs)

    _plain = False   # while ArcSlider draws the band: no text (written along the arc below)

    # The name follows the mode (ArcSlider / RingSegment set ``label`` once: ignored).
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
        """The band and its fill (ArcSlider), then "<name> <value>" along the arc, upright."""
        self._plain = True
        try:
            super().draw_self(dc)
        finally:
            self._plain = False
        theme = dc.theme
        text = f"{self.label} {self.value_text()}"
        size = theme.px(FONT * 0.85)
        mx, my = self.middle()
        mid = math.atan2(my - self.cy, mx - self.cx)
        angle = mid - math.pi * 0.5          # clockwise tangent: reads left to right in the top right
        if math.cos(angle) < 0.0:            # keep it upright anywhere on the circle
            angle += math.pi
        ux, uy = math.cos(angle), math.sin(angle)
        w = draw.text_size(text, size, theme.font_id)[0]
        alpha = dc.alpha * (1.0 if self.is_enabled else theme.disabled_alpha)
        draw.text_along(text, mx - ux * w * 0.5, my - uy * w * 0.5, size, with_alpha(theme.text, alpha), angle,
                        theme.font_id)
