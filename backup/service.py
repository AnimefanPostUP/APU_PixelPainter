"""Blender side of the texture backup: runs the helper process (``backup/helper.py``)
while ``pixel_painter_backup_enabled`` is on and keeps its RAM cache up to date.

* A persistent timer (:func:`_tick`, every ``TICK`` s) starts / stops the helper to
  follow the setting (restarting it if it died) and every
  ``pixel_painter_backup_interval`` seconds runs :meth:`BackupService.sync`.
* ``sync`` sends every image with unsaved pixels (``is_dirty``, or packed into a
  .blend with unsaved changes) whose pixels changed since it was sent: the history
  stamp (``core.history.STAMP_KEY``, new on every Pixel Painter edit / undo) or the
  size changed; every ``RECHECK_EVERY``-th sync also compares the checksum of the
  others (edits by Blender's own brushes). Images that are saved / gone are
  forgotten, so a project closed with everything saved leaves no backup. No sync
  runs during a stroke.
* Writing to the pipe happens on a thread (:class:`_Sender`; the latest message per
  image wins), so Blender only pays for reading the pixels.
* ``unregister`` (also on a normal exit: Blender disables its add-ons) sends
  ``detach``; switching the backup off sends ``quit`` (nothing saved).

The cache folder: ``<Blender config>/apu_pixel_painter/backup`` (:func:`cache_root`).
"""

import atexit
import collections
import os
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import zlib

import bpy

from . import protocol
from . import store as store_mod

HELPER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "helper.py")
TICK = 1.0               # seconds between timer ticks
RESTART_DELAY = 10.0     # seconds between attempts to (re)start the helper
PRUNE_DELAY = 3.0        # seconds after the last keep / days change before pruning
RECHECK_EVERY = 4        # every n-th sync also checksums images whose stamp did not change
PIXEL_TYPES = {'IMAGE', 'UV_TEST'}   # image files and generated images (not render results)
STAMP_KEY = "pixel_painter_history"   # core.history.STAMP_KEY (no import: history imports bpy handlers)


def cache_root():
    """The cache folder (created on demand)."""
    base = None
    try:
        base = bpy.utils.user_resource('CONFIG', path=os.path.join('apu_pixel_painter', 'backup'), create=True)
    except Exception:
        base = None
    if not base:
        base = os.path.join(tempfile.gettempdir(), 'apu_pixel_painter_backup')
    os.makedirs(base, exist_ok=True)
    return base


def python_executable():
    """Blender's bundled Python (``sys.executable`` in Blender 2.92+), or None."""
    exe = sys.executable or ""
    if exe and 'python' in os.path.basename(exe).lower() and os.path.isfile(exe):
        return exe
    ver = f"{sys.version_info.major}.{sys.version_info.minor}"
    for name in ('python.exe', f'python{ver}', 'python3', 'python'):
        path = os.path.join(sys.prefix, 'bin', name)
        if os.path.isfile(path):
            return path
    return None


def _wm():
    return getattr(bpy.context, 'window_manager', None)


def _setting(name, default):
    wm = _wm()
    return getattr(wm, f'pixel_painter_backup_{name}', default) if wm is not None else default


def wants(img, blend_dirty):
    """Does ``img`` hold pixels that a crash would lose?"""
    try:
        if img.type not in PIXEL_TYPES or not img.has_data:
            return False
        w, h = img.size
        if w <= 0 or h <= 0:
            return False
        return bool(img.is_dirty or (img.packed_file is not None and blend_dirty))
    except Exception:
        return False


def image_meta(img, nbytes, crc, blend):
    meta = {'op': 'image', 'name': img.name, 'width': int(img.size[0]), 'height': int(img.size[1]),
            'channels': 4, 'dtype': 'float32', 'nbytes': int(nbytes), 'crc': int(crc), 'blend': blend}
    for key, read in (('is_float', lambda: bool(img.is_float)),
                      ('colorspace', lambda: img.colorspace_settings.name),
                      ('alpha_mode', lambda: img.alpha_mode),
                      ('filepath', lambda: img.filepath_raw),
                      ('packed', lambda: img.packed_file is not None)):
        try:
            meta[key] = read()
        except Exception:
            pass
    return meta


