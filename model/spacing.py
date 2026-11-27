"""Stroke spacing (pure, no Blender): when a stroke stamps.

* ``PIXEL``: once per new pixel, no build-up within a stroke (the brushes keep the
  strongest weight per pixel); value = pixels per step (1 = every pixel).
* ``FREE``: every step builds up; value = distance between stamps in pixels (1 = every
  pixel along the path, as the brushes always did).
* ``TIME``: a stamp at the cursor every ``value`` milliseconds while the button is held,
  also when the cursor stands still (airbrush); moving does not stamp in between.

Each tool has its own mode and values (``pixel_painter_<TOOL>_spacing`` / ``_spacing_step``
/ ``_spacing_distance`` / ``_spacing_interval``) unless ``pixel_painter_spacing_per_tool``
is off: then every tool uses the global ``pixel_painter_spacing`` / ... ones.
"""

import math

MODES = ('PIXEL', 'FREE', 'TIME')
DEFAULT_MODE = 'FREE'
# The mode's value: property suffix, default, (min, max), label, unit.
VALUE_PROP = {'PIXEL': 'spacing_step', 'FREE': 'spacing_distance', 'TIME': 'spacing_interval'}
DEFAULTS = {'PIXEL': 1, 'FREE': 1, 'TIME': 100}
RANGES = {'PIXEL': (1, 32), 'FREE': (1, 64), 'TIME': (16, 1000)}
LABELS = {'PIXEL': "Step", 'FREE': "Spacing", 'TIME': "Interval"}
UNITS = {'PIXEL': "px", 'FREE': "px", 'TIME': "ms"}
MODE_LABELS = {'PIXEL': "Pixel", 'FREE': "Free", 'TIME': "Time"}


def next_mode(mode):
    """Pixel -> Free -> Time -> Pixel."""
    return MODES[(MODES.index(mode) + 1) % len(MODES)] if mode in MODES else DEFAULT_MODE


def clamp_value(mode, value):
    lo, hi = RANGES.get(mode, (1, 64))
    try:
        return max(lo, min(hi, int(round(float(value)))))
    except (TypeError, ValueError):
        return DEFAULTS.get(mode, 1)


# The slider: Time is two linear parts -- the first SLIDER_KNEE[0] of the slider covers up to
# SLIDER_KNEE[1] ms (fine control over short intervals), the rest up to the maximum.
SLIDER_KNEE = {'TIME': (0.6, 100.0)}


def slider_value(mode, fraction):
    """The value at ``fraction`` (0..1) of the mode's slider."""
    lo, hi = RANGES.get(mode, (1, 64))
    f = max(0.0, min(1.0, float(fraction)))
    knee = SLIDER_KNEE.get(mode)
    if knee is None:
        return lo + f * (hi - lo)
    kf, kv = knee
    if f <= kf:
        return lo + f / kf * (kv - lo)
    return kv + (f - kf) / (1.0 - kf) * (hi - kv)


def slider_fraction(mode, value):
    """Inverse of :func:`slider_value`: where ``value`` sits on the slider (0..1)."""
    lo, hi = RANGES.get(mode, (1, 64))
    v = max(lo, min(hi, float(value)))
    knee = SLIDER_KNEE.get(mode)
    if knee is None:
        return 0.0 if hi <= lo else (v - lo) / (hi - lo)
    kf, kv = knee
    if v <= kv:
        return kf * (v - lo) / (kv - lo)
    return kf + (1.0 - kf) * (v - kv) / (hi - kv)


def value_text(mode, value):
    return f"{int(value)} {UNITS.get(mode, '')}".strip()


def _distance(mode, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    if mode == 'PIXEL':
        return max(abs(dx), abs(dy))      # path pixels walked (Bresenham steps)
    return math.hypot(dx, dy)


def thin(mode, steps, start, carry, every):
    """The stamp centers among ``steps`` (the path's pixels after ``start``, the last
    painted pixel, or None at a stroke's first stamp): one whenever ``every`` px were
    walked since the last stamp. ``carry`` is what was walked since the last stamp
    before this call. Returns ``(stamps, carry)``. ``every`` <= 1 keeps every step."""
    steps = list(steps)
    if every <= 1 or not steps:
        return steps, 0.0
    kept = []
    prev = start
    walked = float(carry)
    for p in steps:
        if prev is None:                 # the stroke's first stamp
            kept.append(p)
            walked = 0.0
        else:
            walked += _distance(mode, prev, p)
            if walked >= every - 1e-9:
                kept.append(p)
                walked = 0.0
        prev = p
    return kept, walked


def due(now, last_stamp, interval_ms):
    """Time mode: is the next stamp due (``last_stamp`` None: right away)?"""
    return last_stamp is None or (now - last_stamp) * 1000.0 >= interval_ms - 1e-6
