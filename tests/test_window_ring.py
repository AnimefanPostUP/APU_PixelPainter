"""Unit tests for the pen menu's Windows popup ring (ui/pen_bar._WindowRing).

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

pen_bar_ui = importlib.import_module(f'{_PACKAGE}.ui.pen.bar')
kit = importlib.import_module(f'{_PACKAGE}.ui.kit')
events = importlib.import_module(f'{_PACKAGE}.ui.kit.events')


def _event(type_, value, x, y):
    return kit.UIEvent(type=type_, value=value, x=x, y=y)


class WindowRingTest(unittest.TestCase):

    def setUp(self):
        self.clicked = []
        dial = kit.Dial(kit.RingSegment("Center", key='CENTER'), gap=pen_bar_ui.DIAL_GAP)
        self.inner = kit.RingSegment("Inner", key='INNER', on_click=lambda: self.clicked.append('inner'))
        dial.add_arc([self.inner], *pen_bar_ui.INNER_RING, 0.0, 360.0)
        self.tool = kit.RingSegment("Tool", key='TOOL', on_click=lambda: self.clicked.append('tool'))
        dial.add_arc([self.tool], *pen_bar_ui.OUTER_RING, *pen_bar_ui.TOOL_ARC)
        self.opener = kit.CornerSegment("Windows", key='WINDOWS',
                                        on_click=lambda: setattr(self.ring, 'visible', not self.ring.visible))
        self.opener.activate_on_press = True
        dial.add_corner([self.opener], pen_bar_ui.BOTTOM_LEFT_INNER, pen_bar_ui.SQUARE_HALF,
                        *pen_bar_ui.WINDOWS_ARC)
        self.ring = dial.add(pen_bar_ui._WindowRing(*pen_bar_ui.WINDOW_RING, cover=pen_bar_ui.WINDOW_RING_COVER))
        self.entries = [kit.RingSegment(name, key=name, on_click=lambda n=name: self.clicked.append(n))
                        for name in ("Settings", "Mask", "View", "Color", "Palettes")]
        self.ring.add_entries(dial, self.entries, pen_bar_ui.WINDOW_RING_START)
        self.overlay = kit.Overlay(dial, modal=False, animate=False)
        self.theme = self.overlay.theme

    def _at(self, segment):
        """Screen point in the middle of ``segment``."""
        return segment.middle()

    def test_entries_fill_the_circle_over_the_inner_ring(self):
        spans = [(e.a0, e.a1) for e in self.entries]
        self.assertAlmostEqual(spans[0][0], pen_bar_ui.WINDOW_RING_START)
        self.assertAlmostEqual(spans[-1][1] - spans[0][0], 360.0)
        for entry in self.entries:
            self.assertEqual((entry.r0, entry.r1), tuple(pen_bar_ui.INNER_RING))
            self.assertIs(entry.parent, self.ring)

    def test_hidden_ring_lets_the_inner_ring_through(self):
        x, y = self._at(self.inner)
        self.assertIs(self.overlay.root.pick(x, y), self.inner)

    def test_open_ring_covers_the_inner_ring_and_its_gaps(self):
        self.ring.visible = True
        for entry in self.entries:
            self.assertIs(self.overlay.root.pick(*self._at(entry)), entry)
        # On the border between two entries the ring itself blocks the pointer.
        a = math.radians(self.entries[1].a0)
        r = (self.ring.pr0 + self.ring.pr1) * 0.5
        hit = self.overlay.root.pick(self.ring.cx + math.cos(a) * r, self.ring.cy + math.sin(a) * r)
        self.assertTrue(hit is self.ring or hit in self.entries)
        self.assertIsNot(hit, self.inner)

    def test_open_ring_hides_the_tools(self):
        x, y = self._at(self.tool)
        self.assertIs(self.overlay.root.pick(x, y), self.tool)
        self.ring.visible = True
        self.assertIs(self.overlay.root.pick(x, y), self.ring)
        self.overlay.handle(_event('LEFTMOUSE', events.PRESS, x, y))
        self.overlay.handle(_event('LEFTMOUSE', events.RELEASE, x, y))
        self.assertEqual(self.clicked, [])

    def test_press_opener_drag_release_on_entry(self):
        ox, oy = self._at(self.opener)
        self.assertEqual(self.overlay.handle(_event('LEFTMOUSE', events.PRESS, ox, oy)), events.RUNNING)
        self.assertTrue(self.ring.visible)
        view = self.entries[2]
        vx, vy = self._at(view)
        self.overlay.handle(_event('MOUSEMOVE', 'NOTHING', vx, vy))
        self.overlay.handle(_event('LEFTMOUSE', events.RELEASE, vx, vy))
        self.assertEqual(self.clicked, ['View'])

    def test_tap_opener_then_tap_entry(self):
        ox, oy = self._at(self.opener)
        self.overlay.handle(_event('LEFTMOUSE', events.PRESS, ox, oy))
        self.overlay.handle(_event('LEFTMOUSE', events.RELEASE, ox, oy))
        self.assertTrue(self.ring.visible)
        self.assertEqual(self.clicked, [])
        mx, my = self._at(self.entries[1])
        self.overlay.handle(_event('LEFTMOUSE', events.PRESS, mx, my))
        self.overlay.handle(_event('LEFTMOUSE', events.RELEASE, mx, my))
        self.assertEqual(self.clicked, ['Mask'])


if __name__ == '__main__':
    unittest.main()
