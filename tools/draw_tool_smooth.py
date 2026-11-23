"""Smooth and smear tool paint helpers."""

import bpy
import numpy as np


def _tag_redraw_all_image_views():
    try:
        for screen in bpy.data.screens:
            for area in screen.areas:
                if area.type in {'VIEW_3D', 'IMAGE_EDITOR'}:
                    area.tag_redraw()
    except Exception:
        pass


def smooth_pixels_in_image(img, pixels, smooth_radius, opacity, pixel_weights=None):
    """Blur pixels by averaging their neighbors within smooth_radius.

    ``pixel_weights`` (parallel to ``pixels``) scales the blend per pixel, e.g. a brush falloff.
    """
    w, h = img.size
    arr = np.array(img.pixels, dtype=np.float32)
    arr_4ch = arr.reshape(h, w, 4)
    result = arr_4ch.copy()

    if pixel_weights is None:
        pixel_weights = [1.0] * len(pixels)

    for (px, py), weight in zip(pixels, pixel_weights):
        if not (0 <= px < w and 0 <= py < h) or weight <= 0.0:
            continue
        x0 = max(0, px - smooth_radius)
        x1 = min(w - 1, px + smooth_radius)
        y0 = max(0, py - smooth_radius)
        y1 = min(h - 1, py + smooth_radius)
        kernel = arr_4ch[y0:y1 + 1, x0:x1 + 1, :]
        alpha = kernel[:, :, 3:4]
        alpha_sum = float(alpha.sum())
        if alpha_sum > 1e-6:
            avg = (kernel[:, :, :3] * alpha).sum(axis=(0, 1)) / alpha_sum
        else:
            avg = kernel[:, :, :3].mean(axis=(0, 1))
        orig = arr_4ch[py, px, :3]
        result[py, px, :3] = orig + (avg - orig) * (opacity * weight)

    img.pixels.foreach_set(result.ravel())
    img.update()
    _tag_redraw_all_image_views()


def smear_pixels_in_image(img, pixels, dx, dy, smear_reach, opacity):
    """Smear pixels by sampling color from upstream along (dx, dy)."""
    w, h = img.size
    arr = np.array(img.pixels, dtype=np.float32)
    arr_4ch = arr.reshape(h, w, 4)
    result = arr_4ch.copy()

    for (px, py) in pixels:
        if not (0 <= px < w and 0 <= py < h):
            continue
        src_x = int(round(px - dx * smear_reach))
        src_y = int(round(py - dy * smear_reach))
        src_x = max(0, min(w - 1, src_x))
        src_y = max(0, min(h - 1, src_y))
        src_color = arr_4ch[src_y, src_x, :3]
        orig = arr_4ch[py, px, :3]
        result[py, px, :3] = orig + (src_color - orig) * opacity

    img.pixels.foreach_set(result.ravel())
    img.update()
    _tag_redraw_all_image_views()
