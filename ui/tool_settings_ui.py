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

    left.operator("image.pixel_painter_set_mode", text="Circle (2)", depress=(current_mode == 'CIRCLE')).mode = 'CIRCLE'
    left.operator("image.pixel_painter_set_mode", text="Spray (3)", depress=(current_mode == 'SPRAY')).mode = 'SPRAY'
    left.operator("image.pixel_painter_set_mode", text="Smear (6)", depress=(current_mode == 'SMEAR')).mode = 'SMEAR'

    right.operator("image.pixel_painter_set_mode", text="Square (1)", depress=(current_mode == 'SQUARE')).mode = 'SQUARE'
    right.operator("image.pixel_painter_set_mode", text="Smooth (5)", depress=(current_mode == 'SMOOTH')).mode = 'SMOOTH'
    right.operator("image.pixel_painter_set_mode", text="Line (4)", depress=(current_mode == 'LINE')).mode = 'LINE'
    right.operator("image.pixel_painter_set_mode", text="Eraser (7)", depress=(current_mode == 'ERASER')).mode = 'ERASER'


def _draw_spacing_buttons(layout, wm):
    layout.label(text="Spacing")
    row = layout.row(align=True)
    row.prop_enum(wm, "pixel_painter_spacing", 'FREE', text="Free")
    row.prop_enum(wm, "pixel_painter_spacing", 'PIXEL', text="Pixel")


def _draw_falloff_preset_buttons(layout, wm, prop_name):
    split = layout.split(factor=0.5, align=True)
    left = split.column(align=True)
    right = split.column(align=True)

    left.prop_enum(wm, prop_name, 'CONSTANT', text="Constant")
    left.prop_enum(wm, prop_name, 'SMOOTH', text="Smooth")
    left.prop_enum(wm, prop_name, 'SHARPEN', text="Sharpen")

    right.prop_enum(wm, prop_name, 'LINEAR', text="Linear")
    right.prop_enum(wm, prop_name, 'SPHERE', text="Sphere")
    right.prop_enum(wm, prop_name, 'CUSTOM', text="Custom")


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


def _draw_shortcuts(layout):
    shortcuts = (
        ("LMB", "Paint with primary color"),
        ("RMB", "Paint with secondary color"),
        ("Hold Shift", "Smooth while held"),
        ("Hold Alt", "Line draw while held"),
        ("Hold Ctrl", "Pick image color"),
        ("E", "Open color bubble"),
        ("Shift+E", "Open strength/alpha bubble"),
        ("W", "Open brush type menu"),
        ("Shift+W", "Open blend mode pie"),
        ("Ctrl+Z", "Undo"),
        ("Ctrl+Shift+Z", "Redo"),
        ("Q / Esc", "Exit tool"),
    )

    for key_text, action_text in shortcuts:
        row = layout.split(factor=0.36, align=True)
        row.label(text=key_text)
        row.label(text=action_text)


