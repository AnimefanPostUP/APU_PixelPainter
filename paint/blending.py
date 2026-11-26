"""Blend mode helpers for pixel arrays and RGBA regions."""

import numpy as np

from ..utils import native


# ---------------------------------------------------------------------------
# HSV, vectorized: the same math as colorsys, per row of an (N, 3) array
# ---------------------------------------------------------------------------

def rgb_to_hsv(rgb):
    """``(h, s, v)`` arrays of ``rgb`` (N, 3) -- ``colorsys.rgb_to_hsv`` per row."""
    rgb = np.asarray(rgb, dtype=np.float64)
    r, g, b = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    maxc = rgb.max(axis=1)
    minc = rgb.min(axis=1)
    rangec = maxc - minc
    grey = minc == maxc
    with np.errstate(divide='ignore', invalid='ignore'):
        s = np.where(grey, 0.0, rangec / maxc)
        safe = np.where(grey, 1.0, rangec)
        rc = (maxc - r) / safe
        gc = (maxc - g) / safe
        bc = (maxc - b) / safe
    h = np.where(r == maxc, bc - gc, np.where(g == maxc, 2.0 + rc - bc, 4.0 + gc - rc))
    h = np.where(grey, 0.0, (h / 6.0) % 1.0)
    return h, s, maxc.copy()


def hsv_to_rgb(h, s, v):
    """(N, 3) RGB of ``h``, ``s``, ``v`` (arrays or scalars, broadcast) --
    ``colorsys.hsv_to_rgb`` per element."""
    h, s, v = np.broadcast_arrays(*(np.asarray(x, dtype=np.float64) for x in (h, s, v)))
    i = np.trunc(h * 6.0)
    f = h * 6.0 - i
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    i = i.astype(np.int64) % 6
    r = np.choose(i, (v, q, p, p, t, v))
    g = np.choose(i, (t, v, v, q, p, p))
    b = np.choose(i, (p, p, t, v, v, q))
    grey = s == 0.0
    return np.stack((np.where(grey, v, r), np.where(grey, v, g), np.where(grey, v, b)), axis=1)


def _hsv_blend(dst, src, blend):
    """Target RGB of the HSV modes (COLOR, HUE, SATURATION, VALUE, LUMINOSITY) for
    ``dst`` (N, 3) and ``src`` (N, 3), as float64 (N, 3)."""
    dh, ds, dv = rgb_to_hsv(dst)
    sh, ss, sv = rgb_to_hsv(src)
    if blend == 'COLOR':
        return hsv_to_rgb(sh, ss, dv)
    if blend == 'HUE':
        return hsv_to_rgb(sh, ds, dv)
    if blend == 'SATURATION':
        return hsv_to_rgb(dh, ss, dv)
    return hsv_to_rgb(dh, ds, sv)   # VALUE, LUMINOSITY


_HSV_MODES = frozenset({'COLOR', 'HUE', 'SATURATION', 'VALUE', 'LUMINOSITY'})


def _apply_blend(dst, src, blend, opacity):
    """Apply a blend mode between destination [N,3] and source [3] arrays."""
    if blend == 'MIX':
        out = dst + (src - dst) * opacity
    elif blend == 'ADD':
        out = dst + src * opacity
    elif blend == 'SUB':
        out = dst - src * opacity
    elif blend == 'MUL':
        out = dst + (dst * src - dst) * opacity
    elif blend == 'DARKEN':
        out = dst + (np.minimum(dst, src) - dst) * opacity
    elif blend == 'LIGHTEN':
        out = dst + (np.maximum(dst, src) - dst) * opacity
    elif blend == 'SCREEN':
        screen = 1.0 - (1.0 - dst) * (1.0 - src)
        out = dst + (screen - dst) * opacity
    elif blend == 'OVERLAY':
        overlay = np.where(dst < 0.5, 2.0 * dst * src, 1.0 - 2.0 * (1.0 - dst) * (1.0 - src))
        out = dst + (overlay - dst) * opacity
    elif blend == 'HARDLIGHT':
        hl = np.where(src < 0.5, 2.0 * dst * src, 1.0 - 2.0 * (1.0 - dst) * (1.0 - src))
        out = dst + (hl - dst) * opacity
    elif blend == 'SOFTLIGHT':
        sl = (1.0 - 2.0 * src) * dst ** 2 + 2.0 * src * dst
        out = dst + (sl - dst) * opacity
    elif blend == 'DIFFERENCE':
        out = dst + (np.abs(dst - src) - dst) * opacity
    elif blend == 'EXCLUSION':
        excl = dst + src - 2.0 * dst * src
        out = dst + (excl - dst) * opacity
    elif blend == 'COLORDODGE':
        dodge = np.where(src >= 1.0, 1.0, dst / (1.0 - src + 1e-6))
        out = dst + (dodge - dst) * opacity
    elif blend == 'COLORBURN':
        burn = np.where(src <= 0.0, 0.0, 1.0 - (1.0 - dst) / (src + 1e-6))
        out = dst + (burn - dst) * opacity
    elif blend in _HSV_MODES:
        target = _hsv_blend(dst, np.broadcast_to(np.asarray(src, dtype=np.float64)[:3], dst.shape), blend)
        out = dst + (target.astype(dst.dtype) - dst) * opacity
    else:
        out = dst + (src - dst) * opacity
    return out


