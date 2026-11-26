"""Pure math and discrete geometry helpers — no Blender dependencies."""
import math
import random

import numpy as np


def convert_uv_coord(u, v, w, h):
    """Convert UV [0-1] coordinates to integer image pixel coordinates."""
    return int(u * w), int(v * h)


def get_pixels_in_shape(cx, cy, radius, mode):
    """Return set of (px, py) image pixels covered by the brush shape.

    mode: 'SQUARE' or 'CIRCLE'
    """
    pixels = set()
    if radius == 0:
        pixels.add((cx, cy))
    elif mode == 'SQUARE':
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                pixels.add((cx + dx, cy + dy))
    else:  # CIRCLE
        r2 = radius * radius
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if dx * dx + dy * dy <= r2:
                    pixels.add((cx + dx, cy + dy))
    return pixels


def get_line_pixels(x0, y0, x1, y1):
    """Bresenham integer line — returns ordered list of (px, py) from (x0,y0) to (x1,y1)."""
    pixels = []
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    while True:
        pixels.append((x0, y0))
        if x0 == x1 and y0 == y1:
            break
        e2 = err * 2
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy
    return pixels


# ---------------------------------------------------------------------------
# Falloff
# ---------------------------------------------------------------------------

# Parameters of the shaped presets (normalized distance, 0 = centre, 1 = edge).
PLATEAU_CORE = 0.5        # full strength up to here, then a smooth fade
STEPPED_LEVELS = 4
RING_CENTER = 0.65        # strongest here
RING_WIDTH = 0.35         # fades to 0 this far on both sides
SHAPE_MAX_POWER = 4.0     # Shape falloff: the fade's exponent at sharpness 1 (1 at sharpness 0)


def shape_falloff(t, hardness, sharpness):
    """Shape falloff (the pen menu's field): full strength out to ``hardness`` (0 soft ..
    1 hard = constant), then a fade ``(1 - u) ** p`` with ``p`` from 1 (``sharpness`` 0,
    linear) to ``SHAPE_MAX_POWER`` (sharpness 1)."""
    core = max(0.0, min(1.0, hardness))
    if t <= core or core >= 1.0:
        return 1.0
    u = (t - core) / (1.0 - core)
    power = 1.0 + (SHAPE_MAX_POWER - 1.0) * max(0.0, min(1.0, sharpness))
    return max(0.0, 1.0 - u) ** power


def get_falloff(t, falloff_type, curve_sampler=None):
    """Return a weight in [0, 1] for a normalised distance t in [0, 1].

    t = 0 is the brush centre (full strength), t = 1 is the edge (zero strength).
    ``falloff_type`` is a preset id or a Shape key ``('SHAPE', hardness, sharpness)``.
    """
    t = max(0.0, min(1.0, t))
    if curve_sampler is not None:
        try:
            return max(0.0, min(1.0, float(curve_sampler(t))))
        except Exception:
            pass
    if isinstance(falloff_type, tuple):
        if falloff_type and falloff_type[0] == 'SHAPE':
            return shape_falloff(t, *falloff_type[1:3])
        return 1.0
    if falloff_type == 'SHAPE':        # no values given: the default (linear)
        return 1.0 - t
    if falloff_type == 'CONSTANT':
        return 1.0
    elif falloff_type == 'LINEAR':
        return 1.0 - t
    elif falloff_type == 'SMOOTH':
        # Inverse smoothstep: ease-in/out between 1 (centre) and 0 (edge)
        return 1.0 - t * t * (3.0 - 2.0 * t)
    elif falloff_type == 'SPHERE':
        # Dome shape: sqrt(1 - t²)
        return math.sqrt(max(0.0, 1.0 - t * t))
    elif falloff_type == 'SHARPEN':
        # Quadratic: drops off quickly toward the edge
        return (1.0 - t) ** 2
    elif falloff_type == 'PLATEAU':
        # Full-strength core, then the Smooth fade over the rest
        core = PLATEAU_CORE
        if t <= core:
            return 1.0
        u = (t - core) / (1.0 - core)
        return 1.0 - u * u * (3.0 - 2.0 * u)
    elif falloff_type == 'ROOT':
        return math.sqrt(1.0 - t)
    elif falloff_type == 'SPIKE':
        return (1.0 - t) ** 4
    elif falloff_type == 'STEPPED':
        # Linear, quantized: 1 at the centre, then (levels-1)/levels ... 1/levels, 0 at the edge
        levels = STEPPED_LEVELS
        return math.ceil((1.0 - t) * levels - 1e-9) / levels
    elif falloff_type == 'RING':
        u = min(1.0, abs(t - RING_CENTER) / RING_WIDTH)
        return 1.0 - u * u * (3.0 - 2.0 * u)
    elif falloff_type == 'INVERTED':
        # Smooth, mirrored: 0 at the centre, 1 at the edge
        return t * t * (3.0 - 2.0 * t)
    return 1.0


