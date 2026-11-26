"""The optional tertiary color: a point on the gradient from the primary to the
secondary color (``t`` = 0: primary, 1: secondary), picked with the pen menu's
gradient slider and selected with the bubble between the two colors.

While it is selected (``ACTIVE_KEY``) the left button (the pen tip) paints with it
instead of the primary color. The color selector still edits the primary or the
secondary color -- ``TARGET_KEY`` says which. Pure Python (shared tool state).
"""

ACTIVE_KEY = 'pen_tertiary'          # the tertiary color is selected
T_KEY = 'pen_tertiary_t'             # position on the gradient, 0 .. 1
TARGET_KEY = 'pen_color_target'      # 'PRIMARY' / 'SECONDARY': edited by the color selector meanwhile
DEFAULT_T = 0.5
SNAP = 0.03                          # the slider snaps to the middle within this distance


def active(state):
    return bool(state.get(ACTIVE_KEY))


def position(state):
    try:
        return max(0.0, min(1.0, float(state.get(T_KEY, DEFAULT_T))))
    except (TypeError, ValueError):
        return DEFAULT_T


def snapped(t):
    """``t`` clamped to 0 .. 1, pulled onto the middle when close to it."""
    t = max(0.0, min(1.0, float(t)))
    return DEFAULT_T if abs(t - DEFAULT_T) <= SNAP else t


def blend(primary, secondary, t):
    """RGB at ``t`` on the gradient from ``primary`` to ``secondary``."""
    if primary is None or secondary is None:
        return primary or secondary
    return tuple(p + (s - p) * t for p, s in zip(primary[:3], secondary[:3]))


def color(state, primary, secondary):
    return blend(primary, secondary, position(state))