def blend_pixel_arrays(dst, src, blend, opacity):
    """Blend per-pixel RGB arrays with matching shapes [N, 3]."""
    if dst.shape != src.shape or dst.ndim != 2 or dst.shape[1] != 3:
        raise ValueError("dst and src must both be [N, 3] arrays")

    opacity_arr = np.asarray(opacity, dtype=np.float32)
    if opacity_arr.ndim == 0:
        opacity_arr = np.full((dst.shape[0], 1), float(opacity_arr), dtype=np.float32)
    elif opacity_arr.ndim == 1:
        opacity_arr = opacity_arr[:, None]
    opacity_arr = np.clip(opacity_arr, 0.0, 1.0)

    if blend == 'MIX':
        out = dst + (src - dst) * opacity_arr
    elif blend == 'ADD':
        out = dst + src * opacity_arr
    elif blend == 'SUB':
        out = dst - src * opacity_arr
    elif blend == 'MUL':
        out = dst + (dst * src - dst) * opacity_arr
    elif blend == 'DARKEN':
        out = dst + (np.minimum(dst, src) - dst) * opacity_arr
    elif blend == 'LIGHTEN':
        out = dst + (np.maximum(dst, src) - dst) * opacity_arr
    elif blend == 'SCREEN':
        screen = 1.0 - (1.0 - dst) * (1.0 - src)
        out = dst + (screen - dst) * opacity_arr
    elif blend == 'OVERLAY':
        overlay = np.where(dst < 0.5, 2.0 * dst * src, 1.0 - 2.0 * (1.0 - dst) * (1.0 - src))
        out = dst + (overlay - dst) * opacity_arr
    elif blend == 'HARDLIGHT':
        hl = np.where(src < 0.5, 2.0 * dst * src, 1.0 - 2.0 * (1.0 - dst) * (1.0 - src))
        out = dst + (hl - dst) * opacity_arr
    elif blend == 'SOFTLIGHT':
        sl = (1.0 - 2.0 * src) * dst ** 2 + 2.0 * src * dst
        out = dst + (sl - dst) * opacity_arr
    elif blend == 'DIFFERENCE':
        out = dst + (np.abs(dst - src) - dst) * opacity_arr
    elif blend == 'EXCLUSION':
        excl = dst + src - 2.0 * dst * src
        out = dst + (excl - dst) * opacity_arr
    elif blend == 'COLORDODGE':
        dodge = np.where(src >= 1.0, 1.0, dst / (1.0 - src + 1e-6))
        out = dst + (dodge - dst) * opacity_arr
    elif blend == 'COLORBURN':
        burn = np.where(src <= 0.0, 0.0, 1.0 - (1.0 - dst) / (src + 1e-6))
        out = dst + (burn - dst) * opacity_arr
    elif blend in _HSV_MODES:
        target = _hsv_blend(dst, src, blend).astype(np.float32)
        out = dst + (target - dst[:, :3]) * opacity_arr
    else:
        out = dst + (src - dst) * opacity_arr
    return out


def blend_region_pixels(dst_rgba, src_rgba, blend, opacity):
    """Blend matching RGBA regions and return a new RGBA array."""
    if dst_rgba.shape != src_rgba.shape or dst_rgba.ndim != 3 or dst_rgba.shape[2] != 4:
        raise ValueError("dst_rgba and src_rgba must both be [H, W, 4] arrays")
    if np.ndim(opacity) == 0 and native.enabled():
        out = native.blend_region(dst_rgba, src_rgba, blend, float(opacity))
        if out is not None:
            return out

    flat_dst = dst_rgba[..., :3].reshape(-1, 3)
    flat_src = src_rgba[..., :3].reshape(-1, 3)
    flat_rgb = blend_pixel_arrays(flat_dst, flat_src, blend, opacity).reshape(dst_rgba.shape[0], dst_rgba.shape[1], 3)
    flat_alpha = np.asarray(opacity, dtype=np.float32)
    if flat_alpha.ndim == 0:
        flat_alpha = float(flat_alpha)
    out = dst_rgba.copy()
    out[..., :3] = flat_rgb
    out[..., 3] = np.clip(dst_rgba[..., 3] + (src_rgba[..., 3] - dst_rgba[..., 3]) * flat_alpha, 0.0, 1.0)
    return out
