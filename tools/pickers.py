"""One canvas picker at a time.

Mask editing (tools/mask), an armed Extras tool (tools/extras) and the pen menu's armed
eyedroppers (tools/pen) each take the mouse from the selected tool -- they are the
*secondary* tools (``ToolManager.secondary_tool``). Only one of them may run: starting
one calls :func:`claim`, which stops all the others through the ``release`` each of them
registered. No picker touches another one's state directly.
"""

import traceback


_RELEASE = {}     # picker name -> release(state)


def register(name, release):
    """``release(state)`` stops the picker ``name``: clears its state and its overlays."""
    _RELEASE[name] = release


def release_all(state):
    """Stop every picker (a tool was picked: it gets the mouse back)."""
    claim(state, None)


def claim(state, name):
    """``name`` starts: stop every other picker."""
    for other, release in list(_RELEASE.items()):
        if other == name:
            continue
        try:
            release(state)
        except Exception:
            traceback.print_exc()
