"""WorkspaceTool definitions and pie menus."""
import bpy
from bpy.types import WorkSpaceTool, Menu


class PixelPainterModePie(Menu):
    bl_idname = "PIXELPAINTER_MT_mode_pie"
    bl_label  = "Drawing Mode"

    def draw(self, context):
        layout = self.layout
        pie    = layout.menu_pie()

        pie.operator("image.pixel_painter_set_mode", text="Square", icon='MESH_PLANE').mode   = 'SQUARE'
        pie.operator("image.pixel_painter_set_mode", text="Circle", icon='MESH_CIRCLE').mode  = 'CIRCLE'
        pie.operator("image.pixel_painter_set_mode", text="Spray",  icon='PARTICLES').mode    = 'SPRAY'
        pie.operator("image.pixel_painter_set_mode", text="Smooth", icon='SMOOTHCURVE').mode  = 'SMOOTH'
        pie.operator("image.pixel_painter_set_mode", text="Smear",  icon='FORCE_WIND').mode   = 'SMEAR'


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
