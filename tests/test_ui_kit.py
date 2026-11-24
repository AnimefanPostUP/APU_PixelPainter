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
    BubbleButton, Button, Dial, Grid, Overlay, Panel, RadialMenu, Rect, RingSegment, RingSlider, Theme, UIEvent,
)
from ui.kit.events import CANCELLED, FINISHED, PASS_THROUGH, RUNNING  # noqa: E402
from ui.kit.geometry import clamp_box, corner_contains, corner_segment_points, fit_offset, ring_contains, ring_segment_points  # noqa: E402
from ui.kit import aa  # noqa: E402
from ui.kit.curve import CurveEditor, insert_anchor, move_anchor, simplify, stroke_to_curve  # noqa: E402
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


class RingGeometryTests(unittest.TestCase):
    def test_contains_wraps_past_full_turn(self):
        a0, a1 = math.radians(270), math.radians(375)   # through 0 degrees
        self.assertTrue(ring_contains(0, 0, 10, 20, a0, a1, 15, 0))
        self.assertTrue(ring_contains(0, 0, 10, 20, a0, a1, 0, -15))
        self.assertFalse(ring_contains(0, 0, 10, 20, a0, a1, 0, 15))
        self.assertFalse(ring_contains(0, 0, 10, 20, a0, a1, 25, 0))   # beyond the outer radius
        self.assertFalse(ring_contains(0, 0, 10, 20, a0, a1, 5, 0))    # inside the inner radius

    def test_gap_is_equally_wide_at_every_radius(self):
        # The side edge sits `inset` px from its radial line, at the inner and the outer radius.
        inner, outer = ring_segment_points(0, 0, 30, 120, 0.0, math.radians(40), inset=2.0)
        for x, y in (inner[0], outer[0]):        # a0 = 0: distance to the +x axis is y
            self.assertTrue(math.isclose(y, 2.0, abs_tol=1e-9))

    def test_clamp_box_keeps_box_inside(self):
        bounds = (0, 0, 100, 100)
        self.assertEqual(clamp_box(-20, 50, 30, 30, bounds), (0, 50))     # left edge
        self.assertEqual(clamp_box(90, 90, 30, 30, bounds), (70, 70))     # top-right corner
        self.assertEqual(clamp_box(10, -5, 30, 30, bounds), (10, 0))      # bottom edge
        self.assertEqual(clamp_box(10, 10, 30, 30, bounds), (10, 10))     # inside: unchanged

    def test_clamp_box_too_large_keeps_top_left(self):
        self.assertEqual(clamp_box(50, -50, 150, 150, (0, 0, 100, 100)), (0, -50))

    def test_corner_segment_follows_circle_and_square(self):
        inner, outer = corner_segment_points(100, 140, math.radians(90), math.radians(180), 2.0, 2.0, 30.0)
        self.assertEqual(len(inner), len(outer))
        for x, y in inner:
            self.assertTrue(math.isclose(math.hypot(x, y), 100.0))
        for x, y in outer:   # on the square or on its chamfer
            on_side = math.isclose(abs(x), 140.0) or math.isclose(abs(y), 140.0)
            on_chamfer = math.isclose(-x + y, 2 * 140.0 - 30.0)
            self.assertTrue(on_side or on_chamfer, (x, y))
        self.assertTrue(any(math.isclose(-x + y, 250.0) for x, y in outer[1:-1]))   # walks the chamfer
        self.assertTrue(math.isclose(outer[0][0], -2.0))    # side edge 2 px from the +y axis

    def test_corner_contains(self):
        a0, a1 = math.radians(90), math.radians(180)
        self.assertTrue(corner_contains(100, 140, a0, a1, 30, -100, 100))
        self.assertFalse(corner_contains(100, 140, a0, a1, 30, -50, 50))     # inside the circle
        self.assertFalse(corner_contains(100, 140, a0, a1, 30, -135, 135))   # cut-off corner
        self.assertFalse(corner_contains(100, 140, a0, a1, 30, 100, 100))    # other quadrant

    def test_segment_vanishes_when_inset_too_large(self):
        self.assertEqual(ring_segment_points(0, 0, 2, 4, 0.0, 0.1, inset=3.0), ([], []))


