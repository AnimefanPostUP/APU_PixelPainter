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

  - undo  (new stamp is an ancestor): restore the *before* pixels of the
    oldest undone step, so native brush strokes made in between survive.
  - redo  (any other change): restore the *after* pixels of the new stamp.

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


STAMP_KEY = "pixel_painter_history"


@dataclass
class _Step:
    image_key: int
    prev: Optional[str]     # stamp that was current when the step began
    before: np.ndarray
    after: np.ndarray


_session = f"{int(time.time() * 1000):x}"
_counter = itertools.count(1)

_steps = {}       # stamp -> _Step (insertion ordered = age)
_applied = {}     # image key -> stamp whose pixels are currently in the buffer
_pending = {}     # image key -> (image name, pixels before the change)


def _key(img):
    return img.session_uid


def _pixels(img):
    arr = np.empty(len(img.pixels), dtype=np.float32)
    img.pixels.foreach_get(arr)
    return arr


def _same(a, b):
    return a is not None and b is not None and a.shape == b.shape and np.array_equal(a, b)


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
        steps = int(bpy.context.preferences.edit.undo_steps)
    except Exception:
        steps = 32
    # Blender cannot undo further back than its own step limit.
    return max(16, steps + 4)


def _prune():
    limit = _max_steps()
    while len(_steps) > limit:
        _steps.pop(next(iter(_steps)))


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


def _push_undo(message):
    """Push a global (memfile) undo step.

    In the Image Editor's paint mode a plain ``ed.undo_push`` would create an
    image-paint step, which does not store ID properties, so clear the context
    members the undo system uses to pick that step type.
    """
    try:
        with bpy.context.temp_override(area=None, region=None):
            bpy.ops.ed.undo_push(message=message)
        return True
    except Exception:
        pass
    try:
        bpy.ops.ed.undo_push(message=message)
        return True
    except Exception:
        return False


def _pixels_for_transition(key, old, new):
    """Pixels to show after the image's stamp changed from ``old`` to ``new``."""
    # Undo: walk back from the old stamp; if we reach ``new``, show the state
    # right before the oldest undone step.
    stamp = old
    seen = set()
    while stamp and stamp not in seen:
        seen.add(stamp)
        step = _steps.get(stamp)
        if step is None or step.image_key != key:
            break
        if step.prev == new:
            return step.before
        stamp = step.prev
    # Redo (or unknown history): show the state right after ``new``.
    step = _steps.get(new) if new else None
    return step.after if step is not None else None


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
    _pending[key] = (img.name, _pixels(img))


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
    after = _pixels(img)
    if _same(before, after):
        return False  # nothing changed (e.g. eyedropper click): no empty step

    prev = _applied.get(key)
    prev_step = _steps.get(prev) if prev else None
    if prev_step is not None and _same(prev_step.after, before):
        before = prev_step.after  # share memory when nothing happened in between

    stamp = f"{_session}:{next(_counter)}"
    try:
        img[STAMP_KEY] = stamp
    except Exception:
        return False  # linked / read-only image
    _steps[stamp] = _Step(key, prev, before, after)
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
    _steps.clear()
    _applied.clear()
    _pending.clear()


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

@persistent
def _on_undo_pre(*_args):
    # Uncommitted changes cannot become a step anymore; forget them.
    _pending.clear()


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
        pixels = _pixels_for_transition(key, old, new)
        if pixels is not None and pixels.size == len(img.pixels):
            img.pixels.foreach_set(pixels)
            _refresh_display(img)
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
