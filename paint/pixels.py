"""Pixel writers shared by every tool: paint a footprint with a color and blend
mode (:func:`write_pixels_to_image`), blend alpha (:func:`set_pixels_alpha`).
Each tries the C# backend first (utils/native.py) and falls back to NumPy.
"""


import numpy as np

from ..utils import native
from ..utils import pixel_io
from . import blending as draw_blending


def write_pixels_to_image(img, pixels, color, base_buffer=None,
                          blend='MIX', opacity=1.0, alpha_opacity=1.0, pixel_weights=None,
                          protect_transparent=False):
    """Paint a set of (px, py) coordinates onto img.

    Parameters
    ----------
    img           — bpy.types.Image to modify
    pixels        — iterable of (px, py) integer image coordinates
    color         — RGB or RGBA sequence, brush foreground color
    base_buffer   — optional float32 pixel array to start from (line preview)
    blend         — Blender BrushBlend mode string (default 'MIX')
    opacity       — float [0, 1] brush strength / alpha (default 1.0)
    alpha_opacity — float [0, 1] absolute alpha written to affected pixels
    pixel_weights — optional list of float [0, 1], same length and order as
                    *pixels*, multiplied into opacity per pixel.  Used for
                    falloff on circle/spray brushes.  Requires *pixels* to be
                    an ordered sequence (list), not a set.
    """
    if native.enabled() and _write_pixels_native(
            img, pixels, color, base_buffer, blend, opacity, alpha_opacity, pixel_weights,
            protect_transparent):
        return
    w, h = img.size
    arr  = base_buffer.copy() if base_buffer is not None else pixel_io.read(img)

    # Build parallel lists of flat RGBA base-indices and per-pixel weights
    # for every coordinate that falls inside the image bounds.
    pixels = list(pixels)  # ensure indexable for weight lookup
    flat_indices  = []
    weight_values = []
    for i, (px, py) in enumerate(pixels):
        if 0 <= px < w and 0 <= py < h:
            flat_indices.append((py * w + px) * 4)
            weight_values.append(pixel_weights[i] if pixel_weights is not None else 1.0)

    if not flat_indices:
        return

    flat_idx = np.array(flat_indices, dtype=np.int32)
    weights = np.array(weight_values, dtype=np.float32)

    if protect_transparent:
        alpha_mask = arr[flat_idx + 3] > 1e-6
        if not np.any(alpha_mask):
            return
        flat_idx = flat_idx[alpha_mask]
        weights = weights[alpha_mask]

    src = np.array([color[0], color[1], color[2]], dtype=np.float32)

    # Destination RGB as [N, 3]
    dst = np.stack([arr[flat_idx], arr[flat_idx + 1], arr[flat_idx + 2]], axis=1)



    # Farbmischung: Stärke * Falloff (weight) pro Pixel
    per_pixel_opacity = opacity * weights
    per_pixel_opacity = np.clip(per_pixel_opacity, 0.0, 1.0)
    out = np.clip(draw_blending._apply_blend(dst, src, blend, per_pixel_opacity[:, None]), 0.0, 1.0)

    arr[flat_idx]     = out[:, 0]
    arr[flat_idx + 1] = out[:, 1]
    arr[flat_idx + 2] = out[:, 2]

    # Alpha blend wie gehabt: opacity * falloff (weight)
    alpha_target = float(max(0.0, min(1.0, alpha_opacity)))
    alpha_dst = arr[flat_idx + 3]
    alpha_mix = per_pixel_opacity
    arr[flat_idx + 3] = alpha_dst + (alpha_target - alpha_dst) * alpha_mix

    # Uploads and tags every VIEW_3D / IMAGE_EDITOR showing the image for redraw.
    pixel_io.write(img, arr)


def _write_pixels_native(img, pixels, color, base_buffer, blend, opacity, alpha_opacity,
                         pixel_weights, protect_transparent):
    """C# branch of :func:`write_pixels_to_image`. False = not handled (use Python)."""
    w, h = img.size
    xy = native.coords(pixels)
    weights = native.weights_array(pixel_weights, len(xy)) if pixel_weights is not None else None
    if len(xy) == 0:
        return True
    # Like the Python path: nothing (not even the base buffer) is written
    # when no pixel is inside the image / visible.
    inside = (xy[:, 0] >= 0) & (xy[:, 0] < w) & (xy[:, 1] >= 0) & (xy[:, 1] < h)
    if not inside.any():
        return True
    if protect_transparent:
        alpha_src = base_buffer if base_buffer is not None else pixel_io.buffer(img)
        idx = (xy[inside, 1].astype(np.int64) * w + xy[inside, 0]) * 4 + 3
        if not np.any(alpha_src[idx] > np.float32(1e-6)):
            return True
    arr = pixel_io.buffer(img)
    if base_buffer is not None:
        np.copyto(arr, base_buffer.reshape(-1))
    if native.paint(arr, w, h, xy, weights, color, blend, opacity, alpha_opacity,
                    protect_transparent) is None:
        return False
    pixel_io.write(img, arr)
    return True


def set_pixels_alpha(img, pixels, alpha_opacity, opacity=1.0, protect_transparent=False, pixel_weights=None):
    """Blend image alpha toward target alpha for the given pixel coordinates.

    ``pixel_weights`` (parallel to ``pixels``) scales the blend per pixel.
    """
    w, h = img.size
    if native.enabled():
        arr = pixel_io.buffer(img)
        if native.set_alpha(arr, w, h, pixels, pixel_weights, alpha_opacity, opacity,
                            protect_transparent) is not None:
            pixel_io.write(img, arr)
            return
    arr = pixel_io.read(img)
    alpha = float(max(0.0, min(1.0, alpha_opacity)))
    mix = float(max(0.0, min(1.0, opacity)))

    if pixel_weights is None:
        pixel_weights = [1.0] * len(pixels)

    for (px, py), weight in zip(pixels, pixel_weights):
        if 0 <= px < w and 0 <= py < h:
            idx = (py * w + px) * 4
            if protect_transparent and arr[idx + 3] <= 1e-6:
                continue
            curr = arr[idx + 3]
            arr[idx + 3] = curr + (alpha - curr) * mix * weight

    pixel_io.write(img, arr)
