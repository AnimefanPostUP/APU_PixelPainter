"""Operators of the texture backup (``backup/``): restore, delete a save, clear the
cache, sync now. Used by the pen menu's Backup window and the settings popup's
Backup tab; messages also go to the pen window (state key ``pen_backup_status``).
"""

import bpy
from bpy.types import Operator

from ...backup.service import SERVICE
from ...core.state import STATE


def _redraw(context):
    try:
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type in {'IMAGE_EDITOR', 'VIEW_3D'}:
                    area.tag_redraw()
    except Exception:
        pass


def _status(op, context, level, text):
    STATE['pen_backup_status'] = text
    op.report({level}, text)
    _redraw(context)


class PixelPainterBackupRestoreOperator(Operator):
    """Restore textures from a backup: replaces the pixels of the image with the same
    name and size (undoable), otherwise creates a new image"""
    bl_idname = "image.pixel_painter_backup_restore"
    bl_label = "Restore Backup"
    bl_options = {'REGISTER', 'UNDO'}

    save_id: bpy.props.StringProperty(name="Save", options={'SKIP_SAVE'})
    image_name: bpy.props.StringProperty(name="Image", description="Empty: every image of the save",
                                         options={'SKIP_SAVE'})
    as_copy: bpy.props.BoolProperty(name="As Copy", description="Always restore into a new image",
                                    default=False, options={'SKIP_SAVE'})

    def execute(self, context):
        from ...backup import restore
        restored, errors = restore.restore(self.save_id, self.image_name, self.as_copy)
        if restored and len(restored) == 1:
            space = getattr(context, 'space_data', None)
            if space is not None and space.type == 'IMAGE_EDITOR':
                try:
                    space.image = restored[0]
                except Exception:
                    pass
        if errors:
            _status(self, context, 'WARNING' if restored else 'ERROR',
                    f"Restored {len(restored)}, failed: " + "; ".join(errors))
        elif not restored:
            _status(self, context, 'WARNING', "Nothing to restore.")
            return {'CANCELLED'}
        else:
            names = ", ".join(img.name for img in restored[:3]) + (" ..." if len(restored) > 3 else "")
            _status(self, context, 'INFO', f"Restored {len(restored)} texture(s): {names}")
        return {'FINISHED'} if restored else {'CANCELLED'}


class PixelPainterBackupDeleteOperator(Operator):
    """Delete one backup save from the cache"""
    bl_idname = "image.pixel_painter_backup_delete"
    bl_label = "Delete Backup"
    bl_options = {'REGISTER'}

    save_id: bpy.props.StringProperty(name="Save", options={'SKIP_SAVE'})

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        try:
            SERVICE.store().delete_save(self.save_id)
        except Exception as exc:
            _status(self, context, 'ERROR', f"Could not delete the backup: {exc}")
            return {'CANCELLED'}
        if STATE.get('pen_backup_save') == self.save_id:
            STATE['pen_backup_save'] = None
        _status(self, context, 'INFO', "Backup deleted.")
        return {'FINISHED'}


class PixelPainterBackupClearOperator(Operator):
    """Delete every backup save from the cache"""
    bl_idname = "image.pixel_painter_backup_clear"
    bl_label = "Clear Backup Cache"
    bl_options = {'REGISTER'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        try:
            SERVICE.store().clear()
        except Exception as exc:
            _status(self, context, 'ERROR', f"Could not clear the backup cache: {exc}")
            return {'CANCELLED'}
        STATE['pen_backup_save'] = None
        _status(self, context, 'INFO', "Backup cache cleared.")
        return {'FINISHED'}


class PixelPainterBackupSyncOperator(Operator):
    """Send the changed textures to the backup program now"""
    bl_idname = "image.pixel_painter_backup_sync"
    bl_label = "Back Up Now"
    bl_options = {'REGISTER'}

    def execute(self, context):
        if not SERVICE.running():
            _status(self, context, 'WARNING', "The backup program is not running.")
            return {'CANCELLED'}
        sent = SERVICE.sync(force=True)
        _status(self, context, 'INFO', f"Sent {sent} changed texture(s); {len(SERVICE.sent)} in the backup.")
        return {'FINISHED'}


classes = (PixelPainterBackupRestoreOperator, PixelPainterBackupDeleteOperator, PixelPainterBackupClearOperator,
           PixelPainterBackupSyncOperator)
