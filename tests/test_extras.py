"""Unit tests for the Extras window's pure parts: the AO curve (model/value_curve.py),
the Edges band math (paint/edge_ramp.py), texel blending (paint/region_paint.py) and the
AO texel placement / hemisphere (tools/extras/ao.py).

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

curve = importlib.import_module(f'{_PACKAGE}.model.value_curve')
edge = importlib.import_module(f'{_PACKAGE}.paint.edge_ramp')
region = importlib.import_module(f'{_PACKAGE}.paint.region_paint')
ao = importlib.import_module(f'{_PACKAGE}.tools.extras.ao')


class ValueCurveTest(unittest.TestCase):
    def test_linear(self):
        pts = curve.ao_preset('LINEAR')
        xs = np.linspace(0, 1, 11)
        np.testing.assert_allclose(curve.sample(pts, xs), xs, atol=1e-9)

    def test_presets_stay_in_range_and_hit_anchors(self):
        xs = np.linspace(0, 1, 201)
        for pid, _label, points in curve.AO_PRESETS:
            ys = curve.sample(points, xs)
            self.assertTrue(np.all(ys >= 0.0) and np.all(ys <= 1.0), pid)
            for x, y in points:
                self.assertAlmostEqual(curve.sample(points, x), y, places=6, msg=pid)

    def test_monotone_no_overshoot(self):
        pts = curve.ao_preset('SMOOTH')
        ys = curve.sample(pts, np.linspace(0, 1, 501))
        self.assertTrue(np.all(np.diff(ys) >= -1e-12))

    def test_stepped_flat_runs(self):
        pts = curve.ao_preset('STEPPED')
        ys = curve.sample(pts, np.linspace(0.27, 0.48, 20))
        np.testing.assert_allclose(ys, 0.34, atol=1e-9)

    def test_text_roundtrip_and_fallback(self):
        pts = [(0.0, 0.1), (0.5, 0.9), (1.0, 0.2)]
        self.assertEqual(curve.from_text(curve.to_text(pts)), pts)
        self.assertEqual(curve.from_text(""), curve.ao_preset(curve.AO_DEFAULT))
        self.assertEqual(curve.from_text("{broken"), curve.ao_preset(curve.AO_DEFAULT))

    def test_normalize_adds_ends(self):
        self.assertEqual(curve.normalize([(0.5, 0.3)]), [(0.0, 0.3), (0.5, 0.3), (1.0, 0.3)])


def cube():
    v = np.array([[x, y, z] for x in (0, 1) for y in (0, 1) for z in (0, 1)], dtype=np.float64)
    quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    tris = np.array([t for a, b, c, d in quads for t in ((a, b, c), (a, c, d))])
    edges = np.array(sorted({tuple(sorted(e)) for q in quads for e in zip(q, q[1:] + q[:1])}))
    return v, tris, edges


def band_columns(seg, width, center, w=12, h=4):
    labels = np.zeros(w * h, dtype=np.int32)
    if center == 'ON':
        seg = edge.snap_segments(seg)
    dist = edge.segment_distance(seg, [0] * len(seg), labels, w, h, width + 1.0)
    inside, steps = edge.band(dist, width, center)
    grid = inside.reshape(h, w)
    cols = np.flatnonzero(grid.all(axis=0)).tolist()
    return cols, steps.reshape(h, w)[0]


class EdgeRampTest(unittest.TestCase):
    def test_model_edges_skip_triangulation_diagonals(self):
        v, tris, edges = cube()
        tri, _k = edge.model_edges(tris, v[tris], 'ANGLE', 30.0, real_edges=edges)
        self.assertEqual(len(tri), 24)                 # 12 cube edges, both triangles each
        tri, _k = edge.model_edges(tris, v[tris], 'ALL', real_edges=edges)
        self.assertEqual(len(tri), 24)                 # diagonals are not model edges
        tri, _k = edge.model_edges(tris, v[tris], 'ALL')
        self.assertEqual(len(tri), 36)                 # without the edge list every side counts

    def test_flat_quad_has_no_angle_edges(self):
        flat = np.array([[0, 1, 2], [0, 2, 3]])
        quad = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], dtype=np.float64)
        tri, _k = edge.model_edges(flat, quad[flat], 'ANGLE', 30.0)
        self.assertEqual(len(tri), 0)

    def test_marked_edges(self):
        v, tris, edges = cube()
        marked = np.zeros(len(edges), dtype=bool)
        marked[0] = True
        tri, _k = edge.model_edges(tris, v[tris], 'MARKED', real_edges=edges, marked=marked)
        self.assertEqual(len(tri), 2)
        tri, _k = edge.model_edges(tris, v[tris], 'MARKED', real_edges=edges, marked=None)
        self.assertEqual(len(tri), 0)

    def test_symmetric_on_a_texel_border(self):
        # An edge exactly between columns 5 and 6 (pixel-aligned UVs), both directions.
        for seg in ([[[6.0, 0.0], [6.0, 4.0]]], [[[6.0, 4.0], [6.0, 0.0]]]):
            cols, _steps = band_columns(seg, 2, 'BETWEEN')
            self.assertEqual(cols, [4, 5, 6, 7])       # two texels on each side

    def test_symmetric_through_texel_centers(self):
        cols, steps = band_columns([[[6.5, 0.0], [6.5, 4.0]]], 2, 'BETWEEN')
        self.assertEqual(cols, [5, 6, 7])
        self.assertEqual(steps[5], steps[7])

    def test_pixel_line_is_odd_and_centered(self):
        cols, steps = band_columns([[[6.0, 0.0], [6.0, 4.0]]], 1, 'ON')
        self.assertEqual(cols, [6])                    # a one-texel line
        cols, steps = band_columns([[[6.0, 0.0], [6.0, 4.0]]], 3, 'ON')
        self.assertEqual(cols, [4, 5, 6, 7, 8])
        self.assertEqual(steps[4], steps[8])

    def test_band_stays_on_its_element(self):
        w, h = 12, 1
        labels = np.zeros(w, dtype=np.int32)
        labels[6:] = 1
        dist = edge.segment_distance([[[6.0, 0.0], [6.0, 1.0]]], [0], labels, w, h, 4.0)
        self.assertTrue(np.isinf(dist[6:]).all())
        self.assertTrue(np.isfinite(dist[3:6]).all())

    def test_ramp(self):
        t, op = edge.ramp([0, 1, 2], 3, fade=True)          # default: linear fade 1 - x
        np.testing.assert_allclose(t, [0.0, 1 / 3, 2 / 3])
        np.testing.assert_allclose(op, [1.0, 2 / 3, 1 / 3])
        _t, op = edge.ramp([0, 2], 3, fade=False)
        np.testing.assert_allclose(op, [1.0, 1.0])

    def test_ramp_with_falloff_curve(self):
        const = curve.preset('edge', 'CONSTANT')
        t, op = edge.ramp([0, 1, 2], 3, fade=True, curve=lambda x: curve.sample(const, x))
        np.testing.assert_allclose(t, 0.0)
        np.testing.assert_allclose(op, 1.0)
        stepped = curve.preset('edge', 'STEPPED')
        _t, op = edge.ramp([0, 3], 8, curve=lambda x: curve.sample(stepped, x))
        np.testing.assert_allclose(op, [1.0, 0.75], atol=1e-6)

    def test_edge_presets(self):
        for pid, _label, points in curve.EDGE_PRESETS:
            self.assertIsNotNone(curve.preset('edge', pid))
        self.assertEqual(curve.from_text("", 'edge'), curve.preset('edge', 'LINEAR'))


class RegionPaintTest(unittest.TestCase):
    def test_mix_with_opacity_and_alpha(self):
        arr = np.zeros(3 * 4, dtype=np.float32)
        n = region.blend_texels(arr, [0, 2], (1.0, 0.5, 0.0), [1.0, 0.5], 'MIX', 1.0)
        self.assertEqual(n, 2)
        np.testing.assert_allclose(arr[0:4], [1.0, 0.5, 0.0, 1.0])
        np.testing.assert_allclose(arr[8:12], [0.5, 0.25, 0.0, 0.5])
        np.testing.assert_allclose(arr[4:8], 0.0)

    def test_per_texel_colors_and_protect(self):
        arr = np.array([0, 0, 0, 0, 0, 0, 0, 1], dtype=np.float32)
        rgb = region.gradient((1, 0, 0), (0, 0, 1), [0.0, 1.0])
        n = region.blend_texels(arr, [0, 1], rgb, 1.0, 'MIX', 1.0, protect_transparent=True)
        self.assertEqual(n, 1)                                  # texel 0 is transparent
        np.testing.assert_allclose(arr[:4], 0.0)
        np.testing.assert_allclose(arr[4:], [0.0, 0.0, 1.0, 1.0])

    def test_zero_opacity_writes_nothing(self):
        arr = np.ones(4, dtype=np.float32) * 0.5
        self.assertEqual(region.blend_texels(arr, [0], (1, 1, 1), 0.0), 0)
        np.testing.assert_allclose(arr, 0.5)


class FakeCache:
    def __init__(self, tri_uv, tri_pos):
        self.tri_uv = np.asarray(tri_uv, dtype=np.float64)
        self.tri_pos = np.asarray(tri_pos, dtype=np.float64)


class AOTest(unittest.TestCase):
    def test_hemisphere(self):
        d = ao.hemisphere(64)
        np.testing.assert_allclose(np.linalg.norm(d, axis=1), 1.0, atol=1e-9)
        self.assertTrue(np.all(d[:, 2] > 0.0))

    def test_texel_surface_places_texels_on_a_quad(self):
        # A unit quad in the XY plane, UVs = XY: texel centers map onto the plane.
        uv = [[[0, 0], [1, 0], [1, 1]], [[0, 0], [1, 1], [0, 1]]]
        pos = [[[0, 0, 0], [1, 0, 0], [1, 1, 0]], [[0, 0, 0], [1, 1, 0], [0, 1, 0]]]
        cache = FakeCache(uv, pos)
        w = h = 4
        targets = np.arange(w * h)
        p, n, ok = ao.texel_surface(cache, w, h, targets)
        self.assertTrue(ok.all())
        xs, ys = targets % w, targets // w
        np.testing.assert_allclose(p[:, 0], (xs + 0.5) / w, atol=1e-9)
        np.testing.assert_allclose(p[:, 1], (ys + 0.5) / h, atol=1e-9)
        np.testing.assert_allclose(n, np.tile([0.0, 0.0, 1.0], (len(targets), 1)), atol=1e-9)

    def test_uncovered_edge_texel_takes_a_neighbour(self):
        # A triangle covering only the lower-left half: texel (3, 3) has no center inside,
        # its neighbour (2, 2) does... reached in two steps.
        uv = [[[0, 0], [1, 0], [0, 1]]]
        pos = [[[0, 0, 0], [1, 0, 0], [0, 1, 0]]]
        p, _n, ok = ao.texel_surface(FakeCache(uv, pos), 4, 4, np.array([0, 15]))
        self.assertTrue(ok[0])
        self.assertTrue(ok[1])
        self.assertLess(abs(p[1, 0] - 0.625) + abs(p[1, 1] - 0.375), 0.6)


if __name__ == '__main__':
    unittest.main()
