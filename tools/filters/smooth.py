"""Smooth: blur pixels; the modifier scales the kernel radius.
"""



from ...paint.pixels import set_pixels_alpha
from ...paint import smooth as draw_tool_smooth
from ...paint import native_paths as native_paint
from ..base import SettingDefaults
from ..stroke import StrokeTool
from ...utils import math_utils
from .common import visible_alpha_pixels
from .edge import edge_smooth


class SmoothTool(StrokeTool):
    """Blur pixels; the modifier scales the kernel radius."""

    tool_id = 'SMOOTH'
    label = "Smooth"
    description = "Blur pixels — Spread sets kernel size, Strength sets blend strength"
    icon = "Tool_Smooth.png"
    outline_color = (0.7, 0.3, 1.0, 0.9)
    defaults = SettingDefaults(size=True, modifier=True, strength=False, alpha=False)
    uses_values = frozenset({'strength', 'alpha', 'modifier'})
    falloff_property = 'pixel_painter_smooth_falloff'
    line_tip_shape = 'CIRCLE'

    def on_draw(self, env):
        smooth_radius = max(1, int(env.modifier * max(1, env.radius)))
        falloff, curve_sampler = env.falloff(self.falloff_property)
        if env.edge_patch is not None and edge_smooth(env, smooth_radius, falloff, curve_sampler):
            env.mark_painted()
            return
        if native_paint.usable(env) and native_paint.smooth(env, smooth_radius, falloff, curve_sampler):
            env.mark_painted()
            return
        # Overlapping stamps along the stroke keep the strongest falloff weight.
        weights = {}
        for (sx, sy) in env.interpolation_steps():
            px_list, pw_list = env.expand(sx, sy, *math_utils.get_pixels_in_circle_weighted(
                sx, sy, env.radius, falloff, curve_sampler=curve_sampler))
            for px, w in zip(px_list, pw_list):
                if w > weights.get(px, 0.0):
                    weights[px] = w
        if env.protect_transparent:
            visible = set(visible_alpha_pixels(env.img, weights))
            weights = {px: w for px, w in weights.items() if px in visible}
        if weights:
            pixels = list(weights)
            pixel_weights = [weights[px] for px in pixels]
            draw_tool_smooth.smooth_pixels_in_image(
                env.img, pixels, smooth_radius, env.opacity, pixel_weights=pixel_weights)
            set_pixels_alpha(
                env.img, pixels, env.alpha_opacity, opacity=env.opacity,
                protect_transparent=env.protect_transparent, pixel_weights=pixel_weights)
        env.mark_painted()
