"""Pixel history integrated with Blender's global undo.

Writing ``image.pixels`` from Python creates no undo step, so strokes used to
live in a private stack that only the Pixel Painter tool could undo. After
switching tools, Ctrl+Z hit Blender's previous step (e.g. "New Image") instead.

How it works
------------
* :func:`begin` is called before an image is modified, :func:`commit` after.
* ``commit`` records the step (pixels before and after) under a unique
  *stamp*, writes the stamp into an ID property on the image and pushes a real
  Blender undo step (``ed.undo_push``), forced to be a global (memfile) step so
  the ID property is part of it.
* Blender's Ctrl+Z / Ctrl+Shift+Z restore that ID property. The undo/redo
  handlers see the stamp change and write the matching pixels back:

  - undo  (new stamp is an ancestor): put back the *before* pixels of every
    undone step, newest first, so native brush strokes made in between survive.
  - redo  (the old stamp is an ancestor): put back the *after* pixels of every
    redone step, oldest first.

A step stores only the bounding box of the pixels it changed (before and
after), not two copies of the whole image.

The stamp - not a step counter - identifies the state, so this stays correct
when Pixel Painter steps interleave with native brush strokes or other edits,
and it works no matter which tool is active.
"""

import itertools
import time
from dataclasses import dataclass
from typing import Optional

import bpy
import numpy as np
from bpy.app.handlers import persistent

from ..utils import pixel_io


STAMP_KEY = "pixel_painter_history"


@dataclass
class _Step:
    image_key: int
    prev: Optional[str]     # stamp that was current when the step began
    size: tuple             # (w, h) of the image
    region: tuple           # (y0, y1, x0, x1) end-exclusive box of the changed pixels
    before: np.ndarray      # (y1 - y0, x1 - x0, 4) pixels of the box before the step
    after: np.ndarray       # ... and after it


_session = f"{int(time.time() * 1000):x}"
_counter = itertools.count(1)

steps = {}        # stamp -> _Step (insertion ordered = age)
_applied = {}     # image key -> stamp whose pixels are currently in the buffer
_pending = {}     # image key -> (image name, pixels before the change)


def _key(img):
    return img.session_uid


def _pixels(img):
    arr = np.empty(len(img.pixels), dtype=np.float32)
    img.pixels.foreach_get(arr)
    return arr


def changed_region(before, after, w, h):
    """``(y0, y1, x0, x1)`` end-exclusive box of the pixels that differ between two
    flat RGBA buffers of a ``w`` x ``h`` image, or None when nothing changed."""
    changed = np.any((before != after).reshape(h, w, 4), axis=2)
    rows = np.flatnonzero(changed.any(axis=1))
    if len(rows) == 0:
        return None
    cols = np.flatnonzero(changed.any(axis=0))
    return int(rows[0]), int(rows[-1]) + 1, int(cols[0]), int(cols[-1]) + 1


def make_step(image_key, prev, before, after, w, h):
    """The :class:`_Step` from ``before`` to ``after`` (flat RGBA), or None (no change)."""
    region = changed_region(before, after, w, h)
    if region is None:
        return None
    y0, y1, x0, x1 = region
    box = (slice(y0, y1), slice(x0, x1))
    return _Step(image_key, prev, (w, h), region,
                 before.reshape(h, w, 4)[box].copy(), after.reshape(h, w, 4)[box].copy())


def _find_image(key, name=None):
    img = bpy.data.images.get(name) if name else None
    if img is not None and _key(img) == key:
        return img
    for img in bpy.data.images:
        if _key(img) == key:
            return img
    return None


def _max_steps():
    try:
        limit = int(bpy.context.preferences.edit.undo_steps)
    except Exception:
        limit = 32
    # Blender cannot undo further back than its own step limit.
    return max(16, limit + 4)


def _prune():
    limit = _max_steps()
    while len(steps) > limit:
        steps.pop(next(iter(steps)))


def _tag_redraw():
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type in {'IMAGE_EDITOR', 'VIEW_3D'}:
                    area.tag_redraw()
    except Exception:
        pass


_refresh_keys = set()
_REFRESH_PASSES = 3          # follow-up redraws after a change
_REFRESH_INTERVAL = 0.05     # seconds between them
_refresh_left = 0


def _refresh_now(keys):
    for img in bpy.data.images:
        if _key(img) in keys:
            try:
                img.update()
            except Exception:
                pass
    _tag_redraw()


def _flush_refresh():
    global _refresh_left
    _refresh_now(_refresh_keys)
    _refresh_left -= 1
    if _refresh_left > 0:
        return _REFRESH_INTERVAL
    _refresh_keys.clear()
    return None


def _refresh_display(img):
    """Make every editor show the new pixels of ``img``.

    The Image Editor uploads pixel changes one redraw late: with a single
    redraw (as after Ctrl+Z, when no modal keeps redrawing) it shows the
    previous state. Signal the change now and redraw a few more times.
    """
    global _refresh_left
    key = _key(img)
    _refresh_now({key})
    _refresh_keys.add(key)
    _refresh_left = _REFRESH_PASSES
    if not bpy.app.timers.is_registered(_flush_refresh):
        bpy.app.timers.register(_flush_refresh, first_interval=_REFRESH_INTERVAL)


# Context members the undo system reads to pick the step type. Blender asks
# every undo type's poll in turn and uses the first that accepts; memfile is
# the catch-all at the end. The image-paint type accepts when the editor is an
# Image Editor in Paint mode *or when the active object is in Texture Paint
# mode* (any editor) -- i.e. always while painting in the 3D Viewport. Its
# steps store no ID properties, so the stamp would never be restored. Hiding
# the editor and the active object makes every mode-based type decline.
_MEMFILE_OVERRIDES = (
    dict(area=None, region=None, active_object=None, object=None),
    dict(area=None, region=None),  # fallback if this build rejects None objects
)


