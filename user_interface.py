"""WorkspaceTool definitions and pie menus."""
import os

import bpy
import bpy.utils.previews
from bpy.types import WorkSpaceTool, Menu


_preview_collection = None
_default_favorites = ('MIX', 'ADD', 'MUL', 'DARKEN', 'LIGHTEN', 'COLOR')
_blend_order = (
    'MIX', 'ADD', 'MUL', 'DARKEN', 'LIGHTEN', 'COLOR',
    'SCREEN', 'OVERLAY', 'SOFTLIGHT', 'HARDLIGHT',
    'SUB', 'DIFFERENCE', 'EXCLUSION', 'COLORDODGE', 'COLORBURN',
    'HUE', 'SATURATION', 'VALUE', 'LUMINOSITY',
)
_blend_labels = {
    'MIX': "Normal",
    'ADD': "Add",
    'MUL': "Multiply",
    'DARKEN': "Darken",
    'LIGHTEN': "Lighten",
    'COLOR': "Color",
    'SCREEN': "Screen",
    'OVERLAY': "Overlay",
    'SOFTLIGHT': "Soft Light",
    'HARDLIGHT': "Hard Light",
    'SUB': "Subtract",
    'DIFFERENCE': "Difference",
    'EXCLUSION': "Exclusion",
    'COLORDODGE': "Color Dodge",
    'COLORBURN': "Color Burn",
    'HUE': "Hue",
    'SATURATION': "Saturation",
    'VALUE': "Value",
    'LUMINOSITY': "Luminosity",
}
_blend_categories = {
    "Common": ('MIX', 'ADD', 'MUL', 'DARKEN', 'LIGHTEN', 'COLOR'),
    "Contrast": ('SCREEN', 'OVERLAY', 'SOFTLIGHT', 'HARDLIGHT'),
    "Math": ('SUB', 'DIFFERENCE', 'EXCLUSION', 'COLORDODGE', 'COLORBURN'),
    "HSL/HSV": ('HUE', 'SATURATION', 'VALUE', 'LUMINOSITY'),
}


def register_icons():
    """Load custom tool icons from the addon textures folder."""
    global _preview_collection
    unregister_icons()

    pcoll = bpy.utils.previews.new()
    textures_dir = os.path.join(os.path.dirname(__file__), "textures")

    icon_files = {
        'SQUARE': "Tool_Square.png",
        'CIRCLE': "Tool_Circle.png",
        'SPRAY':  "Tool_Spray.png",
        'SMOOTH': "Tool_Smooth.png",
        'SMEAR':  "Tool_Smear.png",
    }

    for key, filename in icon_files.items():
        path = os.path.join(textures_dir, filename)
        if os.path.exists(path):
            pcoll.load(key, path, 'IMAGE')

    _preview_collection = pcoll


def unregister_icons():
    global _preview_collection
    if _preview_collection is not None:
        bpy.utils.previews.remove(_preview_collection)
        _preview_collection = None


def _tool_icon_value(mode_name):
    if _preview_collection is None:
        return 0
    icon = _preview_collection.get(mode_name)
    return icon.icon_id if icon else 0


def _get_favorites(context):
    raw = getattr(context.window_manager, "pixel_painter_blend_favorites", _default_favorites)
    if isinstance(raw, (set, list, tuple)):
        selected = set(raw)
    elif isinstance(raw, str):
        selected = {raw} if raw else set()
    else:
        selected = set()
    if not selected:
        selected = set(_default_favorites)
    return selected


def _draw_favorites_selector(layout, wm):
    content = layout.column(align=True)
    content.use_property_split = False
    content.use_property_decorate = False
    split = content.split(factor=0.5, align=True)
    left = split.column(align=True)
    right = split.column(align=True)

    left.label(text="Common")
    for blend in _blend_categories["Common"]:
        left.prop_enum(wm, "pixel_painter_blend_favorites", blend)
    left.separator()
    left.label(text="Contrast")
    for blend in _blend_categories["Contrast"]:
        left.prop_enum(wm, "pixel_painter_blend_favorites", blend)

    right.label(text="Math")
    for blend in _blend_categories["Math"]:
        right.prop_enum(wm, "pixel_painter_blend_favorites", blend)
    right.separator()
    right.label(text="HSL/HSV")
    for blend in _blend_categories["HSL/HSV"]:
        right.prop_enum(wm, "pixel_painter_blend_favorites", blend)


class PixelPainterModePie(Menu):
    bl_idname = "PIXELPAINTER_MT_mode_pie"
    bl_label  = "Drawing Mode"

    def draw(self, context):
        layout = self.layout
        pie    = layout.menu_pie()
        pie.scale_x = 1.4
        pie.scale_y = 1.4

        pie.operator("image.pixel_painter_set_mode", text="Circle", icon_value=_tool_icon_value('CIRCLE')).mode  = 'CIRCLE'
        pie.operator("image.pixel_painter_set_mode", text="Smooth", icon_value=_tool_icon_value('SMOOTH')).mode  = 'SMOOTH'
        op = pie.operator("wm.call_menu_pie", text="Blend")
        op.name = "PIXELPAINTER_MT_blend_pie"
        pie.operator("image.pixel_painter_set_mode", text="Spray", icon_value=_tool_icon_value('SPRAY')).mode   = 'SPRAY'
        pie.operator("image.pixel_painter_set_mode", text="Square", icon_value=_tool_icon_value('SQUARE')).mode  = 'SQUARE'
        pie.operator("image.pixel_painter_set_mode", text="Smear", icon_value=_tool_icon_value('SMEAR')).mode   = 'SMEAR'


