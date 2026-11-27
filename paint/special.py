"""Pixel kernels of the special brushes (the pen menu's Brushes window, ``tools/special/``):
pure NumPy, no Blender.

Images are ``(H, W, 4)`` float32 views of the flat RGBA buffer (row ``y`` = image row
``y``); pixel coordinates are integer ``(x, y)`` arrays.

* **Footprints**: :func:`disk` / :func:`stamps` -- the pixels of one or several round
  stamps with falloff weights (a lookup table over the normalized distance).
* **Rust**: :func:`rust_texels` -- fractal value noise anchored to the texture (the same
  pixel always gets the same rust), a mix between two colors plus a patchy coverage.
* **Noise blur**: :func:`noise_blur` -- every pixel takes the average of a few random
  pixels around it (few samples: grainy; many: smooth).
* **Pull**: :func:`pull_field_step` / :func:`warp` -- a liquify-style displacement field
  accumulated over a stroke, resampled from the stroke's starting image.
* **Repair**: :func:`heal` -- healing brush: a source patch's texture with the
  destination's colors at its border (Shepard interpolation of the border differences),
  :func:`best_offset` finds a source for the automatic (spot) mode.
* **Particles**: :func:`scatter_2d` (bounces without a mesh), :func:`chips` (the
  irregular dents painted at the impacts).
"""

import math

import numpy as np


FALLOFF_SAMPLES = 65            # falloff lookup table size (normalized distance 0..1)
MAX_HEAL_RING = 160             # border pixels used by heal() (subsampled above this)
HEAL_RING_WIDTH = 2.0           # px past the brush radius that form the border


# ---------------------------------------------------------------------------
# Footprints
# ---------------------------------------------------------------------------

def smooth_lut():
    """Default falloff table: smoothstep from 1 (center) to 0 (edge)."""
    t = np.linspace(0.0, 1.0, FALLOFF_SAMPLES, dtype=np.float32)
    return 1.0 - t * t * (3.0 - 2.0 * t)


def disk(cx, cy, radius, lut=None, w=None, h=None):
    """``(xs, ys, weights, dist)`` of the pixels within ``radius`` of ``(cx, cy)``
    (clipped to ``w`` x ``h`` when given). ``dist`` is the distance to the center."""
    r = max(0, int(radius))
    oy, ox = np.mgrid[-r:r + 1, -r:r + 1]
    d = np.sqrt((ox * ox + oy * oy).astype(np.float32))
    inside = d <= r + 1e-6
    xs = (ox[inside] + int(cx)).astype(np.int64)
    ys = (oy[inside] + int(cy)).astype(np.int64)
    d = d[inside]
    if r == 0:
        wts = np.ones(len(xs), dtype=np.float32)
    else:
        table = smooth_lut() if lut is None else np.asarray(lut, dtype=np.float32)
        wts = np.interp(d / r, np.linspace(0.0, 1.0, len(table)), table).astype(np.float32)
    if w is not None and h is not None:
        keep = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
        xs, ys, wts, d = xs[keep], ys[keep], wts[keep], d[keep]
    return xs, ys, wts, d


def stamps(centers, radius, lut, w, h):
    """``(xs, ys, weights)`` of round stamps at every center, overlapping stamps keeping
    the strongest weight (a stroke step's footprint), clipped to the image."""
    centers = np.asarray(list(centers), dtype=np.int64).reshape(-1, 2)
    if len(centers) == 0:
        empty = np.zeros(0, dtype=np.int64)
        return empty, empty, np.zeros(0, dtype=np.float32)
    r = max(0, int(radius))
    x0 = max(0, int(centers[:, 0].min()) - r)
    y0 = max(0, int(centers[:, 1].min()) - r)
    x1 = min(w, int(centers[:, 0].max()) + r + 1)
    y1 = min(h, int(centers[:, 1].max()) + r + 1)
    if x1 <= x0 or y1 <= y0:
        empty = np.zeros(0, dtype=np.int64)
        return empty, empty, np.zeros(0, dtype=np.float32)
    grid = np.zeros((y1 - y0, x1 - x0), dtype=np.float32)
    for cx, cy in centers:
        xs, ys, wts, _d = disk(cx, cy, r, lut, w, h)
        np.maximum.at(grid, (ys - y0, xs - x0), wts)
    gy, gx = np.nonzero(grid > 0.0)
    return (gx + x0).astype(np.int64), (gy + y0).astype(np.int64), grid[gy, gx]


