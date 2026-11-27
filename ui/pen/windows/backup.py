"""The Backup window (Windows ring > outer ring > *Backup*): the texture backup
(``backup/``).

* *Backup program*: switch the helper process on / off (``pixel_painter_backup_enabled``),
  its status (textures and MB held in RAM, last sync) and *Back up now*.
* *Backups*: the saves in the cache (newest first, up to ``pixel_painter_backup_keep``,
  1..5), each written when a Blender session with unsaved textures closed or crashed:
  *Images* lists its textures below, *Restore* restores all of them, the bin deletes it.
* *Images*: the chosen save's textures, each with its own *Restore*; *As copy*
  (``pixel_painter_backup_restore_copy``) always restores into new images.
* *Options*: backups kept, delete after (days, 0 = never), sync interval; *Clear
  cache* (after a confirmation), *Open folder*.
"""

import time

import bpy

from ...kit import Column, Row, Slider, TextBlock
from ..style import DangerButton, PenButton, PlainGroup
from ..icons.palettes import library_arrow, paint_trash
from ..icons.windows import paint_backup
from ....backup import store as backup_store

PAGE_WIDTH = 300.0
IMAGES_PER_PAGE = 4
ROW_H = 22.0
TEXT_COLOR = (1.0, 1.0, 1.0, 0.9)
REASONS = {'crash': "crashed", 'closed': "closed"}
DEFAULT_STATUS = "Backups are written when Blender closes or crashes."
HELP = ("Keeps unsaved textures in RAM; writes them to disk only",
        "when Blender closes / crashes. Restore after a restart.")


def _fit(text, chars):
    text = str(text)
    return text if len(text) <= chars else text[:chars - 1] + "…"


def _when(save):
    try:
        return time.strftime("%b %d  %H:%M", time.localtime(float(save.get('timestamp', 0.0))))
    except (TypeError, ValueError, OverflowError):
        return save.get('created', "?")


def _megabytes(n):
    return f"{(n or 0) / (1024.0 * 1024.0):.1f} MB"


