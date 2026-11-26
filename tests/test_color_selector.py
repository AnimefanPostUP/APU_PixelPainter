"""Unit tests for the color selector: color models, layouts, sliders.

Runs with plain Python (no Blender needed) from the addon root:

    python -m unittest discover -s tests -v
"""

import colorsys
import math
import os
import sys
import unittest

_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ADDON_DIR)

from ui.kit import ColorSelector, Overlay, UIEvent  # noqa: E402
from ui.kit import color_models as cm  # noqa: E402


def ev(type_, value='PRESS', x=0.0, y=0.0):
    return UIEvent(type=type_, value=value, x=x, y=y)


def move(x, y):
    return ev('MOUSEMOVE', 'NOTHING', x, y)


class ColorModelTests(unittest.TestCase):
    def test_hsl_round_trip(self):
        hsl = (0.3, 0.6, 0.4)
        hsv = cm.convert(hsl, cm.HSL, cm.HSV)
        back = cm.convert(hsv, cm.HSV, cm.HSL)
        for a, b in zip(hsl, back):
            self.assertAlmostEqual(a, b)

    def test_hint_keeps_hue_and_saturation_at_black_and_white(self):
        self.assertEqual(cm.convert((0.0, 0.0, 0.0), cm.RGB, cm.HSV, hint=(0.6, 0.7, 0.2))[:2], (0.6, 0.7))
        self.assertEqual(cm.convert((0.2, 0.8, 1.0), cm.HSL, cm.HSL), (0.2, 0.8, 1.0))
        h, s, _l = cm.convert((0.2, 0.0, 1.0), cm.HSV, cm.HSL, hint=(0.2, 0.8, 0.9))   # white
        self.assertEqual((h, s), (0.2, 0.8))

    def test_tone_weights_invert(self):
        for model in (cm.HSV, cm.HSL):
            for s, t in ((0.3, 0.7), (1.0, 0.5), (0.8, 0.2)):
                hw, ww = cm.tone_weights(model, s, t)
                s2, t2 = cm.from_tone_weights(model, hw, ww, 0.0)
                self.assertAlmostEqual(s, s2)
                self.assertAlmostEqual(t, t2)

    def test_tone_weights_match_rgb(self):
        # rgb = hue_w * pure + white_w: the triangle's vertex colors are exact.
        for model in (cm.HSV, cm.HSL):
            h, s, t = 0.1, 0.6, 0.35
            hw, ww = cm.tone_weights(model, s, t)
            pure = colorsys.hsv_to_rgb(h, 1.0, 1.0)
            expected = cm.to_rgb(model, (h, s, t))
            for p, e in zip(pure, expected):
                self.assertAlmostEqual(hw * p + ww, e)


class _SelectorCase(unittest.TestCase):
    layout = 'SHEET'
    model = cm.HSV
    sliders = ()
    start = (0.5, 0.5, 0.5)

    def setUp(self):
        self.hsv = self.start
        self.writes = 0

        def set_hsv(h, s, v):
            self.hsv = (h, s, v)
            self.writes += 1

        self.sel = ColorSelector(lambda: self.hsv, set_hsv, layout=self.layout, model=self.model,
                                 sliders=self.sliders, area=(100.0, 100.0), bar=10.0, gap=5.0, gain=1.0)
        self.ui = Overlay(self.sel, modal=False, animate=False)

    def swipe(self, x, y, dx, dy, steps=1):
        self.ui.handle(ev('LEFTMOUSE', 'PRESS', x, y))
        for i in range(1, steps + 1):
            self.ui.handle(move(x + dx * i / steps, y + dy * i / steps))
        self.ui.handle(ev('LEFTMOUSE', 'RELEASE', x + dx, y + dy))

    def tap(self, x, y):
        self.ui.handle(ev('LEFTMOUSE', 'PRESS', x, y))
        self.ui.handle(ev('LEFTMOUSE', 'RELEASE', x, y))