def draw_tool_settings(context, layout):
    wm = context.window_manager
    ups = context.tool_settings.unified_paint_settings
    brush = context.tool_settings.image_paint.brush
    mode = wm.pixel_painter_mode

    layout.use_property_split = False
    layout.use_property_decorate = False

    # Always-visible quick controls at the top (routed to per-tool/global setting)
    layout.prop(wm, "pixel_painter_active_size", text="Size")

    row = layout.row(align=True)
    row.prop(wm, "pixel_painter_active_strength", text="Strength", slider=True)
    row.prop(wm, "pixel_painter_active_alpha", text="Alpha", slider=True)
    row = layout.row(align=True)
    row.prop(wm, "pixel_painter_active_modifier", text="Modifier", slider=True)

    row = layout.row(align=True)
    if ups.use_unified_color:
        row.prop(ups, "color", text="")
        row.prop(ups, "secondary_color", text="")
    elif brush:
        row.prop(brush, "color", text="")
        row.prop(brush, "secondary_color", text="")

    if mode == 'CIRCLE':
        use_custom = (wm.pixel_painter_circle_falloff == 'CUSTOM')
        if use_custom and brush and hasattr(brush, "curve"):
            layout.template_curve_mapping(brush, "curve", brush=True)
            lock_presets = getattr(brush, "curve_preset", "") == 'CUSTOM'
            col = layout.column(align=True)
            col.label(text="Curve Preset")
            col.enabled = not lock_presets
            _draw_falloff_preset_buttons(col, wm, "pixel_painter_circle_falloff")
            if lock_presets:
                layout.label(text="Curve edited: presets locked", icon='LOCKED')
        else:
            layout.label(text="Falloff")
            _draw_falloff_preset_buttons(layout, wm, "pixel_painter_circle_falloff")
    elif mode == 'SPRAY':
        layout.prop(wm, "pixel_painter_spray_strength", text="Density", slider=True)
        use_custom = (wm.pixel_painter_spray_falloff == 'CUSTOM')
        if use_custom and brush and hasattr(brush, "curve"):
            layout.template_curve_mapping(brush, "curve", brush=True)
            lock_presets = getattr(brush, "curve_preset", "") == 'CUSTOM'
            col = layout.column(align=True)
            col.label(text="Curve Preset")
            col.enabled = not lock_presets
            _draw_falloff_preset_buttons(col, wm, "pixel_painter_spray_falloff")
            if lock_presets:
                layout.label(text="Curve edited: presets locked", icon='LOCKED')
        else:
            layout.label(text="Falloff")
            _draw_falloff_preset_buttons(layout, wm, "pixel_painter_spray_falloff")

    root = layout.column(align=True)
    if not _draw_foldout(root, wm, "pixel_painter_ui_show_settings", "Settings"):
        return

    col = root.box().column(align=True)
    _draw_tool_mode_buttons(col, mode)
    col.separator()
    _draw_spacing_buttons(col, wm)
    col.separator()
    col.prop(wm, "pixel_painter_grid_opacity", text="Grid Opacity", slider=True)
    col.separator()
    
    # Per-tool settings for current mode
    if _draw_foldout(col, wm, "pixel_painter_ui_show_tool_settings", "Per-Tool Settings"):
        tool_col = col.box().column(align=True)
        tool_col.use_property_split = True
        
        # Size toggle and value
        row = tool_col.row(align=True)
        row.prop(wm, f'pixel_painter_{mode}_use_global_size', text="Use Global Size")
        if not getattr(wm, f'pixel_painter_{mode}_use_global_size', True):
            row.prop(wm, f'pixel_painter_{mode}_size', text="Size")
        
        # Modifier toggle and value
        row = tool_col.row(align=True)
        row.prop(wm, f'pixel_painter_{mode}_use_global_modifier', text="Use Global Modifier")
        if not getattr(wm, f'pixel_painter_{mode}_use_global_modifier', True):
            row.prop(wm, f'pixel_painter_{mode}_modifier', text="Modifier", slider=True)
        
        # Strength toggle and value
        row = tool_col.row(align=True)
        row.prop(wm, f'pixel_painter_{mode}_use_global_strength', text="Use Global Strength")
        if not getattr(wm, f'pixel_painter_{mode}_use_global_strength', True):
            row.prop(wm, f'pixel_painter_{mode}_strength', text="Strength", slider=True)

        # Alpha toggle and value
        row = tool_col.row(align=True)
        row.prop(wm, f'pixel_painter_{mode}_use_global_alpha', text="Use Global Alpha")
        if not getattr(wm, f'pixel_painter_{mode}_use_global_alpha', True):
            row.prop(wm, f'pixel_painter_{mode}_alpha', text="Alpha", slider=True)

    if _draw_foldout(col, wm, "pixel_painter_ui_show_blend_mode", "Blend Mode"):
        blend_col = col.box().column(align=True)
        if brush:
            blend_col.prop(brush, "blend", text="")
        _draw_favorites_selector(blend_col, wm)

    if _draw_foldout(col, wm, "pixel_painter_ui_show_shortcuts", "Shortcuts"):
        shortcuts_col = col.box().column(align=True)
        _draw_shortcuts(shortcuts_col)
