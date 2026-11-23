"""Unit tests for the pen support: pressure math, pen-friendly UI-kit interaction,
screen-space dispatch.

Runs with plain Python (no Blender needed) from the addon root:

    python -m unittest discover -s tests -v
"""

import importlib
import os
import sys
import types
import unittest

_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PACKAGE = os.path.basename(_ADDON_DIR)
sys.path.insert(0, os.path.dirname(_ADDON_DIR))  # for the package import
sys.path.insert(0, _ADDON_DIR)                   # first: `ui` must be this addon's ui package
sys.modules.setdefault('bpy', types.ModuleType('bpy'))  # the package __init__ imports bpy

from ui.kit import Button, ColorPad, DragBubble, hsv_for_rgb, Overlay, Panel, Row, RoundButton, UIEvent  # noqa: E402
from ui.kit.events import PASS_THROUGH, RUNNING  # noqa: E402

framework = importlib.import_module(f'{_PACKAGE}.core.framework')
pen_pressure = importlib.import_module(f'{_PACKAGE}.tools.pen_pressure')


def ev(type_, value='PRESS', x=0.0, y=0.0):
    return UIEvent(type=type_, value=value, x=x, y=y)


def move(x, y):
    return ev('MOUSEMOVE', 'NOTHING', x, y)


# ---------------------------------------------------------------------------
# Pressure
# ---------------------------------------------------------------------------

class PressureTests(unittest.TestCase):
    def test_factor_is_pressure_without_minimum(self):
        self.assertAlmostEqual(pen_pressure.factor(0.25), 0.25)
        self.assertAlmostEqual(pen_pressure.factor(1.7), 1.0)   # clamped
        self.assertAlmostEqual(pen_pressure.factor(-1.0), 0.0)

    def test_factor_minimum_floor(self):
        self.assertAlmostEqual(pen_pressure.factor(0.0, 0.2), 0.2)
        self.assertAlmostEqual(pen_pressure.factor(0.5, 0.2), 0.6)
        self.assertAlmostEqual(pen_pressure.factor(1.0, 0.2), 1.0)

    def test_scale_radius_scales_diameter(self):
        self.assertEqual(pen_pressure.scale_radius(4, 1.0), 4)    # 9 px stays 9 px
        self.assertEqual(pen_pressure.scale_radius(4, 0.5), 2)    # 9 -> 5 px
        self.assertEqual(pen_pressure.scale_radius(1, 0.3), 0)    # 3 -> 1 px
        self.assertEqual(pen_pressure.scale_radius(10, 0.0), 0)   # never below one pixel

    def test_apply_only_enabled_channels(self):
        pen = pen_pressure.PenPressure(pressure=0.5, channels=frozenset({'strength', 'modifier'}))
        self.assertEqual(pen.apply(4, 0.8, 1.0, 0.6), (4, 0.4, 1.0, 0.3))

    def test_no_channels_is_identity(self):
        pen = pen_pressure.PenPressure(pressure=0.1)
        self.assertEqual(pen.apply(3, 0.7, 0.5, 0.2), (3, 0.7, 0.5, 0.2))

    def test_from_settings(self):
        wm = types.SimpleNamespace(pixel_painter_pen_pressure_size=True,
                                   pixel_painter_pen_pressure_alpha=True,
                                   pixel_painter_pen_pressure_min=0.5)
        pen = pen_pressure.from_settings(wm, {'pen_pressure': 0.0})
        self.assertEqual(pen.channels, frozenset({'size', 'alpha'}))
        self.assertAlmostEqual(pen.multiplier, 0.5)

    def test_input_event_carries_pressure(self):
        raw = types.SimpleNamespace(type='MOUSEMOVE', value='NOTHING', shift=False, ctrl=False, alt=False,
                                    mouse_x=1, mouse_y=2, mouse_region_x=1, mouse_region_y=2,
                                    pressure=0.3, is_tablet=True)
        event = framework.InputEvent.from_blender(raw)
        self.assertAlmostEqual(event.pressure, 0.3)
        self.assertTrue(event.is_tablet)


# ---------------------------------------------------------------------------
# UI kit: drag knobs, press-activated openers, drag-release into a flyout
# ---------------------------------------------------------------------------

