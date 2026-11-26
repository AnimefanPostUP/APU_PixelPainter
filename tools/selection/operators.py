"""Selection operators: Apply / Copy / Cancel / Stencil (buttons under the selection box).
"""

from bpy.types import Operator

from ...core.state import STATE
from . import geometry as ops


# ---------------------------------------------------------------------------
# Operators (on-canvas buttons + settings panel)
# ---------------------------------------------------------------------------

class PixelPainterSelectionApplyOperator(Operator):
    bl_idname = "image.pixel_painter_selection_apply"
    bl_label = "Apply Selection Preview"

    def execute(self, context):
        if not ops.apply_pending(context, STATE):
            self.report({'INFO'}, "No pending selection preview to apply")
            return {'CANCELLED'}
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


class PixelPainterSelectionCopyOperator(Operator):
    bl_idname = "image.pixel_painter_selection_copy"
    bl_label = "Copy Selection"

    def execute(self, context):
        selection_box = STATE.get('selection_box')
        space = context.space_data
        if selection_box is None or not space or not space.image:
            return {'CANCELLED'}
        STATE['selection_clipboard'] = ops.extract_region(space.image, selection_box)
        center = ops.box_center(selection_box)
        if STATE['selection_clipboard'] is not None and center is not None:
            ops.start_paste_preview(STATE, STATE['selection_clipboard'], center, selection_box)
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


class PixelPainterSelectionCancelOperator(Operator):
    bl_idname = "image.pixel_painter_selection_cancel"
    bl_label = "Cancel Selection Preview"

    def execute(self, context):
        ops.clear_like_rmb(STATE, keep_clipboard=True)
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


class PixelPainterSelectionStencilToggleOperator(Operator):
    bl_idname = "image.pixel_painter_selection_stencil_toggle"
    bl_label = "Toggle Selection Stencil Mode"

    def execute(self, context):
        if not ops.toggle_stencil_mode(context, STATE):
            self.report({'WARNING'}, "No selection source available for stencil mode")
            return {'CANCELLED'}
        return {'FINISHED'}


classes = (
    PixelPainterSelectionCopyOperator,
    PixelPainterSelectionApplyOperator,
    PixelPainterSelectionCancelOperator,
    PixelPainterSelectionStencilToggleOperator,
)
