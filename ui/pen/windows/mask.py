"""The Mask window: a circle menu -- Edit in the center (choose islands / parts on the
canvas), Mask on / Invert / Show / Grow slider / Clear around it, and the source band.
"""


from ...kit import Column, Dial, RingSegment
from ..icons.menu import captioned, paint_mask, paint_mask_invert
from ..metrics import TINT_MASK
from ..icons.settings import icon_eye, icon_reset
from .parts import (DIAL_GAP, ROW_GAP, TITLE_INDENT, ArcSlider, DialCenter, ShownSegment, WindowGroup, _Shown,
                    help_lines)
from ..icons.windows import icon_mask_title, paint_edit, paint_source_band, source_options
# Mask circle menu: Edit in the middle, the inner ring around it (Invert, Mask, Show, Grow,
# Clear); outside it the source arc on top and Sharp Angle on the left (only while editing).
MASK_CENTER = 24.0
MASK_RING = (MASK_CENTER + 2.5, 66.0)
MASK_BAND = (MASK_RING[1] + 3.0, MASK_RING[1] + 22.0)
MASK_BAND_ROUND = (MASK_BAND[1] - MASK_BAND[0]) * 0.5   # capsules
ANGLE_ARC = (140.0, 220.0)   # Sharp Angle, left side of the band (only with Sharp Areas)
OPACITY_ARC = (235.0, 305.0)  # the stripes' opacity, bottom of the band (always; grayed out while not shown)
SOURCE_ARC = (52.0, 128.0)
GROW_END = 325.0             # inner ring, bottom right: Grow 270 .. here, Clear (smaller) here .. 360
# per-button colors
TINT_MASK_INVERT = (1.00, 0.55, 0.15)   # orange
TINT_MASK_CLEAR = (0.95, 0.30, 0.30)    # red
TINT_MASK_SHOW = (0.45, 0.80, 0.45)     # green
TINT_MASK_EDIT = (0.35, 0.58, 1.00)     # blue

MASK_HELP = ("Mask: only chosen islands / parts get paint.",
             "Edit (middle): tap them on the canvas (drag:",
             "several); the arc on top switches between UV",
             "islands, connected mesh parts and sharp areas",
             "(split at edges sharper than the S arc, left).",
             "Invert: protect the chosen ones instead.",
             "Show: red stripes over protected pixels.",
             "Grow (ring, bottom right): extra pixels around",
             "each island. Clear (red): forget all chosen ones.",
             "Opacity (arc, bottom): how strong the stripes are.")


class ShownArcSlider(_Shown, ArcSlider):
    pass


def sharp_angle_slider(a, key, shown, tint, fill, **kwargs):
    """The shared Sharp Angle (Sharp Areas source of the mask and the Extras tools)."""
    return ShownArcSlider("Sharp", shown=shown, value=lambda: a.wm_get('sharp_angle', 30.0),
                          on_value=lambda v: a.wm_set('sharp_angle', float(round(v))),
                          value_range=lambda: a.wm_range('sharp_angle')[:2], fill_color=(*fill, 1.0),
                          fmt=lambda v: f"{int(round(v))}\u00b0", key=key, tint=tint, **kwargs)


def build_mask_window(bar):
    """The Mask window's content (a Group): a circle menu. Edit (choose islands / parts
    on the canvas) in the middle; around it Mask (on / off), Invert, Show (stripes) and
    the Grow slider and a small Clear in the ring. The source (UV Islands / Mesh Parts) arc above only shows
    while editing."""
    a = bar.actions
    tint = TINT_MASK

    def segment(key, painter, tint=tint, **kwargs):
        return RingSegment("", painter=painter, key=f'MASKWIN_{key}', tint=tint, **kwargs)

    center = DialCenter(painter=paint_edit, tint=TINT_MASK_EDIT, radius=MASK_CENTER, key='MASKWIN_EDIT',
                         selected=a.mask_picking, on_click=a.toggle_mask_pick)
    dial = Dial(center, gap=DIAL_GAP)
    grow = ArcSlider("Grow", value=lambda: a.wm_get('mask_grow', 0) or 0,
                      on_value=lambda v: a.wm_set('mask_grow', int(round(v))),
                      value_range=lambda: a.wm_range('mask_grow')[:2], fill_color=(*TINT_MASK, 1.0),
                      key='MASKWIN_GROW', tint=tint)
    ring = [   # (segment, a0, a1), counter-clockwise from the right
        (segment('INVERT', paint_mask_invert, selected=a.mask_inverted, on_click=a.toggle_mask_invert,
                 tint=TINT_MASK_INVERT), 0.0, 90.0),
        (segment('MASK', paint_mask, selected=a.mask_enabled, on_click=a.toggle_mask), 90.0, 180.0),
        (segment('SHOW', captioned(icon_eye, "Show"), selected=lambda: bool(a.wm_get('mask_show')),
                 on_click=lambda: a.wm_set('mask_show', not a.wm_get('mask_show')), tint=TINT_MASK_SHOW),
         180.0, 270.0),
        (grow, 270.0, GROW_END),
        (segment('CLEAR', icon_reset, tint=TINT_MASK_CLEAR,
                 on_click=lambda: bar.confirm(["Forget all chosen islands / parts?"], a.clear_mask, "Clear")),
         GROW_END, 360.0),
    ]
    for seg, a0, a1 in ring:
        dial.add_segment(seg, *MASK_RING, a0, a1)
    source = ShownSegment(a.mask_picking, "", painter=paint_source_band(a.mask_source),
                           key='MASKWIN_SOURCE', tint=tint, round=MASK_BAND_ROUND, on_click=a.toggle_mask_source,
                           options=lambda: source_options(a.mask_source()))
    angle = sharp_angle_slider(a, 'MASKWIN_SHARP_ANGLE', lambda: a.mask_picking() and a.mask_source() == 'SHARP',
                               tint, TINT_MASK, round=MASK_BAND_ROUND, short=True, reverse=True)
    opacity = ArcSlider("Opacity", value=lambda: a.wm_get('mask_opacity', 0.15),
                        on_value=lambda v: a.wm_set('mask_opacity', round(float(v), 2)),
                        value_range=(0.0, 1.0), fill_color=(*TINT_MASK_SHOW, 1.0), fmt=lambda v: f"{v * 100:.0f}%",
                        enabled=lambda: bool(a.wm_get('mask_show')), key='MASKWIN_OPACITY', tint=TINT_MASK_SHOW,
                        round=MASK_BAND_ROUND)
    dial.add_band([source], *MASK_BAND, *SOURCE_ARC)
    dial.add_band([angle], *MASK_BAND, *ANGLE_ARC)
    dial.add_band([opacity], *MASK_BAND, *OPACITY_ARC)
    width = 2.0 * MASK_BAND[1]
    content = Column([dial, help_lines(bar, 'mask', MASK_HELP, width)], gap=ROW_GAP)
    return WindowGroup("Mask", content, tint=TINT_MASK, painter=icon_mask_title, title_indent=TITLE_INDENT)