def spaced(points, last, spacing):
    """The points at least ``spacing`` px apart, starting from ``last`` (the previous
    stamp, or None: the first point is kept). Returns ``(kept, new_last)``."""
    kept = []
    for p in points:
        if last is None or math.hypot(p[0] - last[0], p[1] - last[1]) >= spacing:
            kept.append(p)
            last = p
    return kept, last


# ---------------------------------------------------------------------------
# Deterministic noise (anchored to the texture)
# ---------------------------------------------------------------------------

def hash01(ix, iy, seed=0):
    """A float in [0, 1) per integer coordinate pair (stable for the same inputs)."""
    ix = np.asarray(ix, dtype=np.int64) & 0xFFFFFFFF
    iy = np.asarray(iy, dtype=np.int64) & 0xFFFFFFFF
    h = (ix * 374761393 + iy * 668265263 + (int(seed) & 0xFFFF) * 2246822519) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    h = h ^ (h >> 16)
    return (h & 0xFFFFFF).astype(np.float32) / float(1 << 24)


def value_noise(x, y, scale, seed=0):
    """Smooth value noise in [0, 1] with features about ``scale`` px across."""
    s = max(1e-3, float(scale))
    gx = np.asarray(x, dtype=np.float64) / s
    gy = np.asarray(y, dtype=np.float64) / s
    ix, iy = np.floor(gx).astype(np.int64), np.floor(gy).astype(np.int64)
    fx, fy = (gx - ix).astype(np.float32), (gy - iy).astype(np.float32)
    fx = fx * fx * (3.0 - 2.0 * fx)
    fy = fy * fy * (3.0 - 2.0 * fy)
    v00, v10 = hash01(ix, iy, seed), hash01(ix + 1, iy, seed)
    v01, v11 = hash01(ix, iy + 1, seed), hash01(ix + 1, iy + 1, seed)
    top = v00 + (v10 - v00) * fx
    bottom = v01 + (v11 - v01) * fx
    return top + (bottom - top) * fy


def fractal(x, y, scale, seed=0, octaves=3):
    """Octaves of :func:`value_noise` (each half the size, half the weight), stretched
    to use most of [0, 1]."""
    total = np.zeros(np.shape(x), dtype=np.float32)
    amp, norm = 1.0, 0.0
    for o in range(octaves):
        total += amp * value_noise(x, y, scale / (2 ** o), seed + 31 * o)
        norm += amp
        amp *= 0.5
    v = total / norm
    return np.clip((v - 0.5) * 1.9 + 0.5, 0.0, 1.0)


