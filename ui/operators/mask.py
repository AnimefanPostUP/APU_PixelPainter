"""Paint mask operators (settings popup; the pen menu calls tools/mask.py directly).

* ``image.pixel_painter_mask_pick``: start / stop choosing islands / parts on
  the canvas (needs a running Pixel Painter session; turns the mask on).
* ``image.pixel_painter_mask_clear``: forget the chosen islands / parts.
"""

from bpy.types import Operator

from ...core.state import STATE
from ...tools.mask import data as mask_data
from ...tools.mask import tool as mask_tool


class PixelPainterMaskPickOperator(Operator):
    """Start / stop choosing UV islands or mesh parts on the canvas (tap to toggle, Esc: done)"""
    bl_idname = "image.pixel_painter_mask_pick"
    bl_label = "Edit Mask"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        mask_tool.set_picking(STATE, context, not STATE.get('mask_picking'))
        return {'FINISHED'}


class PixelPainterMaskClearOperator(Operator):
    """Forget the chosen UV islands / mesh parts of this project"""
    bl_idname = "image.pixel_painter_mask_clear"
    bl_label = "Clear Mask"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        mask_data.clear(context)
        mask_tool.redraw_editors(context)
        return {'FINISHED'}


classes = (PixelPainterMaskPickOperator, PixelPainterMaskClearOperator)
