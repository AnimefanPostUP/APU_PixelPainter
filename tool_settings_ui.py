"""Tool settings panel drawing for Pixel Painter."""


def _draw_foldout(layout, data, prop_name, label):
    row = layout.row(align=True)
    row.use_property_split = False
    row.use_property_decorate = False
    is_open = bool(getattr(data, prop_name))
    icon = 'TRIA_DOWN' if is_open else 'TRIA_RIGHT'
    row.prop(data, prop_name, text=label, icon=icon, emboss=False)
    return is_open


def _draw_tool_mode_buttons(layout, current_mode):
    layout.label(text="Tool Modes")
    split = layout.split(factor=0.5, align=True)
    left = split.column(align=True)
    right = split.column(align=True)

    left.operator("image.pixel_painter_set_mode", text="Circle", depress=(current_mode == 'CIRCLE')).mode = 'CIRCLE'
    left.operator("image.pixel_painter_set_mode", text="Spray", depress=(current_mode == 'SPRAY')).mode = 'SPRAY'
    left.operator("image.pixel_painter_set_mode", text="Smear", depress=(current_mode == 'SMEAR')).mode = 'SMEAR'

    right.operator("image.pixel_painter_set_mode", text="Square", depress=(current_mode == 'SQUARE')).mode = 'SQUARE'
    right.operator("image.pixel_painter_set_mode", text="Smooth", depress=(current_mode == 'SMOOTH')).mode = 'SMOOTH'
    right.operator("image.pixel_painter_set_mode", text="Line", depress=(current_mode == 'LINE')).mode = 'LINE'


def _draw_spacing_buttons(layout, wm):
    layout.label(text="Spacing")
    row = layout.row(align=True)
    row.prop_enum(wm, "pixel_painter_spacing", 'FREE', text="Free")
    row.prop_enum(wm, "pixel_painter_spacing", 'PIXEL', text="Pixel")


def _draw_favorites_selector(layout, wm):
    content = layout.column(align=True)
    content.use_property_split = False
    content.use_property_decorate = False
    split = content.split(factor=0.5, align=True)
    left = split.column(align=True)
    right = split.column(align=True)

    left.label(text="Common")
    for blend in ('MIX', 'ADD', 'MUL', 'DARKEN', 'LIGHTEN', 'COLOR'):
        left.prop_enum(wm, "pixel_painter_blend_favorites", blend)
    left.separator()
    left.label(text="Contrast")
    for blend in ('SCREEN', 'OVERLAY', 'SOFTLIGHT', 'HARDLIGHT'):
        left.prop_enum(wm, "pixel_painter_blend_favorites", blend)

    right.label(text="Math")
    for blend in ('SUB', 'DIFFERENCE', 'EXCLUSION', 'COLORDODGE', 'COLORBURN'):
        right.prop_enum(wm, "pixel_painter_blend_favorites", blend)
    right.separator()
    right.label(text="HSL/HSV")
    for blend in ('HUE', 'SATURATION', 'VALUE', 'LUMINOSITY'):
        right.prop_enum(wm, "pixel_painter_blend_favorites", blend)


def draw_tool_settings(context, layout):
    wm = context.window_manager
    ups = context.tool_settings.unified_paint_settings
    brush = context.tool_settings.image_paint.brush
    mode = wm.pixel_painter_mode

    layout.use_property_split = False
    layout.use_property_decorate = False

    # Always-visible quick controls at the top
    if ups.use_unified_size:
        layout.prop(ups, "size", text="Size (1-512→0-64px)")
    elif brush:
        layout.prop(brush, "size", text="Size (1-512→0-64px)")

    row = layout.row(align=True)
    if ups.use_unified_strength:
        row.prop(ups, "strength", text="Opacity", slider=True)
    elif brush:
        row.prop(brush, "strength", text="Opacity", slider=True)
    row.prop(wm, "pixel_painter_modifier", text="Modifier", slider=True)

    row = layout.row(align=True)
    if ups.use_unified_color:
        row.prop(ups, "color", text="")
        row.prop(ups, "secondary_color", text="")
    elif brush:
        row.prop(brush, "color", text="")
        row.prop(brush, "secondary_color", text="")

    if mode == 'CIRCLE':
        layout.prop(wm, "pixel_painter_use_curve_falloff", text="Curve Falloff")
        if wm.pixel_painter_use_curve_falloff and brush and hasattr(brush, "curve"):
            layout.template_curve_mapping(brush, "curve", brush=True)
        else:
            layout.prop(wm, "pixel_painter_circle_falloff", text="Falloff")
    elif mode == 'SPRAY':
        layout.prop(wm, "pixel_painter_spray_strength", text="Density", slider=True)
        layout.prop(wm, "pixel_painter_use_curve_falloff", text="Curve Falloff")
        if wm.pixel_painter_use_curve_falloff and brush and hasattr(brush, "curve"):
            layout.template_curve_mapping(brush, "curve", brush=True)
        else:
            layout.prop(wm, "pixel_painter_spray_falloff", text="Falloff")

    root = layout.column(align=True)
    if not _draw_foldout(root, wm, "pixel_painter_ui_show_settings", "Settings"):
        return

    col = root.box().column(align=True)
    _draw_tool_mode_buttons(col, mode)
    col.separator()
    _draw_spacing_buttons(col, wm)
    col.separator()

    if _draw_foldout(col, wm, "pixel_painter_ui_show_blend_mode", "Blend Mode"):
        blend_col = col.box().column(align=True)
        if brush:
            blend_col.prop(brush, "blend", text="")
        _draw_favorites_selector(blend_col, wm)
