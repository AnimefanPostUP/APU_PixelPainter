"""The Extras window: a circle menu in the pen menu's style -- *All* in the center, two
rings around it. Colors by category: the tools in the pen menu's tool blue, the source
purple, the edge choices orange, the options yellow, the sliders green.

* inner ring: the tools Fill / Edges / AO across the top; across the bottom the armed
  tool's choices as deep icon + caption buttons (like Undo / Redo): Edges -- Angle /
  All / Marked (which model edges), AO -- Fade / Curve;
* outer ring: the source (UV Islands / Mesh Parts) on top, a slider on each side
  (labelled by its first letter, name and value in a readout beside the window while
  dragged; Edges -- Width left, Angle right; AO -- Rays left, Distance right), and for Edges below: Placement (Symmetric <-> Pixel line, a tap swaps),
  Fade, Curve.

*Curve* folds the armed tool's curve out under the circle (Edges: its falloff, AO: the
occlusion curve), with Move / Add / Draw / Reset and the presets. Under that the result
of the last run.

Tapping a tool arms it (tools/extras/tool.py): the island / part under the cursor is
outlined, a canvas tap runs the tool on it; *All* runs it on every island / part.
"""


import math

from ...kit import Column, CurveEditor, Dial, Grid, Rect, RingSegment, Row, TextBlock
from ....model import value_curve
from ..icons.extras import (icon_all_edges, icon_angle, icon_curve, icon_fade, icon_marked, icon_pixel_line,
                            icon_symmetric, paint_ao, paint_all, paint_edges, paint_extras_title, paint_fill)
from ..icons.menu import captioned
from ..icons.windows import paint_source_band
from ..metrics import (TINT_EXTRAS, TINT_EXTRAS_EDGES, TINT_EXTRAS_OPTIONS, TINT_EXTRAS_SOURCE,
                       TINT_EXTRAS_TOOLS, TINT_EXTRAS_VALUES)
from .parts import (DIAL_GAP, GAP, HELP_SIZE, ROW_GAP, TITLE_INDENT, ArcSlider, DialCenter, WindowButton,
                    WindowGroup, _Shown, help_lines)

EXTRAS_CENTER = 24.0
INNER_RING = (EXTRAS_CENTER + 2.5, 60.0)
OUTER_RING = (INNER_RING[1] + 2.5, 92.0)
# Arcs (degrees, counter-clockwise from the right).
TOOLS_ARC = (0.0, 180.0)            # inner ring, top (left to right: Fill, Edges, AO)
CHOICES_ARC = (180.0, 360.0)        # inner ring, bottom: the armed tool's choices
SOURCE_ARC = (55.0, 125.0)          # outer ring, top
LEFT_SLIDER_ARC = (125.0, 220.0)    # outer ring, left side (grows upward)
OPTIONS_ARC = (220.0, 320.0)        # outer ring, bottom: Edges' Placement / Fade / Curve
RIGHT_SLIDER_ARC = (-40.0, 55.0)    # outer ring, right side (grows upward)
SLIDER_ROUND = 6.0
CONTROL_HEIGHT = 22.0
CURVE_SIZE = (200.0, 120.0)
CURVE_MODES = (('MOVE', "Move"), ('ADD', "Add"), ('DRAW', "Draw"))
PRESET_COLUMNS = 3
EDGE_SOURCES = (('ANGLE', "Angle"), ('ALL', "All"), ('MARKED', "Marked"))
EDGE_CENTERS = (('BETWEEN', "Symmetric"), ('ON', "Pixel line"))
CURVE_TITLES = {'edge': "Edges falloff", 'ao': "AO curve"}

EXTRAS_HELP = ("Tap Fill, Edges or AO, then tap an island /",
               "part on the canvas (outlined under the cursor).",
               "Left: primary color first, right: secondary.",
               "All (middle): every island / part at once.",
               "Arc on top: UV islands or connected mesh parts.",
               "Fill: one color. Edges: primary along the model's",
               "edges into secondary, the same on both sides",
               "(Pixel line: a 1-texel line on the edge).",
               "AO: secondary in the open, primary in corners.",
               "Curve: the falloff / AO curve with presets.",
               "Uses the blend mode, strength, alpha and mask.")


class TrimmedDial(Dial):
    """A dial that reserves height only for its *visible* parts above and below the
    center, so hidden parts (a tool's choices below while no tool uses them) leave no
    gap. It is still laid out on its full square: ``rect`` is that square, reaching into
    the empty margins where nothing of it is drawn."""

    PAD = 2.0   # unscaled px past the outermost visible part

    def _reach(self, side):
        """Unscaled reach of the visible parts above (``side`` 1) / below (-1) the center."""
        reach = getattr(self.center, 'radius', 0.0) if self.center is not None else 0.0
        peak = 90.0 if side > 0 else 270.0
        for seg in self.segments + self.corners:
            if not seg.visible or not hasattr(seg, 'a0'):
                continue
            a0, a1 = sorted((seg.a0, seg.a1))
            angles = [a0, a1] + [peak + 360.0 * k for k in range(-2, 3) if a0 <= peak + 360.0 * k <= a1]
            extent = max(side * math.sin(math.radians(a)) for a in angles)
            if extent > 0.0:
                reach = max(reach, extent * seg.r1)
        return reach + self.PAD

    def measure(self, theme):
        d, _h = super().measure(theme)
        return d, theme.px(self._reach(1) + self._reach(-1))

    def arrange(self, rect, theme):
        d, _h = super().measure(theme)
        cy = rect.y1 - theme.px(self._reach(1))
        super().arrange(Rect.from_center(rect.cx, cy, d, d), theme)


