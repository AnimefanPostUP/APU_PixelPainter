"""Per-project pen UI layout: which pen windows are open, where they are, their
scale, lock and help state -- stored as JSON in the scene property
``pixel_painter_pen_layout`` (saved with the .blend).

:class:`LayoutStore` (used by ``tools.pen_bar.PenBarTool``) loads the stored
layout into the tool state whenever another project / scene becomes active, and
writes it back (from event handling only, never from a draw callback) when it
changed. A project without a stored layout keeps the current one; it is stored
with the project's first change.

:func:`encode` / :func:`decode` are pure and unit tested.
"""

import json

PROP = 'pixel_painter_pen_layout'
VERSION = 1


def encode(state, keys):
    """JSON text of the ``keys`` of ``state`` (tuples become lists)."""
    data = {k: (list(v) if isinstance(v, tuple) else v) for k, v in ((k, state.get(k)) for k in keys)}
    return json.dumps({'version': VERSION, 'layout': data}, sort_keys=True)


def decode(text, defaults):
    """``{key: value}`` from :func:`encode`'s text: only keys in ``defaults``, values of
    the default's kind (positions as ``(x, y)`` tuples, scales as floats, flags as
    bools); anything unreadable is skipped. Empty dict for empty / broken text."""
    try:
        raw = json.loads(text) if text else {}
        layout = raw.get('layout', {}) if isinstance(raw, dict) else {}
    except (ValueError, TypeError):
        return {}
    if not isinstance(layout, dict):
        return {}
    out = {}
    for key, value in layout.items():
        if key not in defaults:
            continue
        default = defaults[key]
        if key.endswith('_pos'):
            if value is None:
                out[key] = None
            elif (isinstance(value, (list, tuple)) and len(value) == 2
                  and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)):
                out[key] = (float(value[0]), float(value[1]))
        elif isinstance(default, bool):
            if isinstance(value, bool):
                out[key] = value
        elif isinstance(default, (int, float)):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                out[key] = float(value)
    return out


class LayoutStore:
    """Keeps the tool state's layout ``keys`` in sync with the active scene."""

    def __init__(self, defaults):
        self.defaults = dict(defaults)     # key -> default (decides the kind of each value)
        self.keys = tuple(self.defaults)
        self._source = None                # (file, scene pointer) the state was loaded for
        self._saved = None                 # encoded layout as last loaded / written

    @staticmethod
    def _source_of(context):
        import bpy
        scene = getattr(context, 'scene', None)
        if scene is None:
            return None, None
        return scene, (bpy.data.filepath, scene.as_pointer())

    def load_if_needed(self, context, state):
        """Another project / scene: load its layout into ``state`` (safe in draw callbacks:
        only the Python state changes)."""
        scene, source = self._source_of(context)
        if scene is None or source == self._source:
            return False
        self._source = source
        stored = decode(getattr(scene, PROP, ""), self.defaults)
        state.update(stored)
        self._saved = encode(state, self.keys)     # written again only after a change
        return bool(stored)

    def save_if_changed(self, context, state):
        """Write the layout to the scene when it differs from the stored one (not from a
        draw callback)."""
        scene, source = self._source_of(context)
        if scene is None or source != self._source or not hasattr(scene, PROP):
            return False
        text = encode(state, self.keys)
        if text == self._saved:
            return False
        try:
            setattr(scene, PROP, text)
        except Exception:      # e.g. writing ID data is not allowed in this context
            return False
        self._saved = text
        return True
