"""Unit tests for the Shape falloff (the pen menu's falloff field), its widget and the
custom curve presets.

    python -m unittest discover -s tests -v
"""

import importlib
import math
import os
import sys
import types
import unittest

_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PACKAGE = os.path.basename(_ADDON_DIR)
sys.path.insert(0, os.path.dirname(_ADDON_DIR))
sys.modules.setdefault('bpy', types.ModuleType('bpy'))  # the package __init__ imports bpy

falloff = importlib.import_module(f'{_PACKAGE}.tools.falloff')
math_utils = importlib.import_module(f'{_PACKAGE}.utils.math_utils')
pen_bar_ui = importlib.import_module(f'{_PACKAGE}.ui.pen_bar')
theme_mod = importlib.import_module(f'{_PACKAGE}.ui.kit.theme')


class ShapeFalloffTest(unittest.TestCase):

    def test_corners_match_presets(self):
        for i in range(11):
            t = i / 10.0
            self.assertAlmostEqual(math_utils.shape_falloff(t, 1.0, 0.3), 1.0)                       # constant
            self.assertAlmostEqual(math_utils.shape_falloff(t, 0.0, 0.0), math_utils.get_falloff(t, 'LINEAR'))
            self.assertAlmostEqual(math_utils.shape_falloff(t, 0.0, 1.0), math_utils.get_falloff(t, 'SPIKE'))

    def test_hardness_keeps_full_strength_core(self):
        self.assertEqual(math_utils.shape_falloff(0.5, 0.5, 0.0), 1.0)
        self.assertAlmostEqual(math_utils.shape_falloff(0.75, 0.5, 0.0), 0.5)
        self.assertAlmostEqual(math_utils.shape_falloff(1.0, 0.5, 1.0), 0.0)

    def test_monotonic_and_in_range(self):
        for h in (0.0, 0.3, 0.9):
            for s in (0.0, 0.5, 1.0):
                values = [math_utils.shape_falloff(i / 50.0, h, s) for i in range(51)]
                self.assertTrue(all(0.0 <= v <= 1.0 for v in values))
                self.assertTrue(all(a >= b for a, b in zip(values, values[1:])))

    def test_get_falloff_accepts_shape_key(self):
        key = falloff.shape_key(0.4, 0.6)
        self.assertEqual(key, ('SHAPE', 0.4, 0.6))
        self.assertAlmostEqual(math_utils.get_falloff(0.7, key), math_utils.shape_falloff(0.7, 0.4, 0.6))
        self.assertAlmostEqual(math_utils.get_falloff(0.3, 'SHAPE'), 0.7)   # no values: linear

    def test_shape_key_clamps_and_rounds(self):
        self.assertEqual(falloff.shape_key(-1.0, 1.234), ('SHAPE', 0.0, 1.0))
        self.assertEqual(falloff.shape_key(0.12345, 0.5), ('SHAPE', 0.12, 0.5))
        self.assertEqual(hash(falloff.shape_key(0.1, 0.2)), hash(('SHAPE', 0.1, 0.2)))

    def test_shape_values_default_without_properties(self):
        self.assertEqual(falloff.shape_values(object()), falloff.SHAPE_DEFAULT)

    def test_shape_preset_registered(self):
        self.assertIsNotNone(falloff.get('SHAPE'))
        self.assertIn('SHAPE', falloff.PICKER_ORDER)


class CurvePresetTest(unittest.TestCase):

    def test_presets_are_not_covered_by_the_field(self):
        covered = {'CONSTANT', 'LINEAR', 'SHARPEN', 'SPIKE', 'CUSTOM', 'SHAPE'}
        ids = [pid for pid, _label, _points in falloff.CURVE_PRESETS]
        self.assertEqual(set(ids) & covered, set())
        expected = {p.id for p in falloff.FALLOFF_PRESETS} - covered
        self.assertEqual(set(ids), expected)

    def test_points_are_valid_anchors(self):
        for pid, _label, points in falloff.CURVE_PRESETS:
            xs = [p[0] for p in points]
            self.assertEqual(xs, sorted(xs), pid)
            self.assertEqual(len(set(xs)), len(xs), pid)
            self.assertEqual((xs[0], xs[-1]), (0.0, 1.0), pid)
            for x, y, handle in points:
                self.assertTrue(0.0 <= y <= 1.0, pid)
                self.assertIn(handle, ('AUTO', 'AUTO_CLAMPED', 'VECTOR'), pid)
            self.assertIsNotNone(falloff.get(pid), pid)        # has an icon

    def test_points_follow_the_falloff(self):
        for pid, _label, points in falloff.CURVE_PRESETS:
            for x, y, _handle in points:
                if pid == 'STEPPED' or (pid == 'SMOOTH' or pid == 'INVERTED') and x not in (0.0, 0.5, 1.0):
                    continue  # steps sit on the jumps; Smooth / Inverted use Blender's anchors
                self.assertAlmostEqual(y, math_utils.get_falloff(x, pid), delta=0.01, msg=f"{pid} x={x}")


