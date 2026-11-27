"""The backup helper process (stdlib only; started by ``backup/service.py`` with
Blender's own Python: ``python -I helper.py --root <cache> --pid <blender pid>``).

It keeps the textures Blender sends (``protocol``) in RAM, zlib-compressed, and
touches the disk only once: when Blender is gone it writes them as one save
(``store``), prunes the history and exits.

How it notices that Blender is gone:

* its stdin (the pipe from Blender) reaches its end -- the OS closes it when
  Blender exits or crashes;
* Blender's process (``--pid``) has ended (checked every ``POLL`` seconds, in case
  the pipe stays open somehow).

The reason recorded is ``closed`` when the add-on said ``detach`` first (it unloads
on a normal exit), else ``crash``. After ``detach`` / the end of the pipe while
Blender keeps running for ``GRACE`` seconds (Reload Scripts, add-on disabled), it
quits without saving: the reloaded add-on starts a new helper. ``quit`` (backup
switched off) quits at once without saving.
"""

import argparse
import os
import sys
import threading
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I leaves the script dir out

import protocol   # noqa: E402
import store      # noqa: E402

POLL = 0.5        # seconds between checks of Blender's process
GRACE = 20.0     # after detach / end of pipe: Blender still running this long = not a close


def log(message):
    try:
        sys.stderr.write(time.strftime("[%H:%M:%S] ") + message + "\n")
        sys.stderr.flush()
    except Exception:
        pass


# ---- watching Blender's process ------------------------------------------------------------

class ParentWatch:
    """Is the process ``pid`` still running? (Windows: a handle opened at start, so a
    reused pid is never mistaken for Blender.)"""

    def __init__(self, pid):
        self.pid = pid
        self.handle = None
        self.child = os.name != 'nt' and bool(pid) and os.getppid() == pid
        if pid and os.name == 'nt':
            try:
                import ctypes
                kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
                kernel32.OpenProcess.restype = ctypes.c_void_p
                kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
                SYNCHRONIZE = 0x00100000
                self.handle = kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
                self.kernel32 = kernel32
            except Exception:
                self.handle = None

    def alive(self):
        if not self.pid:
            return True
        if os.name == 'nt':
            if not self.handle:
                return True        # cannot tell: rely on the pipe
            WAIT_OBJECT_0 = 0
            return self.kernel32.WaitForSingleObject(self.handle, 0) != WAIT_OBJECT_0
        if self.child and os.getppid() != self.pid:
            return False           # re-parented: Blender is gone (a zombie still answers kill)
        try:
            os.kill(self.pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True


# ---- the cache in RAM -------------------------------------------------------------------------

class Cache:
    def __init__(self, keep, days):
        self.lock = threading.Lock()
        self.images = {}          # key -> (meta, compressed bytes)
        self.keep = keep
        self.days = days
        self.blend = ""
        self.detached_at = None
        self.ended_at = None      # the pipe reached its end
        self.quit = False
        self.wake = threading.Event()

    def handle(self, header, payload):
        op = header.get('op')
        if op == 'config':
            self.keep = store.clamp_keep(header.get('keep', self.keep))
            self.days = int(header.get('days', self.days) or 0)
            self.blend = header.get('blend', self.blend) or self.blend
        elif op == 'image':
            key = header.get('key')
            if not key:
                return
            meta = {k: v for k, v in header.items() if k not in ('op', 'key')}
            data = store.compress(payload)
            with self.lock:
                self.images[key] = (meta, data)
            if header.get('blend'):
                self.blend = header['blend']
        elif op == 'forget':
            with self.lock:
                self.images.pop(header.get('key'), None)
        elif op == 'detach':
            self.detached_at = time.time()
        elif op == 'quit':
            self.quit = True
        self.wake.set()

    def snapshot(self):
        with self.lock:
            items = sorted(self.images.values(), key=lambda item: str(item[0].get('name', '')))
        return list(items)


def read_loop(stream, cache):
    try:
        while True:
            message = protocol.read_message(stream)
            if message is None:
                break
            cache.handle(*message)
    except Exception:
        log("reader: " + traceback.format_exc())
    cache.ended_at = time.time()
    cache.wake.set()


# ---- main -------------------------------------------------------------------------------------

def run(root, pid, keep=3, days=0, stream=None, grace=GRACE):
    """Serve until Blender is gone; returns the save written (or None)."""
    stream = stream if stream is not None else sys.stdin.buffer
    cache = Cache(store.clamp_keep(keep), int(days or 0))
    parent = ParentWatch(pid)
    reader = threading.Thread(target=read_loop, args=(stream, cache), daemon=True)
    reader.start()
    log(f"started: pid {os.getpid()}, watching {pid}, cache {root}")

    while True:
        cache.wake.wait(POLL)
        cache.wake.clear()
        if cache.quit:
            log("quit (backup switched off): nothing saved")
            return None
        if not parent.alive():
            break
        pending = [t for t in (cache.detached_at, cache.ended_at) if t is not None]
        if pending and time.time() - min(pending) > grace:
            log("Blender is still running (add-on reloaded / disabled): nothing saved")
            return None

    reason = 'closed' if cache.detached_at is not None else 'crash'
    reader.join(2.0)               # whatever is still in the pipe
    images = cache.snapshot()
    if not images:
        log(f"Blender {reason}: no unsaved textures")
        store.Store(root).prune(cache.keep, cache.days)
        return None
    save = store.Store(root).write_save(images, reason, blend=cache.blend, keep=cache.keep, days=cache.days)
    log(f"Blender {reason}: saved {len(images)} texture(s) as {save['id']}")
    return save


def main(argv=None):
    parser = argparse.ArgumentParser(description="Pixel Painter texture backup helper")
    parser.add_argument('--root', required=True)
    parser.add_argument('--pid', type=int, default=0)
    parser.add_argument('--keep', type=int, default=3)
    parser.add_argument('--days', type=int, default=0)
    parser.add_argument('--grace', type=float, default=GRACE)
    args = parser.parse_args(argv)
    try:
        run(args.root, args.pid, args.keep, args.days, grace=args.grace)
    except Exception:
        log("failed: " + traceback.format_exc())
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
