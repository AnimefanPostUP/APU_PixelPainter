"""The backup cache on disk (stdlib only: shared by the helper and the add-on).

Layout of the cache folder::

    index.json            every save and the files it holds (see below)
    saves/<save id>/      one folder per save
        000.bin, 001.bin  the textures: raw pixels, zlib-compressed
    helper.log            the helper's log (overwritten on each start)

``index.json``::

    {"version": 1,
     "saves": [                      # newest first
       {"id": "20261127-143005-1234", "created": "2026-11-27T14:30:05",
        "timestamp": 1795793405.2, "reason": "crash" | "closed",
        "blend": "C:/.../project.blend", "size": <bytes on disk>,
        "images": [{"name": "Body", "file": "000.bin", "width": 64, "height": 64,
                    "channels": 4, "dtype": "float32", "nbytes": 65536, "crc": 1234,
                    "is_float": false, "colorspace": "sRGB", "alpha_mode": "STRAIGHT",
                    "filepath": "//textures/body.png", "packed": false}]}]}

Every change to the index goes through :func:`_locked` (a lock file), so several
Blender instances (each with its own helper) can share the cache.
"""

import contextlib
import json
import os
import shutil
import time
import zlib

INDEX_FILE = "index.json"
SAVES_DIR = "saves"
LOCK_FILE = "index.lock"
LOG_FILE = "helper.log"
VERSION = 1
MAX_KEEP = 5
COMPRESS_LEVEL = 1          # fast: the helper compresses every texture it receives
LOCK_TIMEOUT = 10.0         # seconds waiting for the lock
LOCK_STALE = 60.0           # a lock file older than this is left over from a dead process
DAY = 86400.0
ORPHAN_AGE = 3600.0         # an unlisted save folder older than this is removed by prune()


def compress(data):
    return zlib.compress(bytes(data) if not isinstance(data, bytes) else data, COMPRESS_LEVEL)


def clamp_keep(keep):
    try:
        return max(1, min(MAX_KEEP, int(keep)))
    except (TypeError, ValueError):
        return 3


