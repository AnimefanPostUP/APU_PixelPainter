"""Unit tests for the NumPy cursor outlines (utils/math_utils: stamp_mask,
mask_outline_segments, shape_outline_segments): same contour as the set based
get_pixels_in_shape / get_outline_edges.

    python -m unittest discover -s tests -v
"""

import importlib
import os
import sys
import types
import unittest

_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PACKAGE = os.path.basename(_ADDON_DIR)
sys.path.insert(0, os.path.dirname(_ADDON_DIR))
sys.modules.setdefault('bpy', types.ModuleType('bpy'))  # the package __init__ imports bpy

math_utils = importlib.import_module(f'{_PACKAGE}.utils.math_utils')


def unit_edges(segments):
    """Merged segments split back into unit edges ((x0, y0), (x1, y1)), sorted ends."""
    out = set()
    for (ax, ay), (bx, by) in segments.tolist():
        ax, ay, bx, by = int(ax), int(ay), int(bx), int(by)
        if ay == by:
            for x in range(min(ax, bx), max(ax, bx)):
                out.add(((x, ay), (x + 1, ay)))
        else:
            for y in range(min(ay, by), max(ay, by)):
                out.add(((ax, y), (ax, y + 1)))
    return out


def reference_edges(pixels):
    return {tuple(sorted(e)) for e in math_utils.get_outline_edges(pixels)}


class StampMaskTest(unittest.TestCase):

    def test_single_stamp_matches_pixel_set(self):
        for shape in ('SQUARE', 'CIRCLE'):
            for r in (0, 1, 2, 3, 5, 8, 13):
                x0, y0, mask = math_utils.stamp_mask([(4, -3)], r, shape)
                ys, xs = mask.nonzero()
                got = {(int(x) + x0, int(y) + y0) for x, y in zip(xs, ys)}
                self.assertEqual(got, math_utils.get_pixels_in_shape(4, -3, r, shape), f"{shape} r={r}")

    def test_line_union_matches_pixel_set(self):
        line = math_utils.get_line_pixels(0, 0, 23, 9)
        for shape in ('SQUARE', 'CIRCLE'):
            expected = set()
            for x, y in line:
                expected |= math_utils.get_pixels_in_shape(x, y, 4, shape)
            x0, y0, mask = math_utils.stamp_mask(line, 4, shape)
            ys, xs = mask.nonzero()
            self.assertEqual({(int(x) + x0, int(y) + y0) for x, y in zip(xs, ys)}, expected)

    def test_no_centers(self):
        self.assertIsNone(math_utils.stamp_mask([], 3, 'CIRCLE')[2])
        self.assertEqual(len(math_utils.mask_outline_segments(0, 0, None)), 0)


class OutlineSegmentsTest(unittest.TestCase):

    def test_shape_outline_matches_edge_set(self):
        for shape in ('SQUARE', 'CIRCLE'):
            for r in (0, 1, 2, 4, 7, 16):
                segs = math_utils.shape_outline_segments(10, 20, r, shape)
                pixels = math_utils.get_pixels_in_shape(10, 20, r, shape)
                self.assertEqual(unit_edges(segs), reference_edges(pixels), f"{shape} r={r}")

    def test_collinear_edges_are_merged(self):
        segs = math_utils.shape_outline_segments(0, 0, 5, 'SQUARE')
        self.assertEqual(len(segs), 4)

    def test_memoized_result_is_not_shared(self):
        a = math_utils.shape_outline_segments(0, 0, 3, 'CIRCLE')
        a += 100.0
        b = math_utils.shape_outline_segments(0, 0, 3, 'CIRCLE')
        self.assertLess(b.max(), 50.0)

    def test_pixel_set_outline_with_hole(self):
        ring = {(x, y) for x in range(5) for y in range(5)} - {(2, 2)}
        self.assertEqual(unit_edges(math_utils.pixels_outline_segments(ring)), reference_edges(ring))


if __name__ == '__main__':
    unittest.main()
