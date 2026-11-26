"""Paint mask enforcement for one stroke (pure: numpy + pixel_io, no bpy).

Protected pixels (``allowed`` False) must never change during a stroke. Taking a
full copy of the image before every draw step and comparing all of it afterwards
costs two image-sized passes per step (about 256 MB at 4K). Instead,
:class:`StrokeMaskGuard`:

* copies the image **once per stroke** (the first masked step). Every step puts the
  protected pixels back, so throughout the stroke they keep their stroke-start
  value -- that copy stays the reference for the whole stroke;
* after a step, restores protected pixels only inside the **region** the step can
  have written (``(x0, y0, x1, y1)``, end-exclusive; see
  ``StrokeTool.step_region``). ``None`` = the whole image (Edge mode, where stamps
  are carried over seams to anywhere in the texture).

Outside a stroke session (``pixel_io.in_stroke``) there is nothing to keep a
reference for: every step is guarded with its own copy, like before.
"""

import numpy as np

from ...utils import native, pixel_io


def clip_region(region, size):
    """``region`` clipped to the image; ``None`` stays ``None``; empty -> ``()``."""
    if region is None:
        return None
    w, h = size
    x0, y0, x1, y1 = region
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(w, int(x1)), min(h, int(y1))
    if x0 >= x1 or y0 >= y1:
        return ()
    return x0, y0, x1, y1


def bounds_of(points, pad):
    """End-exclusive ``(x0, y0, x1, y1)`` around ``points`` grown by ``pad``, or None."""
    points = list(points)
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    pad = int(pad)
    return min(xs) - pad, min(ys) - pad, max(xs) + pad + 1, max(ys) + pad + 1


def union(a, b):
    """Bounding box of two end-exclusive regions."""
    return min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])


def restore_region(buf, reference, allowed, size, region):
    """Copy protected pixels of ``reference`` into ``buf`` inside ``region``.

    Returns True when ``buf`` changed. ``region`` must be clipped (not None)."""
    if not region:
        return False
    w, h = size
    x0, y0, x1, y1 = region
    blocked = ~allowed.reshape(h, w)[y0:y1, x0:x1]
    if not blocked.any():
        return False
    dst = buf.reshape(h, w, 4)[y0:y1, x0:x1]
    src = reference.reshape(h, w, 4)[y0:y1, x0:x1]
    changed = blocked & np.any(dst != src, axis=2)
    if not changed.any():
        return False
    dst[changed] = src[changed]
    return True


def restore_all(buf, reference, allowed):
    """Whole-image restore (C# when enabled). Returns True when ``buf`` changed."""
    if native.enabled():
        restored = native.restore_blocked(buf, reference, allowed)
        if restored is not None:
            return bool(restored)
    a4, b4 = buf.reshape(-1, 4), reference.reshape(-1, 4)
    changed = ~allowed & np.any(a4 != b4, axis=1)
    if not changed.any():
        return False
    a4[changed] = b4[changed]
    return True


class StrokeMaskGuard:
    """Keeps protected pixels unchanged over the draw steps of a stroke."""

    def __init__(self):
        self._stroke = None      # pixel_io stroke session the reference belongs to
        self._reference = None   # flat float32 pixels at the first guarded step

    def reset(self):
        self._stroke = None
        self._reference = None

    def before_step(self, img):
        """Call before a guarded draw step: takes the reference when needed."""
        stroke = pixel_io.stroke_token(img)
        if stroke is None:
            self._stroke = None
            self._reference = pixel_io.read(img)   # no stroke: per-step copy
        elif stroke != self._stroke or self._reference is None \
                or self._reference.size != img.size[0] * img.size[1] * 4:
            self._stroke = stroke
            self._reference = pixel_io.read(img)

    def after_step(self, img, allowed, region):
        """Put back protected pixels the step changed (inside ``region``)."""
        reference = self._reference
        if reference is None or allowed is None or len(reference) != len(allowed) * 4:
            return
        size = tuple(img.size)
        region = clip_region(region, size)
        buf = pixel_io.buffer(img)
        if region is None:
            changed = restore_all(buf, reference, allowed)
        else:
            changed = restore_region(buf, reference, allowed, size, region)
        if changed:
            pixel_io.write(img, buf)
        if self._stroke is None:
            self._reference = None


GUARD = StrokeMaskGuard()
