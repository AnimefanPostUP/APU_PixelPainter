"""Edge mode (3D Viewport): filter on the surface (core.view3d EdgePatch).

In texture space a blur / smear reads the pixels beside the stamp, which at a
UV seam belong to some other part of the mesh (or the empty margin). In Edge
mode every stamp is filtered in a patch unfolded across the seams: gather the
patch, filter it (only on-surface texels are read), scatter the result back.
"""

import math

import numpy as np

from ...paint.pixels import set_pixels_alpha
from ...paint import smooth as draw_tool_smooth
from ...utils import math_utils, pixel_io


# ---- Edge mode: filter on the surface (core.view3d.patch.EdgePatch) -------------------
#
# In texture space a blur / smear reads the pixels beside the stamp, which at a
# UV seam belong to some other part of the mesh (or the empty margin). In Edge
# mode every stamp is filtered in a patch unfolded across the seams: gather the
# patch, filter it (only on-surface texels are read), scatter the result back.

def _edge_stamp(env, patch, arr, pixels, weights):
    """``(flat, weights, patch_buffer)``: the stamp texels that can be written."""
    flat = patch.flat(pixels)
    wts = np.asarray(weights, dtype=np.float32)
    keep = (wts > 0.0) & (patch.source[flat] >= 0)
    buf = patch.gather(arr)
    if env.protect_transparent:
        keep &= buf.reshape(-1, 4)[flat, 3] > 1e-6
    return flat[keep], wts[keep], buf


def _write_strongest(env, arr, results):
    """Write ``results`` (``(targets, weights, rgb)`` per stamp) into the image; where
    stamps overlap the strongest weight wins. Then blend alpha like the texture path."""
    if not results:
        return
    targets = np.concatenate([r[0] for r in results])
    if not len(targets):
        return
    weights = np.concatenate([r[1] for r in results])
    rgb = np.concatenate([r[2] for r in results])
    order = np.lexsort((-weights, targets))
    targets, weights, rgb = targets[order], weights[order], rgb[order]
    first = np.ones(len(targets), dtype=bool)
    first[1:] = targets[1:] != targets[:-1]
    targets, weights, rgb = targets[first], weights[first], rgb[first]
    arr.reshape(-1, 4)[targets, :3] = rgb
    pixel_io.write(env.img, arr)
    w = env.img.size[0]
    xy = np.stack((targets % w, targets // w), axis=1)
    set_pixels_alpha(
        env.img, xy, env.alpha_opacity, opacity=env.opacity,
        protect_transparent=env.protect_transparent, pixel_weights=weights)


def edge_smooth(env, smooth_radius, falloff, curve_sampler):
    """Edge-mode Smooth. Every stamp reads the image as it was before this draw step
    (one blur pass, like the texture path). False: no surface here, use texture space."""
    arr = pixel_io.buffer(env.img)
    results = []
    for (sx, sy) in env.interpolation_steps():
        pixels, weights = math_utils.get_pixels_in_circle_weighted(
            sx, sy, env.radius, falloff, curve_sampler=curve_sampler)
        patch = env.edge_patch(sx, sy, pixels, smooth_radius)
        if patch is None:
            return False
        flat, wts, buf = _edge_stamp(env, patch, arr, pixels, weights)
        if not len(flat):
            continue
        draw_tool_smooth.smooth_buffer(buf, patch.pw, patch.ph, patch.local(flat), smooth_radius,
                                       env.opacity, pixel_weights=wts, valid=patch.valid)
        owner, target = patch.scatter(flat)
        results.append((target, wts[owner], buf.reshape(-1, 4)[flat[owner], :3]))
    _write_strongest(env, arr, results)
    return True


def edge_smear(env, steps, smear_reach, falloff, curve_sampler, prev_x, prev_y):
    """Edge-mode Smear, step by step (each step pulls from the previous one's result).
    The drag direction is measured on the unfolded surface, so it stays right across
    seams. False: no surface under the first step, use texture space."""
    img = env.img
    for i, (sx, sy) in enumerate(steps):
        ox = (prev_x if prev_x is not None else sx) if i == 0 else steps[i - 1][0]
        oy = (prev_y if prev_y is not None else sy) if i == 0 else steps[i - 1][1]
        pixels, weights = math_utils.get_pixels_in_circle_weighted(
            sx, sy, env.radius, falloff, curve_sampler=curve_sampler)
        # a step that jumped a seam is far away in texture space: cap the padding
        travel = min(math.hypot(sx - ox, sy - oy), max(2.0, float(env.radius)))
        patch = env.edge_patch(sx, sy, pixels, smear_reach * travel + 1)
        if patch is None:
            if i == 0:
                return False
            continue
        start = patch.locate(ox, oy)
        dx, dy = (0.0, 0.0) if start is None else (sx - patch.x0 - start[0], sy - patch.y0 - start[1])
        arr = pixel_io.buffer(img)
        flat, wts, buf = _edge_stamp(env, patch, arr, pixels, weights)
        if not len(flat):
            continue
        draw_tool_smooth.smear_buffer(buf, patch.pw, patch.ph, patch.local(flat), dx, dy, smear_reach,
                                      env.opacity, pixel_weights=wts, valid=patch.valid)
        owner, target = patch.scatter(flat)
        _write_strongest(env, arr, [(target, wts[owner], buf.reshape(-1, 4)[flat[owner], :3])])
    return True
