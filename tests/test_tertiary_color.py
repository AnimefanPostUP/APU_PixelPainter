"""Tests for the pen menu's tertiary color actions (tools/pen_bar.py): selecting it,
the color the selector edits meanwhile, and leaving it again.

Runs with plain Python (no Blender needed) from the addon root:

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

# Blender stubs, removed again after the import (as in test_native.py).
_MODULES_BEFORE = set(sys.modules)
_ADDED_ATTRS = []


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
              'mathutils.bvhtree', 'mathutils.kdtree', 'bmesh', 'blf', 'gpu', 'gpu_extras',
              'gpu_extras.batch'):
    sys.modules.setdefault(_name, _AnyModule(_name))
_stub('bpy', types=_Anything(), props=_Anything(), utils=_Anything(), app=_Anything(), context=_Anything())

pen_bar_tool = importlib.import_module(f'{_PACKAGE}.tools.pen.tool')
pen_color_widgets = importlib.import_module(f'{_PACKAGE}.ui.pen.color_widgets')
pen_metrics = importlib.import_module(f'{_PACKAGE}.ui.pen.metrics')
kit = importlib.import_module(f'{_PACKAGE}.ui.kit')

for _name in set(sys.modules) - _MODULES_BEFORE:
    del sys.modules[_name]
for _module, _attr in _ADDED_ATTRS:
    delattr(_module, _attr)


class _Settings:
    def __init__(self):
        self.rgb = (1.0, 0.0, 0.0)
        self.secondary = (0.0, 0.0, 1.0)

    def get_brush_rgb(self, context):
        return self.rgb

    def get_brush_secondary_rgb(self, context):
        return self.secondary

    def set_brush_rgb(self, context, r, g, b):
        self.rgb = (r, g, b)

    def set_brush_secondary_rgb(self, context, r, g, b):
        self.secondary = (r, g, b)


class _Ctx:
    def __init__(self):
        self.state = {'pen_rmb_lock': False}
        self.settings = _Settings()
        self.context = None
        self.wm = types.SimpleNamespace(pixel_painter_pen_color_preview=False)

    def apply_tool_settings(self):
        pass


class PenTertiaryActionTests(unittest.TestCase):
    def setUp(self):
        self.tool = pen_bar_tool.PenBarTool(registry=None)
        self.ctx = _Ctx()
        self.tool._ctx = self.ctx

    def test_slider_selects_the_tertiary_color(self):
        self.tool.set_tertiary_t(0.25)
        self.assertTrue(self.tool.tertiary_active())
        self.assertEqual(self.tool.tertiary_color(), (0.75, 0.0, 0.25))
        self.assertEqual(self.tool.pen_rgb(), (0.75, 0.0, 0.25))
        self.assertEqual(self.tool.color_role('PRIMARY'), 'TARGET')
        self.assertIsNone(self.tool.color_role('SECONDARY'))

    def test_secondary_selected_drops_the_rmb_lock(self):
        self.tool.set_rmb_lock(True)
        self.tool.select_tertiary()
        self.assertFalse(self.tool.rmb_lock())
        self.assertEqual(self.tool.color_target(), 'SECONDARY')   # the selector keeps editing it

    def test_tap_switches_the_edited_color_then_selects_it(self):
        self.tool.select_tertiary()
        self.tool.select_color('SECONDARY')
        self.assertTrue(self.tool.tertiary_active())
        self.assertEqual(self.tool.color_role('SECONDARY'), 'TARGET')
        self.tool.set_pen_hsv(1 / 3, 1.0, 1.0)                     # the selector edits the secondary
        self.assertEqual(self.ctx.settings.secondary, (0.0, 1.0, 0.0))
        self.assertEqual(self.ctx.settings.rgb, (1.0, 0.0, 0.0))
        self.tool.select_color('SECONDARY')                         # tap again: paint with it
        self.assertFalse(self.tool.tertiary_active())
        self.assertTrue(self.tool.rmb_lock())
        self.assertEqual(self.tool.color_role('SECONDARY'), 'ACTIVE')

    def test_bubble_toggles(self):
        self.tool.toggle_tertiary()
        self.assertTrue(self.tool.tertiary_active())
        self.tool.toggle_tertiary()
        self.assertFalse(self.tool.tertiary_active())
        self.assertEqual(self.tool.color_role('PRIMARY'), 'ACTIVE')

    def test_history_color_leaves_the_tertiary_color(self):
        self.tool.select_tertiary()
        self.tool.use_history_color((0.0, 1.0, 0.0))
        self.assertFalse(self.tool.tertiary_active())
        self.assertEqual(self.ctx.settings.rgb, (0.0, 1.0, 0.0))


class GradientSliderTests(unittest.TestCase):
    def setUp(self):
        self.values = []
        self.slider = pen_color_widgets.GradientSlider("T", colors=lambda: ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
                                                 value=lambda: 0.5, active=lambda: True,
                                                 on_value=self.values.append)
        dial = kit.Dial(kit.RingSegment("Center", key='CENTER'), gap=pen_metrics.DIAL_GAP)
        dial.add_band([self.slider], pen_metrics.CORNER_INNER, pen_metrics.CORNER_INNER + pen_metrics.HISTORY_DEPTH,
                      *pen_metrics.COLORS_ARC)
        dial.arrange(kit.Rect(-400.0, -400.0, 400.0, 400.0), kit.Theme())
        self.r = (self.slider.pr0 + self.slider.pr1) * 0.5

    def at(self, degrees):
        a = math.radians(degrees)
        return math.cos(a) * self.r, math.sin(a) * self.r

    def test_primary_at_the_left_secondary_at_the_top(self):
        self.assertEqual(self.slider.value_at(*self.at(179.9)), 0.0)
        self.assertEqual(self.slider.value_at(*self.at(90.1)), 1.0)
        self.assertAlmostEqual(self.slider.value_at(*self.at(135.0)), 0.5, places=2)

    def test_past_the_ends_clamps(self):
        self.assertEqual(self.slider.value_at(*self.at(250.0)), 0.0)
        self.assertEqual(self.slider.value_at(*self.at(30.0)), 1.0)

    def test_drag_reports_values(self):
        self.slider.drag_begin(*self.at(160.0))
        self.slider.drag_update(*self.at(110.0))
        self.slider.drag_end(*self.at(110.0))
        self.assertEqual(len(self.values), 2)
        self.assertLess(self.values[0], 0.5)
        self.assertGreater(self.values[1], 0.5)


if __name__ == '__main__':
    unittest.main()
