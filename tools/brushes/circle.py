"""Circle brush: a round stamp with falloff.
"""

from ...utils import math_utils
from .weighted import WeightedBrushTool


class CircleBrushTool(WeightedBrushTool):
    tool_id = 'CIRCLE'
    label = "Circle"
    description = "Circle brush shape with falloff"
    icon = "Tool_Circle.png"
    falloff_property = 'pixel_painter_circle_falloff'

    def sample(self, env, x, y, falloff, curve_sampler):
        return math_utils.get_pixels_in_circle_weighted(
            x, y, env.radius, falloff, curve_sampler=curve_sampler)
