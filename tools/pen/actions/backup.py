"""The Backup window's actions (texture backup, ``backup/``)."""

import bpy

from ....backup.service import SERVICE


class BackupActions:
    """Part of :class:`.bar.PenBarTool` (a mixin: uses its state)."""

    def backup_status(self):
        return SERVICE.status()

    def backup_saves(self):
        """The saves in the cache, newest first."""
        try:
            return SERVICE.saves()
        except Exception:
            return []

    def backup_selected(self):
        """The save whose images the window lists (the newest when none is chosen)."""
        saves = self.backup_saves()
        chosen = self._c().state.get('pen_backup_save')
        return next((s for s in saves if s['id'] == chosen), saves[0] if saves else None)

    def select_backup(self, save_id):
        self._c().state['pen_backup_save'] = save_id
        self._c().state['pen_backup_page'] = 0

    def backup_restore(self, save_id, image_name=""):
        as_copy = bool(self.wm_get('backup_restore_copy', False))
        self._run_deferred(lambda: bpy.ops.image.pixel_painter_backup_restore(
            save_id=save_id, image_name=image_name, as_copy=as_copy))

    def backup_delete(self, save_id):
        self._run_deferred(lambda: bpy.ops.image.pixel_painter_backup_delete('EXEC_DEFAULT', save_id=save_id))

    def backup_clear(self):
        self._run_deferred(lambda: bpy.ops.image.pixel_painter_backup_clear('EXEC_DEFAULT'))

    def backup_sync(self):
        self._run_deferred(lambda: bpy.ops.image.pixel_painter_backup_sync())

    def toggle_backup(self):
        self.wm_set('backup_enabled', not self.wm_get('backup_enabled', False))
        self._c().state['pen_backup_status'] = ("Backup program starting..." if self.wm_get('backup_enabled')
                                                else "Backup program stopped (nothing saved).")