class DragTests(unittest.TestCase):
    def setUp(self):
        self.log = []
        self.knob = DragBubble(
            "Size", radius=20.0,
            on_drag_begin=lambda: self.log.append('begin'),
            on_drag=lambda dx, dy: self.log.append(('drag', dx, dy)),
            on_drag_end=lambda cancelled: self.log.append(('end', cancelled)),
        )
        self.ui = Overlay(self.knob, modal=False, animate=False)  # knob centered at (0, 0)

    def test_drag_reports_offset_from_press_and_captures_pointer(self):
        self.assertEqual(self.ui.handle(ev('LEFTMOUSE', 'PRESS', 5, 5)), RUNNING)
        # Far outside the knob: still the knob's drag, consumed.
        self.assertEqual(self.ui.handle(move(5, 200)), RUNNING)
        self.assertEqual(self.ui.handle(ev('LEFTMOUSE', 'RELEASE', 5, 200)), RUNNING)
        self.assertEqual(self.log, ['begin', ('drag', 0, 195), ('end', False)])
        self.assertIsNone(self.ui.dragging)

    def test_cancel_during_drag(self):
        self.ui.handle(ev('LEFTMOUSE', 'PRESS', 0, 0))
        self.ui.handle(ev('RIGHTMOUSE', 'PRESS', 0, 0))
        self.assertEqual(self.log[-1], ('end', True))
        self.assertIsNone(self.ui.dragging)

    def test_host_can_end_drag(self):
        self.ui.handle(ev('LEFTMOUSE', 'PRESS', 0, 0))
        self.ui.end_drag()
        self.assertEqual(self.log[-1], ('end', False))

    def test_moves_without_drag_pass_through(self):
        self.assertEqual(self.ui.handle(move(0, 0)), PASS_THROUGH)


class FlyoutTests(unittest.TestCase):
    """Pen flow: press an opener, drag onto an entry, lift -- no hover in between."""

    def setUp(self):
        self.log = []
        self.entry = Button("Entry", key='ENTRY', size=(40.0, 40.0), on_click=lambda: self.log.append('entry'))
        self.entry.drag_release = True
        self.entry.visible = False
        self.opener = RoundButton("Open", key='OPEN', radius=20.0, on_click=self._open)
        self.opener.activate_on_press = True
        self.root = Row([self.opener, Panel(self.entry, padding=0.0)], gap=60.0)
        self.ui = Overlay(self.root, modal=False, animate=False)

    def _open(self):
        self.log.append('open')
        self.entry.visible = True
        self.ui.layout()

    def test_press_opens_and_release_over_entry_activates(self):
        ox, oy = self.opener.rect.cx, self.opener.rect.cy
        self.assertEqual(self.ui.handle(ev('LEFTMOUSE', 'PRESS', ox, oy)), RUNNING)
        self.assertEqual(self.log, ['open'])
        ex, ey = self.entry.rect.cx, self.entry.rect.cy
        self.ui.handle(move(ex, ey))
        self.assertEqual(self.ui.handle(ev('LEFTMOUSE', 'RELEASE', ex, ey)), RUNNING)
        self.assertEqual(self.log, ['open', 'entry'])

    def test_release_after_foreign_press_does_not_activate(self):
        self._open()
        ex, ey = self.entry.rect.cx, self.entry.rect.cy
        # A press elsewhere (painting) is not ours ...
        self.assertEqual(self.ui.handle(ev('LEFTMOUSE', 'PRESS', 900, 900)), PASS_THROUGH)
        # ... so dragging onto the entry and lifting does not trigger it.
        self.assertEqual(self.ui.handle(ev('LEFTMOUSE', 'RELEASE', ex, ey)), PASS_THROUGH)
        self.assertEqual(self.log, ['open'])

    def test_tap_on_entry_still_works(self):
        self._open()
        ex, ey = self.entry.rect.cx, self.entry.rect.cy
        self.ui.handle(ev('LEFTMOUSE', 'PRESS', ex, ey))
        self.ui.handle(ev('LEFTMOUSE', 'RELEASE', ex, ey))
        self.assertEqual(self.log, ['open', 'entry'])


