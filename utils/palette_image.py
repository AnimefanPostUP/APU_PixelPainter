"""Palette from an image: its distinct pixel colors (numpy, no bpy).

:func:`extract_colors` takes the flat RGBA float buffer Blender gives
(``Image.pixels``, rows bottom-up) and returns at most ``max_colors`` RGB tuples:

* every distinct color (8-bit) of the opaque pixels, in reading order (top-left
  first) -- a palette strip / swatch image keeps its order;
* more distinct colors than that (a picture): reduced by a median cut weighted
  by how often each color occurs, ordered by where each group first appears.
"""

import numpy as np


def _unpack(key):
    key = int(key)
    return ((key >> 16) & 255) / 255.0, ((key >> 8) & 255) / 255.0, (key & 255) / 255.0


def extract_colors(rgba, width, height, max_colors=24, min_alpha=0.5):
    """``(colors, distinct)``: up to ``max_colors`` RGB tuples and how many distinct colors the image has."""
    px = np.asarray(rgba, dtype=np.float32)
    if width <= 0 or height <= 0 or px.size < width * height * 4:
        return [], 0
    px = px[:width * height * 4].reshape(height, width, 4)[::-1].reshape(-1, 4)   # top row first
    px = px[px[:, 3] >= min_alpha][:, :3]
    if not len(px):
        return [], 0
    q = np.clip(np.round(px * 255.0), 0, 255).astype(np.int64)
    keys = (q[:, 0] << 16) | (q[:, 1] << 8) | q[:, 2]
    uniq, first, counts = np.unique(keys, return_index=True, return_counts=True)
    if len(uniq) <= max_colors:
        return [_unpack(uniq[i]) for i in np.argsort(first)], len(uniq)

    rgb = np.stack([(uniq >> 16) & 255, (uniq >> 8) & 255, uniq & 255], axis=1).astype(np.float64)
    boxes = [np.arange(len(uniq))]
    while len(boxes) < max_colors:
        # Split the box with the largest (channel range x pixel count).
        scores = [(np.ptp(rgb[b], axis=0).max() * counts[b].sum()) if len(b) > 1 else -1.0 for b in boxes]
        k = int(np.argmax(scores))
        if scores[k] <= 0:
            break
        box = boxes.pop(k)
        channel = int(np.argmax(np.ptp(rgb[box], axis=0)))
        order = box[np.argsort(rgb[box, channel], kind='stable')]
        weights = np.cumsum(counts[order])
        cut = int(np.searchsorted(weights, weights[-1] / 2.0))
        cut = min(max(cut, 1), len(order) - 1)       # both halves non-empty
        boxes += [order[:cut], order[cut:]]
    result = []
    for box in sorted(boxes, key=lambda b: first[b].min()):
        w = counts[box].astype(np.float64)
        mean = (rgb[box] * w[:, None]).sum(axis=0) / w.sum()
        result.append(tuple(float(np.round(c)) / 255.0 for c in mean))
    return result, len(uniq)
