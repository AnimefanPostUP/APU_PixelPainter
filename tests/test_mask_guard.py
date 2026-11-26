"""Unit tests for the paint mask guard (tools/mask/guard.py, numpy + pixel_io).

    python -m unittest discover -s tests -v
"""

import importlib
import os
import sys
import types
import unittest

import numpy as np

_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PACKAGE = os.path.basename(_ADDON_DIR)
sys.path.insert(0, os.path.dirname(_ADDON_DIR))
sys.modules.setdefault('bpy', types.ModuleType('bpy'))  # the package __init__ imports bpy

guard_mod = importlib.import_module(f'{_PACKAGE}.tools.mask.guard')
pixel_io = importlib.import_module(f'{_PACKAGE}.utils.pixel_io')
native = importlib.import_module(f'{_PACKAGE}.utils.native')


class FakePixels:
    def __init__(self, arr):
        self.arr = arr

    def foreach_get(self, out):
        out[:] = self.arr

    def foreach_set(self, values):
        self.arr = np.array(values, dtype=np.float32).copy()


class FakeImage:
    _uid = 0

    def __init__(self, w, h, rng):
        FakeImage._uid += 1
        self.session_uid = FakeImage._uid
        self.size = (w, h)
        self.pixels = FakePixels(rng.random(w * h * 4).astype(np.float32))

    def update(self):
        pass

    @property
    def arr(self):
        return self.pixels.arr


def paint_rect(img, x0, y0, x1, y1, value):
    """A draw step: writes ``value`` into a rectangle of the working buffer."""
    w, h = img.size
    buf = pixel_io.buffer(img)
    buf.reshape(h, w, 4)[y0:y1, x0:x1] = value
    pixel_io.write(img, buf)


class MaskGuardTest(unittest.TestCase):
    def setUp(self):
        native.set_override(False)
        self.rng = np.random.default_rng(3)
        self.img = FakeImage(32, 24, self.rng)
        self.original = self.img.arr.copy()
        w, h = self.img.size
        allowed = np.zeros((h, w), dtype=bool)
        allowed[:, :16] = True          # left half paintable, right half protected
        self.allowed = allowed.reshape(-1)
        self.guard = guard_mod.StrokeMaskGuard()

    def tearDown(self):
        pixel_io.end_stroke()
        native.set_override(None)

    def step(self, rect, region, value=0.25):
        with pixel_io.deferred(self.img):
            self.guard.before_step(self.img)
            paint_rect(self.img, *rect, value)
            self.guard.after_step(self.img, self.allowed, region)

    def assert_protected_unchanged(self):
        w, h = self.img.size
        a = self.img.arr.reshape(h, w, 4)
        o = self.original.reshape(h, w, 4)
        np.testing.assert_array_equal(a[:, 16:], o[:, 16:])

    def test_region_restore_in_stroke(self):
        pixel_io.begin_stroke(self.img)
        self.step((10, 4, 22, 12), (10, 4, 22, 12))
        self.step((12, 8, 26, 20), (12, 8, 26, 20), value=0.75)
        self.assert_protected_unchanged()
        w, h = self.img.size
        self.assertTrue(np.all(self.img.arr.reshape(h, w, 4)[8:20, 12:16] == 0.75))

    def test_full_restore(self):
        pixel_io.begin_stroke(self.img)
        self.step((0, 0, 32, 24), None)
        self.assert_protected_unchanged()

    def test_without_stroke_session(self):
        self.step((8, 0, 30, 10), (8, 0, 30, 10))
        self.assert_protected_unchanged()

    def test_reference_is_kept_for_the_stroke(self):
        """A step rewriting earlier stamps from a stroke-start copy (Pixel spacing)
        is covered by the union of the regions."""
        pixel_io.begin_stroke(self.img)
        self.step((14, 2, 20, 6), (14, 2, 20, 6))
        first = guard_mod.union((14, 2, 20, 6), (14, 14, 20, 18))
        self.step((14, 2, 20, 6), first)          # earlier stamp rewritten + new one
        self.step((14, 14, 20, 18), first)
        self.assert_protected_unchanged()

    def test_new_stroke_new_reference(self):
        pixel_io.begin_stroke(self.img)
        self.step((0, 0, 8, 8), (0, 0, 8, 8))
        pixel_io.end_stroke()
        # the image changes between strokes (e.g. undo): the next stroke must not
        # restore the previous stroke's pixels
        self.img.pixels.arr = self.rng.random(self.img.arr.size).astype(np.float32)
        self.original = self.img.arr.copy()
        pixel_io.begin_stroke(self.img)
        self.step((10, 10, 30, 20), (10, 10, 30, 20))
        self.assert_protected_unchanged()

    def test_clip_and_bounds(self):
        self.assertEqual(guard_mod.clip_region((-5, -5, 3, 4), (10, 10)), (0, 0, 3, 4))
        self.assertEqual(guard_mod.clip_region((20, 20, 30, 30), (10, 10)), ())
        self.assertIsNone(guard_mod.clip_region(None, (10, 10)))
        self.assertEqual(guard_mod.bounds_of([(3, 4), (6, 1)], 2), (1, -1, 9, 7))
        self.assertIsNone(guard_mod.bounds_of([], 2))


if __name__ == '__main__':
    unittest.main()