# ---------------------------------------------------------------------------
# Framework: screen-space tools
# ---------------------------------------------------------------------------

class FakeCtx:
    mode = 'A'

    def set_mode(self, tool_id):
        self.mode = tool_id


class ScreenDispatchTests(unittest.TestCase):
    def setUp(self):
        self.log = []

        class Screen(framework.ToolFrame):
            is_global = True
            screen_space = True

            def on_event(inner, ctx, event):
                self.log.append(('screen', event.type))
                if event.type == 'X':
                    event.consume()

        class Paint(framework.ToolFrame):
            tool_id = 'A'

            def on_event(inner, ctx, event):
                self.log.append(('paint', event.type))

        self.manager = framework.ToolManager()
        self.manager.register_all([Paint(), Screen()])
        self.ctx = FakeCtx()
        self.manager.begin(self.ctx)

    def test_screen_tool_sees_each_event_once(self):
        event = framework.InputEvent('LEFTMOUSE', 'PRESS')
        self.assertFalse(self.manager.dispatch_screen(self.ctx, event))
        self.manager.dispatch(self.ctx, event)
        self.assertEqual(self.log, [('screen', 'LEFTMOUSE'), ('paint', 'LEFTMOUSE')])

    def test_consumed_by_screen_tool(self):
        event = framework.InputEvent('X', 'PRESS')
        self.assertTrue(self.manager.dispatch_screen(self.ctx, event))
        self.assertEqual(self.log, [('screen', 'X')])

    def test_screen_tool_can_remap_event_for_later_tools(self):
        class Remap(framework.ToolFrame):
            is_global = True
            screen_space = True

            def on_event(inner, ctx, event):
                event.type = 'RIGHTMOUSE'

        manager = framework.ToolManager()
        seen = []

        class Paint(framework.ToolFrame):
            tool_id = 'A'

            def on_event(inner, ctx, event):
                seen.append(event.type)

        manager.register_all([Paint(), Remap()])
        manager.begin(self.ctx)
        event = framework.InputEvent('LEFTMOUSE', 'PRESS')
        manager.dispatch_screen(self.ctx, event)
        manager.dispatch(self.ctx, event)
        self.assertEqual(seen, ['RIGHTMOUSE'])


# ---------------------------------------------------------------------------
# Color picker: saturation slider (drag like a wheel, tap to jump)
# ---------------------------------------------------------------------------

color_pick = importlib.import_module(f'{_PACKAGE}.tools.subtools.color_pick')
helpers = importlib.import_module(f'{_PACKAGE}.tools.subtools.helpers')


class FakeSettings:
    def __init__(self):
        self.rgb = (1.0, 0.0, 0.0)          # pure red: h 0, s 1, v 1
        self.secondary = (0.0, 0.0, 1.0)

    def get_brush_rgb(self, context):
        return self.rgb

    def get_brush_secondary_rgb(self, context):
        return self.secondary

    def set_brush_rgb(self, context, r, g, b):
        self.rgb = (r, g, b)

    def set_brush_secondary_rgb(self, context, r, g, b):
        self.secondary = (r, g, b)


class PickerCtx:
    def __init__(self):
        self.state = {}
        self.settings = FakeSettings()
        window = types.SimpleNamespace(width=4000, height=4000, cursor_warp=lambda x, y: None)
        self.context = types.SimpleNamespace(window=window)

    def redraw(self):
        pass


def pointer(type_, value, x, y):
    return framework.InputEvent(type_, value, mouse_x=x, mouse_y=y, mouse_region_x=x, mouse_region_y=y)