class _Theme:
    def px(self, v):
        return float(v)


class FalloffFieldTest(unittest.TestCase):

    def make(self, warp=False, active=True):
        self.values = [(0.25, 0.75)]
        self.warps, self.hidden = [], []
        self.active = active
        field = pen_bar_ui.FalloffField(
            value=lambda: self.values[-1], on_value=lambda h, s: self.values.append((h, s)),
            active=lambda: self.active, on_drag_state=self.hidden.append,
            warp=(lambda x, y: self.warps.append((x, y))) if warp else None)
        field.r0, field.r1 = 90.0, 170.0
        field.a0, field.a1 = pen_bar_ui.FALLOFF_FIELD_ARC
        field.place_on(0.0, 0.0, _Theme(), 2.5)
        field._theme = _Theme()
        return field

    def test_round_trip(self):
        field = self.make()
        for hs in ((0.0, 0.0), (1.0, 1.0), (0.3, 0.8), (0.5, 0.5)):
            h, s = field.field_at(*field.point_at(*hs))
            self.assertAlmostEqual(h, hs[0], places=6)
            self.assertAlmostEqual(s, hs[1], places=6)

    def test_axes(self):
        """Inner = hard, outer = soft; higher angle = linear, lower = sharp."""
        field = self.make()
        def at(r, a):
            return field.field_at(math.cos(math.radians(a)) * r, math.sin(math.radians(a)) * r)
        mid = sum(pen_bar_ui.FALLOFF_FIELD_ARC) * 0.5
        self.assertGreater(at(100.0, mid)[0], at(160.0, mid)[0])
        self.assertLess(at(130.0, mid + 20.0)[1], at(130.0, mid - 20.0)[1])

    def test_angle_wraps(self):
        """A field across the 0 degree line (e.g. 340 .. 375) stays continuous."""
        field = self.make()
        field.a0, field.a1 = 340.0, 375.0
        field.place_on(0.0, 0.0, _Theme(), 2.5)
        def at(r, a):
            return field.field_at(math.cos(math.radians(a)) * r, math.sin(math.radians(a)) * r)
        self.assertLess(at(130.0, 10.0)[1], at(130.0, -10.0)[1])

    def test_tap_jumps(self):
        field = self.make()
        x, y = field.point_at(0.9, 0.1)
        field.drag_begin(x, y)
        field.drag_end(x, y)
        self.assertAlmostEqual(self.values[-1][0], 0.9, places=6)
        self.assertAlmostEqual(self.values[-1][1], 0.1, places=6)

    def test_first_tap_while_inactive_keeps_values(self):
        """Another falloff (e.g. Custom) in use: the first tap only switches back to
        Shape (on_value with the unchanged values); the next tap jumps."""
        field = self.make(active=False)
        x, y = field.point_at(0.9, 0.1)
        field.drag_begin(x, y)
        field.drag_end(x, y)
        self.assertEqual(self.values, [(0.25, 0.75), (0.25, 0.75)])
        self.active = True
        field.drag_begin(x, y)
        field.drag_end(x, y)
        self.assertAlmostEqual(self.values[-1][0], 0.9, places=6)
        self.assertAlmostEqual(self.values[-1][1], 0.1, places=6)

    def test_swipe_is_relative_with_gain(self):
        field = self.make()
        x0, y0 = field.point_at(0.0, 0.5)      # far from the marker at (0.25, 0.75)
        x1, y1 = field.point_at(0.4, 0.5)
        field.drag_begin(x0, y0)
        for i in range(1, 11):
            t = i / 10.0
            field.drag_update(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
        field.drag_end(x1, y1)
        h, s = self.values[-1]
        self.assertAlmostEqual(h, 0.25 + 0.4 * field.gain - 0.04 * field.gain, delta=0.03)  # first step is the tap travel
        self.assertAlmostEqual(s, 0.75, delta=0.01)

    def test_swipe_axes_are_straight(self):
        """A straight swipe across the field's middle ray changes only the sharpness, and
        one along it only the hardness -- wherever the marker is (no arc to follow)."""
        field = self.make()
        am = math.radians(sum(pen_bar_ui.FALLOFF_FIELD_ARC) * 0.5)
        ux, uy = math.cos(am), math.sin(am)
        for start in ((0.1, 0.1), (0.9, 0.9), (0.5, 0.5)):
            self.values.append(start)
            x, y = field.point_at(*start)
            field.drag_begin(x, y)
            for i in range(1, 6):                       # across: perpendicular to the middle ray
                field.drag_update(x - uy * 3.0 * i, y + ux * 3.0 * i)
            field.drag_end(x - uy * 15.0, y + ux * 15.0)
            self.assertAlmostEqual(self.values[-1][0], start[0], places=6)
            self.assertNotAlmostEqual(self.values[-1][1], start[1], places=3)
        dh, ds = field.motion_delta(ux * 10.0, uy * 10.0)   # along: outward = softer
        self.assertLess(dh, 0.0)
        self.assertAlmostEqual(ds, 0.0, places=9)

    def test_cancel_restores(self):
        field = self.make()
        x0, y0 = field.point_at(0.5, 0.5)
        field.drag_begin(x0, y0)
        for i in range(1, 6):
            field.drag_update(*field.point_at(0.5 + 0.1 * i, 0.5))
        field.drag_end(None, None, cancelled=True)
        self.assertEqual(self.values[-1], (0.25, 0.75))

    def test_cursor_hidden_while_pressed(self):
        field = self.make()
        x, y = field.point_at(0.5, 0.5)
        field.drag_begin(x, y)
        self.assertEqual(self.hidden, [True])
        field.drag_end(x, y)
        self.assertEqual(self.hidden, [True, False])
        field.drag_begin(x, y)
        field.drag_end(None, None, cancelled=True)
        self.assertEqual(self.hidden[-1], False)

    def test_warp_keeps_cursor_on_marker(self):
        field = self.make(warp=True)
        x, y = field.point_at(0.5, 0.2)                 # pressed away from the marker
        field.drag_begin(x, y)
        field.drag_update(x + 10.0, y)                  # past the tap travel: swipes
        marker = field.point_at(*self.values[-1])
        self.assertEqual(len(self.warps), 1)
        self.assertAlmostEqual(self.warps[-1][0], marker[0], places=6)
        self.assertAlmostEqual(self.warps[-1][1], marker[1], places=6)
        # The next motion is measured from the marker (where the cursor now is).
        before = self.values[-1]
        mx, my = self.warps[-1]
        field.drag_update(mx, my)
        self.assertEqual(self.values[-1], before)
        field.drag_end(mx, my)
        self.assertEqual(self.values[-1], before)       # not a tap: no jump

    def test_tap_uses_press_point(self):
        field = self.make(warp=True)
        x, y = field.point_at(0.8, 0.3)
        field.drag_begin(x, y)
        field.drag_end(x + 1.0, y)                       # release slightly off: still a tap there
        self.assertAlmostEqual(self.values[-1][0], 0.8, places=6)
        self.assertAlmostEqual(self.values[-1][1], 0.3, places=6)
        self.assertEqual(self.warps, [])

    def test_corners_point_into_the_field(self):
        field = self.make()
        corners = field.corners()
        self.assertEqual(len(corners), 4)
        step = 3.0
        for (cx, cy), e1, e2 in corners:
            self.assertAlmostEqual(e1[0] * e2[0] + e1[1] * e2[1], 0.0, places=3)   # perpendicular
            px, py = cx + (e1[0] + e2[0]) * step, cy + (e1[1] + e2[1]) * step
            self.assertTrue(field.contains(px, py), (cx, cy))
        # Ordered hard-linear, soft-linear, hard-sharp, soft-sharp.
        values = [field.field_at(*c) for c, _e1, _e2 in corners]
        self.assertGreater(values[0][0], values[1][0])
        self.assertLess(values[0][1], values[2][1])
        self.assertGreater(values[2][0], values[3][0])

    def test_preview_radius_scaled(self):
        field = self.make()
        self.assertGreater(field.preview_radius(), 0.0)
        self.assertEqual(pen_bar_ui.FIELD_PREVIEW_SCALE, 1.6)


if __name__ == '__main__':
    unittest.main()
