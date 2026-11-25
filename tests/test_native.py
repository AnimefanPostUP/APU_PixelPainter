"""Parity tests: the C# backend (native/, utils/native.py) against the Python implementations.

Every test runs the Python path (native forced off) and the C# path (forced on)
on identical images and compares the results. Skipped when the library is not
built for this platform (native/build.ps1).

    python -m unittest discover -s tests -v
"""

import importlib
import os
import random
import sys
import types
import unittest
from types import SimpleNamespace

import numpy as np

_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PACKAGE = os.path.basename(_ADDON_DIR)
sys.path.insert(0, os.path.dirname(_ADDON_DIR))


# Blender stubs and the addon modules are imported once below, then removed
# from sys.modules again so the other test files keep their own environment.
_MODULES_BEFORE = set(sys.modules)
_ADDED_ATTRS = []   # (module, attribute) set on modules that existed before


def _stub(name, **attrs):
    module = sys.modules.get(name)
    if module is None:
        module = types.ModuleType(name)
        sys.modules[name] = module
    for key, value in attrs.items():
        if not hasattr(module, key):
            setattr(module, key, value)
            if name in _MODULES_BEFORE:
                _ADDED_ATTRS.append((module, key))
    return module


class _Anything:
    """Stand-in for Blender API objects that are touched at import time only."""

    def __getattr__(self, _name):
        return _Anything()

    def __call__(self, *args, **kwargs):
        return _Anything()


class _AnyModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return _Anything()


for _name in ('bpy_extras', 'bpy_extras.view3d_utils', 'mathutils', 'mathutils.geometry',
              'mathutils.bvhtree', 'mathutils.kdtree', 'bmesh'):
    sys.modules.setdefault(_name, _AnyModule(_name))

_stub('bpy', types=_Anything(), props=_Anything(), utils=_Anything())
_stub('bpy.app')
_stub('bpy.app.handlers', persistent=lambda fn: fn)
_stub('bpy.types', Operator=object, Panel=object)
_stub('bpy.props')
_stub('blf')
_stub('gpu')
_stub('gpu_extras')
_stub('gpu_extras.batch', batch_for_shader=lambda *a, **k: None)
_stub('bpy', app=sys.modules['bpy.app'])
_stub('bpy.app', handlers=sys.modules['bpy.app.handlers'])

_LOADED = {name: importlib.import_module(f'{_PACKAGE}.{name}') for name in (
    'utils.native', 'utils.pixel_io', 'utils.math_utils', 'tools.draw_blending', 'tools.draw_functions',
    'tools.draw_tool_smooth', 'tools.native_paint', 'tools.mask', 'tools.mask_geometry',
    'tools.selection_ops', 'tools.base', 'tools.brushes', 'tools.filters')}

for _name in set(sys.modules) - _MODULES_BEFORE:
    del sys.modules[_name]
for _module, _attr in _ADDED_ATTRS:
    delattr(_module, _attr)


def _mod(name):
    return _LOADED[name]


native = _mod('utils.native')
pixel_io = _mod('utils.pixel_io')
math_utils = _mod('utils.math_utils')

BLENDS = list(native.BLEND_IDS)
FALLOFFS = ('CONSTANT', 'LINEAR', 'SMOOTH', 'SPHERE', 'SHARPEN', 'PLATEAU', 'ROOT', 'SPIKE',
            'STEPPED', 'RING', 'INVERTED')


class FakePixels:
    def __init__(self, arr):
        self.arr = arr

    def foreach_get(self, out):
        out[:] = self.arr

    def foreach_set(self, data):
        self.arr[:] = np.asarray(data, dtype=np.float32).reshape(-1)

    def __len__(self):
        return self.arr.size


class FakeImage:
    _uid = 0

    def __init__(self, w, h, arr):
        FakeImage._uid += 1
        self.session_uid = FakeImage._uid
        self.size = (w, h)
        self.pixels = FakePixels(np.array(arr, dtype=np.float32).reshape(-1).copy())
        self.updates = 0

    def update(self):
        self.updates += 1

    @property
    def arr(self):
        return self.pixels.arr


