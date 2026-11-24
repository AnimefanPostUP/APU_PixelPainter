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
color_history = importlib.import_module(f'{_PACKAGE}.tools.color_history')
color_palette = importlib.import_module(f'{_PACKAGE}.tools.color_palette')
palette_image = importlib.import_module(f'{_PACKAGE}.utils.palette_image')


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
# Color picker (E): the color selector at the cursor
# ---------------------------------------------------------------------------

color_pick = importlib.import_module(f'{_PACKAGE}.tools.subtools.color_pick')


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
    def __init__(self, layout='SQUARE'):
        self.state = {}
        self.settings = FakeSettings()
        self.warps = []
        window = types.SimpleNamespace(width=4000, height=4000,
                                       cursor_warp=lambda x, y: self.warps.append((x, y)))
        self.context = types.SimpleNamespace(window=window)
        self.wm = types.SimpleNamespace(pixel_painter_color_selector_layout=layout,
                                        pixel_painter_color_selector_model='HSV',
                                        pixel_painter_color_selector_sliders=set())

    def redraw(self):
        pass


def pointer(type_, value, x, y, shift=False):
    return framework.InputEvent(type_, value, mouse_x=x, mouse_y=y, mouse_region_x=x, mouse_region_y=y,
                                shift=shift)


class ColorPickTests(unittest.TestCase):
    def open(self, layout='SQUARE', x=1000, y=1000):
        self.ctx = PickerCtx(layout)
        self.host = framework.ToolFrame()
        self.picker = self.host.add_subtool(color_pick.ColorPickTool())
        self.now = [0.0]
        self.picker.clock = lambda: self.now[0]
        manager = framework.ToolManager(declare_state=lambda d, p: self.ctx.state.update(d))
        self.host.setup(manager)
        self.picker.activate(self.ctx, pointer('E', 'PRESS', x, y))
        self.sel = self.picker.selector

    def send(self, type_, value, x, y, shift=False):
        event = pointer(type_, value, x, y, shift)
        self.host.dispatch(self.ctx, event)
        return event

    def move(self, x, y, dt=0.01):
        self.now[0] += dt
        self.send('MOUSEMOVE', 'NOTHING', x, y)

    def test_uses_the_selected_layout(self):
        self.open('WHEEL')
        self.assertEqual(self.sel.layout_id, 'WHEEL')

    def test_opens_with_the_current_color_under_the_cursor(self):
        for layout in ('SHEET', 'SQUARE', 'TRIANGLE', 'WHEEL'):
            self.open(layout)
            px, py = self.sel.main_point()
            self.assertAlmostEqual(px, 1000)
            self.assertAlmostEqual(py, 1000)
            self.move(1000, 1000)
            self.assertEqual(self.ctx.settings.rgb, (1.0, 0.0, 0.0))   # no jump

    def test_main_area_follows_the_mouse(self):
        self.open()
        sq = self.sel.parts['SQUARE']
        self.move(sq.x0 + sq.width * 0.25, sq.y0 + sq.height * 0.5)
        self.assertAlmostEqual(self.ctx.state['sub_color_s'], 0.25)
        self.assertAlmostEqual(self.ctx.state['sub_color_v'], 0.5)
        self.assertTrue(self.picker.is_active)

    def test_click_on_main_area_applies_and_closes(self):
        self.open()
        sq = self.sel.parts['SQUARE']
        x, y = sq.x0 + sq.width * 0.5, sq.y0 + sq.height * 0.5
        self.move(x, y)
        self.send('LEFTMOUSE', 'PRESS', x, y)
        self.assertFalse(self.picker.is_active)
        r, g, b = self.ctx.settings.rgb
        self.assertAlmostEqual(r, 0.5)
        self.assertAlmostEqual(g, 0.25)

    def test_leaving_restores_the_rested_color(self):
        self.open()
        sq, hue = self.sel.parts['SQUARE'], self.sel.parts['HUE']
        self.move(sq.x0 + sq.width * 0.5, sq.cy)              # pick, then pause
        self.move(sq.x0 + sq.width * 0.6, sq.cy, dt=0.5)      # on the way to the hue bar
        self.move(sq.x1 - 1, sq.cy)
        self.move(hue.cx, hue.cy)                             # arrived: the paused color is back
        self.assertAlmostEqual(self.ctx.state['sub_color_s'], 0.5)

    def test_bar_click_and_drag(self):
        self.open()
        hue = self.sel.parts['HUE']
        self.move(hue.cx, hue.cy)
        self.send('LEFTMOUSE', 'PRESS', hue.cx, hue.y0 + hue.height * 0.25)
        self.send('LEFTMOUSE', 'RELEASE', hue.cx, hue.y0 + hue.height * 0.25)
        self.assertAlmostEqual(self.ctx.state['sub_color_h'], 0.25)
        self.assertTrue(self.picker.is_active)
        self.send('LEFTMOUSE', 'PRESS', hue.cx, hue.cy)
        self.send('MOUSEMOVE', 'NOTHING', hue.cx, hue.cy + hue.height * 0.2)   # gain 0.5
        self.send('LEFTMOUSE', 'RELEASE', hue.cx, hue.cy + hue.height * 0.2)
        self.assertAlmostEqual(self.ctx.state['sub_color_h'], 0.35)

    def test_wheel_over_main_area_sets_the_free_channel(self):
        self.open('SHEET')
        self.send('WHEELDOWNMOUSE', 'PRESS', 1000, 1000)
        self.assertAlmostEqual(self.ctx.state['sub_color_s'], 0.95)   # sheet: saturation
        self.open('WHEEL')
        self.send('WHEELDOWNMOUSE', 'PRESS', 1000, 1000)
        self.assertAlmostEqual(self.ctx.state['sub_color_v'], 0.95)   # wheel: value

    def test_wheel_over_a_bar_sets_that_bar(self):
        self.open('SHEET')
        val = self.sel.parts['VALUE']
        self.send('WHEELDOWNMOUSE', 'PRESS', val.cx, val.cy)
        self.assertAlmostEqual(self.ctx.state['sub_color_v'], 0.95)
        self.assertAlmostEqual(self.ctx.state['sub_color_s'], 1.0)

    def test_click_outside_confirms(self):
        self.open()
        sq = self.sel.parts['SQUARE']
        self.move(sq.cx, sq.cy)
        self.send('LEFTMOUSE', 'PRESS', 3000, 3000)
        self.assertFalse(self.picker.is_active)

    def test_cancel_restores(self):
        self.open()
        sq = self.sel.parts['SQUARE']
        self.move(sq.cx, sq.cy)
        self.send('RIGHTMOUSE', 'PRESS', sq.cx, sq.cy)
        self.assertFalse(self.picker.is_active)
        self.assertEqual(self.ctx.settings.rgb, (1.0, 0.0, 0.0))

    def test_esc_during_bar_drag_only_discards_the_drag(self):
        self.open()
        hue = self.sel.parts['HUE']
        self.send('LEFTMOUSE', 'PRESS', hue.cx, hue.cy)
        self.send('MOUSEMOVE', 'NOTHING', hue.cx, hue.cy + 40)
        self.send('ESC', 'PRESS', hue.cx, hue.cy + 40)
        self.assertTrue(self.picker.is_active)
        self.assertAlmostEqual(self.ctx.state['sub_color_h'], 0.0)

    def test_e_toggles_target(self):
        self.open()
        self.send('E', 'PRESS', 1000, 1000)
        self.assertEqual(self.ctx.state['sub_color_target'], 'SECONDARY')
        self.assertAlmostEqual(self.ctx.state['sub_color_h'], 2 / 3)   # blue
        self.assertEqual(self.picker.panel.title, "Secondary Color")

    def shift_move(self, dx, dy):
        """Move the mouse by ``dx``/``dy`` with Shift held, from where the OS cursor is
        (after the picker's warps, as Blender reports it)."""
        x, y = self.ctx.warps[-1] if self.ctx.warps else self.cursor
        self.cursor = (x + dx, y + dy)
        self.now[0] += 0.01
        self.send('MOUSEMOVE', 'NOTHING', x + dx, y + dy, shift=True)

    def test_shift_slows_the_mouse_on_the_main_area(self):
        self.open()
        sq = self.sel.parts['SQUARE']
        self.cursor = (1000, 1000)                       # red: saturation 1 (right edge)
        self.ctx.warps.clear()
        for _ in range(5):
            self.shift_move(-10, 0)                      # 50 px of mouse travel ...
        travelled = 50 * color_pick.SLOW_FACTOR          # ... moves the pick 10 px
        self.assertAlmostEqual(self.ctx.state['sub_color_s'], 1.0 - travelled / sq.width)
        self.assertEqual(self.ctx.warps[-1], (990, 1000))   # the cursor itself crawls

    def test_shift_slows_slider_drags(self):
        self.open()
        hue = self.sel.parts['HUE']
        self.move(hue.cx, hue.cy)
        self.cursor = (hue.cx, hue.cy)
        self.ctx.warps.clear()
        self.send('LEFTMOUSE', 'PRESS', hue.cx, hue.cy)
        self.shift_move(0, 50)
        x, y = self.ctx.warps[-1]
        self.send('LEFTMOUSE', 'RELEASE', x, y)
        # 50 px slowed to 10 px, times the swipe gain 0.5
        self.assertAlmostEqual(self.ctx.state['sub_color_h'], 10 * 0.5 / hue.height)

    def test_releasing_shift_moves_normally_again(self):
        self.open()
        sq = self.sel.parts['SQUARE']
        self.cursor = (1000, 1000)
        self.shift_move(-10, 0)
        x, y = self.ctx.warps[-1]
        self.move(x - 20, y)                             # no Shift: full speed, absolute
        self.assertAlmostEqual(self.ctx.state['sub_color_s'], 1.0 - 22 / sq.width)

    def test_previous_color_is_remembered(self):
        self.open()
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
        self.assertAlmostEqual(self.pad.drag['color'][0], 0.75)
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


