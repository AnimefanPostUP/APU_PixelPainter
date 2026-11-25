"""Image pixel access for every pixel-writing path (Python and C# backends alike).

``Image.pixels`` copies the whole image on every access: ``np.array(img.pixels)``
even walks it element by element in Python, and one ``img.pixels[i]`` copies the
whole buffer too. This module:

* reads with ``foreach_get`` (one C-level copy);
* keeps a **working buffer** for the image being stroked
  (:func:`begin_stroke` / :func:`end_stroke`), so a stroke reads the image from
  Blender once instead of on every draw step;
* **defers** writes inside :func:`deferred` (one draw step: tool + paint mask),
  so a step uploads the image once.

Rules for callers:

* :func:`read` returns a private copy (safe to keep, e.g. a back buffer).
* :func:`buffer` returns the working buffer itself (or a fresh read when no
  stroke runs) for in-place edits -- always finish with :func:`write`.
* Any other code that writes ``img.pixels`` directly must call
  :func:`invalidate` (the undo handlers do).
"""

from contextlib import contextmanager

import numpy as np


class _Session:
    __slots__ = ('key', 'size', 'img', 'arr', 'dirty')

    def __init__(self, img, arr):
        self.key = _key(img)
        self.size = tuple(img.size)
        self.img = img
        self.arr = arr
        self.dirty = False


_session = None
_defer_depth = 0


def _key(img):
    try:
        return img.session_uid
    except Exception:
        return id(img)


def _fetch(img):
    w, h = img.size
    arr = np.empty(w * h * 4, dtype=np.float32)
    if arr.size:
        img.pixels.foreach_get(arr)
    return arr


def _match(img):
    s = _session
    if s is None or img is None:
        return None
    try:
        if s.key != _key(img) or s.size != tuple(img.size):
            return None
    except Exception:
        return None
    return s


def _tag_redraw():
    try:
        import bpy
        for screen in bpy.data.screens:
            for area in screen.areas:
                if area.type in {'VIEW_3D', 'IMAGE_EDITOR'}:
                    area.tag_redraw()
    except Exception:
        pass


def _upload(img, arr):
    img.pixels.foreach_set(arr)
    img.update()
    _tag_redraw()


# ---------------------------------------------------------------------------
# Reading / writing
# ---------------------------------------------------------------------------

def read(img):
    """The image's pixels as a new flat float32 array (a private copy)."""
    s = _match(img)
    return s.arr.copy() if s is not None else _fetch(img)


def buffer(img):
    """Flat float32 pixels to edit in place, then pass to :func:`write`.

    During a stroke this is the working buffer itself (no copy)."""
    s = _match(img)
    return s.arr if s is not None else _fetch(img)


def pixel(img, x, y):
    """``(r, g, b, a)`` of one pixel, or None outside the image."""
    w, h = img.size
    if not (0 <= x < w and 0 <= y < h):
        return None
    arr = buffer(img)
    i = (y * w + x) * 4
    return tuple(float(v) for v in arr[i:i + 4])


def write(img, arr):
    """Store ``arr`` as the image's pixels (uploaded now, or when the deferred step ends)."""
    arr = np.ascontiguousarray(arr, dtype=np.float32).reshape(-1)
    s = _match(img)
    if s is not None:
        s.arr = arr
        if _defer_depth > 0:
            s.dirty = True
            return
        s.dirty = False
    _upload(img, arr)


@contextmanager
def deferred(img=None):
    """Collect writes to the stroked image and upload them once at the end."""
    global _defer_depth
    _defer_depth += 1
    try:
        yield
    finally:
        _defer_depth -= 1
        if _defer_depth == 0:
            flush()


def flush():
    """Upload a pending deferred write."""
    s = _session
    if s is not None and s.dirty:
        s.dirty = False
        try:
            _upload(s.img, s.arr)
        except Exception:
            pass   # image removed meanwhile


# ---------------------------------------------------------------------------
# Stroke session
# ---------------------------------------------------------------------------

def begin_stroke(img):
    """Keep ``img``'s pixels as the working buffer until :func:`end_stroke`."""
    global _session
    flush()
    _session = _Session(img, _fetch(img)) if img is not None else None


def end_stroke():
    global _session
    flush()
    _session = None


def invalidate():
    """Forget the working buffer without writing it (the image changed elsewhere)."""
    global _session
    _session = None


def in_stroke(img=None):
    return _session is not None if img is None else _match(img) is not None
