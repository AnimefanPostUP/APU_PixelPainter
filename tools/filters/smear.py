"""Smear: drag pixels opposite the cursor motion; the modifier scales the reach.
"""



from ...paint.pixels import set_pixels_alpha
from ...paint import smooth as draw_tool_smooth
from ...paint import native_paths as native_paint
from ..base import SettingDefaults
from ..stroke import StrokeTool
from ...utils import math_utils
from .common import visible_alpha_pixels
from .edge import edge_smear


class SmearTool(StrokeTool):
    """Drag pixels opposite the cursor motion; the modifier scales the reach."""

    tool_id = 'SMEAR'
    label = "Smear"
    description = "Drag pixels — Spread sets reach, Strength sets blend strength"
    icon = "Tool_Smear.png"
    outline_color = (1.0, 0.3, 0.7, 0.9)
    defaults = SettingDefaults(size=True, modifier=True, strength=False, alpha=False)
    uses_values = frozenset({'strength', 'alpha', 'modifier'})
    falloff_property = 'pixel_painter_smear_falloff'
    line_tip_shape = 'CIRCLE'

    def on_draw(self, env):
        modifier = env.modifier
        falloff, curve_sampler = env.falloff(self.falloff_property)
        steps = list(env.interpolation_steps())
        prev_x = env.state['last_paint_cx']
        prev_y = env.state['last_paint_cy']
        smear_reach = modifier * max(1, env.radius)
        if env.edge_patch is not None and edge_smear(
                env, steps, smear_reach, falloff, curve_sampler, prev_x, prev_y):
            env.mark_painted()
            return
        if native_paint.usable(env) and native_paint.smear(
                env, steps, smear_reach, falloff, curve_sampler, prev_x, prev_y):
            env.mark_painted()
            return
        for i, (sx, sy) in enumerate(steps):
            ox = (prev_x if prev_x is not None else sx) if i == 0 else steps[i - 1][0]
            oy = (prev_y if prev_y is not None else sy) if i == 0 else steps[i - 1][1]
            px_list, pw_list = env.clip(sx, sy, *math_utils.get_pixels_in_circle_weighted(
                sx, sy, env.radius, falloff, curve_sampler=curve_sampler))
            weights = dict(zip(px_list, pw_list))
            if env.protect_transparent:
                visible = set(visible_alpha_pixels(env.img, px_list))
                weights = {px: w for px, w in weights.items() if px in visible}
            if not weights:
                continue
            smear_pixels = list(weights)
            pixel_weights = [weights[px] for px in smear_pixels]
            draw_tool_smooth.smear_pixels_in_image(
                env.img, smear_pixels, sx - ox, sy - oy, smear_reach, env.opacity,
                pixel_weights=pixel_weights)
            set_pixels_alpha(
                env.img, smear_pixels, env.alpha_opacity, opacity=env.opacity,
                protect_transparent=env.protect_transparent, pixel_weights=pixel_weights)
        env.mark_painted()