def random_image(w, h, seed, transparent=0.0):
    rng = np.random.default_rng(seed)
    arr = rng.random((h, w, 4), dtype=np.float32)
    if transparent:
        arr[..., 3][rng.random((h, w)) < transparent] = 0.0
    return arr.reshape(-1)


def random_pixels(w, h, n, seed, margin=0):
    rng = random.Random(seed)
    pts = {(rng.randint(-margin, w - 1 + margin), rng.randint(-margin, h - 1 + margin)) for _ in range(n)}
    return sorted(pts)


@unittest.skipUnless(native.available(), f"C# backend not built: {native.status()}")
class NativeTestCase(unittest.TestCase):
    ATOL = 2e-6

    def tearDown(self):
        native.set_override(None)
        pixel_io.end_stroke()

    def both(self, fn, base, w, h):
        """Run ``fn(img)`` on two copies of ``base``: Python first, then C#; return both buffers."""
        results = []
        for use_native in (False, True):
            native.set_override(use_native)
            img = FakeImage(w, h, base)
            fn(img)
            results.append(img.arr.copy())
        native.set_override(None)
        return results

    def assertClose(self, a, b, atol=None, msg=None):
        np.testing.assert_allclose(a, b, rtol=0, atol=atol if atol is not None else self.ATOL, err_msg=msg or '')


class KernelParityTest(NativeTestCase):
    def setUp(self):
        self.draw_functions = _mod('tools.draw_functions')
        self.smooth_mod = _mod('tools.draw_tool_smooth')

    def test_write_pixels_every_blend_mode(self):
        w, h = 23, 17
        base = random_image(w, h, 1, transparent=0.3)
        pixels = random_pixels(w, h, 220, 2, margin=3)
        weights = [random.Random(i).random() * 1.3 for i in range(len(pixels))]
        for blend in BLENDS:
            for protect in (False, True):
                for wts in (None, weights):
                    py, cs = self.both(lambda img: self.draw_functions.write_pixels_to_image(
                        img, pixels, (0.8, 0.25, 0.6), blend=blend, opacity=0.7, alpha_opacity=0.9,
                        pixel_weights=wts, protect_transparent=protect), base, w, h)
                    self.assertClose(py, cs, msg=f"{blend} protect={protect} weights={wts is not None}")

    def test_write_pixels_with_base_buffer(self):
        w, h = 16, 16
        base = random_image(w, h, 3)
        back = random_image(w, h, 4)
        pixels = random_pixels(w, h, 60, 5)
        py, cs = self.both(lambda img: self.draw_functions.write_pixels_to_image(
            img, pixels, (0.1, 0.9, 0.3), base_buffer=back, blend='OVERLAY', opacity=0.5), base, w, h)
        self.assertClose(py, cs)
        # all pixels outside: nothing written, not even the base buffer
        py, cs = self.both(lambda img: self.draw_functions.write_pixels_to_image(
            img, [(-5, 2), (40, 40)], (1, 1, 1), base_buffer=back), base, w, h)
        self.assertClose(py, base)
        self.assertClose(cs, base)

    def test_set_alpha(self):
        w, h = 20, 20
        base = random_image(w, h, 6, transparent=0.4)
        pixels = random_pixels(w, h, 150, 7, margin=2)
        weights = [((i * 37) % 100) / 100.0 for i in range(len(pixels))]
        for protect in (False, True):
            py, cs = self.both(lambda img: self.draw_functions.set_pixels_alpha(
                img, pixels, 0.2, opacity=0.8, protect_transparent=protect, pixel_weights=weights), base, w, h)
            self.assertClose(py, cs)

    def test_smooth_sat_and_direct(self):
        for (w, h, n, radius) in ((30, 25, 120, 3), (40, 40, 300, 7), (1100, 1000, 6, 2)):
            base = random_image(w, h, 8, transparent=0.2)
            pixels = random_pixels(w, h, n, 9)
            if w > 1000:   # bbox spans the image -> direct path
                pixels = [(0, 0), (1, 2), (w - 1, h - 1), (w - 3, h - 2), (500, 500), (3, h - 1)]
            weights = [0.0 if i % 11 == 0 else ((i * 13) % 10) / 10.0 + 0.05 for i in range(len(pixels))]
            py, cs = self.both(lambda img: self.smooth_mod.smooth_pixels_in_image(
                img, pixels, radius, 0.75, pixel_weights=weights), base, w, h)
            self.assertClose(py, cs, atol=1e-5, msg=f"{w}x{h} r={radius}")

    def test_smear(self):
        w, h = 32, 24
        base = random_image(w, h, 10)
        pixels = random_pixels(w, h, 200, 11, margin=2)
        weights = [((i * 7) % 10) / 9.0 for i in range(len(pixels))]
        for (dx, dy, reach) in ((1, 0, 2.5), (-2, 3, 1.5), (0, 0, 4.0), (3, -1, 0.5)):
            py, cs = self.both(lambda img: self.smooth_mod.smear_pixels_in_image(
                img, pixels, dx, dy, reach, 0.6, pixel_weights=weights), base, w, h)
            self.assertClose(py, cs, msg=f"d=({dx},{dy}) reach={reach}")


