"""WorkspaceTool definition for Pixel Painter."""

from bpy.types import WorkSpaceTool

from . import tool_settings_ui


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
        ("image.pixel_painter_open_blend_pie", {"type": 'W', "value": 'PRESS', "shift": True}, None),
        ("image.pixel_painter_custom_pie", {"type": 'W', "value": 'PRESS', "shift": False}, None),
    )

    def draw_settings(context, layout, _tool):
        tool_settings_ui.draw_tool_settings(context, layout)
        # Add extra button for painting selected faces
        if hasattr(tool_settings_ui, 'draw_extra_paint_faces_button'):
            tool_settings_ui.draw_extra_paint_faces_button(layout)
