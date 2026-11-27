"""Unit tests for the special brushes' pixel kernels (paint/special.py) and their place
in the tool registry (group 'SPECIAL': Brushes window only).

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

special = importlib.import_module(f'{_PACKAGE}.paint.special')
brushes_actions = importlib.import_module(f'{_PACKAGE}.tools.pen.actions.brushes')


def _image(w, h, rgba=(0.5, 0.5, 0.5, 1.0)):
    img = np.empty((h, w, 4), dtype=np.float32)
    img[:] = rgba
    return img


class FootprintTest(unittest.TestCase):
    def test_disk_weights_fall_off(self):
        xs, ys, wts, d = special.disk(10, 10, 4)
        self.assertEqual(wts[np.argmin(d)], 1.0)
        self.assertLess(wts[np.argmax(d)], 0.05)
        self.assertTrue(np.all(d <= 4.0 + 1e-6))

    def test_disk_clipped(self):
        xs, ys, _w, _d = special.disk(0, 0, 3, w=5, h=5)
        self.assertTrue(np.all(xs >= 0) and np.all(ys >= 0))

    def test_stamps_keep_the_strongest(self):
        xs, ys, wts = special.stamps([(5, 5), (6, 5)], 3, special.smooth_lut(), 20, 20)
        flat = list(zip(xs.tolist(), ys.tolist()))
        self.assertEqual(len(flat), len(set(flat)))          # no duplicates
        self.assertEqual(wts[flat.index((5, 5))], 1.0)
        self.assertEqual(wts[flat.index((6, 5))], 1.0)

    def test_spaced(self):
        kept, last = special.spaced([(0, 0), (1, 0), (2, 0), (3, 0), (4, 0)], None, 2.0)
        self.assertEqual(kept, [(0, 0), (2, 0), (4, 0)])
        self.assertEqual(last, (4, 0))
        kept, _ = special.spaced([(5, 0)], last, 2.0)
        self.assertEqual(kept, [])


class RustTest(unittest.TestCase):
    def test_deterministic_and_in_range(self):
        xs, ys = np.meshgrid(np.arange(64), np.arange(64))
        t1, p1 = special.rust_texels(xs.ravel(), ys.ravel(), 8, 0.5, seed=3)
        t2, p2 = special.rust_texels(xs.ravel(), ys.ravel(), 8, 0.5, seed=3)
        np.testing.assert_array_equal(t1, t2)
        np.testing.assert_array_equal(p1, p2)
        self.assertTrue(np.all((t1 >= 0) & (t1 <= 1)))
        self.assertGreater(t1.std(), 0.1)                  # really mixes both colors

    def test_coverage(self):
        xs, ys = np.meshgrid(np.arange(64), np.arange(64))
        xs, ys = xs.ravel(), ys.ravel()
        _t, full = special.rust_texels(xs, ys, 8, 1.0)
        _t, none = special.rust_texels(xs, ys, 8, 0.0)
        _t, half = special.rust_texels(xs, ys, 8, 0.5)
        self.assertTrue(np.all(full == 1.0))
        self.assertTrue(np.all(none == 0.0))
        self.assertTrue(0.15 < half.mean() < 0.85)        # patchy


class NoiseBlurTest(unittest.TestCase):
    def test_flat_image_stays_flat(self):
        img = _image(16, 16, (0.2, 0.4, 0.6, 1.0))
        xs, ys, _w, _d = special.disk(8, 8, 4, w=16, h=16)
        out = special.noise_blur(img, xs, ys, 3, 0.5, np.random.default_rng(1))
        np.testing.assert_allclose(out, np.broadcast_to((0.2, 0.4, 0.6, 1.0), out.shape), atol=1e-6)

    def test_scatters_neighbours_in(self):
        img = _image(16, 16, (0.0, 0.0, 0.0, 1.0))
        img[:, 8:] = (1.0, 1.0, 1.0, 1.0)                   # a hard edge
        xs = np.array([7] * 200)
        ys = np.array([8] * 200)
        out = special.noise_blur(img, xs, ys, 3, 1.0, np.random.default_rng(2))
        self.assertTrue(0.0 < out[:, 0].mean() < 1.0)

    def test_samples(self):
        self.assertEqual(special.noise_samples(1.0), 1)
        self.assertEqual(special.noise_samples(0.0), 8)


class PullTest(unittest.TestCase):
    def test_pixel_moves_with_the_drag(self):
        w = h = 32
        img = _image(w, h, (0.0, 0.0, 0.0, 1.0))
        img[16, 16] = (1.0, 0.0, 0.0, 1.0)
        field = np.zeros((h, w, 2), dtype=np.float32)
        lut = np.ones(special.FALLOFF_SAMPLES, dtype=np.float32)   # constant: rigid move
        for x in range(16, 20):                                    # drag 4 px to the right
            special.pull_field_step(field, x, 16, 1, 0, 6, lut=lut)
        xs, ys, rgba = special.warp(img, field, (0, 0, w, h))
        out = np.zeros_like(img)
        out[ys, xs] = rgba
        self.assertEqual(out[16, 20, 0], 1.0)
        self.assertEqual(out[16, 16, 0], 0.0)

    def test_nearest_keeps_colors(self):
        w = h = 16
        img = np.random.default_rng(0).uniform(0, 1, (h, w, 4)).astype(np.float32)
        field = np.zeros((h, w, 2), dtype=np.float32)
        special.pull_field_step(field, 8, 8, 1.3, 0.7, 5)
        _xs, _ys, rgba = special.warp(img, field, (0, 0, w, h))
        palette = {tuple(c) for c in img.reshape(-1, 4).tolist()}
        self.assertTrue(all(tuple(c) in palette for c in rgba.tolist()))   # no new colors

    def _ring_image(self, w=48, h=48, r=8):
        img = _image(w, h, (0.0, 0.0, 0.0, 1.0))
        yy, xx = np.mgrid[0:h, 0:w]
        img[np.abs(np.hypot(xx - 24, yy - 24) - r) < 0.75] = (1.0, 0.0, 0.0, 1.0)   # a red circle
        return img

    def _red_radius(self, img, field):
        xs, ys, rgba = special.warp(img, field, (0, 0, img.shape[1], img.shape[0]))
        red = rgba[:, 0] > 0.5
        return np.hypot(xs[red] - 24, ys[red] - 24).mean()

    def test_pinch_sucks_toward_the_center(self):
        img = self._ring_image()
        field = np.zeros((48, 48, 2), dtype=np.float32)
        for _ in range(4):
            special.pinch_field_step(field, 24, 24, 16)
        self.assertLess(self._red_radius(img, field), 7.0)

    def test_push_moves_away_from_the_center(self):
        img = self._ring_image()
        field = np.zeros((48, 48, 2), dtype=np.float32)
        for _ in range(4):
            special.pinch_field_step(field, 24, 24, 16, outward=True)
        self.assertGreater(self._red_radius(img, field), 9.0)

    def test_pinch_keeps_the_center_pixel(self):
        field = np.zeros((32, 32, 2), dtype=np.float32)
        special.pinch_field_step(field, 16, 16, 8)
        np.testing.assert_allclose(field[16, 16], (0.0, 0.0), atol=1e-6)


class HealTest(unittest.TestCase):
    def test_matches_the_border(self):
        # Source: a bright texture; destination border: darker. The healed patch keeps
        # the texture but takes the destination's brightness.
        rng = np.random.default_rng(4)
        n, m = 30, 40
        texture = rng.uniform(-0.05, 0.05, (n, 1)).astype(np.float32)
        src_inner = np.concatenate([0.8 + texture] * 3 + [np.ones((n, 1), np.float32)], axis=1)
        src_ring = np.full((m, 4), 0.8, dtype=np.float32)
        src_ring[:, 3] = 1.0
        dst_ring = np.full((m, 4), 0.3, dtype=np.float32)
        dst_ring[:, 3] = 1.0
        inner = rng.uniform(-3, 3, (n, 2))
        ang = np.linspace(0, 2 * np.pi, m, endpoint=False)
        ring = np.stack((np.cos(ang) * 5, np.sin(ang) * 5), axis=1)
        out = special.heal(src_inner, src_ring, dst_ring, inner, ring, 1.0)
        np.testing.assert_allclose(out[:, 0], 0.3 + texture[:, 0], atol=1e-5)
        flat = special.heal(src_inner, src_ring, dst_ring, inner, ring, 0.0)
        np.testing.assert_allclose(flat[:, 0], 0.3, atol=1e-5)

    def test_best_offset_finds_the_matching_patch(self):
        w = h = 64
        img = _image(w, h, (0.1, 0.1, 0.1, 1.0))
        img[:, 32:] = (0.9, 0.9, 0.9, 1.0)                  # left dark, right bright
        rx, ry = special.ring(46, 32, 4, w, h)
        img[30:35, 44:49] = (0.0, 1.0, 0.0, 1.0)            # a blemish on the bright side
        ox, oy = special.best_offset(img, 46, 32, 4, rx, ry)
        self.assertTrue(np.all(img[ry + oy, rx + ox, 0] > 0.5))   # took a bright patch

    def test_ring_is_outside_the_disk(self):
        rx, ry = special.ring(20, 20, 5, 64, 64)
        d = np.hypot(rx - 20, ry - 20)
        self.assertTrue(np.all(d > 5.0) and np.all(d <= 5.0 + special.HEAL_RING_WIDTH + 1e-6))


class ParticlesTest(unittest.TestCase):
    def test_scatter_counts(self):
        pts = special.scatter_2d(np.random.default_rng(1), 50, 50, 10, 5, 2)
        self.assertEqual(len(pts), 5 * 3)
        energies = [e for _x, _y, e in pts]
        self.assertEqual(max(energies), 1.0)
        self.assertLess(min(energies), 1.0)

    def test_chips_unique_and_clipped(self):
        pts = [(1, 1, 1.0), (1, 1, 0.3), (30, 30, 0.5)]
        xs, ys, wts = special.chips(pts, 3, np.random.default_rng(2), 32, 32)
        flat = (ys * 32 + xs).tolist()
        self.assertEqual(len(flat), len(set(flat)))
        self.assertTrue(np.all((xs >= 0) & (xs < 32) & (ys >= 0) & (ys < 32)))
        self.assertTrue(np.all((wts > 0) & (wts <= 1)))

    def test_chip_size_zero_is_one_pixel(self):
        xs, _ys, _w = special.chips([(5, 5, 1.0)], 0, np.random.default_rng(0), 16, 16)
        self.assertEqual(len(xs), 1)


class GroupTest(unittest.TestCase):
    def test_special_tools_listed_in_window_order(self):
        self.assertEqual(brushes_actions.SPECIAL_TOOLS, ('RUST', 'PARTICLES', 'NOISE_BLUR', 'PULL', 'REPAIR'))


if __name__ == '__main__':
    unittest.main()
