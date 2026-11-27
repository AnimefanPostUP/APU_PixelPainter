"""Rust: mottled patches mixing the primary and the secondary color.

The pattern is fractal noise anchored to the texture (``paint.special.rust_texels``),
so painting over the same spot again gives the same rust. Within one stroke the
weights do not pile up: every pixel keeps the strongest weight of the stroke and is
repainted from the stroke's starting image (no darker overlaps). Left button: primary
in the patches' cores, secondary around them; right button: the other way round.
Scale (feature size) and Coverage (how patchy) come from the Brushes window.
"""

import numpy as np

from ...paint import region_paint, special
from ..base import SettingDefaults
from .common import SpecialBrush, brush_colors, falloff_lut, image_view, island_keep, commit, wm_value


RUST_SEED = 1931


class RustBrushTool(SpecialBrush):
    tool_id = 'RUST'
    label = "Rust"
    description = "Mottled rust patches mixing the primary and secondary color (Special window: Scale, Coverage)"
    outline_color = (0.85, 0.42, 0.15, 0.9)
    defaults = SettingDefaults(size=False, modifier=False, strength=False, alpha=False)
    falloff_property = 'pixel_painter_rust_falloff'
    paints_color = True
    uses_values = frozenset({'strength', 'alpha'})

    def uses_stroke_snapshot(self, env):
        return True

    def on_stroke_begin(self, env):
        super().on_stroke_begin(env)
        w, h = env.img.size
        env.state['special_stroke_weights'] = np.zeros(w * h, dtype=np.float32)

    def on_draw(self, env):
        w, h = env.img.size
        steps = list(env.interpolation_steps())
        xs, ys, wts = special.stamps(steps, env.radius, falloff_lut(env, self.falloff_property), w, h)
        keep = island_keep(env, env.cursor_x, env.cursor_y, xs, ys)
        xs, ys, wts = xs[keep], ys[keep], wts[keep]
        if len(xs) == 0:
            env.mark_painted()
            return
        flat, _view = image_view(env)
        idx = ys * w + xs
        stroke = env.state.get('special_stroke_weights')
        if stroke is None or len(stroke) != w * h:
            stroke = env.state['special_stroke_weights'] = np.zeros(w * h, dtype=np.float32)
        weights = np.maximum(stroke[idx], wts)
        stroke[idx] = weights
        back = env.state.get('stroke_back_buffer')
        if back is not None and len(back) == len(flat):   # repaint from the stroke's start
            base = (idx * 4)[:, None] + np.arange(4)
            flat[base] = back[base]

        t, presence = special.rust_texels(xs, ys, wm_value(env, 'rust_scale', 8), wm_value(env, 'rust_coverage', 0.6),
                                          RUST_SEED)
        primary, secondary = brush_colors(env)
        if env.state.get('use_secondary'):
            primary, secondary = secondary, primary
        colors = region_paint.gradient(primary, secondary, t)
        region_paint.blend_texels(flat, idx, colors, weights * presence * env.opacity, blend=env.blend,
                                  alpha_target=env.alpha_opacity, protect_transparent=env.protect_transparent)
        commit(env, flat)
        env.mark_painted()