# ---------------------------------------------------------------------------
# Weighted circle and spray pixel sets
# ---------------------------------------------------------------------------

def get_pixels_in_circle_weighted(cx, cy, radius, falloff_type='CONSTANT', curve_sampler=None):
    """Return (pixels, weights) for a filled circle with distance falloff.

    pixels  — list of (px, py) integer image coordinates
    weights — parallel list of float [0, 1] falloff weights
    """
    if radius == 0:
        return [(cx, cy)], [1.0]
    pixels  = []
    weights = []
    r2 = radius * radius
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            if dx * dx + dy * dy <= r2:
                dist = math.sqrt(dx * dx + dy * dy)
                pixels.append((cx + dx, cy + dy))
                weights.append(get_falloff(dist / radius, falloff_type, curve_sampler=curve_sampler))
    return pixels, weights


def get_spray_pixels(cx, cy, radius, spray_strength, falloff_type='CONSTANT', curve_sampler=None):
    """Return (pixels, weights) for a randomised spray brush.

    spray_strength — float [0.01, 1.0]: fraction of the circle area to sample
                     per call.  A value of 1.0 fills the entire circle each frame.
    falloff_type   — controls pixel weight (and thus opacity) by distance.
    """
    if radius == 0:
        return [(cx, cy)], [1.0]

    # Target pixel count: fraction of circle area (π r²)
    total_area = max(1, int(math.pi * radius * radius))
    count      = max(1, int(spray_strength * total_area))

    r2      = radius * radius
    pixels  = []
    weights = []
    seen    = set()
    max_attempts = count * 20

    for _ in range(max_attempts):
        if len(pixels) >= count:
            break
        dx = random.randint(-radius, radius)
        dy = random.randint(-radius, radius)
        if dx * dx + dy * dy > r2:
            continue
        pt = (cx + dx, cy + dy)
        if pt in seen:
            continue
        seen.add(pt)
        dist = math.sqrt(dx * dx + dy * dy)
        pixels.append(pt)
        weights.append(get_falloff(dist / radius, falloff_type, curve_sampler=curve_sampler))

    return pixels, weights


# ---------------------------------------------------------------------------
# Outlines as NumPy masks (the cursor preview: drawn every frame)
# ---------------------------------------------------------------------------

def _row_half_widths(radius, shape):
    """``(dy, half_width)`` per stamp row: a row ``dy`` covers ``dx`` in ``[-hw, hw]``
    (same pixels as :func:`get_pixels_in_shape`)."""
    r = max(0, int(radius))
    dy = np.arange(-r, r + 1)
    if shape == 'SQUARE' or r == 0:
        hw = np.full(dy.shape, r)
    else:
        hw = np.floor(np.sqrt(np.maximum(0, r * r - dy * dy)) + 1e-9).astype(np.int64)
    return dy, hw


