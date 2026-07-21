"""Blend mode helpers for pixel arrays and RGBA regions."""

import colorsys

import numpy as np


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
    elif blend == 'COLOR':
        sh, ss, _ = colorsys.rgb_to_hsv(float(src[0]), float(src[1]), float(src[2]))
        color_rgb = np.empty_like(dst)
        for i in range(dst.shape[0]):
            _, _, dv = colorsys.rgb_to_hsv(float(dst[i, 0]), float(dst[i, 1]), float(dst[i, 2]))
            color_rgb[i] = colorsys.hsv_to_rgb(sh, ss, dv)
        out = dst + (color_rgb - dst) * opacity
    elif blend == 'HUE':
        sh, _, _ = colorsys.rgb_to_hsv(float(src[0]), float(src[1]), float(src[2]))
        hue_rgb = np.empty_like(dst)
        for i in range(dst.shape[0]):
            _, ds, dv = colorsys.rgb_to_hsv(float(dst[i, 0]), float(dst[i, 1]), float(dst[i, 2]))
            hue_rgb[i] = colorsys.hsv_to_rgb(sh, ds, dv)
        out = dst + (hue_rgb - dst) * opacity
    elif blend == 'SATURATION':
        _, ss, _ = colorsys.rgb_to_hsv(float(src[0]), float(src[1]), float(src[2]))
        sat_rgb = np.empty_like(dst)
        for i in range(dst.shape[0]):
            dh, _, dv = colorsys.rgb_to_hsv(float(dst[i, 0]), float(dst[i, 1]), float(dst[i, 2]))
            sat_rgb[i] = colorsys.hsv_to_rgb(dh, ss, dv)
        out = dst + (sat_rgb - dst) * opacity
    elif blend == 'VALUE':
        _, _, sv = colorsys.rgb_to_hsv(float(src[0]), float(src[1]), float(src[2]))
        val_rgb = np.empty_like(dst)
        for i in range(dst.shape[0]):
            dh, ds, _ = colorsys.rgb_to_hsv(float(dst[i, 0]), float(dst[i, 1]), float(dst[i, 2]))
            val_rgb[i] = colorsys.hsv_to_rgb(dh, ds, sv)
        out = dst + (val_rgb - dst) * opacity
    elif blend == 'LUMINOSITY':
        _, _, sv = colorsys.rgb_to_hsv(float(src[0]), float(src[1]), float(src[2]))
        lum_rgb = np.empty_like(dst)
        for i in range(dst.shape[0]):
            dh, ds, _ = colorsys.rgb_to_hsv(float(dst[i, 0]), float(dst[i, 1]), float(dst[i, 2]))
            lum_rgb[i] = colorsys.hsv_to_rgb(dh, ds, sv)
        out = dst + (lum_rgb - dst) * opacity
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
    elif blend == 'COLOR':
        out = np.empty_like(dst)
        for i in range(dst.shape[0]):
            sh, ss, _ = colorsys.rgb_to_hsv(float(src[i, 0]), float(src[i, 1]), float(src[i, 2]))
            _, _, dv = colorsys.rgb_to_hsv(float(dst[i, 0]), float(dst[i, 1]), float(dst[i, 2]))
            color_rgb = np.array(colorsys.hsv_to_rgb(sh, ss, dv), dtype=np.float32)
            out[i] = dst[i] + (color_rgb - dst[i]) * float(opacity_arr[i, 0])
    elif blend == 'HUE':
        out = np.empty_like(dst)
        for i in range(dst.shape[0]):
            sh, _, _ = colorsys.rgb_to_hsv(float(src[i, 0]), float(src[i, 1]), float(src[i, 2]))
            _, ds, dv = colorsys.rgb_to_hsv(float(dst[i, 0]), float(dst[i, 1]), float(dst[i, 2]))
            hue_rgb = np.array(colorsys.hsv_to_rgb(sh, ds, dv), dtype=np.float32)
            out[i] = dst[i] + (hue_rgb - dst[i]) * float(opacity_arr[i, 0])
    elif blend == 'SATURATION':
        out = np.empty_like(dst)
        for i in range(dst.shape[0]):
            _, ss, _ = colorsys.rgb_to_hsv(float(src[i, 0]), float(src[i, 1]), float(src[i, 2]))
            dh, _, dv = colorsys.rgb_to_hsv(float(dst[i, 0]), float(dst[i, 1]), float(dst[i, 2]))
            sat_rgb = np.array(colorsys.hsv_to_rgb(dh, ss, dv), dtype=np.float32)
            out[i] = dst[i] + (sat_rgb - dst[i]) * float(opacity_arr[i, 0])
    elif blend == 'VALUE':
        out = np.empty_like(dst)
        for i in range(dst.shape[0]):
            _, _, sv = colorsys.rgb_to_hsv(float(src[i, 0]), float(src[i, 1]), float(src[i, 2]))
            dh, ds, _ = colorsys.rgb_to_hsv(float(dst[i, 0]), float(dst[i, 1]), float(dst[i, 2]))
            val_rgb = np.array(colorsys.hsv_to_rgb(dh, ds, sv), dtype=np.float32)
            out[i] = dst[i] + (val_rgb - dst[i]) * float(opacity_arr[i, 0])
    elif blend == 'LUMINOSITY':
        out = np.empty_like(dst)
        for i in range(dst.shape[0]):
            _, _, sv = colorsys.rgb_to_hsv(float(src[i, 0]), float(src[i, 1]), float(src[i, 2]))
            dh, ds, _ = colorsys.rgb_to_hsv(float(dst[i, 0]), float(dst[i, 1]), float(dst[i, 2]))
            lum_rgb = np.array(colorsys.hsv_to_rgb(dh, ds, sv), dtype=np.float32)
            out[i] = dst[i] + (lum_rgb - dst[i]) * float(opacity_arr[i, 0])
    else:
        out = dst + (src - dst) * opacity_arr
    return out


def blend_region_pixels(dst_rgba, src_rgba, blend, opacity):
    """Blend matching RGBA regions and return a new RGBA array."""
    if dst_rgba.shape != src_rgba.shape or dst_rgba.ndim != 3 or dst_rgba.shape[2] != 4:
        raise ValueError("dst_rgba and src_rgba must both be [H, W, 4] arrays")

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
