"""Eraser: reduces alpha by the tool strength.
"""

from ...paint import native_paths as native_paint
from ..base import SettingDefaults
from ..stroke import BrushTool
from ...utils import math_utils, native, pixel_io


class EraserTool(BrushTool):
    """Reduce alpha by the tool strength."""

    tool_id = 'ERASER'
    paints_color = False
    label = "Eraser"
    description = "Erase alpha by strength"
    icon = "Tool_Eraser.png"
    outline_color = (1.0, 0.1, 0.1, 0.9)
    defaults = SettingDefaults(size=True, modifier=False, strength=False, alpha=False)
    uses_values = frozenset({'strength'})     # strength = how much alpha is erased
    line_tip_shape = 'CIRCLE'

    def on_draw(self, env):
        if native_paint.usable(env) and native_paint.erase(env):
            env.mark_painted()
            return
        all_pixels = set()
        for (sx, sy) in env.interpolation_steps():
            stamp, _ = env.expand(sx, sy, math_utils.get_pixels_in_shape(sx, sy, env.radius, 'CIRCLE'))
            all_pixels.update(stamp)
        if not all_pixels:
            return
        w, h = env.img.size
        if native.enabled():
            arr = pixel_io.buffer(env.img)
            if native.erase(arr, w, h, all_pixels, env.opacity) is not None:
                pixel_io.write(env.img, arr)
                env.mark_painted()
                return
        arr = pixel_io.read(env.img)
        for (px, py) in all_pixels:
            if 0 <= px < w and 0 <= py < h:
                idx = (py * w + px) * 4
                arr[idx + 3] = max(0.0, arr[idx + 3] - env.opacity)
        pixel_io.write(env.img, arr)
        env.mark_painted()
