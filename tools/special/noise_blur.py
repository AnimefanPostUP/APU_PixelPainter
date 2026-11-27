"""Noise Blur: every pixel under the brush takes the average of a few random pixels
around it -- a grainy, scattered blur (one sample: pure dither-like scatter; more: a
smoother, still noisy blur). Scatter (how far) and Grain (how few samples) come from the
Brushes window; Strength blends the result in.
"""

import numpy as np

from ...paint import special
from ...utils import native
from ..base import SettingDefaults
from .common import (SpecialBrush, commit, falloff_lut, image_view, island_keep, opaque_keep, wm_value)


class NoiseBlurTool(SpecialBrush):
    tool_id = 'NOISE_BLUR'
    label = "Noise Blur"
    description = "Grainy blur: pixels take random neighbours (Special window: Scatter, Grain)"
    outline_color = (0.55, 0.75, 1.0, 0.9)
    defaults = SettingDefaults(size=True, modifier=False, strength=False, alpha=False)
    falloff_property = 'pixel_painter_noise_blur_falloff'
    uses_values = frozenset({'strength'})

    def __init__(self):
        super().__init__()
        self._rng = np.random.default_rng()

    def stamp_spacing(self, env):
        return max(1.0, env.radius * 0.25)

    def on_draw(self, env):
        w, h = env.img.size
        centers = self.spaced_steps(env)
        if not centers:
            env.mark_painted()
            return
        flat, view = image_view(env)
        lut = falloff_lut(env, self.falloff_property)
        scatter = float(wm_value(env, 'noise_scatter', 3))
        grain = float(wm_value(env, 'noise_grain', 0.5))
        if native.enabled() and self._draw_native(env, flat, centers, lut, scatter, grain):
            commit(env, flat)
            env.mark_painted()
            return
        for cx, cy in centers:
            xs, ys, wts, _d = special.disk(cx, cy, env.radius, lut, w, h)
            keep = island_keep(env, cx, cy, xs, ys)
            if env.protect_transparent:
                keep &= opaque_keep(view, xs, ys)
            xs, ys, wts = xs[keep], ys[keep], wts[keep]
            if len(xs) == 0:
                continue
            target = special.noise_blur(view, xs, ys, scatter, grain, self._rng)
            k = np.clip(wts * env.opacity, 0.0, 1.0)[:, None]
            dst = view[ys, xs]
            out = dst + (target - dst) * k
            if env.protect_transparent:
                out[:, 3] = dst[:, 3]
            view[ys, xs] = out
        commit(env, flat)
        env.mark_painted()

    def _draw_native(self, env, flat, centers, lut, scatter, grain):
        """The draw step's stamps in C# (same footprint, clipping and blend; its own random
        sampling). False when the native call failed (nothing was written)."""
        w, h = env.img.size
        r = max(0, int(env.radius))
        try:
            islands = env.island_labels(centers) if env.islands is not None else None
            n = native.noise_blur(flat, w, h, centers, r, special.disk_kernel(r, lut), scatter,
                                  special.noise_samples(grain), int(self._rng.integers(1 << 31)), env.opacity,
                                  protect=env.protect_transparent, islands=islands)
        except ValueError:      # unexpected buffer layout: the Python path
            return False
        return n is not None
