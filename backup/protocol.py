"""Message framing between Blender and the backup helper (stdlib only: the helper
imports this module directly, without the add-on package).

A message is one line of JSON (the header, UTF-8, ``\\n``-terminated) followed by
``header['nbytes']`` raw payload bytes (0 when absent).

Operations (``header['op']``):

* ``config``  -- ``keep`` (saves kept, 1..5), ``days`` (max age, 0 = forever)
* ``image``   -- ``key`` + metadata (``name``, ``width``, ``height``, ``channels``,
  ``dtype``, ...); the payload is the raw pixel buffer
* ``forget``  -- ``key``: the image is saved / gone, drop it from the cache
* ``detach``  -- the add-on unloads: if Blender exits soon this is a normal close
  (save), if it keeps running (reload / disable) the helper quits without saving
* ``quit``    -- quit now, without saving (backup switched off)
"""

import json

MAX_HEADER = 1 << 20     # a header line longer than this is corrupt


def encode_header(header, nbytes=0):
    header = dict(header)
    header['nbytes'] = int(nbytes)
    return (json.dumps(header, separators=(',', ':')) + '\n').encode('utf-8')


def write_message(stream, header, payload=None):
    """Write one message; ``payload`` is any bytes-like object (e.g. a NumPy array)."""
    view = memoryview(payload).cast('B') if payload is not None else None
    stream.write(encode_header(header, 0 if view is None else view.nbytes))
    if view is not None and view.nbytes:
        stream.write(view)
    stream.flush()


def _read_exact(stream, n):
    chunks = []
    while n > 0:
        chunk = stream.read(n)
        if not chunk:
            return None
        chunks.append(chunk)
        n -= len(chunk)
    return b''.join(chunks)


def read_message(stream):
    """``(header, payload bytes)``, or None at the end of the stream (or on corrupt data)."""
    line = stream.readline(MAX_HEADER)
    if not line or not line.endswith(b'\n'):
        return None
    try:
        header = json.loads(line.decode('utf-8'))
    except ValueError:
        return None
    if not isinstance(header, dict):
        return None
    n = int(header.get('nbytes', 0) or 0)
    payload = _read_exact(stream, n) if n > 0 else b''
    if payload is None:
        return None
    return header, payload
