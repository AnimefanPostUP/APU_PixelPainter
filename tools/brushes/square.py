"""Square brush: a uniform square stamp.
"""

from ...paint import native_paths as native_paint
from ..stroke import BrushTool
from ...utils import math_utils
from .common import paint_pixels


class SquareBrushTool(BrushTool):
    tool_id = 'SQUARE'
    label = "Square"
    description = "Square brush shape"
    icon = "Tool_Square.png"
    outline_shape = 'SQUARE'
    line_tip_shape = 'SQUARE'

    def on_draw(self, env):
        if native_paint.usable(env) and native_paint.paint_shape(env, 'SQUARE', env.spacing == 'PIXEL'):
            env.mark_painted()
            return
        if env.spacing == 'PIXEL':
            # Remember painted pixels for the whole stroke so interpolation
            # never double-stamps a coordinate.
            painted = env.state['stroke_painted']
            for (sx, sy) in env.interpolation_steps():
                stamp, _ = env.expand(sx, sy, math_utils.get_pixels_in_shape(sx, sy, env.radius, 'SQUARE'))
                step_pixels = set(stamp) - painted
                if step_pixels:
                    paint_pixels(env, step_pixels)
                    painted |= step_pixels
        else:
            all_pixels = set()
            for (sx, sy) in env.interpolation_steps():
                stamp, _ = env.expand(sx, sy, math_utils.get_pixels_in_shape(sx, sy, env.radius, 'SQUARE'))
                all_pixels.update(stamp)
            if all_pixels:
                paint_pixels(env, all_pixels)
        env.mark_painted()
