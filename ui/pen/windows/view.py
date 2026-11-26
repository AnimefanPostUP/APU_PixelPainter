"""The View window: two 3x3 pads -- Orient (axis views, roll, Level, Back) and Orbit
(arrows around Fit; zoom, Center, Persp / Ortho).
"""


from ...kit import Column, Dial, RingSegment, Row
from ..metrics import TINT_VIEW
from .parts import CELL, DIAL_GAP, DIAL_RING, GAP, PAD_GAP, ROW_GAP, TITLE_INDENT, WindowButton, DialCenter, FlexWindowButton, ShownDial, WindowGroup, help_lines
from ..icons.windows import icon_arrow, icon_back, icon_center, icon_compact, icon_face, icon_fit, icon_level, icon_perspective, icon_roll, icon_zoom, paint_view_title
VIEW_HELP = ("Left dial: view from Front (middle), Top,",
             "Bottom, Left, Right; Back (bottom right) looks",
             "from behind. Upper diagonals roll 15, Level",
             "removes roll. Right dial: orbit 15 around the",
             "object, Fit (middle) zooms until it fills the",
             "view; zoom, Center, Persp / Ortho diagonally.",
             "Bottom left: hide / show the right dial.",
             "Auto Fit: re-fit after every orient / orbit / roll.")


def build_view_window(bar):
    """The View window's content (a Group): the Orient and Orbit pads, Auto Fit / 1:1."""
    a = bar.actions
    is3d = a.in_view3d
    tint = TINT_VIEW

    def segment(key, action, painter, enabled=is3d, **kwargs):
        return RingSegment("", painter=painter, key=f'VIEW_{key}', tint=tint, enabled=enabled,
                           on_click=action, **kwargs)

    def dial(key, action, painter, ring, enabled=True, cls=Dial, **kwargs):
        """``ring``: eight segments counter-clockwise from the right (0, 45, ... 315 degrees)."""
        center = DialCenter(painter=painter, tint=tint, key=f'VIEW_{key}', enabled=enabled, on_click=action)
        result = cls(center, gap=DIAL_GAP, **kwargs)
        for i, seg in enumerate(ring):
            angle = i * 45.0
            result.add_segment(seg, *DIAL_RING, angle - 22.5, angle + 22.5)
        return result

    step = 15.0
    face = lambda axis: segment(axis, lambda: a.view_axis(axis), icon_face(axis))
    # Orient: Front in the middle, the faces around it like an unfolded cube; the
    # diagonals roll (top), level (bottom left) and Back (bottom right, darker).
    orient = dial('FRONT', lambda: a.view_axis('FRONT'), icon_face('FRONT'), ring=[
        face('RIGHT'),
        segment('ROLL_RIGHT', lambda: a.view_roll(-step), icon_roll(-1)),
        face('TOP'),
        segment('ROLL_LEFT', lambda: a.view_roll(step), icon_roll(1)),
        face('LEFT'),
        segment('LEVEL', a.view_level, icon_level),
        face('BOTTOM'),
        segment('BACK', lambda: a.view_axis('BACK'), icon_back, fill=(0.12, 0.12, 0.12, 0.95),
                tint_amount=0.35),
    ], enabled=is3d)
    # Orbit: arrows around Fit; the diagonals zoom (top), Center, Persp / Ortho. Hidden in
    # the compact window (the button bottom left).
    compact = a.view_compact
    orbit = dial('FIT', a.view_fit, icon_fit, cls=ShownDial, shown=lambda: not compact(), ring=[
        segment('ORBIT_RIGHT', lambda: a.view_orbit(step, 0.0), icon_arrow(0.0)),
        segment('ZOOM_OUT', lambda: a.view_zoom(-1), icon_zoom(-1), enabled=True),
        segment('ORBIT_UP', lambda: a.view_orbit(0.0, step), icon_arrow(90.0)),
        segment('ZOOM_IN', lambda: a.view_zoom(1), icon_zoom(1), enabled=True),
        segment('ORBIT_LEFT', lambda: a.view_orbit(-step, 0.0), icon_arrow(180.0)),
        segment('CENTER', a.view_center, icon_center, enabled=True),
        segment('ORBIT_DOWN', lambda: a.view_orbit(0.0, -step), icon_arrow(270.0)),
        segment('PERSPECTIVE', a.toggle_view_perspective, icon_perspective(a.view_perspective)),
    ])
    full = 4 * DIAL_RING[1] + PAD_GAP
    small = 2 * DIAL_RING[1]
    width = lambda: small if compact() else full
    h = 26.0
    toggle = WindowButton("", painter=icon_compact(compact), layout='icon', size=(CELL, h), key='VIEW_COMPACT',
                  tint=tint, selected=compact, on_click=a.toggle_view_compact)
    one_w = lambda: CELL if compact() else CELL * 1.6
    one_to_one = FlexWindowButton("1:1", width=one_w, height=h, layout='row', key='VIEW_ONE_TO_ONE', tint=tint,
                          enabled=lambda: not is3d(), on_click=a.view_one_to_one)
    # Auto Fit takes the rest of the row (icon only in the compact window).
    auto = FlexWindowButton("Auto Fit", width=lambda: width() - CELL - one_w() - 2 * GAP, height=h, painter=icon_fit,
                    layout=lambda: 'icon' if compact() else 'row', key='VIEW_AUTOFIT', tint=tint, enabled=is3d,
                    selected=a.view_autofit, on_click=a.toggle_view_autofit)
    content = Column([Row([orient, orbit], gap=PAD_GAP), Row([toggle, auto, one_to_one], gap=GAP),
                      help_lines(bar, 'view', VIEW_HELP, full)], gap=ROW_GAP)
    return WindowGroup("View", content, tint=TINT_VIEW, painter=paint_view_title, title_indent=TITLE_INDENT)