class BackupMenu:
    """Builds the Backup window's body (``self.content``) for a :class:`ui.pen.bar.PenBar`."""

    def __init__(self, bar):
        self.bar = bar
        self.a = a = bar.actions

        # ---- the program ----
        run = PenButton("Run backup program", painter=paint_backup, layout='row', size=(176.0, 28.0),
                        key='BACKUP_RUN', selected=lambda: bool(a.wm_get('backup_enabled', False)),
                        on_click=a.toggle_backup)
        sync = PenButton("Back up now", layout='row', size=(104.0, 28.0), key='BACKUP_SYNC',
                         enabled=lambda: a.backup_status()['running'], on_click=a.backup_sync)
        program = PlainGroup("Backup program", Column([
            Row([run, sync], gap=6.0),
            TextBlock(self._program_lines, size=9.0, width=PAGE_WIDTH - 20.0, color=TEXT_COLOR),
            TextBlock(list(HELP), size=8.5, width=PAGE_WIDTH - 20.0),
        ], gap=6.0), painter=paint_backup, width=PAGE_WIDTH)

        # ---- the saves ----
        saves = PlainGroup(lambda: f"Backups ({len(a.backup_saves())} of {a.wm_get('backup_keep', 3)} kept)",
                           Column([self._save_row(k) for k in range(backup_store.MAX_KEEP)], gap=4.0),
                           width=PAGE_WIDTH)

        # ---- the chosen save's images ----
        pager = Row([
            PenButton("", painter=library_arrow(-1), layout='icon', size=(28.0, 24.0), key='BACKUP_PREV',
                      on_click=lambda: self.turn(-1)),
            TextBlock(lambda: [f"{self._page() + 1} / {self.pages()}"], size=9.5, color=TEXT_COLOR),
            PenButton("", painter=library_arrow(1), layout='icon', size=(28.0, 24.0), key='BACKUP_NEXT',
                      on_click=lambda: self.turn(1)),
            PenButton("Restore as copy", layout='row', size=(130.0, 24.0), key='BACKUP_AS_COPY',
                      selected=lambda: bool(a.wm_get('backup_restore_copy', False)),
                      on_click=lambda: a.wm_set('backup_restore_copy', not a.wm_get('backup_restore_copy', False))),
        ], gap=8.0)
        images = PlainGroup(self._images_title,
                            Column([self._image_row(k) for k in range(IMAGES_PER_PAGE)] + [pager], gap=4.0),
                            width=PAGE_WIDTH)

        # ---- options ----
        def int_slider(prop, label, lo, hi, fmt, default):
            return Slider(label, lambda: a.wm_get(prop, default) or 0,
                          lambda v: a.wm_set(prop, int(round(v))), value_range=(lo, hi), step=1, fmt=fmt,
                          size=(PAGE_WIDTH - 20.0, 24.0), corner=12.0)

        keep = int_slider('backup_keep', "Keep backups", 1, backup_store.MAX_KEEP,
                          lambda v: f"{int(round(v))}", 3)
        days = int_slider('backup_days', "Delete after", 0, 60,
                          lambda v: "never" if v < 0.5 else f"{int(round(v))} days", 7)
        interval = int_slider('backup_interval', "Sync every", 5, 300, lambda v: f"{int(round(v))} s", 30)
        clear = DangerButton("Clear cache", painter=paint_trash, layout='row', size=(130.0, 28.0),
                             key='BACKUP_CLEAR', on_click=self.clear)
        folder = PenButton("Open folder", layout='row', size=(130.0, 28.0), key='BACKUP_FOLDER',
                           on_click=self.open_folder)
        options = PlainGroup("Options", Column([keep, days, interval, Row([clear, folder], gap=6.0)], gap=6.0),
                             width=PAGE_WIDTH)

        status = TextBlock(lambda: [_fit(a.get_state('pen_backup_status') or DEFAULT_STATUS, 58)],
                           size=9.0, width=PAGE_WIDTH)
        self.content = Column([program, saves, images, options, status], gap=8.0)

    # ---- program ---------------------------------------------------------------------

    def _program_lines(self):
        a = self.a
        st = a.backup_status()
        if st['running']:
            last = (time.strftime("%H:%M:%S", time.localtime(st['last_sync'])) if st['last_sync'] else "pending")
            return [f"Running (pid {st['pid']}): {st['images']} texture(s), {_megabytes(st['bytes'])}",
                    f"Last sync: {last}"]
        if a.wm_get('backup_enabled', False):
            return [_fit(st['error'] or "Starting...", 58), ""]
        return ["Off: textures are not backed up.", _fit(st['error'], 58) if st['error'] else ""]

    # ---- saves -----------------------------------------------------------------------

    def _save(self, k):
        saves = self.a.backup_saves()
        return saves[k] if k < len(saves) else None

    def _save_lines(self, k):
        save = self._save(k)
        if save is None:
            return ["", ""]
        reason = REASONS.get(save.get('reason'), save.get('reason', "?"))
        blend = bpy.path.basename(save.get('blend') or "") or "(unsaved file)"
        n = len(save.get('images', []))
        return [f"{_when(save)}  {reason}", _fit(f"{n} tex, {_megabytes(save.get('size'))}  {blend}", 30)]

    def _save_row(self, k):
        a = self.a
        filled = lambda: self._save(k) is not None
        text = TextBlock(lambda: self._save_lines(k), size=8.5, width=146.0, color=TEXT_COLOR, line_gap=1.25)

        def chosen():
            save, sel = self._save(k), a.backup_selected()
            return save is not None and sel is not None and save['id'] == sel['id']

        show = PenButton("Images", layout='row', size=(52.0, ROW_H), key=f'BACKUP_SHOW_{k}', enabled=filled,
                         selected=chosen, on_click=lambda: filled() and a.select_backup(self._save(k)['id']))
        restore = PenButton("Restore", layout='row', size=(56.0, ROW_H), key=f'BACKUP_RESTORE_{k}',
                            enabled=filled, on_click=lambda: self.restore_save(k))
        delete = PenButton("", painter=paint_trash, layout='icon', size=(26.0, ROW_H), key=f'BACKUP_DELETE_{k}',
                           enabled=filled, on_click=lambda: self.delete_save(k))
        return Row([text, show, restore, delete], gap=4.0)

    def restore_save(self, k):
        save = self._save(k)
        if save is None:
            return
        n = len(save.get('images', []))
        mode = "into new images" if self.a.wm_get('backup_restore_copy', False) else "(same name + size: replaced)"
        self.bar.confirm([f"Restore {n} texture(s) from {_when(save)}", mode + "?"],
                         lambda: self.a.backup_restore(save['id']), "Restore")

    def delete_save(self, k):
        save = self._save(k)
        if save is None:
            return
        self.bar.confirm([f"Delete the backup from {_when(save)}?"], lambda: self.a.backup_delete(save['id']),
                         "Delete")

    # ---- images of the chosen save -----------------------------------------------------

    def _images(self):
        save = self.a.backup_selected()
        return save, (save or {}).get('images', [])

    def _images_title(self):
        save, images = self._images()
        return f"Images of {_when(save)} ({len(images)})" if save else "Images (no backups yet)"

    def pages(self):
        return max(1, (len(self._images()[1]) + IMAGES_PER_PAGE - 1) // IMAGES_PER_PAGE)

    def _page(self):
        return max(0, min(self.pages() - 1, int(self.a.get_state('pen_backup_page') or 0)))

    def turn(self, step):
        self.a.set_state('pen_backup_page', max(0, min(self.pages() - 1, self._page() + step)))

    def _image(self, k):
        save, images = self._images()
        i = self._page() * IMAGES_PER_PAGE + k
        return (save, images[i]) if i < len(images) else (save, None)

    def _image_row(self, k):
        def line():
            _save, entry = self._image(k)
            if entry is None:
                return [""]
            exists = bpy.data.images.get(entry.get('name', '')) is not None
            size = f"{entry.get('width')} x {entry.get('height')}"
            return [_fit(f"{entry.get('name', '?')}  {size}{'' if exists else '  (missing)'}", 38)]

        filled = lambda: self._image(k)[1] is not None
        text = TextBlock(line, size=9.0, width=212.0, color=TEXT_COLOR)
        restore = PenButton("Restore", layout='row', size=(64.0, ROW_H), key=f'BACKUP_IMAGE_{k}', enabled=filled,
                            on_click=lambda: self.restore_image(k))
        return Row([text, restore], gap=4.0)

    def restore_image(self, k):
        save, entry = self._image(k)
        if save is not None and entry is not None:
            self.a.backup_restore(save['id'], entry.get('name', ''))

    # ---- options -----------------------------------------------------------------------

    def clear(self):
        n = len(self.a.backup_saves())
        if n == 0:
            self.a.set_state('pen_backup_status', "The backup cache is empty.")
            return
        self.bar.confirm(["Delete every backup", f"({n} in the cache)?"], self.a.backup_clear, "Clear")

    def open_folder(self):
        root = self.a.backup_status()['root'] or ""
        if not root:
            from ....backup.service import SERVICE
            root = SERVICE.root()
        self.a._run_deferred(lambda: bpy.ops.wm.path_open(filepath=root))

    def opened(self):
        from ....backup.service import SERVICE
        SERVICE._saves = (None, [])          # index.json may have changed (another Blender)
        self.a.set_state('pen_backup_page', 0)
