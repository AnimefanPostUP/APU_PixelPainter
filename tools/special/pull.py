"""Pull: liquify -- drag pixels along with the cursor, or suck them into / push them out
of the brush's center.

Modes (``pixel_painter_pull_mode``, the Brushes window):

* **Drag**: the pixels under the brush follow the cursor (forward warp).
* **Pinch**: every stamp pulls the pixels toward its center (the image contracts into
  it); the right button pushes instead.
* **Push**: every stamp pushes the pixels away from its center (the image swells); the
  right button pinches instead.

A displacement field over the stroke (``paint.special.pull_field_step``): every cursor
move shifts the pixels under the brush by the move, weighted by the falloff and the
strength, composed with the earlier moves -- so a stroke drags pixels far without
smearing them. The pixels are re-taken from the stroke's starting image through the
field (nearest pixel: pixel art stays crisp; *Smooth* in the Brushes window: bilinear).
"""

import numpy as np

from ...paint import special
from ..base import SettingDefaults
from ..mask import guard as mask_guard
from .common import SpecialBrush, commit, falloff_lut, image_view, island_keep, wm_value


class PullTool(SpecialBrush):
    tool_id = 'PULL'
    label = "Pull"
    description = "Liquify: drag pixels along, or pinch them into / push them out of the center"
    outline_color = (0.35, 0.95, 0.55, 0.9)
    defaults = SettingDefaults(size=False, modifier=False, strength=False, alpha=False)
    falloff_property = 'pixel_painter_pull_falloff'
    uses_values = frozenset({'strength'})

    def __init__(self):
        super().__init__()
        self._box = None

    def uses_stroke_snapshot(self, env):
        return True

    def on_stroke_begin(self, env):
        super().on_stroke_begin(env)
        w, h = env.img.size
        env.state['pull_field'] = np.zeros((h, w, 2), dtype=np.float32)

    def on_draw(self, env):
        self._box = None
        w, h = env.img.size
        state = env.state
        prev = (state.get('last_paint_cx'), state.get('last_paint_cy'))
        steps = list(env.interpolation_steps())
        field = state.get('pull_field')
        back = state.get('stroke_back_buffer')
        if field is None or field.shape[:2] != (h, w) or back is None:
            env.mark_painted()
            return
        lut = falloff_lut(env, self.falloff_property)
        mode = wm_value(env, 'pull_mode', 'DRAG')
        box = None
        if mode in ('PINCH', 'PUSH'):
            # Radial: every stamp (the first press too) pulls in / pushes out around itself;
            # the right button does the opposite.
            outward = (mode == 'PUSH') != bool(state.get('use_secondary'))
            for sx, sy in self.spaced_steps(env):
                changed = special.pinch_field_step(field, sx, sy, env.radius, amount=env.opacity, lut=lut,
                                                   outward=outward)
                if changed is not None:
                    box = changed if box is None else mask_guard.union(box, changed)
        elif prev[0] is not None:     # Drag: the first stamp only anchors the stroke
            px, py = prev
            for sx, sy in steps:
                changed = special.pull_field_step(field, px, py, sx - px, sy - py, env.radius,
                                                  amount=env.opacity, lut=lut)
                px, py = sx, sy
                if changed is not None:
                    box = changed if box is None else mask_guard.union(box, changed)
        if box is not None:
            flat, view = image_view(env)
            source = back.reshape(h, w, 4)
            xs, ys, rgba = special.warp(source, field, box, smooth=bool(wm_value(env, 'pull_smooth', False)))
            keep = island_keep(env, env.cursor_x, env.cursor_y, xs, ys)
            if env.protect_transparent:
                keep &= source[ys, xs, 3] > 1e-6
            view[ys[keep], xs[keep]] = rgba[keep]
            commit(env, flat)
            self._box = box
        env.mark_painted()

    def stamp_spacing(self, env):
        return max(1.0, env.radius * 0.25)   # pinch / push: stamps along the stroke

    def step_region(self, ctx, env, steps):
        if self._box is None:
            return super().step_region(ctx, env, steps)
        x0, y0, x1, y1 = self._box
        return max(0, x0 - 1), max(0, y0 - 1), x1 + 1, y1 + 1
