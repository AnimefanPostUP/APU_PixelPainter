"""Paint per-texel colors into a flat RGBA buffer (pure NumPy): the Extras window's
Fill / Edges / Ambient Occlusion write through :func:`blend_texels` with the brush's
blend mode, strength and alpha.
"""

import numpy as np

from . import blending


def gradient(primary, secondary, t):
    """RGB (N, 3) float32 from ``primary`` (t = 0) to ``secondary`` (t = 1)."""
    a = np.asarray(primary, dtype=np.float32)[:3]
    b = np.asarray(secondary, dtype=np.float32)[:3]
    t = np.asarray(t, dtype=np.float32).reshape(-1, 1)
    return a + (b - a) * t


def blend_texels(arr, flat_idx, rgb, opacity, blend='MIX', alpha_target=1.0, protect_transparent=False):
    """Blend ``rgb`` (N, 3, or one color) into the texels ``flat_idx`` of the flat RGBA
    float32 buffer ``arr`` (in place) with per-texel ``opacity`` (N or scalar).

    Alpha moves toward ``alpha_target`` by the opacity (like the brushes);
    ``protect_transparent`` leaves fully transparent texels alone. Returns the number
    of texels written."""
    idx = np.asarray(flat_idx, dtype=np.int64).reshape(-1)
    if len(idx) == 0:
        return 0
    op = np.broadcast_to(np.asarray(opacity, dtype=np.float32), idx.shape).copy()
    src = np.asarray(rgb, dtype=np.float32)
    src = np.broadcast_to(src.reshape(-1, 3) if src.ndim > 1 else src[:3], (len(idx), 3)).copy()
    base = idx * 4
    if protect_transparent:
        keep = arr[base + 3] > 1e-6
        base, op, src = base[keep], op[keep], src[keep]
    keep = op > 0.0
    base, op, src = base[keep], np.clip(op[keep], 0.0, 1.0), src[keep]
    if len(base) == 0:
        return 0
    dst = np.stack((arr[base], arr[base + 1], arr[base + 2]), axis=1)
    out = np.clip(blending.blend_pixel_arrays(dst, src, blend, op), 0.0, 1.0)
    arr[base] = out[:, 0]
    arr[base + 1] = out[:, 1]
    arr[base + 2] = out[:, 2]
    alpha = arr[base + 3]
    arr[base + 3] = alpha + (float(alpha_target) - alpha) * op
    return int(len(base))