class SquareTests(_SelectorCase):
    layout = 'SQUARE'

    def test_square_swipe_moves_saturation_and_value(self):
        sq = self.sel.parts['SQUARE']
        self.swipe(sq.x0 + 5, sq.y0 + 5, sq.width * 0.2, -sq.height * 0.1)
        h, s, v = self.hsv
        self.assertAlmostEqual(h, 0.5)
        self.assertAlmostEqual(s, 0.7)
        self.assertAlmostEqual(v, 0.4)

    def test_hue_bar_is_vertical_and_wraps(self):
        hue = self.sel.parts['HUE']
        self.assertEqual(self.sel.part_at(hue.cx, hue.cy), 'HUE')
        self.swipe(hue.cx, hue.cy, 0, hue.height * 0.6)
        self.assertAlmostEqual(self.hsv[0], 0.1)

    def test_tap_jumps(self):
        sq = self.sel.parts['SQUARE']
        self.tap(sq.x0 + sq.width * 0.25, sq.y0 + sq.height * 0.75)
        self.assertAlmostEqual(self.hsv[1], 0.25)
        self.assertAlmostEqual(self.hsv[2], 0.75)


class WheelTests(_SelectorCase):
    layout = 'WHEEL'
    start = (0.0, 0.5, 0.8)

    def test_disc_swipe_is_relative(self):
        disc = self.sel.parts['DISC']
        r = disc.width * 0.5
        # Press far from the cursor (which sits right of center); swipe outward.
        self.swipe(disc.cx - r * 0.5, disc.cy, r * 0.3, 0)
        h, s, v = self.hsv
        self.assertAlmostEqual(h, 0.0)
        self.assertAlmostEqual(s, 0.8)
        self.assertAlmostEqual(v, 0.8)

    def test_disc_clamps_to_rim_and_passes_center(self):
        disc = self.sel.parts['DISC']
        r = disc.width * 0.5
        self.swipe(disc.cx, disc.cy, -r * 1.0, 0, steps=4)   # through the center to the other side
        h, s, _v = self.hsv
        self.assertAlmostEqual(h, 0.5)
        self.assertAlmostEqual(s, 0.5)
        self.swipe(disc.cx, disc.cy, 0, r * 5)
        self.assertAlmostEqual(self.hsv[1], 1.0)

    def test_tap_on_disc(self):
        disc = self.sel.parts['DISC']
        r = disc.width * 0.5
        self.tap(disc.cx, disc.cy + r * 0.5)
        h, s, v = self.hsv
        self.assertAlmostEqual(h, 0.25)
        self.assertAlmostEqual(s, 0.5)
        self.assertAlmostEqual(v, 0.8)

    def test_tone_bar(self):
        tone = self.sel.parts['TONE']
        self.assertEqual(self.sel.part_at(tone.cx, tone.cy), 'TONE')
        self.swipe(tone.cx, tone.cy, 0, -tone.height * 0.3)
        self.assertAlmostEqual(self.hsv[2], 0.5)


class TriangleTests(_SelectorCase):
    layout = 'TRIANGLE'
    start = (0.25, 0.5, 0.5)

    def test_parts(self):
        tri, ring = self.sel.parts['TRIANGLE'], self.sel.parts['RING']
        self.assertEqual(self.sel.part_at(ring.cx, ring.cy), 'TRIANGLE')
        self.assertEqual(self.sel.part_at(ring.x1 - 2, ring.cy), 'RING')

    def test_ring_follows_rotation(self):
        ring = self.sel.parts['RING']
        cx, cy, r = ring.cx, ring.cy, ring.width * 0.5 - 3
        self.ui.handle(ev('LEFTMOUSE', 'PRESS', cx + r, cy))
        steps = 8
        for i in range(1, steps + 1):   # a quarter turn counter-clockwise
            a = (math.pi / 2) * i / steps
            self.ui.handle(move(cx + math.cos(a) * r, cy + math.sin(a) * r))
        self.ui.handle(ev('LEFTMOUSE', 'RELEASE', cx, cy + r))
        self.assertAlmostEqual(self.hsv[0], 0.5)
        self.assertAlmostEqual(self.hsv[1], 0.5)

    def test_tap_vertices(self):
        hue_v, white_v, black_v = self.sel.shape.vertices
        self.tap(*hue_v)
        self.assertAlmostEqual(self.hsv[1], 1.0)
        self.assertAlmostEqual(self.hsv[2], 1.0)
        self.assertAlmostEqual(self.hsv[0], 0.25)   # the triangle keeps the hue
        self.tap(*white_v)
        self.assertAlmostEqual(self.hsv[1], 0.0)
        self.assertAlmostEqual(self.hsv[2], 1.0)

    def test_swipe_clamps_into_triangle(self):
        tri = self.sel.parts['TRIANGLE']
        self.swipe(tri.cx, tri.cy, -500, 0)   # far left: onto the white / black edge
        self.assertAlmostEqual(self.hsv[1], 0.0, places=6)
        self.assertTrue(0.0 <= self.hsv[2] <= 1.0)


