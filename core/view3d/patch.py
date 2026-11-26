"""Edge mode filters: :class:`EdgePatch` -- the surface around a stamp unfolded into a
small image (gather from the texture, filter, scatter back over the seams).
"""


import numpy as np

from .footprint import MAX_SUPERSAMPLE, footprint_box
from .frames import bary2d, find_triangle, unfold
from . import mesh


# ---- filter patches (Edge-mode Smooth / Smear) -------------------------------------

MAX_PATCH_TEXELS = 1 << 20


def _patch_samples(frame, x0, y0, pw, ph, w, h, tile, k, mask=None):
    """Map the ``k * k`` subsamples of the patch texels onto the image.

    The patch is the texel box ``x0, y0`` .. ``x0 + pw - 1, y0 + ph - 1`` of the
    frame (seed texture space). Seed-island triangles come first, then the
    unfolded neighbours in unfold order (nearest first); every subsample goes
    to the first triangle covering it. ``mask`` (pw * ph bools) limits the
    texels mapped. Works triangle by triangle on the subsample grid inside the
    triangle's box, so the cost follows the patch area, not texels x triangles.

    Returns ``(owner, target, on_island)`` arrays, one entry per covered
    subsample: patch flat index, flat image pixel index, from the seed island.
    """
    size = np.array((w, h), dtype=np.float64)
    tile = np.asarray(tile, dtype=np.float64)
    gw, gh = pw * k, ph * k
    claimed = np.zeros(gw * gh, dtype=bool)
    if mask is not None:
        grid = np.asarray(mask, dtype=bool).reshape(ph, pw)
        claimed |= ~np.repeat(np.repeat(grid, k, axis=0), k, axis=1).ravel()
    owners, targets, islands = [], [], []
    order = np.concatenate((np.nonzero(frame.identity)[0], np.nonzero(~frame.identity)[0]))
    for j in order:
        tri = frame.uv[j]
        tp = (tri - tile) * size                      # frame texel coords
        mn, mx = tp.min(axis=0), tp.max(axis=0)
        gx0 = max(0, int(np.ceil((mn[0] - x0) * k - 0.5)))
        gx1 = min(gw - 1, int(np.floor((mx[0] - x0) * k - 0.5)))
        gy0 = max(0, int(np.ceil((mn[1] - y0) * k - 0.5)))
        gy1 = min(gh - 1, int(np.floor((mx[1] - y0) * k - 0.5)))
        if gx0 > gx1 or gy0 > gy1:
            continue
        gx, gy = np.meshgrid(np.arange(gx0, gx1 + 1), np.arange(gy0, gy1 + 1))
        flat = (gy * gw + gx).ravel()
        flat = flat[~claimed[flat]]
        if not len(flat):
            continue
        sx, sy = flat % gw, flat // gw
        q = (np.stack((x0 + (sx + 0.5) / k, y0 + (sy + 0.5) / k), axis=1)) / size + tile
        bw = bary2d(np.broadcast_to(tri, (len(q), 3, 2)), q)
        inside = np.all(bw >= -1e-9, axis=1)
        if not inside.any():
            continue
        flat, sx, sy, bw = flat[inside], sx[inside], sy[inside], bw[inside]
        claimed[flat] = True
        uv = bw @ frame.actual[j]
        t = np.floor((uv % 1.0) * size).astype(np.int64)
        tx = np.minimum(t[:, 0], w - 1)
        ty = np.minimum(t[:, 1], h - 1)
        owners.append((sy // k) * pw + sx // k)
        targets.append(ty * w + tx)
        islands.append(np.full(len(flat), bool(frame.identity[j])))
    if not owners:
        empty = np.zeros(0, dtype=np.int64)
        return empty, empty, np.zeros(0, dtype=bool)
    return np.concatenate(owners), np.concatenate(targets), np.concatenate(islands)


def _area2(tri):
    """Twice the area of 2D triangle ``tri`` (3, 2)."""
    (ax, ay), (bx, by), (cx, cy) = tri
    return abs((bx - ax) * (cy - ay) - (by - ay) * (cx - ax))


def _supersample(frame):
    """Subsamples per texel side so no neighbour with a higher texel density gets holes."""
    k = 1
    for j in np.nonzero(~frame.identity)[0]:
        a_placed = _area2(frame.uv[j])
        a_actual = _area2(frame.actual[j])
        if a_placed >= 1e-18:
            k = max(k, int(min(MAX_SUPERSAMPLE, np.ceil(np.sqrt(a_actual / a_placed)))))
    return k


class EdgePatch:
    """The texels around one Edge-mode stamp, laid out in the stamp's texture space.

    Smooth and Smear read neighbouring pixels, which in texture space would
    pull in whatever lies beside the UV island. A patch unfolds the surface
    around the stamp (like :func:`edge_expand`), so a filter runs on the
    surface: gather the patch from the image, filter it, scatter the result.

    ``x0, y0`` / ``pw, ph``: the patch box in the seed's texel coords (it may
    leave the image). Per patch texel (flat ``ly * pw + lx``):

    * ``source``: flat image pixel it reads from (-1 = none);
    * ``valid``: it lies on the surface (seed island or an unfolded
      neighbour) -- the only texels a filter may sample;
    * texels off every triangle but next to the seed island read and write
      in place (they straddle the seam, see :func:`expand_footprint`) without
      being sampled.
    """

    def __init__(self, frame, x0, y0, pw, ph, w, h, tile, source, valid):
        self.frame = frame
        self.x0, self.y0, self.pw, self.ph = x0, y0, pw, ph
        self.w, self.h = w, h
        self.tile = tile
        self.source = source
        self.valid = valid

    def flat(self, pixels):
        """Patch flat indices of image-texel ``pixels`` (they must lie in the patch box)."""
        pix = np.asarray(pixels, dtype=np.int64).reshape(-1, 2)
        return (pix[:, 1] - self.y0) * self.pw + (pix[:, 0] - self.x0)

    def local(self, flat):
        """``(N, 2)`` patch coords of flat indices."""
        flat = np.asarray(flat, dtype=np.int64)
        return np.stack((flat % self.pw, flat // self.pw), axis=1)

    def gather(self, arr):
        """The patch as a flat float32 RGBA buffer read from image buffer ``arr``."""
        out = np.zeros((self.pw * self.ph, 4), dtype=np.float32)
        has = self.source >= 0
        out[has] = np.asarray(arr).reshape(-1, 4)[self.source[has]]
        return out.reshape(-1)

    def scatter(self, flat):
        """Where patch texels ``flat`` are written: ``(index into flat, flat image pixel)``.

        Supersampled, so neighbours with a higher texel density get no holes.
        """
        flat = np.asarray(flat, dtype=np.int64)
        if not len(flat):
            empty = np.zeros(0, dtype=np.int64)
            return empty, empty
        mask = np.zeros(self.pw * self.ph, dtype=bool)
        mask[flat] = True
        owner, target, _ = _patch_samples(self.frame, self.x0, self.y0, self.pw, self.ph,
                                          self.w, self.h, self.tile, _supersample(self.frame), mask)
        border = flat[(self.source[flat] >= 0) & ~self.valid[flat]]
        owner = np.concatenate((owner, border))
        target = np.concatenate((target, self.source[border]))
        pairs = np.unique(owner * (self.w * self.h) + target)
        owner, target = pairs // (self.w * self.h), pairs % (self.w * self.h)
        position = np.full(self.pw * self.ph, -1, dtype=np.int64)
        position[flat] = np.arange(len(flat))
        return position[owner], target

    def locate(self, x, y):
        """Patch coords (float) of image texel ``(x, y)`` on the unfolded surface, or None."""
        frame = self.frame
        if not len(frame):
            return None
        size = np.array((self.w, self.h), dtype=np.float64)
        tile = np.asarray(self.tile, dtype=np.float64)
        q = (np.array((x, y), dtype=np.float64) + 0.5) / size + tile
        bw = bary2d(frame.actual, np.broadcast_to(q, (len(frame), 2)))
        inside = np.all(bw >= -1e-6, axis=1)
        if not inside.any():
            return None
        # the seed island first, then the nearest unfolded neighbour
        hits = np.nonzero(inside & frame.identity)[0]
        j = int(hits[0] if len(hits) else np.nonzero(inside)[0][0])
        p = (bw[j] @ frame.uv[j] - tile) * size - 0.5
        return float(p[0] - self.x0), float(p[1] - self.y0)


def edge_patch(context, img, cx, cy, pixels, pad, tile, prefer_tri=None):
    """:class:`EdgePatch` around the stamp ``pixels`` centred on texel ``(cx, cy)``,
    padded by ``pad`` texels; None without a mesh / seed triangle or when too large."""
    pixels = list(pixels)
    w, h = img.size
    if not pixels or w == 0 or h == 0:
        return None
    cache = mesh.mesh_cache(context)
    if cache is None:
        return None
    center_uv = ((cx + 0.5) / w + tile[0], (cy + 0.5) / h + tile[1])
    seed = find_triangle(cache, center_uv, prefer=prefer_tri)
    if seed is None:
        return None
    pix = np.asarray(pixels, dtype=np.int64).reshape(-1, 2)
    pad = max(0, int(np.ceil(pad)))
    x0, y0 = (int(v) - pad for v in pix.min(axis=0))
    x1, y1 = (int(v) + pad for v in pix.max(axis=0))
    pw, ph = x1 - x0 + 1, y1 - y0 + 1
    if pw * ph > MAX_PATCH_TEXELS:
        return None
    lo, hi = footprint_box(((x0, y0), (x1, y1)), w, h, tile)
    frame = unfold(cache, seed, lo, hi)

    owner, target, on_island = _patch_samples(frame, x0, y0, pw, ph, w, h, tile, 1)
    source = np.full(pw * ph, -1, dtype=np.int64)
    source[owner] = target
    valid = source >= 0
    island = np.zeros(pw * ph, dtype=bool)
    island[owner[on_island]] = True

    # texels off every triangle that border the seed island: in place, never sampled
    grid = np.pad(island.reshape(ph, pw), 1)
    near = np.zeros((ph, pw), dtype=bool)
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            near |= grid[dy:dy + ph, dx:dx + pw]
    border = np.nonzero(near.ravel() & ~valid)[0]
    bx = (x0 + border % pw) % w
    by = (y0 + border // pw) % h
    source[border] = by * w + bx
    return EdgePatch(frame, x0, y0, pw, ph, w, h, tile, source, valid)
