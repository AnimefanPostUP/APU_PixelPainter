"""Recently painted colors, newest first (shown in the pen menu's color corner).

Recorded by :meth:`tools.stroke.StrokeTool.begin_stroke` for tools that paint
with the brush color (``paints_color``). Stored as a tuple of RGB tuples in the
shared state key ``color_history`` (declared by ``StrokeTool``). Pure Python.
"""

HISTORY_KEY = 'color_history'
HISTORY_SIZE = 8
_SAME = 1e-3   # colors closer than this (per channel) count as the same


def colors(state):
    return list(state.get(HISTORY_KEY) or ())


def record(state, rgb, size=HISTORY_SIZE):
    """Put ``rgb`` first; an equal color already in the history moves instead of repeating."""
    rgb = tuple(round(float(c), 4) for c in tuple(rgb)[:3])
    rest = [c for c in colors(state) if max(abs(a - b) for a, b in zip(c, rgb)) > _SAME]
    state[HISTORY_KEY] = tuple([rgb] + rest)[:size]
