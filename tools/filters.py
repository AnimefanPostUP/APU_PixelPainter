"""Filter tools that modify existing pixels: Smooth, Smear."""

import numpy as np

from . import draw_functions
from . import draw_tool_smooth
from .base import SettingDefaults, ToolBase
from ..utils import math_utils


def _filter_visible_alpha_pixels(img, pixels, alpha_threshold=1e-6):
    """Return only pixels whose destination alpha is above threshold."""
    if not pixels:
        return []
    w, h = img.size
    arr = np.array(img.pixels, dtype=np.float32)
    visible = []
    for (px, py) in pixels:
        if 0 <= px < w and 0 <= py < h:
            if arr[(py * w + px) * 4 + 3] > alpha_threshold:
                visible.append((px, py))
    return visible


class SmoothTool(ToolBase):
    """Blur pixels; the modifier scales the kernel radius."""

    tool_id = 'SMOOTH'
    label = "Smooth"
    description = "Blur pixels — Spread sets kernel size, Strength sets blend strength"
    icon = "Tool_Smooth.png"
    outline_color = (0.7, 0.3, 1.0, 0.9)
    defaults = SettingDefaults(size=True, modifier=True, strength=False, alpha=False)
    line_tip_shape = 'CIRCLE'

    def on_draw(self, env):
        smooth_radius = max(1, int(env.wm.pixel_painter_modifier * max(1, env.radius)))
        all_pixels = set()
        for (sx, sy) in env.interpolation_steps():
            all_pixels |= math_utils.get_pixels_in_shape(sx, sy, env.radius, 'CIRCLE')
        if env.protect_transparent:
            all_pixels = set(_filter_visible_alpha_pixels(env.img, all_pixels))
        draw_tool_smooth.smooth_pixels_in_image(env.img, list(all_pixels), smooth_radius, env.opacity)
        if all_pixels:
            draw_functions.set_pixels_alpha(
                env.img, all_pixels, env.alpha_opacity,
                opacity=env.opacity, protect_transparent=env.protect_transparent)
        env.mark_painted()


class SmearTool(ToolBase):
    """Drag pixels opposite the cursor motion; the modifier scales the reach."""

    tool_id = 'SMEAR'
    label = "Smear"
    description = "Drag pixels — Spread sets reach, Strength sets blend strength"
    icon = "Tool_Smear.png"
    outline_color = (1.0, 0.3, 0.7, 0.9)
    defaults = SettingDefaults(size=True, modifier=True, strength=False, alpha=False)
    line_tip_shape = 'CIRCLE'

    def on_draw(self, env):
        modifier = env.wm.pixel_painter_modifier
        steps = list(env.interpolation_steps())
        prev_x = env.state['last_paint_cx']
        prev_y = env.state['last_paint_cy']
        smear_reach = modifier * max(1, env.radius)
        for i, (sx, sy) in enumerate(steps):
            ox = (prev_x if prev_x is not None else sx) if i == 0 else steps[i - 1][0]
            oy = (prev_y if prev_y is not None else sy) if i == 0 else steps[i - 1][1]
            smear_pixels = list(math_utils.get_pixels_in_shape(sx, sy, env.radius, 'CIRCLE'))
            if env.protect_transparent:
                smear_pixels = _filter_visible_alpha_pixels(env.img, smear_pixels)
            if not smear_pixels:
                continue
            draw_tool_smooth.smear_pixels_in_image(
                env.img, smear_pixels, sx - ox, sy - oy, smear_reach, env.opacity)
            draw_functions.set_pixels_alpha(
                env.img, smear_pixels, env.alpha_opacity,
                opacity=env.opacity, protect_transparent=env.protect_transparent)
        env.mark_painted()