class _Sender(threading.Thread):
    """Writes queued messages to the helper's stdin. One slot per key: a newer
    message for an image replaces one not sent yet."""

    def __init__(self, stream):
        super().__init__(daemon=True, name="PixelPainterBackupSender")
        self.stream = stream
        self.cond = threading.Condition()
        self.pending = collections.OrderedDict()
        self.closed = False
        self.failed = None
        self.sent_bytes = 0

    def put(self, key, header, payload=None):
        with self.cond:
            self.pending.pop(key, None)
            self.pending[key] = (header, payload)
            self.cond.notify()

    def close(self):
        with self.cond:
            self.closed = True
            self.cond.notify()

    def busy(self):
        with self.cond:
            return bool(self.pending)

    def run(self):
        while True:
            with self.cond:
                while not self.pending and not self.closed:
                    self.cond.wait()
                if not self.pending:
                    break
                _key, (header, payload) = self.pending.popitem(last=False)
            try:
                protocol.write_message(self.stream, header, payload)
                self.sent_bytes += int(header.get('nbytes', 0) or 0)
            except Exception as exc:
                self.failed = str(exc) or exc.__class__.__name__
                return
        try:
            self.stream.close()
        except Exception:
            pass


class BackupService:
    def __init__(self):
        self.proc = None
        self.sender = None
        self.sent = {}            # key -> {'token', 'crc', 'nbytes', 'name'}
        self.syncs = 0
        self.last_sync = 0.0
        self.last_sync_wall = None
        self.last_start_try = 0.0
        self.error = ""
        self.pruned = False
        self.prune_at = None      # monotonic time of a pending prune (config_changed)
        self._root = None
        self._saves = (None, [])  # (index mtime, saves)

    # ---- cache ---------------------------------------------------------------------

    def root(self):
        if self._root is None:
            self._root = cache_root()
        return self._root

    def store(self):
        return store_mod.Store(self.root())

    def saves(self):
        """The saves in the cache, newest first (re-read when index.json changed)."""
        store = self.store()
        mtime = store.index_mtime()
        if mtime != self._saves[0]:
            self._saves = (mtime, store.saves())
        return self._saves[1]

    def prune(self):
        removed = self.store().prune(_setting('keep', 3), _setting('days', 7))
        self._saves = (None, [])
        return removed

    def config_changed(self):
        """Keep / days changed: tell the helper; prune once the value settled (a slider
        dragged from 7 to 0 days passes 1 day on the way)."""
        self._send_config()
        self.prune_at = time.monotonic() + PRUNE_DELAY

    # ---- process -------------------------------------------------------------------

    def running(self):
        return (self.proc is not None and self.proc.poll() is None
                and self.sender is not None and self.sender.failed is None)

    def _send_config(self):
        if self.sender is not None:
            self.sender.put('__config__', {'op': 'config', 'keep': store_mod.clamp_keep(_setting('keep', 3)),
                                           'days': int(_setting('days', 7)), 'blend': bpy.data.filepath})

    def start(self):
        exe = python_executable()
        if exe is None:
            self.error = "Blender's Python was not found: backup not started."
            return False
        root = self.root()
        cmd = [exe, '-I', HELPER, '--root', root, '--pid', str(os.getpid()),
               '--keep', str(store_mod.clamp_keep(_setting('keep', 3))), '--days', str(int(_setting('days', 7)))]
        try:
            log = open(os.path.join(root, store_mod.LOG_FILE), 'wb')
        except OSError:
            log = subprocess.DEVNULL
        kwargs = dict(stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log, cwd=root)
        attempts = []
        if os.name == 'nt':
            base = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            # Out of Blender's job object (if any), so the helper outlives a crash.
            attempts = [dict(creationflags=base | subprocess.CREATE_BREAKAWAY_FROM_JOB), dict(creationflags=base)]
        else:
            attempts = [dict(start_new_session=True)]
        proc, failure = None, None
        for extra in attempts:
            try:
                proc = subprocess.Popen(cmd, **kwargs, **extra)
                break
            except OSError as exc:
                failure = exc
        if log is not subprocess.DEVNULL:
            log.close()
        if proc is None:
            self.error = f"Could not start the backup program: {failure}"
            return False
        self.proc = proc
        self.sender = _Sender(proc.stdin)
        self.sender.start()
        self.sent.clear()
        self.syncs = 0
        self.last_sync = 0.0          # first sync on the next tick
        self.error = ""
        self._send_config()
        return True

    def stop(self, op='quit'):
        """``op``: 'quit' (nothing saved) or 'detach' (saved if Blender exits now)."""
        sender, proc = self.sender, self.proc
        self.sender = self.proc = None
        self.sent.clear()
        if sender is not None:
            if sender.failed is None:
                sender.put(f'__{op}__', {'op': op})
            sender.close()
            sender.join(5.0 if op == 'detach' else 2.0)
        if proc is not None and op == 'quit':
            try:
                proc.wait(2.0)
            except Exception:
                pass

    # ---- syncing -------------------------------------------------------------------

    def sync(self, force=False):
        """Send changed images, forget saved / removed ones. Returns the number sent."""
        if not self.running():
            return 0
        if not force:
            try:
                from ..utils import pixel_io
                if getattr(pixel_io, '_session', None) is not None:
                    return 0              # a stroke runs: next tick
            except Exception:
                pass
            if self.sender.busy():
                return 0                  # the last batch is still on its way
        from ..utils import pixel_io
        self.syncs += 1
        recheck = force or self.syncs % RECHECK_EVERY == 1
        blend = bpy.data.filepath
        blend_dirty = bool(bpy.data.is_dirty)
        current, sent = set(), 0
        for img in bpy.data.images:
            if not wants(img, blend_dirty):
                continue
            key = f"{blend}|{img.name_full}"
            current.add(key)
            try:
                token = (img.get(STAMP_KEY), tuple(img.size))
            except Exception:
                token = (None, tuple(img.size))
            prev = self.sent.get(key)
            if prev is not None and prev['token'] == token and not recheck:
                continue
            try:
                arr = pixel_io.read(img)
            except Exception:
                traceback.print_exc()
                continue
            crc = zlib.crc32(memoryview(arr).cast('B'))
            if prev is not None and prev['crc'] == crc and prev['token'][1] == token[1]:
                prev['token'] = token
                continue
            header = image_meta(img, arr.nbytes, crc, blend)
            header['key'] = key
            self.sender.put(key, header, arr)
            self.sent[key] = {'token': token, 'crc': crc, 'nbytes': int(arr.nbytes), 'name': img.name}
            sent += 1
        for key in [k for k in self.sent if k not in current]:
            self.sender.put(key, {'op': 'forget', 'key': key})
            del self.sent[key]
        self.last_sync_wall = time.time()
        return sent

    def tick(self):
        if _wm() is None:
            return
        if not self.pruned:
            self.pruned = True
            try:
                self.prune()
            except Exception:
                traceback.print_exc()
        now = time.monotonic()
        if self.prune_at is not None and now >= self.prune_at:
            self.prune_at = None
            try:
                self.prune()
            except Exception:
                traceback.print_exc()
        if _setting('enabled', False):
            if not self.running():
                if self.proc is not None:
                    detail = self.sender.failed if self.sender is not None and self.sender.failed else "it exited"
                    self.error = f"The backup program stopped ({detail}); restarting."
                    self.stop('quit')
                if now - self.last_start_try >= RESTART_DELAY:
                    self.last_start_try = now
                    self.start()
            elif now - self.last_sync >= max(1, int(_setting('interval', 30))):
                self.last_sync = now
                self.sync()
        elif self.proc is not None:
            self.stop('quit')

    # ---- UI ------------------------------------------------------------------------

    def status(self):
        running = self.running()
        return {
            'running': running,
            'pid': self.proc.pid if running else None,
            'images': len(self.sent),
            'bytes': sum(v['nbytes'] for v in self.sent.values()),
            'last_sync': self.last_sync_wall,
            'error': self.error,
            'root': self._root or "",
        }


SERVICE = BackupService()


def _tick():
    try:
        SERVICE.tick()
    except Exception:
        traceback.print_exc()
    return TICK


def _at_exit():
    try:
        if SERVICE.proc is not None:
            SERVICE.stop('detach')
    except Exception:
        pass


def register():
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=TICK, persistent=True)
    atexit.register(_at_exit)


def unregister():
    try:
        if bpy.app.timers.is_registered(_tick):
            bpy.app.timers.unregister(_tick)
    except Exception:
        pass
    try:
        atexit.unregister(_at_exit)
    except Exception:
        pass
    _at_exit()
