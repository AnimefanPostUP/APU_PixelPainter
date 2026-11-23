"""Unit tests for the UI kit's layout and interaction logic.

Runs with plain Python (no Blender needed) from the addon root:

    python -m unittest discover -s tests -v
"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from ui.kit import (  # noqa: E402
    BubbleButton, Button, Grid, Overlay, Panel, RadialMenu, Rect, Theme, UIEvent,
)
from ui.kit.events import CANCELLED, FINISHED, PASS_THROUGH, RUNNING  # noqa: E402
from ui.kit.geometry import fit_offset  # noqa: E402
from ui.kit.radial import Connector  # noqa: E402


class FakeClock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def ev(type_, value='PRESS', x=0.0, y=0.0, **mods):
    return UIEvent(type=type_, value=value, x=x, y=y, **mods)


def move(x, y):
    return ev('MOUSEMOVE', 'NOTHING', x, y)


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, name):
        return lambda: self.calls.append(name)


def build_pie(rec, with_panel=True):
    """8 items on the upper arc + a 3x2 button grid panel below, like the tool pie."""
    menu = RadialMenu()
    for i in range(8):
        menu.add_item(BubbleButton(f"T{i}", key=f"T{i}", on_click=rec(f"T{i}")))
    if with_panel:
        grid = Grid(columns=3, gap=12)
        for i in range(6):
            grid.add(Button(f"F{i}", key=f"F{i}", on_click=rec(f"F{i}")))
        menu.attach_below(Panel(grid, title="Falloff", key='panel'))
    return menu


class LayoutTests(unittest.TestCase):
    def test_grid_places_cells_row_major(self):
        grid = Grid([Button(size=(10, 10)) for _ in range(5)], columns=3, gap=2)
        theme = Theme()
        w, h = grid.measure(theme)
        self.assertEqual((w, h), (34, 22))
        grid.arrange(Rect.from_size(0, 0, w, h), theme)
        centers = [(c.rect.cx, c.rect.cy) for c in grid.children]
        self.assertEqual(centers[:3], [(5, 17), (17, 17), (29, 17)])
        self.assertEqual(centers[3:], [(5, 5), (17, 5)])

    def test_theme_scale_scales_layout(self):
        grid = Grid([Button(size=(10, 10))], columns=1)
        self.assertEqual(grid.measure(Theme(scale=2.0)), (20, 20))

    def test_radial_items_on_upper_arc(self):
        menu = build_pie(Recorder(), with_panel=False)
        menu.place((500, 500), Theme())
        first, last = menu.items[0].rect, menu.items[-1].rect
        self.assertAlmostEqual(first.cx, 380)   # 180 degrees: left
        self.assertAlmostEqual(last.cx, 620)    # 0 degrees: right
        top = max(menu.items, key=lambda w: w.rect.cy)
        self.assertGreater(top.rect.cy, 600)

    def test_panel_attached_below_center(self):
        menu = build_pie(Recorder())
        menu.place((500, 500), Theme())
        panel = menu.find('panel')
        self.assertAlmostEqual(panel.rect.cx, 500)
        self.assertLess(panel.rect.y1, 500)
        self.assertTrue(all(panel.rect.contains(b.rect.cx, b.rect.cy) for b in panel.content.children))

    def test_fit_offset(self):
        self.assertEqual(fit_offset(Rect(10, 10, 50, 50), 100, 100), (0, 0))
        self.assertEqual(fit_offset(Rect(-20, 10, 20, 50), 100, 100, margin=5), (25, 0))
        self.assertEqual(fit_offset(Rect(60, 70, 120, 130), 100, 100), (-20, -30))


class RadialInteractionTests(unittest.TestCase):
    def setUp(self):
        self.rec = Recorder()
        self.clock = FakeClock()
        self.menu = build_pie(self.rec)
        self.ui = Overlay(self.menu, origin=(500, 500), clock=self.clock, trigger_key='W')

    def finish(self):
        self.clock.advance(1.0)
        return self.ui.handle(ev('TIMER', 'NOTHING'))

    def test_dead_zone_has_no_hover(self):
        self.ui.handle(move(505, 505))
        self.assertIsNone(self.ui.hot)

    def test_direction_picks_nearest_item(self):
        self.ui.handle(move(500, 560))          # straight up -> middle items
        self.assertIn(self.ui.hot.key, {'T3', 'T4'})
        self.ui.handle(move(440, 500))          # left
        self.assertEqual(self.ui.hot.key, 'T0')

    def test_click_confirms_after_close_animation(self):
        self.ui.handle(move(440, 500))
        self.assertEqual(self.ui.handle(ev('LEFTMOUSE', 'PRESS', 440, 500)), RUNNING)
        self.assertEqual(self.ui.handle(ev('LEFTMOUSE', 'RELEASE', 440, 500)), RUNNING)
        self.assertTrue(self.ui.is_closing)
        self.assertEqual(self.rec.calls, [])     # not yet: animating out
        self.assertEqual(self.finish(), FINISHED)
        self.assertEqual(self.rec.calls, ['T0'])

    def test_input_is_swallowed_while_closing(self):
        self.ui.handle(move(440, 500))
        self.ui.handle(ev('LEFTMOUSE', 'PRESS', 440, 500))
        self.ui.handle(ev('LEFTMOUSE', 'RELEASE', 440, 500))
        self.ui.handle(move(560, 500))
        self.ui.handle(ev('ESC'))
        self.assertEqual(self.finish(), FINISHED)
        self.assertEqual(self.rec.calls, ['T0'])

    def test_radial_accepts_drag_release(self):
        self.ui.handle(ev('LEFTMOUSE', 'PRESS', 500, 500))   # press in dead zone
        self.ui.handle(move(560, 500))                         # drag right
        self.ui.handle(ev('LEFTMOUSE', 'RELEASE', 560, 500))
        self.finish()
        self.assertEqual(self.rec.calls, ['T7'])

    def test_stray_release_without_press_is_ignored(self):
        self.ui.handle(move(440, 500))
        self.ui.handle(ev('LEFTMOUSE', 'RELEASE', 440, 500))
        self.assertFalse(self.ui.is_closing)

    def test_escape_and_rmb_cancel(self):
        self.assertEqual(self.ui.handle(ev('ESC')), CANCELLED)
        ui2 = Overlay(build_pie(self.rec), origin=(500, 500), clock=self.clock)
        self.assertEqual(ui2.handle(ev('RIGHTMOUSE', x=440, y=500)), CANCELLED)
        self.assertEqual(self.rec.calls, [])

    def test_enter_confirms_hot(self):
        self.ui.handle(move(560, 500))
        self.ui.handle(ev('RET', x=560, y=500))   # Blender key events carry the mouse position
        self.finish()
        self.assertEqual(self.rec.calls, ['T7'])

    def test_number_keys_pick_items(self):
        self.ui.handle(ev('THREE', x=500, y=500))
        self.finish()
        self.assertEqual(self.rec.calls, ['T2'])

    def test_trigger_key_hold_release_confirms(self):
        self.ui.handle(move(560, 500))
        self.clock.advance(0.5)
        self.ui.handle(ev('W', 'RELEASE', 560, 500))
        self.finish()
        self.assertEqual(self.rec.calls, ['T7'])

    def test_trigger_key_quick_tap_keeps_menu_open(self):
        self.ui.handle(move(560, 500))
        self.clock.advance(0.05)
        self.assertEqual(self.ui.handle(ev('W', 'RELEASE', 560, 500)), RUNNING)
        self.assertFalse(self.ui.is_closing)


class PanelInteractionTests(unittest.TestCase):
    def setUp(self):
        self.rec = Recorder()
        self.clock = FakeClock()
        self.menu = build_pie(self.rec)
        self.ui = Overlay(self.menu, origin=(500, 500), clock=self.clock)
        self.panel = self.menu.find('panel')
        self.button = self.menu.find('F4')

    def test_panel_blocks_sector_hover(self):
        # Empty panel padding: claimed by the panel, so no radial item is hot.
        x, y = self.panel.rect.x0 + 2, self.panel.rect.cy
        self.ui.handle(move(x, y))
        self.assertIs(self.ui.pointer_widget, self.panel)
        self.assertIsNone(self.ui.hot)

    def test_button_inside_panel_is_hot_and_connector_targets_panel(self):
        b = self.button.rect
        self.ui.handle(move(b.cx, b.cy))
        self.assertIs(self.ui.hot, self.button)
        (point, center) = self.button.find_anchor(500, 450)
        self.assertEqual(center, (self.panel.rect.cx, self.panel.rect.cy))

    def test_button_requires_press_and_release_on_itself(self):
        b, other = self.button.rect, self.menu.find('F0').rect
        self.ui.handle(move(other.cx, other.cy))
        self.ui.handle(ev('LEFTMOUSE', 'PRESS', other.cx, other.cy))
        self.ui.handle(ev('LEFTMOUSE', 'RELEASE', b.cx, b.cy))
        self.assertFalse(self.ui.is_closing)
        self.ui.handle(ev('LEFTMOUSE', 'PRESS', b.cx, b.cy))
        self.ui.handle(ev('LEFTMOUSE', 'RELEASE', b.cx, b.cy))
        self.clock.advance(1.0)
        self.assertEqual(self.ui.handle(ev('TIMER', 'NOTHING')), FINISHED)
        self.assertEqual(self.rec.calls, ['F4'])

    def test_disabled_widget_cannot_be_hot(self):
        self.button.enabled_binding = lambda: False
        self.ui.handle(move(self.button.rect.cx, self.button.rect.cy))
        self.assertIsNone(self.ui.hot)

    def test_keep_open_activates_immediately(self):
        self.button.keep_open = True
        b = self.button.rect
        self.ui.handle(ev('LEFTMOUSE', 'PRESS', b.cx, b.cy))
        self.assertEqual(self.ui.handle(ev('LEFTMOUSE', 'RELEASE', b.cx, b.cy)), RUNNING)
        self.assertEqual(self.rec.calls, ['F4'])
        self.assertFalse(self.ui.is_closing)


class WidgetLayerTests(unittest.TestCase):
    """Non-modal overlays embedded in another operator."""

    def setUp(self):
        self.rec = Recorder()
        self.button = Button("Go", on_click=self.rec("go"), size=(20, 20))
        self.ui = Overlay(self.button, origin=(100, 100), modal=False, animate=False)

    def test_events_outside_pass_through(self):
        self.assertEqual(self.ui.handle(move(10, 10)), PASS_THROUGH)
        self.assertEqual(self.ui.handle(ev('LEFTMOUSE', 'PRESS', 10, 10)), PASS_THROUGH)
        self.assertEqual(self.ui.handle(ev('LEFTMOUSE', 'RELEASE', 10, 10)), PASS_THROUGH)
        self.assertEqual(self.ui.handle(ev('ESC')), PASS_THROUGH)

    def test_click_on_widget_is_consumed_and_activates(self):
        self.assertEqual(self.ui.handle(ev('LEFTMOUSE', 'PRESS', 100, 100)), RUNNING)
        self.assertEqual(self.ui.handle(ev('LEFTMOUSE', 'RELEASE', 100, 100)), RUNNING)
        self.assertEqual(self.rec.calls, ['go'])

    def test_release_elsewhere_after_press_is_consumed_without_click(self):
        self.ui.handle(ev('LEFTMOUSE', 'PRESS', 100, 100))
        self.assertEqual(self.ui.handle(ev('LEFTMOUSE', 'RELEASE', 10, 10)), RUNNING)
        self.assertEqual(self.rec.calls, [])


class ConnectorTests(unittest.TestCase):
    def test_eases_to_new_target_only_when_key_changes(self):
        c = Connector()
        self.assertEqual(c.update(0.0, (0, 0), 'a', 0.25), ((0, 0), 0.0))
        point, transition = c.update(0.0, (10, 0), 'a', 0.25)   # same widget moved: snap
        self.assertEqual((point, transition), ((10, 0), 0.0))
        point, transition = c.update(0.0, (10, 10), 'b', 0.25)  # new widget: restart ease
        self.assertEqual(transition, 1.0)
        point, transition = c.update(0.0625, (10, 10), 'b', 0.25)
        self.assertTrue(math.isclose(transition, 0.75))
        self.assertTrue(math.isclose(point[1], 2.5))
        point, transition = c.update(5.0, (10, 10), 'b', 0.25)  # stalled frame: dt clamped
        self.assertTrue(math.isclose(transition, 0.35))


if __name__ == '__main__':
    unittest.main()