class FootprintTest(NativeTestCase):
    def setUp(self):
        self.np_paint = _mod('tools.native_paint')

    @staticmethod
    def python_merge(centers, radius, falloff):
        weights = {}
        for (cx, cy) in centers:
            for px, wt in zip(*math_utils.get_pixels_in_circle_weighted(cx, cy, radius, falloff)):
                if wt > weights.get(px, 0.0):
                    weights[px] = wt
        return weights

    def test_falloff_kernels_match_python_merge(self):
        w, h = 60, 50
        centers = [(5, 5), (7, 6), (30, 25), (58, 49), (0, 0), (45, 10)]
        for falloff in FALLOFFS:
            for radius in (0, 1, 4, 9):
                expected = {px: wt for px, wt in self.python_merge(centers, radius, falloff).items()
                            if 0 <= px[0] < w and 0 <= px[1] < h}
                kernel = self.np_paint.falloff_kernel(radius, falloff)
                xy, wts = native.stamp(centers, radius, kernel, w, h)
                got = {(int(x), int(y)): float(v) for (x, y), v in zip(xy, wts)}
                self.assertEqual(set(got), set(expected), f"{falloff} r={radius}")
                for px, wt in expected.items():
                    self.assertAlmostEqual(got[px], wt, places=6)

    def test_shape_kernels(self):
        w, h = 40, 40
        for shape in ('SQUARE', 'CIRCLE'):
            for radius in (0, 1, 3, 6):
                centers = [(2, 3), (20, 20), (21, 22), (39, 0)]
                expected = set()
                for (cx, cy) in centers:
                    expected |= math_utils.get_pixels_in_shape(cx, cy, radius, shape)
                expected = {p for p in expected if 0 <= p[0] < w and 0 <= p[1] < h}
                xy, wts = native.stamp(centers, radius, self.np_paint.shape_kernel(radius, shape), w, h)
                self.assertEqual({(int(x), int(y)) for x, y in xy}, expected, f"{shape} r={radius}")
                self.assertTrue(np.all(wts == 1.0))

    def test_stroke_grid_emits_new_pixels_once(self):
        w, h = 30, 30
        grid = np.zeros(w * h, dtype=np.float32)
        kernel = self.np_paint.falloff_kernel(3, 'LINEAR')
        xy1, _ = native.stamp([(10, 10)], 3, kernel, w, h, grid)
        xy2, _ = native.stamp([(11, 10)], 3, kernel, w, h, grid)
        first, second = {tuple(p) for p in xy1.tolist()}, {tuple(p) for p in xy2.tolist()}
        self.assertFalse(first & second)
        expected = self.python_merge([(10, 10), (11, 10)], 3, 'LINEAR')
        self.assertEqual(first | second, set(expected))
        for (x, y), wt in expected.items():
            self.assertAlmostEqual(float(grid[y * w + x]), wt, places=6)

    def test_spray(self):
        w, h = 80, 80
        radius, density = 6, 0.3
        kernel = self.np_paint.falloff_kernel(radius, 'CONSTANT')
        xy, wts = native.spray([(40, 40)], radius, density, kernel, 1234, w, h)
        expected_count = max(1, int(density * max(1, int(np.pi * radius * radius))))
        self.assertEqual(len(xy), expected_count)
        self.assertEqual(len({tuple(p) for p in xy.tolist()}), len(xy))
        self.assertTrue(np.all((xy[:, 0] - 40) ** 2 + (xy[:, 1] - 40) ** 2 <= radius * radius))
        self.assertTrue(np.all(wts == 1.0))
        again, _ = native.spray([(40, 40)], radius, density, kernel, 1234, w, h)
        self.assertTrue(np.array_equal(xy, again))   # deterministic per seed


