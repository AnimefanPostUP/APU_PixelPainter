"""The Extras window: a circle menu in the pen menu's style -- the source in the center,
two rings around it. Colors by category: the tools (and All) in the pen menu's tool blue,
the source purple, the edge choices orange, the options yellow (Fade stronger), the
sliders green (Fill's fade yellow).

* center: the source (UV Islands / Mesh Parts / Sharp Areas; a tap steps to the next,
  dots show which);
* inner ring: across the top, left to right, *All* (run the shown tool on every island
  / part) and the tools Fill / Edges / AO (a tap arms one, tapping the armed one
  disarms it); across the bottom, left to right, Fade (Fill's runs the color past the
  island / part, fading out) and Curve as deep icon + caption buttons, then the tool's
  two sliders (labelled by a short name, full name and value in a readout beside the
  window while dragged; Fill -- Fade (its width), Edges -- Width / Angle, AO -- Rays /
  Dist);
* outer ring, only what did not fit inside: on the right, for Edges, Placement
  (Symmetric <-> Pixel line) above the edge type (Angle / All / Marked, a tap steps);
  on the left, with Sharp Areas, the Sharp Angle.

*Curve* folds the armed tool's curve out under the circle (Edges: its falloff, AO: the
occlusion curve), with Move / Add / Draw / Reset and the presets. Under that the result
of the last run.

Tapping a tool arms it (tools/extras/tool.py): the island / part under the cursor is
outlined, a canvas tap runs the tool on it; *All* runs it on every island / part.
"""


import math

from ...kit import Column, CurveEditor, Dial, Grid, Rect, RingSegment, Row, TextBlock
from ...kit import draw
from ...kit.theme import with_alpha
from ....model import value_curve
from ..icons.extras import (icon_all_edges, icon_angle, icon_curve, icon_fade, icon_marked, icon_pixel_line,
                            icon_symmetric, paint_ao, paint_all, paint_edges, paint_extras_title, paint_fill)
from ..icons.menu import captioned
from ..icons.windows import paint_source_name, source_options
from .mask import sharp_angle_slider
from ..metrics import (CUSTOM_TINT_AMOUNT, TINT_CUSTOM, TINT_EXTRAS, TINT_EXTRAS_EDGES, TINT_EXTRAS_OPTIONS, TINT_EXTRAS_SOURCE,
                       TINT_EXTRAS_TOOLS, TINT_EXTRAS_VALUES)
from .parts import (DIAL_GAP, GAP, HELP_SIZE, ROW_GAP, TITLE_INDENT, ArcSlider, DialCenter, WindowButton,
                    WindowGroup, _Shown, help_lines)

EXTRAS_CENTER = 24.0
INNER_RING = (EXTRAS_CENTER + 2.5, 60.0)
OUTER_RING = (INNER_RING[1] + 2.5, 92.0)
# Arcs (degrees, counter-clockwise from the right).
# Inner ring: eight 45 degree slots. Top, left to right: All, Fill, Edges, AO; bottom,
# left to right: Fade, Curve, the tool's two sliders.
TOOL_ARCS = {'FILL': (90.0, 135.0), 'EDGES': (45.0, 90.0), 'AO': (0.0, 45.0)}
ALL_ARC = (135.0, 180.0)
FADE_ARC = (180.0, 225.0)
CURVE_ARC = (225.0, 270.0)
FIRST_SLIDER_ARC = (270.0, 315.0)   # Fill's Fade / Width / Rays (grows to the right)
SECOND_SLIDER_ARC = (315.0, 360.0)  # Angle / Dist (grows upward)
# Outer ring, what did not fit inside: right -- Edges' Placement above its edge type;
# left (the right is full) -- the Sharp Angle (only with Sharp Areas, grows upward).
PLACEMENT_ARC = (0.0, 40.0)
EDGE_KIND_ARC = (-40.0, 0.0)
SHARP_ARC = (160.0, 200.0)
SLIDER_ROUND = 6.0
TINT_FADE = TINT_CUSTOM               # the Fade buttons and Fill's fade slider: yellow
FADE_TINT_AMOUNT = CUSTOM_TINT_AMOUNT
CONTROL_HEIGHT = 22.0
CURVE_SIZE = (200.0, 120.0)
CURVE_MODES = (('MOVE', "Move"), ('ADD', "Add"), ('DRAW', "Draw"))
PRESET_COLUMNS = 3
EDGE_SOURCES = (('ANGLE', "Angle"), ('ALL', "All"), ('MARKED', "Marked"))
EDGE_CENTERS = (('BETWEEN', "Symmetric"), ('ON', "Pixel line"))
CURVE_TITLES = {'edge': "Edges falloff", 'ao': "AO curve", 'fill': "Fill fade-out"}