class DialTests(unittest.TestCase):
    def setUp(self):
        self.clicked = []
        self.values = []
        self.dial = Dial(Button("C", size=(20, 20), on_click=lambda: self.clicked.append('C')), gap=4.0)
        self.dial.add_arc([RingSegment("a", key='A', on_click=lambda: self.clicked.append('A')),
                           RingSegment("b", key='B', on_click=lambda: self.clicked.append('B'))],
                          20, 50, 0, 180)
        self.slider = self.dial.add_segment(
            RingSlider("S", key='S', cap=10.0, on_value=self.values.append), 20, 50, 180, 360)
        self.overlay = Overlay(self.dial, modal=False, animate=False, origin=(100.0, 100.0))

    def tap(self, x, y):
        self.overlay.handle(ev('LEFTMOUSE', 'PRESS', x, y))
        self.overlay.handle(ev('LEFTMOUSE', 'RELEASE', x, y))

    def test_measures_outer_diameter_plus_dividers_centered_on_origin(self):
        self.assertEqual(self.dial.measure(Theme()), (112.0, 112.0))   # 2 x (50 + 6 overhang)
        self.assertEqual((self.dial.rect.cx, self.dial.rect.cy), (100.0, 100.0))

    def test_arc_split_evenly_and_picked_by_angle(self):
        self.tap(135, 110)   # right, slightly up: A (0..90)
        self.tap(65, 110)    # left, slightly up: B (90..180)
        self.tap(100, 100)   # center widget
        self.assertEqual(self.clicked, ['A', 'B', 'C'])

    def test_dividers_between_groups_only(self):
        self.assertEqual(sorted(self.dial.dividers), [0.0, 180.0])

    def test_group_gap_widens_only_the_group_edges(self):
        dial = Dial(gap=4.0, group_gap=12.0)
        a, b = dial.add_arc([RingSegment(), RingSegment()], 20, 50, 0, 180, tint=(1.0, 0.0, 0.0))
        self.assertEqual((a.edge_extra, b.edge_extra), ((4.0, 0.0), (0.0, 4.0)))
        self.assertEqual(a.tint, (1.0, 0.0, 0.0))
        dial.arrange(Rect.from_center(0, 0, 100, 100), Theme())
        self.assertEqual(a.insets, (6.0, 2.0))   # group edge: 12 / 2, inside the group: 4 / 2

    def test_slider_value_follows_distance(self):
        self.overlay.handle(ev('LEFTMOUSE', 'PRESS', 100, 100 - 22))     # inner end of the track
        self.overlay.handle(move(100, 100 - 40))                          # track end: 50 - cap
        self.overlay.handle(ev('LEFTMOUSE', 'RELEASE', 100, 60))
        self.assertTrue(math.isclose(self.values[0], 0.0, abs_tol=1e-9))
        self.assertTrue(math.isclose(self.values[-1], 1.0))
        self.assertFalse(self.slider.dragging)


class CurveLogicTests(unittest.TestCase):
    def test_insert_keeps_order_and_ends(self):
        pts, i = insert_anchor([(0.0, 1.0), (1.0, 0.0)], 0.3, 0.7)
        self.assertEqual((pts, i), ([(0.0, 1.0), (0.3, 0.7), (1.0, 0.0)], 1))

    def test_move_keeps_ends_x_and_neighbour_order(self):
        pts = [(0.0, 1.0), (0.4, 0.5), (1.0, 0.0)]
        self.assertEqual(move_anchor(pts, 0, 0.3, 0.2), [(0.0, 0.2), (0.4, 0.5), (1.0, 0.0)])
        moved = move_anchor(pts, 1, 1.5, -1.0)
        self.assertTrue(math.isclose(moved[1][0], 0.99) and moved[1][1] == 0.0)

    def test_simplify_straight_line(self):
        line = [(i / 10, i / 10) for i in range(11)]
        self.assertEqual(simplify(line, 0.01), [(0.0, 0.0), (1.0, 1.0)])

    def test_stroke_to_curve_spans_0_to_1(self):
        stroke = [(0.1 + 0.8 * t / 30, 1.0 - (t / 30) ** 2) for t in range(31)]
        curve = stroke_to_curve(stroke, max_points=8)
        self.assertEqual((curve[0][0], curve[-1][0]), (0.0, 1.0))
        self.assertTrue(2 < len(curve) <= 8)
        self.assertEqual(curve, sorted(curve))

    def test_stroke_too_narrow_is_ignored(self):
        self.assertIsNone(stroke_to_curve([(0.5, 0.1), (0.51, 0.9)]))


class CurveEditorTests(unittest.TestCase):
    def setUp(self):
        self.pts = [(0.0, 1.0), (0.5, 0.5), (1.0, 0.0)]
        self.mode = 'MOVE'
        self.ed = CurveEditor(lambda: self.pts, self._set, mode=lambda: self.mode, size=(120, 120), padding=10)
        self.ov = Overlay(self.ed, modal=False, animate=False, origin=(100.0, 100.0))

    def _set(self, pts):
        self.pts = pts

    def drag(self, a, b):
        self.ov.handle(ev('LEFTMOUSE', 'PRESS', *self.ed.to_screen(*a)))
        self.ov.handle(move(*self.ed.to_screen(*b)))
        self.ov.handle(ev('LEFTMOUSE', 'RELEASE', *self.ed.to_screen(*b)))

    def test_move_anchor(self):
        self.drag((0.5, 0.5), (0.6, 0.8))
        self.assertTrue(math.isclose(self.pts[1][0], 0.6) and math.isclose(self.pts[1][1], 0.8))

    def test_add_mode_adds_where_pressed(self):
        self.mode = 'ADD'
        self.drag((0.25, 0.9), (0.25, 0.9))
        self.assertEqual(len(self.pts), 4)

    def test_drag_out_removes_inner_anchor(self):
        x, y = self.ed.to_screen(0.5, 0.5)
        self.ov.handle(ev('LEFTMOUSE', 'PRESS', x, y))
        self.ov.handle(move(x, y - 400))
        self.ov.handle(ev('LEFTMOUSE', 'RELEASE', x, y - 400))
        self.assertEqual(self.pts, [(0.0, 1.0), (1.0, 0.0)])

    def test_cancel_restores(self):
        x, y = self.ed.to_screen(0.5, 0.5)
        self.ov.handle(ev('LEFTMOUSE', 'PRESS', x, y))
        self.ov.handle(move(x + 20, y + 20))
        self.ov.handle(ev('ESC', 'PRESS', x + 20, y + 20))
        self.assertEqual(self.pts, [(0.0, 1.0), (0.5, 0.5), (1.0, 0.0)])

    def test_draw_mode_replaces_curve(self):
        self.mode = 'DRAW'
        self.ov.handle(ev('LEFTMOUSE', 'PRESS', *self.ed.to_screen(0.0, 0.0)))
        for t in range(1, 21):
            self.ov.handle(move(*self.ed.to_screen(t / 20, t / 20)))
        self.ov.handle(ev('LEFTMOUSE', 'RELEASE', *self.ed.to_screen(1.0, 1.0)))
        self.assertEqual(len(self.pts), 2)
        self.assertTrue(self.pts[0][1] < 0.1 and self.pts[-1][1] > 0.9)


