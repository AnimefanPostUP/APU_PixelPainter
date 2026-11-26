"""Paint mask actions of the Mask window (picking, source, invert, grow, clear).
"""

import traceback

import bpy

from ...mask import data as mask_data
from ...mask import tool as mask_tool


class MaskActions:
    """Part of :class:`.bar.PenBarTool` (a mixin: uses its state)."""

    # ---- paint mask (tools/mask.py) ---------------------------------------------------

    def mask_enabled(self):
        return bool(self.wm_get('mask_enabled', False))

    def toggle_mask(self):
        on = not self.mask_enabled()
        self.wm_set('mask_enabled', on)
        if not on and self.mask_picking():
            mask_tool.set_picking(self._c().state, self._c().context, False)

    def mask_source(self):
        return self.wm_get('mask_source', 'UV_ISLAND')

    def toggle_mask_source(self):
        self.wm_set('mask_source', 'MESH_PART' if self.mask_source() == 'UV_ISLAND' else 'UV_ISLAND')

    def mask_inverted(self):
        return bool(self.wm_get('mask_invert', False))

    def toggle_mask_invert(self):
        self.wm_set('mask_invert', not self.mask_inverted())

    def mask_picking(self):
        return bool(self._c().state.get('mask_picking'))

    def toggle_mask_pick(self):
        ctx = self._c()
        mask_tool.set_picking(ctx.state, ctx.context, not self.mask_picking())

    def clear_mask(self):
        mask_data.clear(self._c().context)

    def save_image(self):
        """Save the painted image (how: settings > Pen > Save Image, ui/image_save_ops.py)."""
        self._run_deferred(lambda: bpy.ops.image.pixel_painter_save_image())

    def image_unsaved(self):
        """The painted image has changes that are not saved / packed yet."""
        try:
            image = self._c().image
            return bool(image is not None and image.is_dirty)
        except Exception:
            return False

    def undo(self):
        self._run_deferred(lambda: bpy.ops.ed.undo())

    def redo(self):
        self._run_deferred(lambda: bpy.ops.ed.redo())

    def _run_deferred(self, fn):
        """Call ``fn`` (an operator call) on the next tick, outside the modal event handler."""
        ctx = self._c()
        window, area, region = ctx.context.window, ctx.area, ctx.region

        def _run():
            try:
                with bpy.context.temp_override(window=window, area=area, region=region):
                    fn()
            except Exception:
                traceback.print_exc()
            return None

        bpy.app.timers.register(_run, first_interval=0.0)