class Store:
    def __init__(self, root):
        self.root = root

    # ---- paths ---------------------------------------------------------------------

    @property
    def index_path(self):
        return os.path.join(self.root, INDEX_FILE)

    def save_dir(self, save_id):
        return os.path.join(self.root, SAVES_DIR, save_id)

    def ensure(self):
        os.makedirs(os.path.join(self.root, SAVES_DIR), exist_ok=True)

    # ---- lock ----------------------------------------------------------------------

    @contextlib.contextmanager
    def _locked(self):
        self.ensure()
        path = os.path.join(self.root, LOCK_FILE)
        deadline = time.time() + LOCK_TIMEOUT
        fd = None
        while fd is None:
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(path) > LOCK_STALE:
                        os.remove(path)
                        continue
                except OSError:
                    pass
                if time.time() > deadline:
                    break          # go on unlocked rather than lose a save
                time.sleep(0.05)
        try:
            yield
        finally:
            if fd is not None:
                os.close(fd)
                try:
                    os.remove(path)
                except OSError:
                    pass

    # ---- index ---------------------------------------------------------------------

    def load_index(self):
        try:
            with open(self.index_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError):
            return {'version': VERSION, 'saves': []}
        saves = data.get('saves') if isinstance(data, dict) else None
        if not isinstance(saves, list):
            saves = []
        saves = [s for s in saves if isinstance(s, dict) and isinstance(s.get('id'), str)]
        saves.sort(key=lambda s: s.get('timestamp', 0.0), reverse=True)
        return {'version': VERSION, 'saves': saves}

    def _write_index(self, index):
        tmp = self.index_path + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(index, f, indent=2)
        os.replace(tmp, self.index_path)

    def saves(self):
        """Every save, newest first."""
        return self.load_index()['saves']

    def find(self, save_id):
        return next((s for s in self.saves() if s['id'] == save_id), None)

    def index_mtime(self):
        try:
            return os.path.getmtime(self.index_path)
        except OSError:
            return None

    # ---- writing -------------------------------------------------------------------

    @staticmethod
    def new_id(now):
        t = time.localtime(now)
        return time.strftime("%Y%m%d-%H%M%S", t) + f"-{os.getpid() % 10000:04d}"

    def write_save(self, images, reason, blend="", keep=3, days=0, now=None):
        """Write a save: ``images`` is a list of ``(meta dict, compressed bytes)``.
        Returns the save's index entry (None when there was nothing to save). Prunes
        to ``keep`` saves / ``days`` afterwards."""
        if not images:
            return None
        now = time.time() if now is None else now
        save_id = self.new_id(now)
        self.ensure()
        folder = self.save_dir(save_id)
        n = 1
        while os.path.exists(folder):
            n += 1
            folder = self.save_dir(f"{save_id}-{n}")
        save_id = os.path.basename(folder)
        os.makedirs(folder)
        entries, size = [], 0
        for i, (meta, data) in enumerate(images):
            name = f"{i:03d}.bin"
            with open(os.path.join(folder, name), 'wb') as f:
                f.write(data)
            size += len(data)
            entry = {k: v for k, v in meta.items() if k not in ('op', 'key', 'nbytes_raw')}
            entry['file'] = name
            entries.append(entry)
        save = {'id': save_id, 'created': time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
                'timestamp': now, 'reason': reason, 'blend': blend, 'size': size, 'images': entries}
        with self._locked():
            index = self.load_index()
            index['saves'].insert(0, save)
            self._write_index(index)
        self.prune(keep, days, now=now)
        return save

    # ---- reading -------------------------------------------------------------------

    def read_pixels(self, save_id, entry):
        """The raw pixel bytes of one image of a save (decompressed)."""
        with open(os.path.join(self.save_dir(save_id), entry['file']), 'rb') as f:
            data = zlib.decompress(f.read())
        expected = entry.get('nbytes')
        if expected is not None and len(data) != int(expected):
            raise ValueError(f"{entry.get('name')}: {len(data)} bytes, expected {expected}")
        return data

    # ---- removing ------------------------------------------------------------------

    def delete_save(self, save_id):
        with self._locked():
            index = self.load_index()
            index['saves'] = [s for s in index['saves'] if s['id'] != save_id]
            self._write_index(index)
        shutil.rmtree(self.save_dir(save_id), ignore_errors=True)

    def prune(self, keep, days, now=None):
        """Keep the newest ``keep`` saves (1..5), drop saves older than ``days``
        (0 = no age limit) and folders the index does not list. Returns the removed ids."""
        now = time.time() if now is None else now
        keep = clamp_keep(keep)
        if not os.path.isdir(self.root):
            return []
        with self._locked():
            index = self.load_index()
            kept, removed = [], []
            for save in index['saves']:
                too_old = days and days > 0 and now - float(save.get('timestamp', now)) > days * DAY
                if too_old or len(kept) >= keep:
                    removed.append(save['id'])
                else:
                    kept.append(save)
            if removed or not os.path.exists(self.index_path):
                index['saves'] = kept
                self._write_index(index)
            listed = {s['id'] for s in kept}
        saves_root = os.path.join(self.root, SAVES_DIR)
        try:
            folders = os.listdir(saves_root)
        except OSError:
            folders = []
        for name in folders:
            path = os.path.join(saves_root, name)
            if name not in listed:
                if name not in removed:   # an unlisted folder: maybe another helper is writing it
                    try:
                        if now - os.path.getmtime(path) < ORPHAN_AGE:
                            continue
                    except OSError:
                        continue
                shutil.rmtree(path, ignore_errors=True)
                if name not in removed:
                    removed.append(name)
        return removed

    def clear(self):
        """Delete every save."""
        with self._locked():
            self._write_index({'version': VERSION, 'saves': []})
        shutil.rmtree(os.path.join(self.root, SAVES_DIR), ignore_errors=True)
        self.ensure()

    def disk_size(self):
        return sum(int(s.get('size', 0) or 0) for s in self.saves())