def stamp_mask(centers, radius, shape):
    """Union of the ``shape`` stamps at every center as ``(x0, y0, mask)``:
    ``mask[y - y0, x - x0]`` is True for a covered pixel. ``mask`` is None when
    there are no centers. Built from one row interval per stamp row."""
    pts = np.asarray(list(centers) if not isinstance(centers, np.ndarray) else centers,
                     dtype=np.int64).reshape(-1, 2)
    if len(pts) == 0:
        return 0, 0, None
    r = max(0, int(radius))
    x0, y0 = int(pts[:, 0].min()) - r, int(pts[:, 1].min()) - r
    w = int(pts[:, 0].max()) + r - x0 + 1
    h = int(pts[:, 1].max()) + r - y0 + 1
    dy, hw = _row_half_widths(r, shape)
    rows = (pts[:, 1, None] - y0 + dy[None, :]).ravel()
    cols = pts[:, 0, None] - x0
    starts = (cols - hw[None, :]).ravel()
    ends = (cols + hw[None, :] + 1).ravel()
    diff = np.zeros((h, w + 1), dtype=np.int32)
    np.add.at(diff, (rows, starts), 1)
    np.add.at(diff, (rows, ends), -1)
    return x0, y0, np.cumsum(diff[:, :w], axis=1) > 0


def _runs(lines):
    """``(line, start, end)`` of the runs of True along axis 1 of a 2D bool array."""
    d = np.diff(lines.astype(np.int8), axis=1, prepend=0, append=0)
    line, start = np.nonzero(d == 1)
    _l, end = np.nonzero(d == -1)
    return line, start, end


def mask_outline_segments(x0, y0, mask):
    """Contour of a pixel mask as ``(E, 2, 2)`` float segments between pixel corners
    (image coordinates). Collinear unit edges are merged into one segment, so it
    draws the same lines as :func:`get_outline_edges` with far fewer vertices."""
    if mask is None or not mask.any():
        return np.empty((0, 2, 2), dtype=np.float64)
    padded = np.pad(mask, 1)
    # Horizontal boundaries: corner row k (0..h) between pixel rows k - 1 and k.
    hor = padded[1:, 1:-1] != padded[:-1, 1:-1]
    k, s, e = _runs(hor)
    h_seg = np.stack((np.stack((x0 + s, y0 + k), axis=1),
                      np.stack((x0 + e, y0 + k), axis=1)), axis=1)
    # Vertical boundaries: corner column k (0..w) between pixel columns k - 1 and k.
    ver = (padded[1:-1, 1:] != padded[1:-1, :-1]).T
    k, s, e = _runs(ver)
    v_seg = np.stack((np.stack((x0 + k, y0 + s), axis=1),
                      np.stack((x0 + k, y0 + e), axis=1)), axis=1)
    return np.concatenate((h_seg, v_seg)).astype(np.float64)


def pixels_outline_segments(pixels):
    """:func:`mask_outline_segments` of an iterable of ``(x, y)`` pixels."""
    pts = np.array(list(pixels), dtype=np.int64).reshape(-1, 2)
    if len(pts) == 0:
        return np.empty((0, 2, 2), dtype=np.float64)
    x0, y0 = pts.min(axis=0)
    w, h = pts.max(axis=0) - (x0, y0) + 1
    mask = np.zeros((int(h), int(w)), dtype=bool)
    mask[pts[:, 1] - y0, pts[:, 0] - x0] = True
    return mask_outline_segments(int(x0), int(y0), mask)


_shape_outline_cache = {}


def shape_outline_segments(x, y, radius, shape):
    """:func:`mask_outline_segments` of one stamp at ``(x, y)`` (memoized per size)."""
    key = (max(0, int(radius)), shape)
    base = _shape_outline_cache.get(key)
    if base is None:
        if len(_shape_outline_cache) > 256:
            _shape_outline_cache.clear()
        base = _shape_outline_cache[key] = mask_outline_segments(*stamp_mask([(0, 0)], *key))
    return base + np.array((x, y), dtype=np.float64)


def get_outline_edges(pixels):
    """Return (p0, p1) corner pairs for the outer contour of a pixel set."""
    edges = []
    for (px, py) in pixels:
        if (px, py + 1) not in pixels:
            edges.append(((px, py + 1), (px + 1, py + 1)))
        if (px, py - 1) not in pixels:
            edges.append(((px, py), (px + 1, py)))
        if (px + 1, py) not in pixels:
            edges.append(((px + 1, py), (px + 1, py + 1)))
        if (px - 1, py) not in pixels:
            edges.append(((px, py), (px, py + 1)))
    return edges