class AntiAliasTests(unittest.TestCase):
    SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]

    def test_fringe_ramp_is_centered_on_the_edge(self):
        # Full color 0.5 px inside the edge, transparent 0.5 px outside -- either winding.
        for pts in (self.SQUARE, list(reversed(self.SQUARE))):
            verts, colors = aa.fringe_mesh(pts, (1.0, 0.0, 0.0, 1.0))
            outer = {v for v, c in zip(verts, colors) if c[3] == 0.0}
            inner = {v for v, c in zip(verts, colors) if c[3] == 1.0}
            self.assertEqual(outer, {(-0.5, -0.5), (10.5, -0.5), (10.5, 10.5), (-0.5, 10.5)})
            self.assertEqual(inner, {(0.5, 0.5), (9.5, 0.5), (9.5, 9.5), (0.5, 9.5)})

    def test_solid_fill_meets_the_ramp(self):
        self.assertEqual(aa.offset_points(self.SQUARE, -aa.EDGE),
                         [(0.5, 0.5), (9.5, 0.5), (9.5, 9.5), (0.5, 9.5)])

    def test_offset_keeps_length_and_closing_point(self):
        closed = self.SQUARE + [self.SQUARE[0]]
        moved = aa.offset_points(closed, 1.0)
        self.assertEqual(len(moved), 5)
        self.assertEqual(moved[0], moved[-1])
        self.assertEqual(moved[0], (-1.0, -1.0))

    def test_fringe_keeps_per_point_colors(self):
        cols = [(i / 4, 0.0, 0.0, 1.0) for i in range(4)]
        verts, colors = aa.fringe_mesh(self.SQUARE, cols)
        self.assertIn(((0.5, 0.5), cols[0]), list(zip(verts, colors)))
        self.assertIn(((9.5, 9.5), cols[2]), list(zip(verts, colors)))

    def test_stroke_width_and_soft_edges(self):
        verts, colors = aa.stroke_mesh([(0.0, 0.0), (10.0, 0.0)], (1.0, 1.0, 1.0, 1.0), width=3.0)
        solid = [v[1] for v, c in zip(verts, colors) if c[3] > 0.0]
        soft = [v[1] for v, c in zip(verts, colors) if c[3] == 0.0]
        self.assertEqual((min(solid), max(solid)), (-1.0, 1.0))       # core: width - AA
        self.assertEqual((min(soft), max(soft)), (-2.0, 2.0))         # + AA fading rim

    def test_thin_stroke_fades_instead_of_shrinking(self):
        verts, colors = aa.stroke_mesh([(0.0, 0.0), (10.0, 0.0)], (1.0, 1.0, 1.0, 1.0), width=0.5)
        self.assertEqual(max(c[3] for c in colors), 0.5)
        self.assertEqual(max(abs(v[1]) for v in verts), 1.0)

    def test_closed_stroke_has_a_segment_per_edge(self):
        verts, _colors = aa.stroke_mesh(self.SQUARE, (1.0, 1.0, 1.0, 1.0), width=1.0, closed=True)
        self.assertEqual(len(verts), 4 * 2 * 6)    # 4 edges x 2 rim quads (no core at 1 px)

    def test_rim_is_a_darker_shade_of_the_fill_not_black(self):
        theme = Theme()
        rim = theme.edge_for((1.0, 0.5, 0.0, 1.0), alpha=0.5)
        self.assertEqual(rim[:3], (theme.edge_darken, 0.5 * theme.edge_darken, 0.0))
        self.assertEqual(rim[3], theme.edge_alpha * 0.5)

    def test_segments_grow_with_radius(self):
        self.assertEqual(aa.segments_for(1.0), 12)
        self.assertGreater(aa.segments_for(200.0), aa.segments_for(50.0))


if __name__ == '__main__':
    unittest.main()
