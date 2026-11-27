"""Value curves (pure, no bpy): a 0..1 -> 0..1 curve given by anchors ``(x, y)``,
sampled smoothly without overshooting (monotone cubic, Fritsch-Carlson), plus the
presets of the Extras window's curves (``kind``):

* ``'ao'`` -- Ambient Occlusion: ``x`` = occlusion (0 = open, 1 = fully occluded),
  ``y`` = how far the color goes from the secondary (open) toward the primary
  (occluded) color.
* ``'edge'`` -- the Edges falloff: ``x`` = distance from the edge (0 = on it, 1 = the
  band's width), ``y`` = the edge's weight (1 = primary color, full opacity).
"""

import json

import numpy as np

from . import falloff


# (id, label, anchors). Flat runs stay flat (monotone cubic: no overshoot), so a
# step made of two anchors close together is a hard step.
AO_PRESETS = (
    ('LINEAR', "Linear", ((0.0, 0.0), (1.0, 1.0))),
    ('SMOOTH', "Smooth", ((0.0, 0.0), (0.25, 0.06), (0.75, 0.94), (1.0, 1.0))),
    ('STRONG', "Strong", ((0.0, 0.0), (0.25, 0.55), (0.5, 0.8), (1.0, 1.0))),
    ('CONTACT', "Contact", ((0.0, 0.0), (0.5, 0.06), (0.75, 0.35), (1.0, 1.0))),
    ('THRESHOLD', "Hard", ((0.0, 0.0), (0.45, 0.0), (0.55, 1.0), (1.0, 1.0))),
    ('STEPPED', "Stepped", ((0.0, 0.0), (0.24, 0.0), (0.26, 0.34), (0.49, 0.34), (0.51, 0.67),
                            (0.74, 0.67), (0.76, 1.0), (1.0, 1.0))),
    ('INVERTED', "Inverted", ((0.0, 1.0), (1.0, 0.0))),
)
AO_DEFAULT = 'LINEAR'
_AO = {pid: points for pid, _label, points in AO_PRESETS}

# The Edges falloff: a linear fade, constant, and the brush curve presets (without
# their handle types).
EDGE_PRESETS = (
    ('LINEAR', "Linear", ((0.0, 1.0), (1.0, 0.0))),
    ('CONSTANT', "Constant", ((0.0, 1.0), (1.0, 1.0))),
    *((pid, label, tuple((x, y) for x, y, _handle in points)) for pid, label, points in falloff.CURVE_PRESETS),
)
EDGE_DEFAULT = 'LINEAR'

PRESETS = {'ao': AO_PRESETS, 'edge': EDGE_PRESETS}
DEFAULTS = {'ao': AO_DEFAULT, 'edge': EDGE_DEFAULT}
_BY_KIND = {kind: {pid: points for pid, _label, points in presets} for kind, presets in PRESETS.items()}


def preset(kind, preset_id):
    """Anchors of a ``kind`` preset (None if unknown)."""
    points = _BY_KIND.get(kind, {}).get(preset_id)
    return [tuple(p) for p in points] if points is not None else None


def default_points(kind):
    return preset(kind, DEFAULTS.get(kind, AO_DEFAULT)) or preset('ao', AO_DEFAULT)


def ao_preset(preset_id):
    """Anchors of an AO preset (None if unknown)."""
    return preset('ao', preset_id)


def normalize(points):
    """Anchors sorted by x, clamped to 0..1, duplicates in x dropped; at least two
    (the ends at x = 0 and 1 are added when missing). Bad input -> the default."""
    try:
        pts = sorted((min(1.0, max(0.0, float(p[0]))), min(1.0, max(0.0, float(p[1])))) for p in points)
    except (TypeError, ValueError):
        pts = []
    out = []
    for x, y in pts:
        if out and x - out[-1][0] < 1e-6:
            out[-1] = (out[-1][0], y)
        else:
            out.append((x, y))
    if not out:
        return list(_AO[AO_DEFAULT])
    if out[0][0] > 0.0:
        out.insert(0, (0.0, out[0][1]))
    if out[-1][0] < 1.0:
        out.append((1.0, out[-1][1]))
    return out


def to_text(points):
    return json.dumps([[round(x, 4), round(y, 4)] for x, y in normalize(points)])


def from_text(text, kind='ao'):
    """Anchors stored by :func:`to_text` (the kind's default preset when empty / broken)."""
    try:
        raw = json.loads(text) if text else None
    except (TypeError, ValueError):
        raw = None
    if not raw:
        return default_points(kind)
    return normalize(raw)


def _slopes(xs, ys):
    """Fritsch-Carlson tangents: monotone between anchors, flat runs stay flat."""
    n = len(xs)
    h = np.diff(xs)
    delta = np.diff(ys) / np.where(h > 0, h, 1.0)
    m = np.zeros(n)
    if n == 2:
        m[:] = delta[0]
        return m
    m[0], m[-1] = delta[0], delta[-1]
    for k in range(1, n - 1):
        if delta[k - 1] * delta[k] <= 0.0:
            m[k] = 0.0
        else:   # weighted harmonic mean
            w1, w2 = 2.0 * h[k] + h[k - 1], h[k] + 2.0 * h[k - 1]
            m[k] = (w1 + w2) / (w1 / delta[k - 1] + w2 / delta[k])
    for k in range(n - 1):
        if delta[k] == 0.0:
            m[k] = m[k + 1] = 0.0
    return m


def sample(points, x):
    """Curve value(s) at ``x`` (scalar or array), clamped to 0..1."""
    pts = normalize(points)
    xs = np.array([p[0] for p in pts], dtype=np.float64)
    ys = np.array([p[1] for p in pts], dtype=np.float64)
    m = _slopes(xs, ys)
    xv = np.clip(np.asarray(x, dtype=np.float64), 0.0, 1.0)
    k = np.clip(np.searchsorted(xs, xv, side='right') - 1, 0, len(xs) - 2)
    h = xs[k + 1] - xs[k]
    t = np.where(h > 0, (xv - xs[k]) / np.where(h > 0, h, 1.0), 0.0)
    t2, t3 = t * t, t * t * t
    out = ((2 * t3 - 3 * t2 + 1) * ys[k] + (t3 - 2 * t2 + t) * h * m[k]
           + (-2 * t3 + 3 * t2) * ys[k + 1] + (t3 - t2) * h * m[k + 1])
    out = np.clip(out, 0.0, 1.0)
    return float(out) if np.ndim(out) == 0 else out
