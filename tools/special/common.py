"""Shared by the special brushes: the image as an (H, W, 4) view, the falloff as a lookup
table, UV island clipping of whole pixel arrays, both brush colors, stamp spacing.
"""

import numpy as np

from ...paint import special
from ...utils import math_utils, pixel_io
from ..stroke import StrokeTool


def image_view(env):
    """``(flat, view)``: the working buffer and an (H, W, 4) view of it (same memory)."""
    w, h = env.img.size
    flat = pixel_io.buffer(env.img)
    return flat, flat.reshape(h, w, 4)


def commit(env, flat):
    pixel_io.write(env.img, flat)


def falloff_lut(env, prop_name):
    """The tool's falloff (``prop_name``; None: smoothstep) as a table over 0..1."""
    if prop_name is None:
        return special.smooth_lut()
    falloff, sampler = env.falloff(prop_name)
    ts = np.linspace(0.0, 1.0, special.FALLOFF_SAMPLES)
    return np.array([math_utils.get_falloff(float(t), falloff, curve_sampler=sampler) for t in ts],
                    dtype=np.float32)


def island_keep(env, cx, cy, xs, ys):
    """Bool mask of the pixels on the UV island of ``(cx, cy)`` (3D Viewport, UV mode;
    elsewhere all of them) -- the vectorized ``DrawEnvironment.clip``."""
    islands = env.islands
    n = len(xs)
    if islands is None or n == 0:
        return np.ones(n, dtype=bool)
    label = islands.label_at(int(cx), int(cy))
    if label == islands.NONE:
        return np.ones(n, dtype=bool)
    if label == islands.SKIP:
        return np.zeros(n, dtype=bool)
    return islands.labels[ys * islands.w + xs] == label


def opaque_keep(view, xs, ys):
    """Bool mask of the pixels that are not fully transparent (Alphalock)."""
    return view[ys, xs, 3] > 1e-6


def brush_colors(env):
    """``(primary, secondary)`` RGB of the brush."""
    try:
        brush = env.context.tool_settings.image_paint.brush
        return tuple(brush.color)[:3], tuple(brush.secondary_color)[:3]
    except Exception:
        return (1.0, 1.0, 1.0), (0.0, 0.0, 0.0)


def wm_value(env, name, default):
    return getattr(env.wm, f'pixel_painter_{name}', default)


class SpecialBrush(StrokeTool):
    """Base of the Brushes window's tools: kept out of the pen menu's tool ring (the
    window lists them), stamps spaced along the stroke (``stamp_spacing``)."""

    group = 'SPECIAL'
    state_defaults = {
        **StrokeTool.state_defaults,
        'special_last_stamp': None,     # last stamp center of the stroke (spacing)
        'special_stroke_weights': None,  # Rust: flat max weight per pixel of the stroke
        'pull_field': None,             # Pull: (H, W, 2) displacement of the stroke
        'repair_source': None,          # Repair: (x, y) source pixel set with the right button
        'repair_offset': None,          # Repair: source - destination, kept while aligned
    }
    line_tip_shape = 'CIRCLE'
    usable_as_line_tip = False

    def stamp_spacing(self, env):
        """Pixels between stamps (heavier tools stamp less often)."""
        return 1.0

    def spaced_steps(self, env):
        """This draw step's stamp centers, at least ``stamp_spacing`` apart along the stroke."""
        state = env.state
        if state.get('last_paint_cx') is None:
            state['special_last_stamp'] = None
        steps = list(env.interpolation_steps())
        if env.spacing == 'TIME':
            # Time spacing already decides when to stamp (one per due tick, at the cursor):
            # spacing by distance would drop every stamp while the pen stands still.
            state['special_last_stamp'] = steps[-1] if steps else state.get('special_last_stamp')
            return steps
        kept, last = special.spaced(steps, state.get('special_last_stamp'), self.stamp_spacing(env))
        state['special_last_stamp'] = last
        return kept