EXTRAS_HELP = ("Top: tap Fill, Edges or AO to arm it (again:",
               "disarm), then tap an island / part on the canvas",
               "(outlined under the cursor). Left: primary color",
               "first, right: secondary. All, left of the tools:",
               "every island / part at once.",
               "Middle: UV islands, connected mesh parts or",
               "sharp areas (split at edges sharper than the",
               "Sharp arc, outside on the left); a tap switches.",
               "Fill: one color; Fade: it also runs past the",
               "island / part into its neighbours, fading out.",
               "Edges: primary along the model's",
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

    def _square(self, theme):
        """The full square's side, from the visible bands only (the Sharp Angle band
        outside the rings takes room only while shown)."""
        corners = self.corners
        self.corners = [c for c in corners if c.visible]
        try:
            return Dial.measure(self, theme)[0]
        finally:
            self.corners = corners

    def measure(self, theme):
        d = self._square(theme)
        return d, theme.px(self._reach(1) + self._reach(-1))

    def arrange(self, rect, theme):
        d = self._square(theme)
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


class Placeholder(_Shown, RingSegment):
    """An empty slot of the ring (nothing there for the current tool / source): a faint
    plate, not clickable -- the ring keeps its shape."""

    interactive = False

    def draw_self(self, dc):
        inner, outer = self.points()
        if inner:
            draw.ring_segment(inner, outer, with_alpha(dc.theme.surface_dark, 0.45 * dc.alpha))


def build_extras_window(bar):
    """The Extras window's content (a Group)."""
    a = bar.actions
    tint = TINT_EXTRAS
    colors = a.colors

    tool = a.extras_tool
    center = DialCenter(painter=lambda dc, x, y, size, alpha: paint_source_name(a.extras_source())(dc, x, y, size, alpha),
                        tint=TINT_EXTRAS_SOURCE, radius=EXTRAS_CENTER, key='EXTRAS_SOURCE',
                        on_click=a.toggle_extras_source, options=lambda: source_options(a.extras_source()))
    dial = TrimmedDial(center, gap=DIAL_GAP)

    def choice(caption, painter, key, shown, selected, on_click, tint, radii=INNER_RING, arc=None, **kwargs):
        """A deep icon + caption button (like Undo / Redo), shown while ``shown()``, placed at ``arc``."""
        if not callable(caption):
            painter = captioned(painter, caption)
        seg = ShownSegment("", shown=shown, painter=painter, key=key, tint=tint,
                           selected=selected, on_click=on_click, **kwargs)
        dial.add_segment(seg, *radii, *arc)
        return seg

    def wm_toggle(name):
        return lambda: a.wm_set(name, not a.wm_get(name, True))

    is_edges = lambda: tool() == 'EDGES'
    is_ao = lambda: tool() == 'AO'
    is_fill = lambda: tool() == 'FILL'
    fill_fade = lambda: bool(a.wm_get('extras_fill_fade', False))
    edge_kind = lambda: a.wm_get('extras_edge_source', 'ANGLE')
    edge_center = lambda: a.wm_get('extras_edge_center', 'BETWEEN')
    edge_icons = {'ANGLE': icon_angle, 'ALL': icon_all_edges, 'MARKED': icon_marked}
    center_icons = {'BETWEEN': icon_symmetric, 'ON': icon_pixel_line}
    center_labels = dict(EDGE_CENTERS)
    center_order = [kind for kind, _label in EDGE_CENTERS]

    # ---- inner ring, top: All, Fill, Edges, AO (left to right; the armed tool selected,
    # a tap on it disarms; All runs the shown tool on every island / part).
    tool_painters = {'FILL': paint_fill(colors), 'EDGES': paint_edges(colors), 'AO': paint_ao(colors)}
    for mode in tool_painters:
        dial.add_segment(RingSegment("", painter=tool_painters[mode], key=f'EXTRAS_{mode}', tint=TINT_EXTRAS_TOOLS,
                                     selected=lambda m=mode: a.extras_selected(m),
                                     on_click=lambda m=mode: a.toggle_extras_mode(m)),
                         *INNER_RING, *TOOL_ARCS[mode])
    dial.add_segment(RingSegment("", painter=paint_all, key='EXTRAS_ALL', tint=TINT_EXTRAS_TOOLS,
                                 on_click=a.extras_run_all), *INNER_RING, *ALL_ARC)

    # ---- inner ring, bottom left: Fade (yellow), Curve -- the same slots for every tool.
    for mode, key, fade_on, fade_toggle in (
            ('FILL', 'FILL', fill_fade, lambda: a.wm_set('extras_fill_fade', not fill_fade())),
            ('EDGES', 'EDGE', lambda: bool(a.wm_get('extras_edge_fade', True)), wm_toggle('extras_edge_fade')),
            ('AO', 'AO', lambda: bool(a.wm_get('extras_ao_fade', True)), wm_toggle('extras_ao_fade'))):
        shown = lambda m=mode: tool() == m
        choice("Fade", icon_fade, f'EXTRAS_{key}_FADE', shown, fade_on, fade_toggle, TINT_FADE,
               arc=FADE_ARC, tint_amount=FADE_TINT_AMOUNT)
        choice("Curve", icon_curve, f'EXTRAS_{key}_CURVE_OPEN', shown, a.extras_curve_open, a.toggle_extras_curve,
               TINT_EXTRAS_OPTIONS, arc=CURVE_ARC)

    # ---- inner ring, bottom right: the tool's two sliders (green; Fill's fade yellow),
    # labelled by a short name; while one is dragged a readout beside the window shows its
    # full name and value.
    def arc_slider(label, tag, name, lo, hi, step, fmt, shown, arc, enabled=True, color=TINT_EXTRAS_VALUES):
        def set_value(v):
            a.wm_set(name, int(round(v)) if step == 1 else round(float(v), 2))
        slider = ShownArcSlider(label, shown=shown, value=lambda: a.wm_get(name, lo), on_value=set_value,
                                value_range=(lo, hi), fill_color=(*color, 1.0), fmt=fmt,
                                enabled=enabled, short=True, tag=tag,
                                key=f'EXTRAS_{name.upper()}', tint=color, round=SLIDER_ROUND)
        dial.add_segment(slider, *INNER_RING, *arc)
        return slider

    arc_slider("Fade width", "Fade", 'extras_fill_width', 1, 32, 1, lambda v: f"{int(round(v))} px", is_fill,
               FIRST_SLIDER_ARC, enabled=fill_fade, color=TINT_FADE)
    arc_slider("Width", "Width", 'extras_edge_width', 1, 16, 1, lambda v: f"{int(round(v))} px", is_edges, FIRST_SLIDER_ARC)
    arc_slider("Angle", "Angle", 'extras_edge_angle', 5.0, 90.0, 1, lambda v: f"{int(round(v))}°", is_edges,
               SECOND_SLIDER_ARC, enabled=lambda: edge_kind() == 'ANGLE')
    arc_slider("Rays", "Rays", 'extras_ao_samples', 8, 128, 1, lambda v: f"{int(round(v))}", is_ao, FIRST_SLIDER_ARC)
    arc_slider("Distance", "Dist", 'extras_ao_distance', 0.02, 1.0, None, lambda v: f"{v * 100:.0f}%", is_ao,
               SECOND_SLIDER_ARC)
    # Fill has one slider: a placeholder keeps the ring whole.
    dial.add_segment(Placeholder("", shown=is_fill, key='EXTRAS_EMPTY_SECOND_SLIDER', round=SLIDER_ROUND),
                     *INNER_RING, *SECOND_SLIDER_ARC)

    # ---- outer ring, right (what did not fit inside; Edges only): Placement above, the
    # edge type below.
    def paint_placement(dc, x, y, size, alpha):
        kind = edge_center()
        captioned(center_icons.get(kind, icon_symmetric), center_labels.get(kind, "Symmetric"))(dc, x, y, size, alpha)

    def swap_placement():
        a.wm_set('extras_edge_center', 'ON' if edge_center() == 'BETWEEN' else 'BETWEEN')

    def placement_options():
        kind = edge_center()
        return len(center_order), center_order.index(kind) if kind in center_order else 0

    choice(None, paint_placement, 'EXTRAS_EDGE_CENTER', is_edges, None, swap_placement, TINT_EXTRAS_OPTIONS,
           radii=OUTER_RING, arc=PLACEMENT_ARC, options=placement_options)

    # The edge type (orange), one button: a tap steps Angle -> All -> Marked, dots show which.
    edge_order = [kind for kind, _label in EDGE_SOURCES]
    edge_labels = dict(EDGE_SOURCES)

    def paint_edge_kind(dc, x, y, size, alpha):
        kind = edge_kind()
        captioned(edge_icons.get(kind, icon_angle), edge_labels.get(kind, "Angle"))(dc, x, y, size, alpha)

    def edge_kind_index():
        kind = edge_kind()
        return edge_order.index(kind) if kind in edge_order else 0

    def next_edge_kind():
        a.wm_set('extras_edge_source', edge_order[(edge_kind_index() + 1) % len(edge_order)])

    choice(None, paint_edge_kind, 'EXTRAS_EDGE_KIND', is_edges, None, next_edge_kind, TINT_EXTRAS_EDGES,
           radii=OUTER_RING, arc=EDGE_KIND_ARC, options=lambda: (len(edge_order), edge_kind_index()))

    # ---- outer ring, left (the right side is full): the Sharp Angle, only with Sharp
    # Areas; grows upward.
    dial.add_segment(sharp_angle_slider(a, 'EXTRAS_SHARP_ANGLE', lambda: a.extras_source() == 'SHARP',
                                        TINT_EXTRAS_SOURCE, TINT_EXTRAS_VALUES, round=SLIDER_ROUND,
                                        short=True, reverse=True, tag="Sharp"),
                     *OUTER_RING, *SHARP_ARC)

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
                           gap=GAP, shown=lambda: a.extras_curve_open() and a.extras_tool() == mode)

    def status_lines():
        text = a.extras_status()
        if text:
            return [text]
        if a.extras_mode() is None:
            return ["Choose a tool on top."]
        return ["Tap an island / part on the canvas."]

    status = ShownText(status_lines, size=HELP_SIZE, width=width, shown=lambda: True)
    content = Column([dial, curve_section('fill', 'FILL'), curve_section('edge', 'EDGES'), curve_section('ao', 'AO'), status,
                      help_lines(bar, 'extras', EXTRAS_HELP, width)], gap=ROW_GAP)
    return WindowGroup("Extras", content, tint=tint, painter=paint_extras_title(colors), title_indent=TITLE_INDENT)
