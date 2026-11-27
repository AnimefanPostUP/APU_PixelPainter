"""Unit tests for stroke spacing (model/spacing.py): Pixel step, Free spacing, Time.

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

spacing = importlib.import_module(f'{_PACKAGE}.model.spacing')


def _row(x0, x1, y=0):
    return [(x, y) for x in range(x0, x1 + 1)]


class ThinTest(unittest.TestCase):
    def test_every_pixel_by_default(self):
        steps = _row(1, 9)
        for mode in ('PIXEL', 'FREE'):
            kept, carry = spacing.thin(mode, steps, (0, 0), 0.0, 1)
            self.assertEqual(kept, steps)
            self.assertEqual(carry, 0.0)

    def test_pixel_step(self):
        kept, carry = spacing.thin('PIXEL', _row(1, 9), (0, 0), 0.0, 3)
        self.assertEqual(kept, [(3, 0), (6, 0), (9, 0)])
        self.assertEqual(carry, 0.0)

    def test_first_stamp_of_a_stroke(self):
        kept, _carry = spacing.thin('PIXEL', [(5, 5)], None, 0.0, 4)
        self.assertEqual(kept, [(5, 5)])

    def test_carry_across_events(self):
        kept, carry = spacing.thin('PIXEL', _row(1, 2), (0, 0), 0.0, 4)
        self.assertEqual(kept, [])
        self.assertEqual(carry, 2.0)
        kept, carry = spacing.thin('PIXEL', _row(3, 5), (2, 0), carry, 4)
        self.assertEqual(kept, [(4, 0)])
        self.assertEqual(carry, 1.0)

    def test_pixel_counts_diagonal_steps_as_one(self):
        diag = [(i, i) for i in range(1, 7)]
        kept, _ = spacing.thin('PIXEL', diag, (0, 0), 0.0, 2)
        self.assertEqual(kept, [(2, 2), (4, 4), (6, 6)])

    def test_free_uses_true_distance(self):
        diag = [(i, i) for i in range(1, 7)]       # ~1.41 px apart
        kept, _ = spacing.thin('FREE', diag, (0, 0), 0.0, 2)
        self.assertEqual(kept, [(2, 2), (4, 4), (6, 6)])
        kept, _ = spacing.thin('FREE', diag, (0, 0), 0.0, 4)
        self.assertEqual(kept, [(3, 3), (6, 6)])  # 4.24 px each


class ModeTest(unittest.TestCase):
    def test_cycle(self):
        self.assertEqual(spacing.next_mode('PIXEL'), 'FREE')
        self.assertEqual(spacing.next_mode('FREE'), 'TIME')
        self.assertEqual(spacing.next_mode('TIME'), 'PIXEL')
        self.assertEqual(spacing.next_mode('???'), spacing.DEFAULT_MODE)

    def test_defaults_are_one_pixel(self):
        self.assertEqual(spacing.DEFAULT_MODE, 'FREE')
        self.assertEqual(spacing.DEFAULTS['PIXEL'], 1)
        self.assertEqual(spacing.DEFAULTS['FREE'], 1)

    def test_clamp(self):
        self.assertEqual(spacing.clamp_value('PIXEL', 0), 1)
        self.assertEqual(spacing.clamp_value('TIME', 5), spacing.RANGES['TIME'][0])
        self.assertEqual(spacing.clamp_value('FREE', 3.6), 4)
        self.assertEqual(spacing.value_text('TIME', 120), "120 ms")


class SliderTest(unittest.TestCase):
    def test_time_first_60_percent_up_to_100_ms(self):
        lo, hi = spacing.RANGES['TIME']
        self.assertAlmostEqual(spacing.slider_value('TIME', 0.0), lo)
        self.assertAlmostEqual(spacing.slider_value('TIME', 0.6), 100.0)
        self.assertAlmostEqual(spacing.slider_value('TIME', 1.0), hi)
        self.assertLess(spacing.slider_value('TIME', 0.3), 100.0)
        self.assertGreater(spacing.slider_value('TIME', 0.8), 100.0)

    def test_inverse(self):
        for mode in spacing.MODES:
            for f in (0.0, 0.1, 0.35, 0.6, 0.75, 1.0):
                self.assertAlmostEqual(spacing.slider_fraction(mode, spacing.slider_value(mode, f)), f)

    def test_others_linear(self):
        lo, hi = spacing.RANGES['FREE']
        self.assertAlmostEqual(spacing.slider_value('FREE', 0.5), lo + (hi - lo) * 0.5)


class TimeTest(unittest.TestCase):
    def test_due(self):
        self.assertTrue(spacing.due(10.0, None, 100))
        self.assertFalse(spacing.due(10.05, 10.0, 100))
        self.assertTrue(spacing.due(10.1, 10.0, 100))


if __name__ == '__main__':
    unittest.main()
