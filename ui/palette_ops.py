"""Palette operators.

``image.pixel_painter_palette_from_image`` -- pick an image file; its pixel
colors become a new palette (see ``utils/palette_image.py``) in the first empty
palette slot of the project, which becomes the active palette. With all slots
taken it goes to the palette library instead (nothing is overwritten). The
result is reported, and shown in the pen menu's library window
(state key ``pen_palette_status``).
"""

import os

import bpy
import numpy as np
from bpy.types import Operator

from ..core.state import STATE
from ..tools import color_palette
from ..utils import palette_image, palette_library


def _redraw(context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type in {'IMAGE_EDITOR', 'VIEW_3D'}:
                area.tag_redraw()


class PixelPainterPaletteFromImageOperator(Operator):
    """Create a palette from the pixel colors of an image file (up to 24 colors)"""
    bl_idname = "image.pixel_painter_palette_from_image"
    bl_label = "Palette from Image"
    bl_options = {'REGISTER'}

    filepath: bpy.props.StringProperty(subtype='FILE_PATH', options={'SKIP_SAVE'})
    filter_image: bpy.props.BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'})
    filter_folder: bpy.props.BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def _status(self, context, level, text):
        STATE['pen_palette_status'] = text
        self.report({level}, text)
        _redraw(context)

    def execute(self, context):
        path = bpy.path.abspath(self.filepath)
        name = os.path.splitext(os.path.basename(path))[0] or "Image Palette"
        try:
            image = bpy.data.images.load(path, check_existing=False)
        except Exception as exc:
            self._status(context, 'ERROR', f"Cannot load the image: {exc}")
            return {'CANCELLED'}
        try:
            width, height = image.size
            pixels = np.empty(width * height * 4, dtype=np.float32)
            image.pixels.foreach_get(pixels)
        finally:
            bpy.data.images.remove(image)   # only the colors are kept

        colors, distinct = palette_image.extract_colors(pixels, width, height, color_palette.PALETTE_SIZE)
        if not colors:
            self._status(context, 'WARNING', f"“{name}” has no opaque pixels.")
            return {'CANCELLED'}
        palette = color_palette.normalize(colors, name)
        reduced = f" (reduced from {distinct})" if distinct > len(colors) else ""

        scene = context.scene
        project = color_palette.decode_project(getattr(scene, 'pixel_painter_palettes', ""))
        slot = next((i for i, p in enumerate(project["palettes"]) if p is None), None)
        if slot is None:
            library = palette_library.load() + [palette]
            palette_library.save(library)
            self._status(context, 'INFO', f"All palette slots are taken: saved “{name}” "
                                          f"({len(colors)} colors{reduced}) to the library.")
            return {'FINISHED'}
        project = color_palette.with_active(color_palette.with_palette(project, slot, palette), slot)
        scene.pixel_painter_palettes = color_palette.encode_project(project)
        self._status(context, 'INFO', f"Loaded {len(colors)} colors{reduced} from “{name}” "
                                      f"into palette slot {slot + 1}.")
        return {'FINISHED'}


classes = (PixelPainterPaletteFromImageOperator,)
