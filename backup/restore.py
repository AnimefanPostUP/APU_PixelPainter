"""Restore textures from a backup save (``backup/store.py``) into the project.

* An image with the saved name and size exists (and *as copy* is off): its pixels
  are replaced -- one Pixel Painter undo step, so Ctrl+Z brings the current pixels
  back.
* Otherwise a new image gets the pixels: the saved name, or
  ``<name> (backup <time>)`` when that name is taken.

The restored image has unsaved changes; save it as usual.
"""

import time

import bpy
import numpy as np

from .service import PIXEL_TYPES, SERVICE


def _copy_name(name, save):
    stamp = time.strftime("%m-%d %H:%M", time.localtime(float(save.get('timestamp', time.time()))))
    return f"{name} (backup {stamp})"


def _new_image(name, entry, arr):
    w, h = int(entry['width']), int(entry['height'])
    img = bpy.data.images.new(name, w, h, alpha=True, float_buffer=bool(entry.get('is_float', False)))
    for attr, value in ((('colorspace_settings', 'name'), entry.get('colorspace')),
                        (('alpha_mode',), entry.get('alpha_mode'))):
        if not value:
            continue
        try:
            target = img
            for part in attr[:-1]:
                target = getattr(target, part)
            setattr(target, attr[-1], value)
        except Exception:
            pass
    img.pixels.foreach_set(arr)
    img.update()
    return img


def _replace(img, arr, history, pixel_io):
    history.begin(img)
    pixel_io.write(img, arr)
    history.commit(img, "Restore Backup", push=False)
    try:
        img.update()
    except Exception:
        pass


def restore(save_id, image_name="", as_copy=False):
    """Restore one image (``image_name``) or every image of the save. Returns
    ``(restored images, error messages)``."""
    from ..core import history
    from ..utils import pixel_io
    store = SERVICE.store()
    save = store.find(save_id)
    if save is None:
        return [], [f"Backup {save_id} not found"]
    restored, errors = [], []
    for entry in save.get('images', []):
        name = entry.get('name', '')
        if image_name and name != image_name:
            continue
        try:
            if entry.get('dtype', 'float32') != 'float32' or int(entry.get('channels', 4)) != 4:
                raise ValueError("unknown pixel format")
            arr = np.frombuffer(store.read_pixels(save_id, entry), dtype=np.float32).copy()
            w, h = int(entry['width']), int(entry['height'])
            if arr.size != w * h * 4:
                raise ValueError(f"{arr.size} values for {w} x {h}")
            img = bpy.data.images.get(name)
            if not as_copy and img is not None and img.type in PIXEL_TYPES and tuple(img.size) == (w, h):
                _replace(img, arr, history, pixel_io)
            else:
                img = _new_image(name if img is None else _copy_name(name, save), entry, arr)
            restored.append(img)
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    pixel_io.invalidate()
    return restored, errors