def _add_blend_item(layout, label, blend, favorites):
    icon = 'CHECKMARK' if blend in favorites else 'BLANK1'
    layout.operator("image.pixel_painter_set_blend", text=label, icon=icon).blend = blend


class PixelPainterBlendPie(Menu):
    bl_idname = "PIXELPAINTER_MT_blend_pie"
    bl_label  = "Blend Mode"

    def draw(self, context):
        layout = self.layout
        pie = layout.menu_pie()
        favorites = _get_favorites(context)

        contrast = pie.column(align=True)
        contrast.label(text="Contrast")
        _add_blend_item(contrast, "Screen", 'SCREEN', favorites)
        _add_blend_item(contrast, "Overlay", 'OVERLAY', favorites)
        _add_blend_item(contrast, "Soft Light", 'SOFTLIGHT', favorites)
        _add_blend_item(contrast, "Hard Light", 'HARDLIGHT', favorites)

        hsl = pie.column(align=True)
        hsl.label(text="HSL/HSV")
        _add_blend_item(hsl, "Hue", 'HUE', favorites)
        _add_blend_item(hsl, "Saturation", 'SATURATION', favorites)
        _add_blend_item(hsl, "Value", 'VALUE', favorites)
        _add_blend_item(hsl, "Luminosity", 'LUMINOSITY', favorites)

        math_col = pie.column(align=True)
        math_col.label(text="Math")
        math_grid = math_col.grid_flow(row_major=True, columns=3, even_columns=True, even_rows=True, align=True)
        _add_blend_item(math_grid, "Subtract", 'SUB', favorites)
        _add_blend_item(math_grid, "Difference", 'DIFFERENCE', favorites)
        _add_blend_item(math_grid, "Exclusion", 'EXCLUSION', favorites)
        _add_blend_item(math_grid, "Color Dodge", 'COLORDODGE', favorites)
        _add_blend_item(math_grid, "Color Burn", 'COLORBURN', favorites)
        math_grid.label(text="")

        common = pie.column(align=True)
        common.label(text="Favorites")
        common_grid = common.grid_flow(row_major=True, columns=3, even_columns=True, even_rows=True, align=True)
        for blend in _blend_order:
            if blend in favorites:
                _add_blend_item(common_grid, _blend_labels[blend], blend, favorites)

        # Keep the final two slots empty.
        pie.separator()
        pie.separator()


class PixelPainterTool(WorkSpaceTool):
    bl_space_type   = 'IMAGE_EDITOR'
    bl_context_mode = 'PAINT'

    bl_idname      = "image.pixel_painter_tool"
    bl_label       = "Pixel Painter"
    bl_description = "Paint pixel-perfect strokes in the Image Editor"
    bl_icon        = "ops.generic.select_box"
    bl_operator    = "image.pixel_painter_operator"

    bl_keymap = (
        ("image.pixel_painter_operator", {"type": 'LEFTMOUSE',  "value": 'PRESS'}, None),
        ("image.pixel_painter_operator", {"type": 'RIGHTMOUSE', "value": 'PRESS'}, None),
        ("image.pixel_painter_undo",     {"type": 'Z', "value": 'PRESS', "ctrl": True}, None),
        ("image.pixel_painter_redo",     {"type": 'Z', "value": 'PRESS', "ctrl": True, "shift": True}, None),
        ("wm.call_menu_pie", {"type": 'W', "value": 'PRESS'},
            {"properties": [("name", "PIXELPAINTER_MT_mode_pie")]}),
    )

    def draw_settings(context, layout, _tool):
        wm    = context.window_manager
        ups   = context.tool_settings.unified_paint_settings
        brush = context.tool_settings.image_paint.brush
        mode  = wm.pixel_painter_mode

        layout.prop(wm, "pixel_painter_mode",   text="")
        layout.prop(wm, "pixel_painter_spacing", text="")

        # Blend mode
        if brush:
            layout.prop(brush, "blend", text="")
        _draw_favorites_selector(layout, wm)

        # Size
        if ups.use_unified_size:
            layout.prop(ups, "size", text="Size (1-512→0-64px)")
        elif brush:
            layout.prop(brush, "size", text="Size (1-512→0-64px)")

        # Opacity + Modifier side by side
        row = layout.row(align=True)
        if ups.use_unified_strength:
            row.prop(ups, "strength", text="Opacity", slider=True)
        elif brush:
            row.prop(brush, "strength", text="Opacity", slider=True)
        row.prop(wm, "pixel_painter_modifier", text="Modifier", slider=True)

        # Primary + secondary color swatches side by side
        row = layout.row(align=True)
        if ups.use_unified_color:
            row.prop(ups, "color",           text="")
            row.prop(ups, "secondary_color", text="")
        elif brush:
            row.prop(brush, "color",           text="")
            row.prop(brush, "secondary_color", text="")

        # Mode-specific controls
        if mode == 'CIRCLE':
            layout.prop(wm, "pixel_painter_circle_falloff", text="Falloff")
        elif mode == 'SPRAY':
            layout.prop(wm, "pixel_painter_spray_strength", text="Density", slider=True)
            layout.prop(wm, "pixel_painter_spray_falloff",  text="Falloff")
