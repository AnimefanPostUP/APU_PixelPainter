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


def frame_dt(now, last, max_dt=0.1):
    """Delta time between frames, clamped so a stalled frame does not jump."""
    if last is None:
        return 0.0
    return max(0.0, min(max_dt, now - last))