class RegionMaskRasterTest(NativeTestCase):
    def test_restore_blocked(self):
        mask = _mod('tools.mask')
        w, h = 25, 20
        before = random_image(w, h, 12)
        after = before.copy()
        after[::7] += 0.5
        after[40] = np.nan
        allowed = np.random.default_rng(13).random(w * h) < 0.5
        results = []
        for use_native in (False, True):
            native.set_override(use_native)
            img = FakeImage(w, h, after)
            mask.restore_blocked(img, before.copy(), allowed)
            results.append(img.arr.copy())
        np.testing.assert_array_equal(results[0], results[1])

    def test_blend_region_every_mode(self):
        blending = _mod('tools.draw_blending')
        dst = random_image(9, 7, 14).reshape(7, 9, 4)
        src = random_image(9, 7, 15).reshape(7, 9, 4)
        for blend in BLENDS:
            for opacity in (0.0, 0.35, 1.0, 1.4):
                native.set_override(False)
                py = blending.blend_region_pixels(dst, src, blend, opacity)
                native.set_override(True)
                cs = blending.blend_region_pixels(dst, src, blend, opacity)
                self.assertClose(py, cs, msg=f"{blend} {opacity}")

    def test_blit_region(self):
        selection_ops = _mod('tools.selection_ops')
        w, h = 30, 26
        base = random_image(w, h, 16)
        region = random_image(7, 5, 17).reshape(5, 7, 4)
        cases = [
            dict(dest_left=3, dest_bottom=4),
            dict(dest_left=-2, dest_bottom=20, blend='MUL', opacity=0.6),
            dict(dest_left=5, dest_bottom=2, dest_box=(5, 2, 19, 13), blend='HUE', opacity=0.8),
            dict(dest_left=1, dest_bottom=1, dest_box=(1, 1, 3, 2), clear_box=(10, 10, 15, 12)),
        ]
        for case in cases:
            py, cs = self.both(lambda img: selection_ops.blit_region(img, region, **case), base, w, h)
            self.assertClose(py, cs, msg=str(case))

    def test_raster_triangles(self):
        geo = _mod('tools.mask_geometry')
        rng = np.random.default_rng(18)
        tris = rng.random((40, 3, 2))
        for (w, h, grow) in ((64, 48, 0.0), (33, 70, 1.5), (128, 128, 0.0)):
            native.set_override(False)
            py = geo.raster_triangles(tris, w, h, grow)
            native.set_override(True)
            cs = geo.raster_triangles(tris, w, h, grow)
            np.testing.assert_array_equal(py, cs)


class PixelIoTest(NativeTestCase):
    def test_stroke_buffer_and_deferred_upload(self):
        img = FakeImage(4, 4, np.zeros(64, dtype=np.float32))
        pixel_io.begin_stroke(img)
        with pixel_io.deferred(img):
            buf = pixel_io.buffer(img)
            buf[0] = 1.0
            pixel_io.write(img, buf)
            self.assertEqual(img.arr[0], 0.0)           # not uploaded yet
            self.assertEqual(pixel_io.read(img)[0], 1.0)  # but visible to readers
            copy = pixel_io.read(img)
            copy[1] = 5.0
            self.assertEqual(pixel_io.buffer(img)[1], 0.0)  # read() is private
        self.assertEqual(img.arr[0], 1.0)
        self.assertEqual(img.updates, 1)
        pixel_io.end_stroke()
        other = FakeImage(4, 4, np.full(64, 0.5, dtype=np.float32))
        self.assertEqual(pixel_io.read(other)[0], 0.5)


