"""Selection tool definition.

Selection interaction (drag boxes, copy/paste, stencil) is handled by the
modal operator and :mod:`core.submodes.selector`; this class provides the
tool's metadata and settings UI.
"""

from .base import SettingDefaults, ToolBase


class SelectionTool(ToolBase):
    tool_id = 'SELECT'
    label = "Select"
    description = "Select, move, resize, copy and paste pixel regions"
    icon = "Tool_Select.png"
    defaults = SettingDefaults(size=True, modifier=True, strength=True, alpha=True)
    usable_as_line_tip = False
    shows_brush_outline = False

    def on_stroke_begin(self, env):
        pass

    def on_draw(self, env):
        return  # selection never paints through the brush path

    def draw_settings(self, context, layout):
        wm = context.window_manager
        info = layout.box().column(align=True)
        info.label(text="Selection Tool")
        info.label(text="Drag LMB to create or move a box")
        info.label(text="Drag sides or corners to resize")
        info.label(text="Ctrl+C copies, Ctrl+V pastes at cursor")
        if (getattr(wm, "pixel_painter_selection_has_pending", False)
                and not getattr(wm, "pixel_painter_selection_stencil_mode", False)):
            row = info.row(align=True)
            row.operator("image.pixel_painter_selection_copy", text="Copy", icon='COPYDOWN')
            info.label(text="Copy the selection before pasting it elsewhere")
        info.separator()
        row = info.row(align=True)
        row.operator(
            "image.pixel_painter_selection_stencil_toggle",
            text="Stencil Mode",
            depress=getattr(wm, "pixel_painter_selection_stencil_mode", False),
            icon='SNAP_FACE_CENTER',
        )
        info.label(text="Stencil mode stamps on LMB and follows the mouse")
