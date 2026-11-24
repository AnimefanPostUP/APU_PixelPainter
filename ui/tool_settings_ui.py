"""Tool settings panel drawing for Pixel Painter."""

from bpy.types import Panel

from ..tools import falloff
from ..tools.catalog import TOOLS, falloff_property_for


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


def _is_view3d(context):
    space = getattr(context, 'space_data', None)
    return space is not None and space.type == 'VIEW_3D'


def _draw_view3d_mode_buttons(layout, wm, label=True):
    if label:
        layout.label(text="3D Mode")
    row = layout.row(align=True)
    row.prop_enum(wm, "pixel_painter_view3d_mode", 'UV', text="UV")
    row.prop_enum(wm, "pixel_painter_view3d_mode", 'EDGE', text="Edge")


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


def _draw_settings_button(layout, text="Settings"):
    from .settings_menu import draw_settings_button  # late import: settings_menu imports this module
    draw_settings_button(layout, text=text)


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

    # Quick controls; rarely changed options live in the settings popup (ui/settings_menu.py).
    layout.prop(wm, "pixel_painter_active_size", text="Size")

    row = layout.row(align=True)
    row.prop(wm, "pixel_painter_active_strength", text="Strength", slider=True)
    row.prop(wm, "pixel_painter_active_alpha", text="Alpha", slider=True)
    row.prop(wm, "pixel_painter_protect_transparent", text="Protect Transparent", toggle=True)
    row = layout.row(align=True)
    row.prop(wm, "pixel_painter_active_modifier", text="Modifier", slider=True)
    row = layout.row(align=True)
    row.prop(wm, "pixel_painter_pen_bar", text="Pen Bar", toggle=True, icon='GREASEPENCIL')
    row.operator("image.pixel_painter_reset_pen_ui", text="" if _in_tool_header(context) else "Reset Pen UI",
                 icon='LOOP_BACK')

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
    in_header = _in_tool_header(context)
    if tool.falloff_property:
        if in_header:
            draw_falloff_popover(layout, context, tool.falloff_property)
        else:
            draw_falloff_section(layout, context, tool.falloff_property)

    if in_header:
        row = layout.row(align=True)
        row.prop_enum(wm, "pixel_painter_spacing", 'FREE', text="Free")
        row.prop_enum(wm, "pixel_painter_spacing", 'PIXEL', text="Pixel")
        if _is_view3d(context):
            _draw_view3d_mode_buttons(layout, wm, label=False)
        _draw_settings_button(layout, text="")
        return

    col = layout.column(align=True)
    col.separator()
    _draw_tool_mode_buttons(col, mode)
    col.separator()
    _draw_spacing_buttons(col, wm)
    if _is_view3d(context):
        col.separator()
        _draw_view3d_mode_buttons(col, wm)
    layout.separator()
    _draw_settings_button(layout)


classes = (
    IMAGE_PT_pixel_painter_falloff,
)
