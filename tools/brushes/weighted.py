"""WeightedBrushTool: base of brushes whose footprint has per-pixel weights (falloff).
"""

from ...paint import native_paths as native_paint
from ..stroke import BrushTool
from .common import paint_pixels


class WeightedBrushTool(BrushTool):
    """Brush whose footprint has per-pixel weights (falloff).

    Subclasses implement :meth:`sample`. Overlapping samples keep the max
    weight; in 'Pixel' spacing the weight map lives for the whole stroke and is
    re-applied onto the pre-stroke snapshot, so revisiting pixels never
    over-darkens them.
    """

    outline_shape = 'CIRCLE'
    line_tip_shape = 'FALLOFF'

    def sample(self, env, x, y, falloff, curve_sampler):
        """Return ``(pixels, weights)`` for one stamp at ``(x, y)``."""
        raise NotImplementedError

    def uses_stroke_snapshot(self, env):
        # 'Pixel' spacing repaints the stroke onto the pre-stroke snapshot.
        return env.spacing == 'PIXEL'

    def rewrites_stroke(self, env):
        # 'Pixel' spacing re-applies the whole stroke's weight map every step.
        return env.spacing == 'PIXEL'

    def native_draw(self, env, falloff, curve_sampler):
        """C# version of :meth:`on_draw` (paint/native_paths.py); False = not handled."""
        return native_paint.paint_weighted(env, falloff, curve_sampler)

    def on_draw(self, env):
        falloff, curve_sampler = env.falloff(self.falloff_property)
        if native_paint.usable(env) and self.native_draw(env, falloff, curve_sampler):
            env.mark_painted()
            return
        pixel_spacing = env.spacing == 'PIXEL'
        weights = env.state['stroke_weight_map'] if pixel_spacing else {}
        for (sx, sy) in env.interpolation_steps():
            px_list, pw_list = env.expand(sx, sy, *self.sample(env, sx, sy, falloff, curve_sampler))
            for px, w in zip(px_list, pw_list):
                if w > weights.get(px, 0.0):
                    weights[px] = w
        if weights:
            paint_pixels(
                env,
                list(weights.keys()),
                base_buffer=env.state['stroke_back_buffer'] if pixel_spacing else None,
                weights=list(weights.values()),
            )
        env.mark_painted()
