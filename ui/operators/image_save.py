"""Save the painted image (the pen menu's *Save* button).

``image.pixel_painter_save_image`` saves the image being painted (the Image
Editor's image or the 3D Viewport's paint canvas) the way the settings say
(settings popup > Pen > Save Image):

* ``pixel_painter_save_image_method``

  - ``AUTO``: a packed image is repacked, an image with a file is saved to it,
    anything else (e.g. a new, generated image) is packed;
  - ``PACK``: always packed into the .blend;
  - ``FILE``: always written to a file -- its own, else
    ``pixel_painter_save_image_folder`` / ``<image name>.png`` (relative paths
    need a saved .blend; a packed image is unpacked to that file).

* ``pixel_painter_save_image_blend``: also save the .blend afterwards (packed
  pixels only reach the disk with the .blend).
"""

import os

import bpy
from bpy.types import Operator

from ...utils import blender_utils


def _pack(image):
    """Pack the current pixels (a modified image is packed as PNG from memory)."""
    image.pack()
    return "packed into the .blend"


def _save_to_own_file(image):
    image.save()
    return f"saved to {image.filepath}"


def _target_path(image, folder):
    """Absolute path for an image without a file: ``folder`` / ``<name>.png``."""
    if folder.startswith('//') and not bpy.data.is_saved:
        raise RuntimeError("save the .blend first (the folder is relative to it)")
    name = bpy.path.clean_name(os.path.splitext(image.name)[0]) or "image"
    return os.path.join(bpy.path.abspath(folder), name + ".png")


def _save_as_file(image, folder):
    """Write ``image`` to a file: its own path, else one in ``folder``."""
    has_path = bool(image.filepath_raw)
    if image.packed_file is not None:
        image.pack()                                   # the current pixels, not the old packed ones
        if not has_path:
            image.filepath_raw = _target_path(image, folder)
        os.makedirs(os.path.dirname(bpy.path.abspath(image.filepath_raw)), exist_ok=True)
        image.unpack(method='WRITE_ORIGINAL')
        return f"unpacked to {image.filepath}"
    if not has_path or image.source == 'GENERATED':
        path = _target_path(image, folder)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        image.filepath_raw = path
        image.file_format = 'PNG'
    return _save_to_own_file(image)


def save_image(image, method, folder):
    """Save ``image`` with ``method`` ('AUTO' / 'PACK' / 'FILE'); returns what happened."""
    if method == 'PACK':
        return _pack(image)
    if method == 'FILE':
        return _save_as_file(image, folder)
    if image.packed_file is not None:
        return _pack(image)
    if image.filepath_raw and image.source == 'FILE':
        return _save_to_own_file(image)
    return _pack(image)


class PixelPainterSaveImageOperator(Operator):
    """Save the painted image (how: settings > Pen > Save Image)"""
    bl_idname = "image.pixel_painter_save_image"
    bl_label = "Save Image"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return blender_utils.get_paint_image(context) is not None

    def execute(self, context):
        wm = context.window_manager
        image = blender_utils.get_paint_image(context)
        if image is None:
            self.report({'WARNING'}, "No image to save")
            return {'CANCELLED'}
        method = getattr(wm, 'pixel_painter_save_image_method', 'AUTO')
        folder = getattr(wm, 'pixel_painter_save_image_folder', "//textures/") or "//"
        try:
            what = save_image(image, method, folder)
        except Exception as exc:
            self.report({'ERROR'}, f"Could not save “{image.name}”: {exc}")
            return {'CANCELLED'}

        message = f"“{image.name}” {what}"
        if getattr(wm, 'pixel_painter_save_image_blend', False):
            if bpy.data.is_saved:
                bpy.ops.wm.save_mainfile()
                message += ", .blend saved"
            else:
                message += " (.blend not saved yet: use File > Save)"
        self.report({'INFO'}, message)
        for area in context.screen.areas if context.screen else ():
            area.tag_redraw()
        return {'FINISHED'}


classes = (PixelPainterSaveImageOperator,)