class SaturationSliderTests(unittest.TestCase):
    def open(self, tool_cls, x=1000, y=1000, trigger='E'):
        self.ctx = PickerCtx()
        self.host = framework.ToolFrame()
        self.picker = self.host.add_subtool(tool_cls())
        manager = framework.ToolManager(declare_state=lambda d, p: self.ctx.state.update(d))
        self.host.setup(manager)
        self.picker.activate(self.ctx, pointer(trigger, 'PRESS', x, y))
        x0, y0, x1, y1 = helpers.sat_bar_rect(self.ctx.state)
        self.bar_x, self.bar_bottom, self.bar_top = (x0 + x1) / 2, y0, y1

    def send(self, type_, value, x, y):
        event = pointer(type_, value, x, y)
        self.host.dispatch(self.ctx, event)
        return event

    def test_swipe_is_relative_and_does_not_confirm(self):
        self.open(color_pick.ColorPickTool)
        state = self.ctx.state
        h, v = state['sub_color_h'], state['sub_color_v']
        mid = (self.bar_bottom + self.bar_top) / 2
        self.send('MOUSEMOVE', 'NOTHING', self.bar_x, mid)       # onto the slider
        self.assertEqual((state['sub_color_h'], state['sub_color_v']), (h, v))  # hue/value hold
        self.assertTrue(state['sub_color_sat_hover'])
        self.send('LEFTMOUSE', 'PRESS', self.bar_x, mid)
        self.assertTrue(self.picker.is_active)                   # grabbed, not applied
        self.send('MOUSEMOVE', 'NOTHING', self.bar_x, mid - 60)  # swipe down 60 px
        self.send('LEFTMOUSE', 'RELEASE', self.bar_x, mid - 60)
        self.assertAlmostEqual(state['sub_color_s'], 0.8)        # 1.0 - 60/300, no jump to mid
        self.assertTrue(self.picker.is_active)
        self.assertAlmostEqual(self.ctx.settings.rgb[1], 0.2)    # written live (red, s 0.8)

    def test_tap_jumps(self):
        self.open(color_pick.ColorPickTool)
        self.send('LEFTMOUSE', 'PRESS', self.bar_x, self.bar_bottom + 75)
        self.send('LEFTMOUSE', 'RELEASE', self.bar_x, self.bar_bottom + 75)
        self.assertAlmostEqual(self.ctx.state['sub_color_s'], 0.25)

    def test_press_on_sheet_still_applies(self):
        self.open(color_pick.ColorPickTool)
        self.send('LEFTMOUSE', 'PRESS', 1000, 1000)
        self.assertFalse(self.picker.is_active)

    def test_previous_color_is_remembered(self):
        self.open(color_pick.ColorPickTool)
        state = self.ctx.state
        self.assertEqual((state['sub_color_start_h'], state['sub_color_start_s'], state['sub_color_start_v']),
                         (0.0, 1.0, 1.0))



# ---------------------------------------------------------------------------
# Color pad: touchpad-style swiping
# ---------------------------------------------------------------------------