class ColorHistoryTests(unittest.TestCase):
    def test_newest_first_without_repeats(self):
        state = {}
        for rgb in ((1, 0, 0), (0, 1, 0), (1, 0, 0.0002)):   # the last one equals the first
            color_history.record(state, rgb)
        self.assertEqual(color_history.colors(state), [(1.0, 0.0, 0.0002), (0.0, 1.0, 0.0)])

    def test_capped(self):
        state = {}
        for i in range(12):
            color_history.record(state, (i / 12, 0, 0), size=8)
        self.assertEqual(len(color_history.colors(state)), 8)
        self.assertEqual(color_history.colors(state)[0][0], round(11 / 12, 4))


class ColorPaletteTests(unittest.TestCase):
    def setUp(self):
        cp = color_palette
        self.cp = cp
        self.red = cp.with_color(cp.empty_palette("Reds"), 0, (1.0, 0.0, 0.0))

    def test_sizes(self):
        self.assertEqual((self.cp.PALETTE_SIZE, self.cp.PROJECT_SLOTS), (24, 24))

    def test_project_round_trip(self):
        cp = self.cp
        project = cp.with_active(cp.with_palette(cp.empty_project(), 3, self.red), 3)
        back = cp.decode_project(cp.encode_project(project))
        self.assertEqual(back, project)
        self.assertEqual(cp.active_palette(back)["colors"][0], (1.0, 0.0, 0.0))

    def test_decode_tolerates_bad_data(self):
        cp = self.cp
        self.assertEqual(cp.decode_project(""), cp.empty_project())
        self.assertEqual(cp.decode_project("not json"), cp.empty_project())
        self.assertEqual(cp.decode_library('{"palettes": [null, 5, {"colors": ["#00ff00"]}]}')[0]["colors"][0],
                         (0.0, 1.0, 0.0))

    def test_edit_active_creates_a_palette_in_an_empty_slot(self):
        cp = self.cp
        project = cp.edit_active(cp.empty_project(), lambda pal: cp.with_color(pal, 2, (0, 0, 1)))
        self.assertEqual(cp.active_palette(project)["name"], "Palette 1")
        self.assertEqual(cp.active_palette(project)["colors"][2], (0.0, 0.0, 1.0))

    def test_swapping_palettes_keeps_the_active_one_active(self):
        cp = self.cp
        project = cp.with_active(cp.with_palette(cp.empty_project(), 0, self.red), 0)
        swapped = cp.with_swapped_palettes(project, 0, 5)
        self.assertEqual((swapped["active"], swapped["palettes"][5]["name"]), (5, "Reds"))

    def test_inputs_are_not_modified(self):
        cp = self.cp
        project = cp.empty_project()
        cp.with_palette(project, 0, self.red)
        self.assertIsNone(project["palettes"][0])

    def test_clipboard_round_trip(self):
        cp = self.cp
        back = cp.from_text(cp.to_text(self.red))
        self.assertEqual((back["name"], back["colors"][0], back["colors"][1]), ("Reds", (1.0, 0.0, 0.0), None))

    def test_paste_plain_hex_codes(self):
        pal = self.cp.from_text("my palette: #FF0000, 00ff00 / #0000ff and junk")
        self.assertEqual(self.cp.filled(pal), [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)])

    def test_paste_without_colors_is_none(self):
        self.assertIsNone(self.cp.from_text("hello"))
        self.assertIsNone(self.cp.from_text('{"colors": []}'))

    def test_library_round_trip(self):
        cp = self.cp
        self.assertEqual(cp.decode_library(cp.encode_library([self.red])), [self.red])


