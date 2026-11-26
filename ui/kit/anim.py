"""Easing curves and small frame-rate independent animation helpers.

No Blender dependency.
"""


def clamp01(t):
    return 0.0 if t < 0.0 else 1.0 if t > 1.0 else t


def ease_in_out(t):
    """Smoothstep: zero slope at both ends."""
    t = clamp01(t)
    return t * t * (3.0 - 2.0 * t)


def ease_in(t):
    t = clamp01(t)
    return t * t * t


def ease_out(t):
    t = clamp01(t)
    inv = 1.0 - t
    return 1.0 - inv * inv * inv


def progress(now, started_at, duration):
    """Linear 0..1 progress of an animation that started at ``started_at``."""
    if duration <= 0.0:
        return 1.0
    return clamp01((now - started_at) / duration)


def approach(current, target, step):
    """Move ``current`` toward ``target`` by at most ``step``."""
    if current < target:
        return min(target, current + step)
    if current > target:
        return max(target, current - step)
    return current


IDLE_FRAME = 1.0 / 60.0   # dt of the first frame after an idle pause (no redraws)


def frame_dt(now, last, max_dt=0.1, idle=None):
    """Delta time between frames, clamped so a stalled frame does not jump.

    ``idle``: dt to use for a gap longer than ``max_dt`` instead of ``max_dt`` --
    for hosts that only redraw while :func:`request_frame` asks for it, where such
    a gap means nothing was drawn meanwhile: an animation starting then begins
    with one ordinary frame instead of jumping to its end."""
    if last is None:
        return 0.0
    gap = now - last
    if idle is not None and gap > max_dt:
        return idle
    return max(0.0, min(max_dt, gap))


# ---------------------------------------------------------------------------
# Frame requests: a running animation asks for another frame. The host's timer
# redraws only while one is pending, so an idle overlay costs no redraws.
# ---------------------------------------------------------------------------

_frame_requested = False


def request_frame():
    """Call while drawing an animation that has not reached its end yet."""
    global _frame_requested
    _frame_requested = True


def take_frame_request():
    """True (once) when an animation asked for another frame since the last call."""
    global _frame_requested
    requested, _frame_requested = _frame_requested, False
    return requested
