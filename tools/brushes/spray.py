"""Spray brush: random sprinkles within a circle; the modifier sets the density.
"""

from ...paint import native_paths as native_paint
from ..base import SettingDefaults
from ...utils import math_utils
from .weighted import WeightedBrushTool


SPRAY_KNEE = (0.5, 0.016)  # M up to 50 % = density up to 1.6 % (the spray reacts strongly)
SPRAY_MAX = 1.0             # density at M = 100 %: the full circle


def spray_density(modifier):
    """Spray density (share of the circle per step) for the modifier ``modifier`` (0..1).

    A hard curve: linear up to the knee (M 0..50 % -> 0..1.6 %), then a quadratic rise
    to SPRAY_MAX (100 %) at M = 100 %, starting with the same slope (no kink)."""
    m = min(1.0, max(0.0, float(modifier)))
    km, kd = SPRAY_KNEE
    slope = kd / km
    if m <= km:
        return m * slope
    t = (m - km) / (1.0 - km)
    linear = slope * (1.0 - km)          # the linear part's share of the rest
    return min(SPRAY_MAX, kd + linear * t + (SPRAY_MAX - kd - linear) * t * t)


class SprayBrushTool(WeightedBrushTool):
    tool_id = 'SPRAY'
    label = "Spray"
    description = "Randomised spray within a circle"
    icon = "Tool_Spray.png"
    outline_color = (1.0, 0.55, 0.0, 0.9)
    defaults = SettingDefaults(size=False, modifier=False, strength=False, alpha=False)
    falloff_property = 'pixel_painter_spray_falloff'
    uses_values = frozenset({'strength', 'alpha', 'modifier'})   # modifier = how many sprinkles

    @staticmethod
    def density(env):
        """Share of the circle sprinkled per step, from the tool modifier (M; pen pressure
        applied): higher M = more sprinkles. See :func:`spray_density`."""
        return spray_density(env.modifier)

    def native_draw(self, env, falloff, curve_sampler):
        return native_paint.paint_weighted(env, falloff, curve_sampler, spray_density=self.density(env))

    def sample(self, env, x, y, falloff, curve_sampler):
        return math_utils.get_spray_pixels(
            x, y, env.radius, self.density(env), falloff, curve_sampler=curve_sampler)