class ToolParityTest(NativeTestCase):
    """Whole tool draw steps (footprint + paint) through both backends."""

    def setUp(self):
        self.base_mod = _mod('tools.base')
        self.brushes = _mod('tools.brushes')
        self.filters = _mod('tools.filters')

    def run_tool(self, tool, base, w, h, step_lists, spacing='FREE', protect=False, **env_kw):
        results = []
        for use_native in (False, True):
            native.set_override(use_native)
            img = FakeImage(w, h, base)
            state = {'last_paint_cx': None, 'last_paint_cy': None, 'stroke_painted': None}
            wm = SimpleNamespace(pixel_painter_circle_falloff='SMOOTH', pixel_painter_smooth_falloff='LINEAR',
                                 pixel_painter_smear_falloff='SPHERE', pixel_painter_spray_strength=1.0)
            pixel_io.begin_stroke(img)
            for i, steps in enumerate(step_lists):
                env = self.base_mod.DrawEnvironment(
                    context=None, state=state, img=img, mode=tool.tool_id, color=(0.9, 0.2, 0.4),
                    blend=env_kw.get('blend', 'MIX'), opacity=env_kw.get('opacity', 0.6),
                    alpha_opacity=0.8, protect_transparent=protect, radius=env_kw.get('radius', 3),
                    spacing=spacing, wm=wm, cursor_x=steps[-1][0], cursor_y=steps[-1][1],
                    interpolation_steps=(lambda s=steps: list(s)), curve_sampler_factory=lambda ctx: None,
                    modifier=0.5)
                if i == 0:
                    tool.on_stroke_begin(env)
                with pixel_io.deferred(img):
                    tool.on_draw(env)
            pixel_io.end_stroke()
            results.append(img.arr.copy())
        native.set_override(None)
        return results

    STEPS = [[(5, 5)], [(6, 5), (7, 6), (8, 6)], [(9, 7), (10, 8)], [(10, 9)], [(30, 12), (31, 13)]]

    def test_brush_tools(self):
        w, h = 40, 30
        base = random_image(w, h, 19, transparent=0.25)
        for tool_cls in (self.brushes.SquareBrushTool, self.brushes.CircleBrushTool, self.brushes.EraserTool):
            for spacing in ('FREE', 'PIXEL'):
                for protect in (False, True):
                    py, cs = self.run_tool(tool_cls(), base, w, h, self.STEPS, spacing=spacing, protect=protect,
                                           blend='SCREEN')
                    self.assertClose(py, cs, msg=f"{tool_cls.__name__} {spacing} protect={protect}")
                    self.assertFalse(np.allclose(cs, base), "tool painted nothing")

    def test_filter_tools(self):
        w, h = 40, 30
        base = random_image(w, h, 20, transparent=0.25)
        for tool_cls in (self.filters.SmoothTool, self.filters.SmearTool):
            for protect in (False, True):
                py, cs = self.run_tool(tool_cls(), base, w, h, self.STEPS, protect=protect)
                self.assertClose(py, cs, atol=1e-5, msg=f"{tool_cls.__name__} protect={protect}")
                self.assertFalse(np.allclose(cs, base), "tool painted nothing")

    def test_native_path_is_taken(self):
        np_paint = _mod('tools.native_paint')
        calls = []
        original = np_paint.paint_weighted
        np_paint.paint_weighted = lambda *a, **k: calls.append(1) or original(*a, **k)
        try:
            base = random_image(20, 20, 21)
            self.run_tool(self.brushes.CircleBrushTool(), base, 20, 20, self.STEPS[:2])
        finally:
            np_paint.paint_weighted = original
        self.assertEqual(len(calls), 2)   # once per step, native run only


if __name__ == '__main__':
    unittest.main()
