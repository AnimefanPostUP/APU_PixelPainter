"""Unit tests for the paint mask geometry (tools/mask_geometry.py, pure numpy).

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

geo = importlib.import_module(f'{_PACKAGE}.tools.mask.geometry')


def quad_mesh(quads, uvs):
    """Quads given as 4 vertex indices each, with one UV per corner."""
    loop_start = np.arange(len(quads)) * 4
    loop_total = np.full(len(quads), 4)
    loop_vert = np.array(quads).ravel()
    loop_uv = np.array(uvs, dtype=np.float64).reshape(-1, 2)
    return loop_start, loop_total, loop_vert, loop_uv


class ComponentsTest(unittest.TestCase):
    def test_chain_and_singletons(self):
        labels = geo.components(6, [0, 1, 4], [1, 2, 5])
        self.assertEqual(labels[0], labels[1])
        self.assertEqual(labels[1], labels[2])
        self.assertEqual(labels[4], labels[5])
        self.assertEqual(len(set(labels.tolist())), 3)   # {0,1,2}, {3}, {4,5}

    def test_long_chain_reversed(self):
        n = 200
        labels = geo.components(n, np.arange(n - 1)[::-1], np.arange(1, n)[::-1])
        self.assertTrue(np.all(labels == 0))

    def test_no_pairs(self):
        self.assertEqual(geo.components(3, [], []).tolist(), [0, 1, 2])


class IslandTest(unittest.TestCase):
    # Two quads sharing the edge 1-2 (vertices 0..5 in a strip).
    QUADS = [(0, 1, 2, 3), (1, 4, 5, 2)]

    def test_shared_uv_edge_is_one_island(self):
        uvs = [(0, 0), (.5, 0), (.5, 1), (0, 1),
               (.5, 0), (1, 0), (1, 1), (.5, 1)]
        labels = geo.uv_island_labels(*quad_mesh(self.QUADS, uvs))
        self.assertEqual(labels[0], labels[1])

    def test_seam_splits_islands(self):
        uvs = [(0, 0), (.4, 0), (.4, 1), (0, 1),
               (.6, 0), (1, 0), (1, 1), (.6, 1)]            # edge 1-2 has other UVs on each side
        labels = geo.uv_island_labels(*quad_mesh(self.QUADS, uvs))
        self.assertNotEqual(labels[0], labels[1])

    def test_mesh_parts(self):
        quads = [(0, 1, 2, 3), (1, 4, 5, 2), (6, 7, 8, 9)]
        edges = [(0, 1), (1, 2), (2, 3), (3, 0), (1, 4), (4, 5), (5, 2), (6, 7), (7, 8), (8, 9), (9, 6)]
        labels = geo.mesh_part_labels(np.arange(3) * 4, np.array(quads).ravel(), 10, edges)
        self.assertEqual(labels[0], labels[1])
        self.assertNotEqual(labels[0], labels[2])


class RasterTest(unittest.TestCase):
    def test_pixel_aligned_square(self):
        # Pixels 2..5 x 1..3 of an 8x8 image, as two triangles.
        x0, x1, y0, y1 = 2 / 8, 6 / 8, 1 / 8, 4 / 8
        tris = [[(x0, y0), (x1, y0), (x1, y1)], [(x0, y0), (x1, y1), (x0, y1)]]
        px = geo.raster_triangles(tris, 8, 8)
        expected = sorted(y * 8 + x for y in range(1, 4) for x in range(2, 6))
        self.assertEqual(px.tolist(), expected)

    def test_grow_adds_a_ring(self):
        x0, x1, y0, y1 = 2 / 8, 6 / 8, 1 / 8, 4 / 8
        tris = [[(x0, y0), (x1, y0), (x1, y1)], [(x0, y0), (x1, y1), (x0, y1)]]
        grown = set(geo.raster_triangles(tris, 8, 8, grow=1.0).tolist())
        self.assertIn(1 * 8 + 1, grown)      # left of the square
        self.assertIn(4 * 8 + 3, grown)      # above it
        self.assertNotIn(7 * 8 + 7, grown)

    def test_clipped_and_degenerate(self):
        self.assertEqual(len(geo.raster_triangles([[(2, 2), (3, 2), (3, 3)]], 8, 8)), 0)
        self.assertEqual(len(geo.raster_triangles([[(0, 0), (.5, .5), (1, 1)]], 8, 8)), 0)

    def test_contains(self):
        px = np.array([3, 7, 9])
        self.assertTrue(geo.contains(px, 7))
        self.assertFalse(geo.contains(px, 8))
        self.assertFalse(geo.contains(px, 10))


class RunTest(unittest.TestCase):
    def test_runs(self):
        blocked = np.array([[1, 1, 0, 1],
                            [0, 0, 0, 0],
                            [0, 1, 1, 1]], dtype=bool)
        rows, starts, ends = geo.blocked_runs(blocked)
        self.assertEqual(list(zip(rows.tolist(), starts.tolist(), ends.tolist())),
                         [(0, 0, 2), (0, 3, 4), (2, 1, 4)])
        self.assertEqual(geo.run_triangles(rows, starts, ends).shape, (18, 2))


if __name__ == '__main__':
    unittest.main()