def _push_undo(message):
    """Push a global (memfile) undo step (the only kind that stores ID properties)."""
    for override in _MEMFILE_OVERRIDES:
        try:
            with bpy.context.temp_override(**override):
                bpy.ops.ed.undo_push(message=message)
            return True
        except Exception:
            continue
    try:
        bpy.ops.ed.undo_push(message=message)
        return True
    except Exception:
        return False


def _chain(key, start, stop):
    """Steps from stamp ``start`` back to (excluding) stamp ``stop``, newest first, or
    None when ``stop`` is not an ancestor of ``start`` in the recorded steps."""
    chain = []
    stamp = start
    seen = set()
    while stamp and stamp not in seen:
        seen.add(stamp)
        step = steps.get(stamp)
        if step is None or step.image_key != key:
            return None
        chain.append(step)
        if step.prev == stop:
            return chain
        stamp = step.prev
    return None


def transition(key, old, new):
    """``[(step, use_after), ...]``: the boxes to write, in order, when the image's stamp
    changed from ``old`` to ``new``; None when the history does not connect them."""
    undone = _chain(key, old, new)       # undo: ``new`` is an ancestor of ``old``
    if undone is not None:
        return [(step, False) for step in undone]
    redone = _chain(key, new, old)       # redo: ``old`` is an ancestor of ``new``
    if redone is not None:
        return [(step, True) for step in reversed(redone)]
    step = steps.get(new) if new else None   # unknown history: at least ``new``'s own change
    return [(step, True)] if step is not None and step.image_key == key else None


def apply_transition(buf, w, h, plan):
    """Write the boxes of ``plan`` (see :func:`transition`) into the flat RGBA ``buf``.
    False (``buf`` untouched) when a step was recorded at another image size."""
    if any(step.size != (w, h) for step, _after in plan):
        return False
    view = buf.reshape(h, w, 4)
    for step, use_after in plan:
        y0, y1, x0, x1 = step.region
        view[y0:y1, x0:x1] = step.after if use_after else step.before
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def begin(img):
    """Call before modifying ``img``'s pixels."""
    if img is None:
        return
    key = _key(img)
    if key in _pending:
        return
    _applied.setdefault(key, img.get(STAMP_KEY))
    _pending[key] = (img.name, pixel_io.read(img))   # the stroke's working buffer when one runs


def commit(img, message="Pixel Paint", push=True):
    """Call after modifying ``img``. Records an undo step if pixels changed.

    ``push=False`` only records the step (for operators whose own ``UNDO``
    flag creates the Blender step). Returns True when a step was recorded.
    """
    if img is None:
        return False
    key = _key(img)
    pending = _pending.pop(key, None)
    if pending is None:
        return False
    before = pending[1]
    after = pixel_io.read(img)
    w, h = img.size
    if before.shape != after.shape or after.size != w * h * 4:
        return False  # resized meanwhile: no step to record
    prev = _applied.get(key)
    step = make_step(key, prev, before, after, w, h)
    if step is None:
        return False  # nothing changed (e.g. eyedropper click): no empty step

    stamp = f"{_session}:{next(_counter)}"
    try:
        img[STAMP_KEY] = stamp
    except Exception:
        return False  # linked / read-only image
    steps[stamp] = step
    _applied[key] = stamp
    _prune()
    if push:
        _push_undo(message)
    _refresh_display(img)
    return True


def commit_all(message="Pixel Paint"):
    """Commit every begun image (safety net, e.g. when the tool is switched)."""
    for key, (name, _before) in list(_pending.items()):
        img = _find_image(key, name)
        if img is None:
            _pending.pop(key, None)
            continue
        commit(img, message)


def has_pending():
    return bool(_pending)


def clear():
    steps.clear()
    _applied.clear()
    _pending.clear()


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

@persistent
def _on_undo_pre(*_args):
    # Uncommitted changes cannot become a step anymore; forget them.
    _pending.clear()
    pixel_io.invalidate()


@persistent
def _on_undo_redo_post(*_args):
    for img in bpy.data.images:
        key = _key(img)
        if key not in _applied:
            continue
        new = img.get(STAMP_KEY)
        old = _applied[key]
        if new == old:
            continue
        plan = transition(key, old, new)
        if plan:
            w, h = img.size
            pixels = _pixels(img)
            if pixels.size == w * h * 4 and apply_transition(pixels, w, h, plan):
                img.pixels.foreach_set(pixels)
                _refresh_display(img)
                pixel_io.invalidate()
        _applied[key] = new


@persistent
def _on_load_pre(*_args):
    clear()


_HANDLERS = (
    ('undo_pre', _on_undo_pre),
    ('redo_pre', _on_undo_pre),
    ('undo_post', _on_undo_redo_post),
    ('redo_post', _on_undo_redo_post),
    ('load_pre', _on_load_pre),
)


def register():
    unregister()
    for attr, fn in _HANDLERS:
        getattr(bpy.app.handlers, attr).append(fn)


def unregister():
    for attr, fn in _HANDLERS:
        handlers = getattr(bpy.app.handlers, attr)
        # Match by name too: a module reload creates new function objects.
        for h in list(handlers):
            if h is fn or (getattr(h, '__module__', None) == __name__ and h.__name__ == fn.__name__):
                handlers.remove(h)
