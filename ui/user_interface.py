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
        ("image.pixel_painter_open_blend_pie", {"type": 'W', "value": 'PRESS', "shift": True}, None),
        ("image.pixel_painter_custom_pie", {"type": 'W', "value": 'PRESS', "shift": False}, None),
    )

    def draw_settings(context, layout, _tool):
        tool_settings_ui.draw_tool_settings(context, layout)
        # Add extra button for painting selected faces
        if hasattr(tool_settings_ui, 'draw_extra_paint_faces_button'):
            tool_settings_ui.draw_extra_paint_faces_button(layout)


class PixelPainterTool3D(WorkSpaceTool):
    """Pixel Painter in the 3D Viewport (Texture Paint mode).

    Runs the same modal operator; the hovered pixel comes from ray-casting
    the active mesh (see core/view3d.py).
    TODO(3D): pies (W / Shift+W) still only exist in the Image Editor.
    """
    bl_space_type   = 'VIEW_3D'
    bl_context_mode = 'PAINT_TEXTURE'

    bl_idname      = "view3d.pixel_painter_tool"
    bl_label       = "Pixel Painter"
    bl_description = "Paint pixel-perfect strokes on the active texture in the 3D Viewport"
    bl_icon        = "ops.generic.select_box"
    bl_operator    = "image.pixel_painter_operator"

    bl_keymap = (
        ("image.pixel_painter_operator", {"type": 'LEFTMOUSE',  "value": 'PRESS'}, None),
        ("image.pixel_painter_operator", {"type": 'RIGHTMOUSE', "value": 'PRESS'}, None),
    )

    def draw_settings(context, layout, _tool):
        tool_settings_ui.draw_tool_settings(context, layout)


TOOLS = (PixelPainterTool, PixelPainterTool3D)
