"""The Brushes window: the special brushes (tools/special/) as a circle menu in the pen
menu's style, opened from the Windows ring's outer ring.

* center: the shown brush -- a tap selects it, tapping it while selected goes back to
  the tool used before;
* inner ring, top, left to right: Particles, Rust, Noise Blur, Pull, Repair (a tap
  selects one; tapping the selected one goes back);
* inner ring, bottom: the shown brush's two settings -- Rust: Scale / Coverage;
  Particles: Count / Bounces; Noise Blur: Scatter / Grain; Pull: Pixel <-> Smooth /
  Drag -> Pinch -> Push;
  Repair: Auto <-> Source / Texture. Sliders show a short name; while dragged a readout
  beside the window gives the full name and value.

Size, strength, alpha, the modifier and the falloff stay on the pen menu (they are
per tool, like for every other tool). Under the circle a one-line hint for the brush,
shown with the help only while the window's '?' is on.
"""

from ...kit import Column, Dial, RingSegment
from ..icons.brushes import (BRUSH_PAINTERS, icon_auto, icon_drag, icon_pinch, icon_pixels, icon_push, icon_smooth,
                             icon_source, paint_brushes_title)
from ..icons.menu import captioned
from ..metrics import TINT_BRUSHES, TINT_CUSTOM, TINT_EXTRAS_VALUES, TINT_TOOLS
from .extras import ShownArcSlider, ShownSegment, ShownText
from .parts import DIAL_GAP, HELP_SIZE, ROW_GAP, TITLE_INDENT, DialCenter, WindowGroup, help_lines
from ....tools.pen.actions.brushes import SPECIAL_TOOLS

BRUSH_CENTER = 24.0
INNER_RING = (BRUSH_CENTER + 2.5, 62.0)
# Inner ring, top: the brushes left to right (36 degrees each); bottom: the two settings.
TOOL_SPAN = 180.0 / len(SPECIAL_TOOLS)
FIRST_ARC = (180.0, 270.0)     # bottom left (grows upward from the bottom)
SECOND_ARC = (270.0, 360.0)    # bottom right (grows upward from the bottom)
SLIDER_ROUND = 6.0
TINT_OPTIONS = TINT_CUSTOM

HINTS = {
    'RUST': "Left: primary patches into secondary; right: swapped.",
    'PARTICLES': "Bodies bounce off the model, denting it (M: dent size).",
    'NOISE_BLUR': "Pixels take random neighbours: a grainy blur.",
    'PULL': "Drag pixels along, pinch them in or push them out.",
    'REPAIR': "Paint over flaws. Right button: set a source.",
}

BRUSHES_HELP = ("Top: tap a brush to use it (again: back to",
                "the tool before). Size, strength, alpha, M and",
                "the falloff are on the pen menu, per brush.",
                "Rust: mottled primary / secondary patches;",
                "Scale = patch size, Coverage = how patchy.",
                "Particles: in 3D, bodies fly at the model and",
                "bounce off it, a dent at every hit (edges get",
                "chipped). Count per stamp, Bounces per body.",
                "Noise Blur: Scatter = how far pixels jump,",
                "Grain = fewer samples, noisier.",
                "Pull: liquify. Drag moves pixels along; Pinch",
                "sucks them into the center, Push away (right",
                "button: the opposite). Pixel keeps them crisp.",
                "Repair: Auto finds a matching patch nearby;",
                "Source: right click sets the source, strokes",
                "copy from it (aligned), colors matched to the",
                "surroundings. Texture 0: only a smooth fill.")


