"""Tool settings panel drawing for Pixel Painter."""

from bpy.types import Panel

from ..tools import blend_modes
from ..tools import falloff
from ..tools.catalog import TOOLS, falloff_property_for


def _draw_foldout(layout, data, prop_name, label):
    row = layout.row(align=True)
    row.use_property_split = False
    row.use_property_decorate = False
    is_open = bool(getattr(data, prop_name))
    icon = 'TRIA_DOWN' if is_open else 'TRIA_RIGHT'
    row.prop(data, prop_name, text=label, icon=icon, emboss=False)
    return is_open


def _draw_tool_mode_buttons(layout, current_mode):
    layout.label(text="Tool Modes  (Shift + number)")
    grid = layout.grid_flow(row_major=True, columns=2, even_columns=True, align=True)
    for index, tool in enumerate(TOOLS, start=1):
        grid.operator(
            "image.pixel_painter_set_mode",
            text=f"{tool.label} ({index})",
            depress=(current_mode == tool.tool_id),
        ).mode = tool.tool_id


def _draw_spacing_buttons(layout, wm):
    layout.label(text="Spacing")
    row = layout.row(align=True)
    row.prop_enum(wm, "pixel_painter_spacing", 'FREE', text="Free")
    row.prop_enum(wm, "pixel_painter_spacing", 'PIXEL', text="Pixel")


def _draw_falloff_preset_buttons(layout, wm, prop_name):
    grid = layout.grid_flow(row_major=True, columns=2, even_columns=True, align=True)
    for preset in falloff.FALLOFF_PRESETS:
        grid.prop_enum(wm, prop_name, preset.id, text=preset.label)


def draw_falloff_section(layout, context, prop_name):
    """Falloff presets, or the custom curve editor when 'Custom' is selected."""
    wm = context.window_manager
    brush = context.tool_settings.image_paint.brush
    use_custom = getattr(wm, prop_name) == 'CUSTOM'
    if use_custom and brush and hasattr(brush, "curve"):
        layout.template_curve_mapping(brush, "curve", brush=True)
        lock_presets = getattr(brush, "curve_preset", "") == 'CUSTOM'
        col = layout.column(align=True)
        col.label(text="Curve Preset")
        col.enabled = not lock_presets
        _draw_falloff_preset_buttons(col, wm, prop_name)
        if lock_presets:
            layout.label(text="Curve edited: presets locked", icon='LOCKED')
    else:
        layout.label(text="Falloff")
        _draw_falloff_preset_buttons(layout, wm, prop_name)


def _in_tool_header(context):
    return getattr(getattr(context, 'region', None), 'type', '') == 'TOOL_HEADER'


class IMAGE_PT_pixel_painter_falloff(Panel):
    """Falloff presets + custom curve editor, opened from the tool header."""
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'HEADER'
    bl_label = "Falloff"
    bl_ui_units_x = 12

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False
        prop_name = falloff_property_for(context.window_manager.pixel_painter_mode)
        draw_falloff_section(layout, context, prop_name)
        if getattr(context.window_manager, prop_name) != 'CUSTOM':
            layout.label(text="Pick 'Custom' to edit the falloff curve", icon='INFO')


def draw_falloff_popover(layout, context, prop_name):
    """Compact header entry: current falloff name, opens the falloff popover."""
    preset = falloff.get(getattr(context.window_manager, prop_name))
    label = preset.label if preset else "Falloff"
    layout.popover(panel=IMAGE_PT_pixel_painter_falloff.__name__, text=f"Falloff: {label}",
                   icon='SMOOTHCURVE')


def _draw_favorites_selector(layout, wm):
    content = layout.column(align=True)
    content.use_property_split = False
    content.use_property_decorate = False
    split = content.split(factor=0.5, align=True)
    columns = (
        (split.column(align=True), (("Common", 'COMMON'), ("Contrast", 'CONTRAST'))),
        (split.column(align=True), (("Math", 'MATH'), ("HSL/HSV", 'HSL'))),
    )
    for col, groups in columns:
        for i, (title, group) in enumerate(groups):
            if i:
                col.separator()
            col.label(text=title)
            for blend in blend_modes.ids(group):
                col.prop_enum(wm, "pixel_painter_blend_favorites", blend)


def _draw_shortcuts(layout):

    shortcuts = (
        ("LMB", "Paint with primary color"),
        ("RMB", "Paint with secondary color"),
        ("Select: Drag LMB", "Create or move selection"),
        ("Select: Edge/Corner Drag", "Resize selection box"),
        ("Select: RMB", "Clear selection box"),
        ("Select: Ctrl+C / Ctrl+V", "Copy and paste selection"),
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

def draw_extra_paint_faces_button(layout):
    layout.separator()
    layout.operator("apu.paint_selected_faces_uv", text="Paint Selected Faces (UV)", icon='FACESEL')


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
    row.prop(wm, "pixel_painter_protect_transparent", text="Protect Transparent", toggle=True)
    row = layout.row(align=True)
    row.prop(wm, "pixel_painter_active_modifier", text="Modifier", slider=True)

    row = layout.row(align=True)
    if ups.use_unified_color:
        row.prop(ups, "color", text="")
        row.prop(ups, "secondary_color", text="")
    elif brush:
        row.prop(brush, "color", text="")
        row.prop(brush, "secondary_color", text="")

    # Tool-specific controls come from the tool itself.
    tool = TOOLS.get(mode)
    tool.draw_settings(context, layout)
    if tool.falloff_property:
        if _in_tool_header(context):
            draw_falloff_popover(layout, context, tool.falloff_property)
        else:
            draw_falloff_section(layout, context, tool.falloff_property)

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

        # Add a button to reset tool settings to defaults
        col.separator()
        col.operator("image.pixel_painter_reset_tool_settings", text="Reset Tool Settings", icon='LOOP_BACK')


classes = (
    IMAGE_PT_pixel_painter_falloff,
)