class ColorPadTests(unittest.TestCase):
    def setUp(self):
        self.hsv = (0.5, 0.5, 0.5)
        self.writes = 0

        def set_hsv(h, s, v):
            self.hsv = (h, s, v)
            self.writes += 1

        # gain 1: the selection moves exactly as far as the pen (in part lengths).
        self.pad = ColorPad(lambda: self.hsv, set_hsv, sheet_size=(100.0, 100.0), bar=10.0, gap=5.0, gain=1.0)
        self.ui = Overlay(self.pad, modal=False, animate=False)
        self.sheet = self.pad.parts['SHEET']

    def swipe(self, x, y, dx, dy, cancel=False):
        self.ui.handle(ev('LEFTMOUSE', 'PRESS', x, y))
        self.ui.handle(move(x + dx, y + dy))
        if cancel:
            self.ui.handle(ev('ESC', 'PRESS', x + dx, y + dy))
        else:
            self.ui.handle(ev('LEFTMOUSE', 'RELEASE', x + dx, y + dy))

    def test_sheet_swipe_is_relative(self):
        # Press far from the cursor (which sits at the center): no jump, it moves by the swipe.
        self.swipe(self.sheet.x0 + 5, self.sheet.y0 + 5, 20, -10)
        h, s, v = self.hsv
        self.assertAlmostEqual(h, 0.7)
        self.assertAlmostEqual(v, 0.4)
        self.assertAlmostEqual(s, 0.5)

    def test_hue_wraps_value_clamps(self):
        self.swipe(self.sheet.cx, self.sheet.cy, 70, 80)
        h, _s, v = self.hsv
        self.assertAlmostEqual(h, 0.2)
        self.assertAlmostEqual(v, 1.0)

    def test_saturation_bar(self):
        sat = self.pad.parts['SATURATION']
        self.swipe(sat.cx, sat.cy, 0, 30)
        self.assertAlmostEqual(self.hsv[1], 0.8)
        self.assertAlmostEqual(self.hsv[0], 0.5)

    def test_value_and_hue_bars(self):
        val, hue = self.pad.parts['VALUE'], self.pad.parts['HUE']
        self.swipe(val.cx, val.cy, 0, -20)
        self.assertAlmostEqual(self.hsv[2], 0.3)
        self.swipe(hue.cx, hue.cy, -10, 0)
        self.assertAlmostEqual(self.hsv[0], 0.4)

    def test_tap_jumps(self):
        self.ui.handle(ev('LEFTMOUSE', 'PRESS', self.sheet.x0 + 25, self.sheet.y0 + 90))
        self.ui.handle(ev('LEFTMOUSE', 'RELEASE', self.sheet.x0 + 25, self.sheet.y0 + 90))
        h, _s, v = self.hsv
        self.assertAlmostEqual(h, 0.25)
        self.assertAlmostEqual(v, 0.9)

    def test_cancel_discards(self):
        self.swipe(self.sheet.cx, self.sheet.cy, 30, 30, cancel=True)
        self.assertEqual(self.hsv, (0.5, 0.5, 0.5))
        self.assertEqual(self.writes, 0)

    def test_commits_once_on_release(self):
        x, y = self.sheet.cx, self.sheet.cy
        self.ui.handle(ev('LEFTMOUSE', 'PRESS', x, y))
        for step in range(1, 6):
            self.ui.handle(move(x + step * 5, y))
        self.assertEqual(self.writes, 0)             # shown live, not written
        self.assertAlmostEqual(self.pad.drag['hsv'][0], 0.75)
        self.ui.handle(ev('LEFTMOUSE', 'RELEASE', x + 25, y))
        self.assertEqual(self.writes, 1)
        self.assertAlmostEqual(self.hsv[0], 0.75)

    def test_live_commits_while_dragging_and_cancel_restores(self):
        self.pad.live = lambda: True
        x, y = self.sheet.cx, self.sheet.cy
        self.ui.handle(ev('LEFTMOUSE', 'PRESS', x, y))
        self.ui.handle(move(x + 10, y))
        self.assertAlmostEqual(self.hsv[0], 0.6)      # applied during the press
        self.ui.handle(move(x + 20, y))
        self.assertAlmostEqual(self.hsv[0], 0.7)
        self.ui.handle(ev('ESC', 'PRESS', x + 20, y))
        self.assertEqual(self.hsv, (0.5, 0.5, 0.5))   # live steps undone

    def test_press_in_corner_grabs_nearest_bar(self):
        self.assertEqual(self.pad.part_at(self.pad.rect.x0 + 1, self.pad.rect.y0 + 1), 'HUE')
        self.assertEqual(self.pad.part_at(self.pad.rect.x0 + 1, self.sheet.cy), 'VALUE')


class HsvMemoryTests(unittest.TestCase):
    """The pen bar keeps the pad's HSV while the brush still has the color it wrote."""

    def test_hue_and_saturation_survive_black(self):
        self.assertEqual(hsv_for_rgb((0.0, 0.0, 0.0), ((0.0, 0.0, 0.0), (0.6, 0.7, 0.0))), (0.6, 0.7, 0.0))

    def test_hue_survives_grey_changed_elsewhere(self):
        h, s, v = hsv_for_rgb((0.5, 0.5, 0.5), ((0.1, 0.2, 0.3), (0.6, 0.7, 0.3)))
        self.assertEqual((h, s, v), (0.6, 0.0, 0.5))

    def test_external_change_is_picked_up(self):
        h, s, v = hsv_for_rgb((0.0, 1.0, 0.0), ((0.2, 0.3, 0.4), (0.6, 0.5, 0.4)))
        self.assertAlmostEqual(h, 1 / 3)
        self.assertEqual((s, v), (1.0, 1.0))

    def test_nothing_remembered(self):
        self.assertEqual(hsv_for_rgb((1.0, 0.0, 0.0)), (0.0, 1.0, 1.0))


if __name__ == '__main__':
    unittest.main()