def _smoothstep(e0, e1, v):
    t = np.clip((v - e0) / max(1e-6, e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def rust_texels(xs, ys, scale, coverage, seed=0):
    """Rust at the pixels ``(xs, ys)``: ``(t, presence)`` float32 arrays.

    ``t`` mixes the two rust colors (0 = first, 1 = second): broad patches with a pixel
    grain on top. ``presence`` (0..1) makes the rust patchy: ``coverage`` 1 covers
    everything, 0 nothing; in between blotches about ``scale`` px across."""
    xs = np.asarray(xs)
    ys = np.asarray(ys)
    base = fractal(xs, ys, scale, seed, 3)
    grain = hash01(xs, ys, seed + 7)
    t = _smoothstep(0.15, 0.85, np.clip(base + (grain - 0.5) * 0.35, 0.0, 1.0))
    coverage = float(np.clip(coverage, 0.0, 1.0))
    if coverage >= 1.0:
        presence = np.ones_like(t)
    elif coverage <= 0.0:
        presence = np.zeros_like(t)
    else:
        patch = fractal(xs, ys, scale * 1.7, seed + 101, 3) * 0.85 + grain * 0.15
        edge = 1.0 - coverage
        presence = _smoothstep(edge - 0.06, edge + 0.06, patch)
    return t.astype(np.float32), presence.astype(np.float32)


# ---------------------------------------------------------------------------
# Noise blur
# ---------------------------------------------------------------------------

def noise_samples(grain):
    """Random samples averaged per pixel: 1 (grain 1, pure scatter) .. 8 (grain 0)."""
    return 1 + int(round((1.0 - float(np.clip(grain, 0.0, 1.0))) * 7))


def noise_blur(img, xs, ys, scatter, grain, rng):
    """RGBA ``(N, 4)``: each pixel ``(xs, ys)`` as the average of random pixels within
    ``scatter`` px of it (:func:`noise_samples` of them), read from ``img`` (H, W, 4)."""
    h, w = img.shape[:2]
    n = len(xs)
    k = noise_samples(grain)
    acc = np.zeros((n, 4), dtype=np.float32)
    reach = max(0.0, float(scatter))
    for _ in range(k):
        ang = rng.uniform(0.0, math.tau, n)
        rad = reach * np.sqrt(rng.uniform(0.0, 1.0, n))
        sx = np.clip(np.rint(xs + np.cos(ang) * rad), 0, w - 1).astype(np.int64)
        sy = np.clip(np.rint(ys + np.sin(ang) * rad), 0, h - 1).astype(np.int64)
        acc += img[sy, sx]
    return acc / k


# ---------------------------------------------------------------------------
# Pull (liquify)
# ---------------------------------------------------------------------------

def _bilinear(field, x, y):
    """``field`` (H, W, C) sampled at float coordinates (clamped to the edges)."""
    h, w = field.shape[:2]
    x = np.clip(x, 0.0, w - 1.0)
    y = np.clip(y, 0.0, h - 1.0)
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    x1 = np.minimum(x0 + 1, w - 1)
    y1 = np.minimum(y0 + 1, h - 1)
    fx = (x - x0)[..., None].astype(np.float32)
    fy = (y - y0)[..., None].astype(np.float32)
    top = field[y0, x0] * (1.0 - fx) + field[y0, x1] * fx
    bottom = field[y1, x0] * (1.0 - fx) + field[y1, x1] * fx
    return top * (1.0 - fy) + bottom * fy


def pull_field_step(field, cx, cy, dx, dy, radius, amount=1.0, lut=None):
    """Move the pixels around ``(cx, cy)`` by ``(dx, dy)`` (weighted by the falloff and
    ``amount``) in the displacement field ``field`` (H, W, 2; per pixel: where its
    color comes from is ``p - field[p]``). Composes with the earlier displacement, so
    a stroke can drag pixels far. Returns the changed box ``(x0, y0, x1, y1)``
    (end-exclusive) or None."""
    h, w = field.shape[:2]
    xs, ys, wts, _d = disk(cx, cy, max(1, int(radius)), lut, w, h)
    if len(xs) == 0:
        return None
    k = (wts * float(amount))[:, None]
    shift = np.stack((np.full(len(xs), dx, dtype=np.float32), np.full(len(xs), dy, dtype=np.float32)), axis=1) * k
    return _compose(field, xs, ys, shift)


PINCH_RATE = 0.2     # pinch / push: share of the distance to the center moved per stamp (full weight)


def pinch_field_step(field, cx, cy, radius, amount=1.0, lut=None, outward=False, rate=PINCH_RATE):
    """Suck the pixels around ``(cx, cy)`` toward the center (``outward``: push them away),
    each by ``rate`` x its distance to the center, weighted by the falloff and ``amount``.
    Composes with the earlier displacement like :func:`pull_field_step`; returns the
    changed box or None."""
    h, w = field.shape[:2]
    xs, ys, wts, _d = disk(cx, cy, max(1, int(radius)), lut, w, h)
    if len(xs) == 0:
        return None
    k = (wts * float(amount) * float(rate))[:, None]
    toward = np.stack(((cx - xs).astype(np.float32), (cy - ys).astype(np.float32)), axis=1)
    # A pixel's color comes from p - shift: shift toward the center reads from farther out
    # (the image contracts into the center); away from it reads from nearer (it swells).
    shift = (-toward if outward else toward) * k
    return _compose(field, xs, ys, shift)


def _compose(field, xs, ys, shift):
    """Apply ``shift`` (N, 2) at the pixels ``(xs, ys)`` on top of the field's earlier
    displacement; returns the changed box (end-exclusive)."""
    before = _bilinear(field, xs - shift[:, 0], ys - shift[:, 1])
    field[ys, xs] = shift + before
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def warp(source, field, box, smooth=False):
    """Pixels of ``box`` (x0, y0, x1, y1) taken from ``source`` (H, W, 4) through the
    displacement ``field``: ``(xs, ys, rgba)``. ``smooth``: bilinear, else the nearest
    pixel (pixel art stays crisp)."""
    x0, y0, x1, y1 = box
    gy, gx = np.mgrid[y0:y1, x0:x1]
    xs, ys = gx.reshape(-1), gy.reshape(-1)
    d = field[ys, xs]
    sx = xs - d[:, 0]
    sy = ys - d[:, 1]
    h, w = source.shape[:2]
    if smooth:
        rgba = _bilinear(source, sx, sy)
    else:
        rgba = source[np.clip(np.rint(sy), 0, h - 1).astype(np.int64),
                      np.clip(np.rint(sx), 0, w - 1).astype(np.int64)]
    return xs.astype(np.int64), ys.astype(np.int64), rgba


# ---------------------------------------------------------------------------
# Repair (healing brush)
# ---------------------------------------------------------------------------

def ring(cx, cy, radius, w, h, width=HEAL_RING_WIDTH, limit=MAX_HEAL_RING):
    """``(xs, ys)`` of the border just outside a stamp (``radius`` .. ``radius + width``),
    clipped to the image and evenly subsampled to at most ``limit`` pixels."""
    r = max(1, int(radius))
    reach = int(math.ceil(r + width))
    oy, ox = np.mgrid[-reach:reach + 1, -reach:reach + 1]
    d = np.sqrt((ox * ox + oy * oy).astype(np.float32))
    band = (d > r + 1e-6) & (d <= r + width + 1e-6)
    xs = (ox[band] + int(cx)).astype(np.int64)
    ys = (oy[band] + int(cy)).astype(np.int64)
    keep = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
    xs, ys = xs[keep], ys[keep]
    if len(xs) > limit:
        pick = np.linspace(0, len(xs) - 1, limit).astype(np.int64)
        xs, ys = xs[pick], ys[pick]
    return xs, ys


def heal(src_inner, src_ring, dst_ring, inner_xy, ring_xy, texture=1.0):
    """Healed RGBA ``(N, 4)`` of the stamp's pixels.

    ``src_inner`` / ``src_ring``: the source patch at the stamp's pixels / border;
    ``dst_ring``: the destination's border. The source keeps its texture while its colors
    are shifted to meet the destination at the border: the border differences are spread
    inward (Shepard interpolation, weights 1 / distance²). ``texture`` 0 gives only the
    smooth fill from the destination's border (no texture), 1 the full source texture."""
    if len(ring_xy) == 0:
        return np.asarray(src_inner, dtype=np.float32)
    p = np.asarray(inner_xy, dtype=np.float32)
    q = np.asarray(ring_xy, dtype=np.float32)
    d2 = ((p[:, None, :] - q[None, :, :]) ** 2).sum(axis=2)
    wts = 1.0 / np.maximum(d2, 0.25)
    wts /= wts.sum(axis=1, keepdims=True)
    dst_ring = np.asarray(dst_ring, dtype=np.float32)
    correction = wts @ (dst_ring - np.asarray(src_ring, dtype=np.float32))
    healed = np.asarray(src_inner, dtype=np.float32) + correction
    t = float(np.clip(texture, 0.0, 1.0))
    if t >= 1.0:
        return np.clip(healed, 0.0, 1.0)
    membrane = wts @ dst_ring
    return np.clip(membrane + (healed - membrane) * t, 0.0, 1.0)


def candidate_offsets(radius, distances=(2.2, 3.2), directions=8):
    """Offsets around a stamp to look for a source (spot healing)."""
    out = []
    r = max(1, int(radius))
    for k in distances:
        for i in range(directions):
            a = math.tau * i / directions
            out.append((int(round(math.cos(a) * k * r)), int(round(math.sin(a) * k * r))))
    return out


def best_offset(img, cx, cy, radius, ring_xs, ring_ys, candidates=None):
    """The candidate offset whose border best matches the stamp's border (least squared
    RGBA difference), with its whole patch inside the image; None if none fits."""
    h, w = img.shape[:2]
    r = max(1, int(radius)) + int(math.ceil(HEAL_RING_WIDTH))
    dst = img[ring_ys, ring_xs]
    best, best_err = None, None
    for ox, oy in candidates if candidates is not None else candidate_offsets(radius):
        sx, sy = cx + ox, cy + oy
        if sx - r < 0 or sy - r < 0 or sx + r >= w or sy + r >= h:
            continue
        src = img[ring_ys + oy, ring_xs + ox]
        err = float(((src - dst) ** 2).sum())
        if best_err is None or err < best_err:
            best, best_err = (ox, oy), err
    return best


# ---------------------------------------------------------------------------
# Particles
# ---------------------------------------------------------------------------

def scatter_2d(rng, cx, cy, radius, count, bounces, restitution=0.5):
    """Impacts of ``count`` particles dropped into the brush circle, each bouncing
    ``bounces`` times (image space, no mesh): ``[(x, y, energy), ...]``. Bounces lean
    downward (gravity) and get shorter by ``restitution``."""
    out = []
    r = max(1.0, float(radius))
    for _ in range(max(0, int(count))):
        a = rng.uniform(0.0, math.tau)
        d = r * math.sqrt(rng.uniform(0.0, 1.0))
        x, y = cx + math.cos(a) * d, cy + math.sin(a) * d
        energy = 1.0
        out.append((x, y, energy))
        hop = r * 0.9
        for _b in range(max(0, int(bounces))):
            energy *= restitution
            hop *= restitution + 0.25
            a = rng.uniform(-math.pi * 0.95, -math.pi * 0.05)   # mostly downward
            x += math.cos(a) * hop * rng.uniform(0.5, 1.0)
            y += math.sin(a) * hop * rng.uniform(0.5, 1.0)
            out.append((x, y, energy))
    return out


def chips(points, size, rng, w, h):
    """The pixels of small irregular dents at ``points`` (``(x, y, energy)``; ``size`` px
    radius at full energy, less after bounces): ``(xs, ys, weights)``, clipped to the
    image; overlapping dents keep the strongest weight."""
    xs_all, ys_all, w_all = [], [], []
    for x, y, energy in points:
        rr = max(0.0, float(size)) * (0.55 + 0.45 * math.sqrt(max(0.0, energy))) * rng.uniform(0.6, 1.25)
        reach = int(math.ceil(rr))
        oy, ox = np.mgrid[-reach:reach + 1, -reach:reach + 1]
        d = np.sqrt((ox * ox + oy * oy).astype(np.float32))
        rough = 0.7 + 0.6 * rng.uniform(0.0, 1.0, d.shape)
        inside = d <= rr * rough + 0.5
        px = (ox[inside] + int(round(x))).astype(np.int64)
        py = (oy[inside] + int(round(y))).astype(np.int64)
        wt = np.full(len(px), 0.35 + 0.65 * min(1.0, max(0.0, energy)) ** 0.5, dtype=np.float32)
        xs_all.append(px)
        ys_all.append(py)
        w_all.append(wt)
    if not xs_all:
        empty = np.zeros(0, dtype=np.int64)
        return empty, empty, np.zeros(0, dtype=np.float32)
    xs, ys, wts = np.concatenate(xs_all), np.concatenate(ys_all), np.concatenate(w_all)
    keep = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
    xs, ys, wts = xs[keep], ys[keep], wts[keep]
    if len(xs) == 0:
        return xs, ys, wts
    flat = ys * w + xs
    order = np.lexsort((-wts, flat))            # per pixel: the strongest first
    flat, wts = flat[order], wts[order]
    first = np.ones(len(flat), dtype=bool)
    first[1:] = flat[1:] != flat[:-1]
    flat, wts = flat[first], wts[first]
    return flat % w, flat // w, wts