class HslTests(_SelectorCase):
    layout = 'SQUARE'
    model = cm.HSL

    def setUp(self):
        self.start = cm.convert((0.5, 1.0, 0.5), cm.HSL, cm.HSV)   # pure cyan
        super().setUp()

    def test_tone_is_lightness(self):
        sq = self.sel.parts['SQUARE']
        self.swipe(sq.cx, sq.cy, 0, sq.height * 0.5)     # lightness 0.5 -> 1: white
        self.assertAlmostEqual(self.hsv[2], 1.0)
        self.assertAlmostEqual(self.hsv[1], 0.0)
        # Back down: hue and saturation survive white.
        self.swipe(sq.cx, sq.cy, 0, -sq.height * 0.5)
        h, s, v = self.hsv
        self.assertAlmostEqual(h, 0.5)
        self.assertAlmostEqual(s, 1.0)
        self.assertAlmostEqual(v, 1.0)


class SliderTests(_SelectorCase):
    layout = 'SHEET'
    sliders = ('HSL', 'RGB')   # shown in fixed order: RGB, then HSL
    start = (0.0, 1.0, 1.0)    # red

    def test_slider_order_and_parts(self):
        keys = [k for k, _s, _i in self.sel.sliders]
        self.assertEqual(keys, ['RGB_R', 'RGB_G', 'RGB_B', 'HSL_H', 'HSL_S', 'HSL_L'])
        main = self.sel.main_rect
        for key in keys:
            self.assertLess(self.sel.parts[key].y1, main.y0)
        g = self.sel.parts['RGB_G']
        self.assertEqual(self.sel.part_at(g.cx, g.cy), 'RGB_G')

    def test_rgb_slider_swipe(self):
        g = self.sel.parts['RGB_G']
        self.swipe(g.x0 + 2, g.cy, g.width * 0.5, 0)
        r, gg, b = colorsys.hsv_to_rgb(*self.hsv)
        self.assertAlmostEqual(r, 1.0)
        self.assertAlmostEqual(gg, 0.5)
        self.assertAlmostEqual(b, 0.0)

    def test_hsl_lightness_tap(self):
        l_bar = self.sel.parts['HSL_L']
        self.tap(l_bar.x0 + l_bar.width * 0.25, l_bar.cy)
        rgb = colorsys.hsv_to_rgb(*self.hsv)
        for a, e in zip(rgb, (0.5, 0.0, 0.0)):
            self.assertAlmostEqual(a, e)

    def test_config_follows_bindings(self):
        layout = ['SHEET']
        sel = ColorSelector(lambda: self.hsv, lambda *c: None, layout=lambda: layout[0])
        Overlay(sel, modal=False, animate=False)
        self.assertEqual(sel.layout_id, 'SHEET')
        layout[0] = 'WHEEL'
        sel.measure(Overlay(sel, modal=False, animate=False).theme)
        self.assertEqual(sel.layout_id, 'WHEEL')


def key(type_, char='', value='PRESS', ctrl=False, shift=False):
    return UIEvent(type=type_, value=value, unicode=char, ctrl=ctrl, shift=shift)


def type_text(ui, text):
    for c in text:
        ui.handle(key(c.upper() if c.isalpha() else 'X', c))


