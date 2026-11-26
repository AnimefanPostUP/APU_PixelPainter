"""Smooth and smear tool paint helpers.

The ``*_buffer`` functions work on a flat float32 RGBA buffer in place (C# first,
Python as fallback). ``valid`` (optional, ``w * h`` bools) marks the pixels the
filter may read from -- Edge mode filters a patch unfolded across UV seams
(``core.view3d.EdgePatch``) whose off-surface texels must never be sampled.
"""

import numpy as np

from ..utils import native
from ..utils import pixel_io


def smooth_buffer(arr, w, h, pixels, smooth_radius, opacity, pixel_weights=None, valid=None):
    """Blur ``pixels`` of ``arr`` by averaging their readable neighbors within smooth_radius.

    ``pixel_weights`` (parallel to ``pixels``) scales the blend per pixel, e.g. a brush falloff.
    A pixel with no readable neighbor keeps its color.
    """
    if native.enabled():
        if native.smooth(arr, w, h, pixels, pixel_weights, smooth_radius, opacity, valid=valid) is not None:
            return
    arr_4ch = arr.reshape(h, w, 4)
    result = arr_4ch.copy()
    valid_2d = None if valid is None else np.asarray(valid, dtype=bool).reshape(h, w)

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
        if valid_2d is not None:
            readable = valid_2d[y0:y1 + 1, x0:x1 + 1]
            if not readable.any():
                continue
            kernel = kernel[readable][None]     # (1, K, 4): only the readable pixels
        alpha = kernel[:, :, 3:4]
        alpha_sum = float(alpha.sum())
        if alpha_sum > 1e-6:
            avg = (kernel[:, :, :3] * alpha).sum(axis=(0, 1)) / alpha_sum
        else:
            avg = kernel[:, :, :3].mean(axis=(0, 1))
        orig = arr_4ch[py, px, :3]
        result[py, px, :3] = orig + (avg - orig) * (opacity * weight)

    arr[:] = result.reshape(-1)


def smear_buffer(arr, w, h, pixels, dx, dy, smear_reach, opacity, pixel_weights=None, valid=None):
    """Smear ``pixels`` of ``arr`` by sampling color from upstream along (dx, dy).

    ``pixel_weights`` (parallel to ``pixels``) scales the blend per pixel, e.g. a brush falloff.
    Without ``valid`` the source is clamped to the buffer; with it, a source outside the
    buffer or on an unreadable pixel leaves the pixel unchanged.
    """
    if native.enabled():
        if native.smear(arr, w, h, pixels, pixel_weights, dx, dy, smear_reach, opacity,
                        valid=valid) is not None:
            return
    arr_4ch = arr.reshape(h, w, 4)
    result = arr_4ch.copy()
    valid_2d = None if valid is None else np.asarray(valid, dtype=bool).reshape(h, w)
    if pixel_weights is None:
        pixel_weights = [1.0] * len(pixels)

    for (px, py), weight in zip(pixels, pixel_weights):
        if not (0 <= px < w and 0 <= py < h) or weight <= 0.0:
            continue
        src_x = int(round(px - dx * smear_reach))
        src_y = int(round(py - dy * smear_reach))
        if valid_2d is not None:
            if not (0 <= src_x < w and 0 <= src_y < h) or not valid_2d[src_y, src_x]:
                continue
        src_x = max(0, min(w - 1, src_x))
        src_y = max(0, min(h - 1, src_y))
        src_color = arr_4ch[src_y, src_x, :3]
        orig = arr_4ch[py, px, :3]
        result[py, px, :3] = orig + (src_color - orig) * (opacity * weight)

    arr[:] = result.reshape(-1)


def smooth_pixels_in_image(img, pixels, smooth_radius, opacity, pixel_weights=None):
    """:func:`smooth_buffer` on an image."""
    w, h = img.size
    arr = pixel_io.buffer(img)
    smooth_buffer(arr, w, h, pixels, smooth_radius, opacity, pixel_weights=pixel_weights)
    pixel_io.write(img, arr)


def smear_pixels_in_image(img, pixels, dx, dy, smear_reach, opacity, pixel_weights=None):
    """:func:`smear_buffer` on an image."""
    w, h = img.size
    arr = pixel_io.buffer(img)
    smear_buffer(arr, w, h, pixels, dx, dy, smear_reach, opacity, pixel_weights=pixel_weights)
    pixel_io.write(img, arr)