def build_brushes_window(bar):
    """The Brushes window's content (a Group)."""
    a = bar.actions
    colors = a.colors
    shown_tool = a.special_tool

    def paint_center(dc, x, y, size, alpha):
        BRUSH_PAINTERS[shown_tool()](colors, caption=False)(dc, x, y, size, alpha)

    center = DialCenter(painter=paint_center, tint=TINT_BRUSHES, radius=BRUSH_CENTER, key='BRUSHES_CENTER',
                        selected=a.special_active, on_click=lambda: a.toggle_special(shown_tool()))
    dial = Dial(center, gap=DIAL_GAP)

    # ---- inner ring, top: the brushes, left to right.
    for i, tool_id in enumerate(SPECIAL_TOOLS):
        a1 = 180.0 - i * TOOL_SPAN
        dial.add_segment(RingSegment("", painter=BRUSH_PAINTERS[tool_id](colors), tint=TINT_TOOLS,
                                     key=f'BRUSHES_{tool_id}', selected=lambda t=tool_id: a.special_selected(t),
                                     on_click=lambda t=tool_id: a.toggle_special(t)),
                         *INNER_RING, a1 - TOOL_SPAN, a1)

    # ---- inner ring, bottom: the shown brush's two settings.
    def is_tool(tool_id):
        return lambda: shown_tool() == tool_id

    def slider(label, tag, name, lo, hi, fmt, tool_id, arc, integer=True):
        def set_value(v):
            a.wm_set(name, int(round(v)) if integer else round(float(v), 2))
        dial.add_segment(ShownArcSlider(label, shown=is_tool(tool_id), value=lambda: a.wm_get(name, lo),
                                        on_value=set_value, value_range=(lo, hi),
                                        fill_color=(*TINT_EXTRAS_VALUES, 1.0), fmt=fmt, short=True, tag=tag,
                                        reverse=arc is FIRST_ARC, key=f'BRUSHES_{name.upper()}',
                                        tint=TINT_EXTRAS_VALUES, round=SLIDER_ROUND),
                         *INNER_RING, *arc)

    px = lambda v: f"{int(round(v))} px"
    count = lambda v: f"{int(round(v))}"
    percent = lambda v: f"{v * 100:.0f}%"
    slider("Scale", "Scale", 'rust_scale', 2, 48, px, 'RUST', FIRST_ARC)
    slider("Coverage", "Cover", 'rust_coverage', 0.0, 1.0, percent, 'RUST', SECOND_ARC, integer=False)
    slider("Count", "Count", 'particle_count', 1, 24, count, 'PARTICLES', FIRST_ARC)
    slider("Bounces", "Bounce", 'particle_bounces', 0, 6, count, 'PARTICLES', SECOND_ARC)
    slider("Scatter", "Scatter", 'noise_scatter', 1, 16, px, 'NOISE_BLUR', FIRST_ARC)
    slider("Grain", "Grain", 'noise_grain', 0.0, 1.0, percent, 'NOISE_BLUR', SECOND_ARC, integer=False)
    slider("Texture", "Texture", 'repair_texture', 0.0, 1.0, percent, 'REPAIR', SECOND_ARC, integer=False)

    # Pull: Pixel <-> Smooth (one button, dots show which); the second slot stays empty.
    smooth = lambda: bool(a.wm_get('pull_smooth', False))

    def paint_pull_mode(dc, x, y, size, alpha):
        captioned(icon_smooth if smooth() else icon_pixels, "Smooth" if smooth() else "Pixel")(dc, x, y, size, alpha)

    dial.add_segment(ShownSegment("", shown=is_tool('PULL'), painter=paint_pull_mode, key='BRUSHES_PULL_SMOOTH',
                                  tint=TINT_OPTIONS, on_click=lambda: a.wm_set('pull_smooth', not smooth()),
                                  options=lambda: (2, 1 if smooth() else 0)),
                     *INNER_RING, *FIRST_ARC)
    # Pull: Drag -> Pinch -> Push (a tap steps, dots show which).
    pull_modes = (('DRAG', "Drag", icon_drag), ('PINCH', "Pinch", icon_pinch), ('PUSH', "Push", icon_push))
    pull_order = [m for m, _label, _icon in pull_modes]

    def pull_index():
        mode = a.wm_get('pull_mode', 'DRAG')
        return pull_order.index(mode) if mode in pull_order else 0

    def paint_pull_kind(dc, x, y, size, alpha):
        _mode, label, icon = pull_modes[pull_index()]
        captioned(icon, label)(dc, x, y, size, alpha)

    dial.add_segment(ShownSegment("", shown=is_tool('PULL'), painter=paint_pull_kind, key='BRUSHES_PULL_MODE',
                                  tint=TINT_OPTIONS,
                                  on_click=lambda: a.wm_set('pull_mode', pull_order[(pull_index() + 1) % len(pull_order)]),
                                  options=lambda: (len(pull_order), pull_index())),
                     *INNER_RING, *SECOND_ARC)

    # Repair: Auto <-> Source.
    source = lambda: a.repair_mode() == 'SOURCE'

    def paint_repair_mode(dc, x, y, size, alpha):
        captioned(icon_source if source() else icon_auto, "Source" if source() else "Auto")(dc, x, y, size, alpha)

    dial.add_segment(ShownSegment("", shown=is_tool('REPAIR'), painter=paint_repair_mode, key='BRUSHES_REPAIR_MODE',
                                  tint=TINT_OPTIONS, on_click=a.toggle_repair_mode,
                                  options=lambda: (2, 1 if source() else 0)),
                     *INNER_RING, *FIRST_ARC)

    width = 2.0 * INNER_RING[1]

    def status_lines():
        tool_id = shown_tool()
        if tool_id == 'REPAIR' and source() and not a.repair_has_source():
            return ["Right click on the canvas: set the source."]
        return [HINTS.get(tool_id, "")]

    status = ShownText(status_lines, size=HELP_SIZE, width=width,
                       shown=lambda: bar.help_shown('brushes'))   # only with '?' on
    content = Column([dial, status, help_lines(bar, 'brushes', BRUSHES_HELP, width)], gap=ROW_GAP)
    return WindowGroup("Special", content, tint=TINT_BRUSHES, painter=paint_brushes_title(colors),
                       title_indent=TITLE_INDENT)
