"""C# fast paths for the stroke tools (see :mod:`utils.native`).

A tool's ``on_draw`` calls into here when :func:`usable` is True. The footprint
of the whole draw step (every interpolation step) is built in C# from a
*kernel* -- the stamp's (2r+1)^2 weights, computed once in Python with the same
falloff function the Python path uses -- and painted in C# into the stroke's
working buffer (:mod:`utils.pixel_io`). Results match the Python paths: same
weights, same max-merge of overlapping stamps, same blend math.

Not used in the 3D Viewport's Edge mode: there ``env.expand`` carries every
stamp over UV seams in Python (the pixel kernels are still native there, see
``draw_functions.write_pixels_to_image`` and friends).

Every function returns False when the native call failed; the tool then runs
its Python implementation instead.
"""

import math
import random

import numpy as np

from ..utils import math_utils, native, pixel_io


_kernels = {}
_KERNEL_CACHE_SIZE = 64


def usable(env):
    return env.expand_stamp is None and native.enabled()


# ---------------------------------------------------------------------------
# Kernels
# ---------------------------------------------------------------------------

def _remember(key, kernel):
    if len(_kernels) >= _KERNEL_CACHE_SIZE:
        _kernels.clear()
    _kernels[key] = kernel
    return kernel


def _offsets(r):
    d = np.arange(-r, r + 1)
    dy, dx = np.meshgrid(d, d, indexing='ij')   # row-major: dy, then dx
    return (dx * dx + dy * dy).ravel()


def shape_kernel(radius, shape):
    """Uniform kernel of ``math_utils.get_pixels_in_shape`` ('SQUARE' / 'CIRCLE')."""
    r = max(0, int(radius))
    key = ('shape', r, shape)
    kernel = _kernels.get(key)
    if kernel is not None:
        return kernel
    if r == 0:
        kernel = np.ones(1, dtype=np.float32)
    elif shape == 'SQUARE':
        kernel = np.ones((2 * r + 1) ** 2, dtype=np.float32)
    else:
        kernel = (_offsets(r) <= r * r).astype(np.float32)
    return _remember(key, kernel)


def falloff_kernel(radius, falloff, curve_sampler=None):
    """Weights of ``math_utils.get_pixels_in_circle_weighted`` (0 outside the circle)."""
    r = max(0, int(radius))
    key = ('falloff', r, falloff)
    if curve_sampler is None:
        kernel = _kernels.get(key)
        if kernel is not None:
            return kernel
    if r == 0:
        kernel = np.ones(1, dtype=np.float32)
    else:
        d2 = _offsets(r)
        kernel = np.zeros(d2.size, dtype=np.float32)
        inside = d2 <= r * r
        # One falloff evaluation per distinct distance.
        values, inverse = np.unique(d2[inside], return_inverse=True)
        weights = np.array([math_utils.get_falloff(math.sqrt(int(v)) / r, falloff,
                                                   curve_sampler=curve_sampler) for v in values],
                           dtype=np.float32)
        kernel[inside] = weights[inverse]
    if curve_sampler is None:
        _remember(key, kernel)
    return kernel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def centers(steps):
    return native.coords(list(steps))


def stroke_grid(env):
    """Per-stroke ``w * h`` weight grid (reset by ``ToolBase.on_stroke_begin``)."""
    w, h = env.img.size
    grid = env.state.get('native_stroke_grid')
    if grid is None or grid.size != w * h:
        grid = np.zeros(w * h, dtype=np.float32)
        env.state['native_stroke_grid'] = grid
        env.state['native_stroke_pixels'] = np.zeros((0, 2), dtype=np.int32)
    return grid


def _paint(env, xy, weights, base=None):
    if len(xy) == 0:
        return True
    w, h = env.img.size
    buf = pixel_io.buffer(env.img)
    count = native.paint(buf, w, h, xy, weights, env.color, env.blend, env.opacity,
                         env.alpha_opacity, env.protect_transparent, base=base)
    if count is None:
        return False
    if count:
        pixel_io.write(env.img, buf)
    return True


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def paint_shape(env, shape, stroke_unique):
    """Uniform brush (Square). ``stroke_unique``: every pixel once per stroke ('Pixel' spacing)."""
    w, h = env.img.size
    grid = stroke_grid(env) if stroke_unique else None
    steps = centers(env.interpolation_steps())
    result = native.stamp(steps, env.radius, shape_kernel(env.radius, shape), w, h, grid,
                          islands=env.island_labels(steps))
    if result is None:
        return False
    return _paint(env, result[0], None)