class SliderFieldTests(_SelectorCase):
    sliders = ('RGB', 'HSV')
    start = (0.0, 1.0, 1.0)    # red

    def setUp(self):
        super().setUp()
        self.sel = ColorSelector(lambda: self.hsv, self._set, sliders=self.sliders, fields=True,
                                 area=(100.0, 100.0), bar=10.0, gap=5.0, gain=1.0)
        self.ui = Overlay(self.sel, modal=False, animate=False)

    def _set(self, h, s, v):
        self.hsv = (h, s, v)

    def _field(self, part):
        return self.sel.value_fields[part]

    def _edit(self, part):
        f = self._field(part)
        self.tap(f.rect.cx, f.rect.cy)
        return f

    def test_fields_sit_right_of_their_sliders(self):
        for key_, _s, _i in self.sel.sliders:
            bar, f = self.sel.parts[key_], self._field(key_)
            self.assertGreater(f.rect.x0, bar.x1)
            self.assertAlmostEqual(f.rect.cy, bar.cy)
            self.assertAlmostEqual(bar.height, 10.0)   # slider_bar default
        self.assertEqual(self._field('RGB_R').shown_text(), '255')
        self.assertEqual(self._field('HSV_H').shown_text(), '0°')

    def test_typing_a_value_and_enter(self):
        f = self._edit('RGB_G')
        self.assertIs(self.ui.focus, f)
        self.assertTrue(f.select_all)
        type_text(self.ui, '128')
        self.assertEqual(f.text, '128')
        self.ui.handle(key('RET'))
        self.assertIsNone(self.ui.focus)
        r, g, b = colorsys.hsv_to_rgb(*self.hsv)
        self.assertAlmostEqual(r, 1.0)
        self.assertAlmostEqual(g, 128 / 255)
        self.assertAlmostEqual(b, 0.0)

    def test_escape_cancels_and_letters_are_filtered(self):
        f = self._edit('HSV_H')
        type_text(self.ui, 'ab12')
        self.assertEqual(f.text, '12')
        self.ui.handle(key('ESC'))
        self.assertEqual(self.hsv, self.start)

    def test_hue_in_degrees_wraps_and_tab_moves_on(self):
        f = self._edit('HSV_H')
        type_text(self.ui, '450')
        self.ui.handle(key('TAB'))
        self.assertAlmostEqual(self.hsv[0], 0.25)
        self.assertIs(self.ui.focus, self._field('HSV_S'))
        type_text(self.ui, '50')
        self.ui.handle(key('BACK_SPACE'))
        self.ui.handle(key('ONE', '1'))
        self.assertEqual(self.ui.focus.text, '51')

    def test_press_elsewhere_commits(self):
        self._edit('HSV_V')
        type_text(self.ui, '40')
        main = self.sel.main_rect
        self.ui.handle(ev('LEFTMOUSE', 'PRESS', main.cx, main.cy))
        self.ui.handle(ev('LEFTMOUSE', 'RELEASE', main.cx, main.cy))
        self.assertIsNone(self.ui.focus)
        self.assertAlmostEqual(self.hsv[1], 1.0)

    def test_set_rgb_keeps_hue_through_grey(self):
        self.sel.set_rgb((0.5, 0.5, 0.5))
        self.assertAlmostEqual(self.hsv[0], 0.0)
        self.assertAlmostEqual(self.hsv[2], 0.5)
        self.assertEqual(cm.to_hex(self.sel.rgb()), '#808080')


class ColorCodeTests(unittest.TestCase):
    def test_hex_round_trip(self):
        self.assertEqual(cm.to_hex((1.0, 0.5, 0.0)), '#FF8000')
        for text in ('#ff8000', 'FF8000', '0xff8000', ' #FF8000 '):
            self.assertEqual(cm.to_hex(cm.parse_color(text)), '#FF8000')
        self.assertEqual(cm.to_hex(cm.parse_color('#f80')), '#FF8800')

    def test_rgb_triples(self):
        self.assertEqual(cm.to_hex(cm.parse_color('255, 128, 0')), '#FF8000')
        self.assertEqual(cm.to_hex(cm.parse_color('rgb(255 128 0)')), '#FF8000')
        self.assertEqual(cm.to_hex(cm.parse_color('1.0, 0.5, 0.0')), '#FF8000')
        for bad in ('', 'hello', '#12345', '1, 2'):
            self.assertIsNone(cm.parse_color(bad))


if __name__ == '__main__':
    unittest.main()