class ShownColumn(_Shown, Column):
    pass


class ShownText(_Shown, TextBlock):
    pass


class ShownSegment(_Shown, RingSegment):
    pass


class ShownArcSlider(_Shown, ArcSlider):
    pass


def build_extras_window(bar):
    """The Extras window's content (a Group)."""
    a = bar.actions
    tint = TINT_EXTRAS
    colors = a.colors

    center = DialCenter(painter=paint_all, tint=tint, radius=EXTRAS_CENTER, key='EXTRAS_ALL',
                        enabled=lambda: a.extras_mode() is not None, on_click=a.extras_run_all)
    dial = TrimmedDial(center, gap=DIAL_GAP)

    def ring(segments, radii, arc):
        """``segments`` side by side along ``arc``, listed counter-clockwise (left to
        right on the bottom half, right to left on the top half)."""
        step = (arc[1] - arc[0]) / len(segments)
        for i, seg in enumerate(segments):
            dial.add_segment(seg, *radii, arc[0] + i * step, arc[0] + (i + 1) * step)

    # Inner ring, top: the tools (left to right: Fill, Edges, AO), in the pen menu's tool blue.
    painters = {'FILL': paint_fill(colors), 'EDGES': paint_edges(colors), 'AO': paint_ao(colors)}
    ring([RingSegment("", painter=painters[mode], key=f'EXTRAS_{mode}', tint=TINT_EXTRAS_TOOLS,
                      selected=lambda m=mode: a.extras_selected(m), on_click=lambda m=mode: a.toggle_extras_mode(m))
          for mode in ('AO', 'EDGES', 'FILL')], INNER_RING, TOOLS_ARC)

    # Outer ring, top: the source.
    ring([RingSegment("", painter=paint_source_band(a.extras_source), key='EXTRAS_SOURCE', tint=TINT_EXTRAS_SOURCE,
                      on_click=a.toggle_extras_source)], OUTER_RING, SOURCE_ARC)

    def choice(caption, painter, key, shown, selected, on_click, tint):
        """A deep icon + caption button (like Undo / Redo), shown while ``shown()``."""
        if not callable(caption):
            painter = captioned(painter, caption)
        return ShownSegment("", shown=shown, painter=painter, key=key, tint=tint,
                            selected=selected, on_click=on_click)

    def wm_toggle(name):
        return lambda: a.wm_set(name, not a.wm_get(name, True))

    is_edges = lambda: a.extras_selected('EDGES')
    is_ao = lambda: a.extras_selected('AO')
    edge_kind = lambda: a.wm_get('extras_edge_source', 'ANGLE')
    edge_center = lambda: a.wm_get('extras_edge_center', 'BETWEEN')
    edge_icons = {'ANGLE': icon_angle, 'ALL': icon_all_edges, 'MARKED': icon_marked}
    center_icons = {'BETWEEN': icon_symmetric, 'ON': icon_pixel_line}
    center_labels = dict(EDGE_CENTERS)

    # Inner ring, bottom: Edges -- which model edges (orange); AO -- Fade, Curve (yellow).
    ring([choice(label, edge_icons[kind], f'EXTRAS_EDGE_{kind}', is_edges,
                 lambda k=kind: edge_kind() == k, lambda k=kind: a.wm_set('extras_edge_source', k), TINT_EXTRAS_EDGES)
          for kind, label in EDGE_SOURCES], INNER_RING, CHOICES_ARC)
    ring([choice("Fade", icon_fade, 'EXTRAS_AO_FADE', is_ao, lambda: bool(a.wm_get('extras_ao_fade', True)),
                 wm_toggle('extras_ao_fade'), TINT_EXTRAS_OPTIONS),
          choice("Curve", icon_curve, 'EXTRAS_AO_CURVE_OPEN', is_ao, a.extras_curve_open, a.toggle_extras_curve,
                 TINT_EXTRAS_OPTIONS)],
         INNER_RING, CHOICES_ARC)

    # Outer ring, bottom (Edges): Placement -- one button, a tap swaps Symmetric <-> Pixel line.
    def paint_placement(dc, x, y, size, alpha):
        kind = edge_center()
        captioned(center_icons.get(kind, icon_symmetric), center_labels.get(kind, "Symmetric"))(dc, x, y, size, alpha)

    def swap_placement():
        a.wm_set('extras_edge_center', 'ON' if edge_center() == 'BETWEEN' else 'BETWEEN')

    ring([choice(None, paint_placement, 'EXTRAS_EDGE_CENTER', is_edges, None, swap_placement, TINT_EXTRAS_OPTIONS),
          choice("Fade", icon_fade, 'EXTRAS_EDGE_FADE', is_edges, lambda: bool(a.wm_get('extras_edge_fade', True)),
                 wm_toggle('extras_edge_fade'), TINT_EXTRAS_OPTIONS),
          choice("Curve", icon_curve, 'EXTRAS_EDGE_CURVE', is_edges, a.extras_curve_open, a.toggle_extras_curve,
                 TINT_EXTRAS_OPTIONS)],
         OUTER_RING, OPTIONS_ARC)

    # Outer ring, sides: the sliders (green), labelled by their first letter; while one is
    # dragged a readout beside the window shows its name and value. Both grow upward.
    def arc_slider(label, name, lo, hi, step, fmt, shown, arc, enabled=True):
        def set_value(v):
            a.wm_set(name, int(round(v)) if step == 1 else round(float(v), 2))
        slider = ShownArcSlider(label, shown=shown, value=lambda: a.wm_get(name, lo), on_value=set_value,
                                value_range=(lo, hi), fill_color=(*TINT_EXTRAS_VALUES, 1.0), fmt=fmt,
                                enabled=enabled, short=True, reverse=arc is LEFT_SLIDER_ARC,
                                key=f'EXTRAS_{name.upper()}', tint=TINT_EXTRAS_VALUES, round=SLIDER_ROUND)
        dial.add_segment(slider, *OUTER_RING, *arc)
        return slider

    arc_slider("Width", 'extras_edge_width', 1, 16, 1, lambda v: f"{int(round(v))} px", is_edges, LEFT_SLIDER_ARC)
    arc_slider("Angle", 'extras_edge_angle', 5.0, 90.0, 1, lambda v: f"{int(round(v))}\u00b0", is_edges,
               RIGHT_SLIDER_ARC, enabled=lambda: edge_kind() == 'ANGLE')
    arc_slider("Rays", 'extras_ao_samples', 8, 128, 1, lambda v: f"{int(round(v))}", is_ao, LEFT_SLIDER_ARC)
    arc_slider("Distance", 'extras_ao_distance', 0.02, 1.0, None, lambda v: f"{v * 100:.0f}%", is_ao,
               RIGHT_SLIDER_ARC)

    # ---- curve section (folded out by Curve) ---------------------------------------------
    width = CURVE_SIZE[0]
    curve_mode = {'mode': 'MOVE'}

    def button(label, key, selected, on_click, w):
        return WindowButton(label, layout='row', size=(w, CONTROL_HEIGHT), key=key, tint=tint,
                            selected=selected, on_click=on_click)

    def curve_section(kind, mode):
        editor = CurveEditor(lambda: a.extras_curve_points(kind), lambda pts: a.set_extras_curve_points(kind, pts),
                             sample=lambda: a.extras_curve_sampler(kind), mode=lambda: curve_mode['mode'],
                             size=CURVE_SIZE, curve_color=(*tint, 1.0), key=f'EXTRAS_{kind.upper()}_CURVE')
        quarter = (width - 3 * GAP) / 4.0
        modes = [button(label, f'EXTRAS_{kind.upper()}_CURVE_{m}', lambda m=m: curve_mode['mode'] == m,
                        lambda m=m: curve_mode.__setitem__('mode', m), quarter)
                 for m, label in CURVE_MODES]
        modes.append(button("Reset", f'EXTRAS_{kind.upper()}_CURVE_RESET', None,
                            lambda: a.load_extras_curve_preset(kind, value_curve.DEFAULTS[kind]), quarter))
        cell = (width - (PRESET_COLUMNS - 1) * GAP) / PRESET_COLUMNS
        presets = [button(label, f'EXTRAS_{kind.upper()}_PRESET_{pid}', None,
                          lambda p=pid: a.load_extras_curve_preset(kind, p), cell)
                   for pid, label, _points in value_curve.PRESETS[kind]]
        return ShownColumn([TextBlock([CURVE_TITLES[kind]], size=HELP_SIZE, width=width), editor,
                            Row(modes, gap=GAP), Grid(presets, columns=PRESET_COLUMNS, gap=GAP)],
                           gap=GAP, shown=lambda: a.extras_curve_open() and a.extras_selected(mode))

    def status_lines():
        text = a.extras_status()
        if text:
            return [text]
        if a.extras_mode() is None:
            return ["Choose a tool."]
        return ["Tap an island / part on the canvas."]

    status = ShownText(status_lines, size=HELP_SIZE, width=width, shown=lambda: True)
    content = Column([dial, curve_section('edge', 'EDGES'), curve_section('ao', 'AO'), status,
                      help_lines(bar, 'extras', EXTRAS_HELP, width)], gap=ROW_GAP)
    return WindowGroup("Extras", content, tint=tint, painter=paint_extras_title(colors), title_indent=TITLE_INDENT)