def paint_weighted(env, falloff, curve_sampler, spray_density=None):
    """Circle / Spray brush. 'Pixel' spacing re-applies the stroke's max weights
    onto the pre-stroke snapshot, exactly like the Python path."""
    w, h = env.img.size
    r = env.radius
    kernel = falloff_kernel(r, falloff, curve_sampler)
    steps = centers(env.interpolation_steps())
    pixel_spacing = env.spacing == 'PIXEL'
    grid = stroke_grid(env) if pixel_spacing else None
    islands = env.island_labels(steps)
    if spray_density is None:
        result = native.stamp(steps, r, kernel, w, h, grid, islands=islands)
    else:
        result = native.spray(steps, r, spray_density, kernel, random.getrandbits(31), w, h, grid,
                              islands=islands)
    if result is None:
        return False
    xy, weights = result
    if not pixel_spacing:
        return _paint(env, xy, weights)

    if len(xy):
        env.state['native_stroke_pixels'] = np.concatenate([env.state['native_stroke_pixels'], xy])
    stroke_xy = env.state['native_stroke_pixels']
    if len(stroke_xy) == 0:
        return True
    stroke_weights = grid[stroke_xy[:, 1].astype(np.int64) * w + stroke_xy[:, 0]]
    # Pixels outside the stroke still equal the snapshot, so painting the stroke
    # pixels from it equals the Python path's full reset + repaint.
    return _paint(env, stroke_xy, stroke_weights, base=env.state['stroke_back_buffer'])


def line_footprint(env, line, tip):
    """``(xy, weights|None)`` of the Line tool's tip stamped along ``line``; None on failure."""
    w, h = env.img.size
    if tip == 'FALLOFF':
        falloff, curve_sampler = env.falloff('pixel_painter_circle_falloff')
        kernel = falloff_kernel(env.radius, falloff, curve_sampler)
    else:
        kernel = shape_kernel(env.radius, 'SQUARE' if tip == 'SQUARE' else 'CIRCLE')
    line = native.coords(line)
    result = native.stamp(line, env.radius, kernel, w, h, islands=env.island_labels(line))
    if result is None:
        return None
    xy, weights = result
    return xy, (weights if tip == 'FALLOFF' else None)


def erase(env):
    w, h = env.img.size
    steps = centers(env.interpolation_steps())
    result = native.stamp(steps, env.radius, shape_kernel(env.radius, 'CIRCLE'), w, h,
                          islands=env.island_labels(steps))
    if result is None:
        return False
    xy = result[0]
    if len(xy) == 0:
        return True
    buf = pixel_io.buffer(env.img)
    if native.erase(buf, w, h, xy, env.opacity) is None:
        return False
    pixel_io.write(env.img, buf)
    return True


def smooth(env, smooth_radius, falloff, curve_sampler):
    w, h = env.img.size
    steps = centers(env.interpolation_steps())
    result = native.stamp(steps, env.radius, falloff_kernel(env.radius, falloff, curve_sampler), w, h,
                          islands=env.island_labels(steps))
    if result is None:
        return False
    xy, weights = result
    if len(xy) == 0:
        return True
    buf = pixel_io.buffer(env.img)
    protect = env.protect_transparent
    if native.smooth(buf, w, h, xy, weights, smooth_radius, env.opacity, protect) is None:
        return False
    native.set_alpha(buf, w, h, xy, weights, env.alpha_opacity, env.opacity, protect)
    pixel_io.write(env.img, buf)
    return True


def smear(env, steps, smear_reach, falloff, curve_sampler, prev_x, prev_y):
    """Smear step by step (each step pulls from the result of the previous one)."""
    w, h = env.img.size
    kernel = falloff_kernel(env.radius, falloff, curve_sampler)
    protect = env.protect_transparent
    buf = pixel_io.buffer(env.img)
    changed = False
    for i, (sx, sy) in enumerate(steps):
        ox = (prev_x if prev_x is not None else sx) if i == 0 else steps[i - 1][0]
        oy = (prev_y if prev_y is not None else sy) if i == 0 else steps[i - 1][1]
        center = native.coords([(sx, sy)])
        result = native.stamp(center, env.radius, kernel, w, h, islands=env.island_labels(center))
        if result is None:
            return False if not changed else _finish(env, buf)
        xy, weights = result
        if len(xy) == 0:
            continue
        if native.smear(buf, w, h, xy, weights, sx - ox, sy - oy, smear_reach, env.opacity, protect) is None:
            return False if not changed else _finish(env, buf)
        native.set_alpha(buf, w, h, xy, weights, env.alpha_opacity, env.opacity, protect)
        changed = True
    return _finish(env, buf) if changed else True


def _finish(env, buf):
    pixel_io.write(env.img, buf)
    return True
