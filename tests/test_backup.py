"""Tests of the texture backup's standalone parts (backup/protocol.py, store.py,
helper.py -- stdlib only, no Blender): message framing, the cache index (write,
history limit, age limit, delete, clear) and the helper process end to end.

    python -m unittest discover -s tests -v
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zlib

_BACKUP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backup')
sys.path.insert(0, _BACKUP_DIR)

import protocol  # noqa: E402
import store     # noqa: E402
import helper    # noqa: E402

HELPER = os.path.join(_BACKUP_DIR, 'helper.py')


def _pixels(n, value):
    import array
    return array.array('f', [value] * (n * 4))


def _meta(name, w=2, h=2):
    return {'op': 'image', 'key': f"|{name}", 'name': name, 'width': w, 'height': h, 'channels': 4,
            'dtype': 'float32', 'nbytes': w * h * 16}


class ProtocolTest(unittest.TestCase):
    def test_roundtrip(self):
        buf = io.BytesIO()
        payload = _pixels(4, 0.5)
        protocol.write_message(buf, {'op': 'image', 'name': 'A'}, payload)
        protocol.write_message(buf, {'op': 'forget', 'key': 'k'})
        buf.seek(0)
        header, data = protocol.read_message(buf)
        self.assertEqual(header['op'], 'image')
        self.assertEqual(header['nbytes'], 64)
        self.assertEqual(data, payload.tobytes())
        header, data = protocol.read_message(buf)
        self.assertEqual((header['op'], data), ('forget', b''))
        self.assertIsNone(protocol.read_message(buf))

    def test_truncated_payload_is_end(self):
        buf = io.BytesIO()
        protocol.write_message(buf, {'op': 'image'}, b'12345678')
        data = buf.getvalue()[:-3]
        self.assertIsNone(protocol.read_message(io.BytesIO(data)))


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='pp_backup_test_')
        self.store = store.Store(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _save(self, now, names=('Body',), reason='crash', keep=5, days=0):
        images = [(_meta(n), store.compress(_pixels(4, i / 10.0).tobytes())) for i, n in enumerate(names)]
        return self.store.write_save(images, reason, blend="C:/p.blend", keep=keep, days=days, now=now)

    def test_write_and_read(self):
        save = self._save(1000.0, names=('Body', 'Head'))
        with open(os.path.join(self.root, store.INDEX_FILE), encoding='utf-8') as f:
            index = json.load(f)
        self.assertEqual(index['saves'][0]['id'], save['id'])
        self.assertEqual([e['name'] for e in save['images']], ['Body', 'Head'])
        self.assertNotIn('key', save['images'][0])
        data = self.store.read_pixels(save['id'], save['images'][1])
        self.assertEqual(data, _pixels(4, 0.1).tobytes())

    def test_nothing_to_save(self):
        self.assertIsNone(self.store.write_save([], 'crash'))
        self.assertEqual(self.store.saves(), [])

    def test_keep_limit(self):
        ids = [self._save(1000.0 + i * 10, keep=3)['id'] for i in range(5)]
        self.assertEqual([s['id'] for s in self.store.saves()], ids[:1:-1])
        self.assertEqual(sorted(os.listdir(os.path.join(self.root, store.SAVES_DIR))), sorted(ids[2:]))
        self.store.prune(1, 0, now=2000.0)
        self.assertEqual([s['id'] for s in self.store.saves()], [ids[-1]])

    def test_age_limit(self):
        day = store.DAY
        old = self._save(0.0)['id']
        new = self._save(9 * day)['id']
        self.store.prune(5, 7, now=10 * day)
        self.assertEqual([s['id'] for s in self.store.saves()], [new])
        self.assertFalse(os.path.exists(self.store.save_dir(old)))
        self.store.prune(5, 0, now=1000 * day)      # 0 days: no age limit
        self.assertEqual(len(self.store.saves()), 1)

    def test_delete_and_clear(self):
        a = self._save(1000.0)['id']
        b = self._save(2000.0)['id']
        self.store.delete_save(a)
        self.assertEqual([s['id'] for s in self.store.saves()], [b])
        self.store.clear()
        self.assertEqual(self.store.saves(), [])
        self.assertEqual(os.listdir(os.path.join(self.root, store.SAVES_DIR)), [])

    def test_broken_index(self):
        os.makedirs(self.root, exist_ok=True)
        with open(os.path.join(self.root, store.INDEX_FILE), 'w') as f:
            f.write("{not json")
        self.assertEqual(self.store.saves(), [])
        self._save(1000.0)
        self.assertEqual(len(self.store.saves()), 1)


class HelperTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='pp_backup_helper_')

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_detach_while_parent_lives_saves_nothing(self):
        r, w = os.pipe()
        reader, writer = os.fdopen(r, 'rb'), os.fdopen(w, 'wb')
        result = {}
        t = threading.Thread(target=lambda: result.setdefault(
            'save', helper.run(self.root, os.getpid(), stream=reader, grace=0.5)))
        t.start()
        protocol.write_message(writer, _meta('A'), _pixels(4, 1.0))
        protocol.write_message(writer, {'op': 'detach'})
        writer.close()
        t.join(10.0)
        self.assertFalse(t.is_alive())
        reader.close()
        self.assertIsNone(result['save'])
        self.assertEqual(store.Store(self.root).saves(), [])

    def test_quit_saves_nothing(self):
        stream = io.BytesIO()
        protocol.write_message(stream, _meta('A'), _pixels(4, 1.0))
        protocol.write_message(stream, {'op': 'quit'})
        stream.seek(0)
        self.assertIsNone(helper.run(self.root, os.getpid(), stream=stream, grace=30.0))

    def _run_with_parent(self, messages, end):
        """A stand-in 'Blender' process; the helper watches it. ``end``: 'kill' (crash) or
        'detach' (normal close: detach, then the parent exits)."""
        parent = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        proc = subprocess.Popen([sys.executable, '-I', HELPER, '--root', self.root, '--pid', str(parent.pid),
                                 '--keep', '2', '--grace', '30'],
                                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            for header, payload in messages:
                protocol.write_message(proc.stdin, header, payload)
            if end == 'detach':
                protocol.write_message(proc.stdin, {'op': 'detach'})
            time.sleep(0.5)
            parent.kill()
            parent.wait(10)
            proc.wait(20)
        finally:
            for p in (proc, parent):
                if p.poll() is None:
                    p.kill()
            try:
                proc.stdin.close()
            except OSError:
                pass
        log = proc.stderr.read().decode('utf-8', 'replace')
        proc.stderr.close()
        return log

    def test_crash_writes_save(self):
        log = self._run_with_parent([
            (_meta('Body'), _pixels(4, 0.25)),
            (_meta('Head'), _pixels(4, 0.5)),
            ({'op': 'forget', 'key': '|Head'}, None),
            (_meta('Body'), _pixels(4, 0.75)),        # the newer pixels win
        ], 'kill')
        saves = store.Store(self.root).saves()
        self.assertEqual(len(saves), 1, log)
        save = saves[0]
        self.assertEqual(save['reason'], 'crash')
        self.assertEqual([e['name'] for e in save['images']], ['Body'])
        data = store.Store(self.root).read_pixels(save['id'], save['images'][0])
        self.assertEqual(data, _pixels(4, 0.75).tobytes())
        path = os.path.join(store.Store(self.root).save_dir(save['id']), save['images'][0]['file'])
        with open(path, 'rb') as f:
            self.assertEqual(zlib.decompress(f.read()), data)

    def test_close_after_detach_is_closed(self):
        log = self._run_with_parent([(_meta('Body'), _pixels(4, 0.25))], 'detach')
        saves = store.Store(self.root).saves()
        self.assertEqual([s['reason'] for s in saves], ['closed'], log)

    def test_no_textures_no_save(self):
        self._run_with_parent([], 'kill')
        self.assertEqual(store.Store(self.root).saves(), [])


if __name__ == '__main__':
    unittest.main()