class PaletteFromImageTests(unittest.TestCase):
    @staticmethod
    def image(rows):
        """Blender-style flat RGBA buffer (bottom row first) from rows given top row first."""
        flat = []
        for row in reversed(rows):
            for px in row:
                flat += list(px)
        return flat, len(rows[0]), len(rows)

    R, G, B, W = (1, 0, 0, 1), (0, 1, 0, 1), (0, 0, 1, 1), (1, 1, 1, 1)

    def test_distinct_colors_in_reading_order(self):
        buf, w, h = self.image([[self.B, self.R], [self.R, self.G]])
        colors, distinct = palette_image.extract_colors(buf, w, h)
        self.assertEqual(colors, [(0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)])
        self.assertEqual(distinct, 3)

    def test_transparent_pixels_are_ignored(self):
        buf, w, h = self.image([[(1, 0, 0, 0.0), self.G]])
        self.assertEqual(palette_image.extract_colors(buf, w, h)[0], [(0.0, 1.0, 0.0)])

    def test_many_colors_are_reduced(self):
        row = [(i / 99.0, (i * 7 % 100) / 99.0, 0.5, 1.0) for i in range(100)]
        buf, w, h = self.image([row])
        colors, distinct = palette_image.extract_colors(buf, w, h, max_colors=24)
        self.assertEqual((len(colors), distinct), (24, 100))
        for c in colors:
            self.assertTrue(all(0.0 <= v <= 1.0 for v in c))

    def test_empty_image(self):
        self.assertEqual(palette_image.extract_colors([], 0, 0), ([], 0))


if __name__ == '__main__':
    unittest.main()
