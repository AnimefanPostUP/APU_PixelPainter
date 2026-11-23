"""Pen pressure as a multiplier for size, strength, alpha and modifier.

Pure Python: the core stores the pen pressure of the last pointer event in
the shared state (``pen_pressure``, 1.0 for a mouse); :func:`from_settings`
reads which channels follow it from the WindowManager properties
(``pixel_painter_pen_pressure_<channel>``, ``pixel_painter_pen_pressure_min``).
"""

from dataclasses import dataclass, field
from typing import FrozenSet


CHANNELS = ('size', 'strength', 'alpha', 'modifier')
PROPERTY_PREFIX = 'pixel_painter_pen_pressure_'


def _clamp01(value):
    return max(0.0, min(1.0, float(value)))


def factor(pressure, minimum=0.0):
    """Multiplier for ``pressure`` (0..1): ``minimum`` at no pressure, 1 at full pressure."""
    m = _clamp01(minimum)
    return m + (1.0 - m) * _clamp01(pressure)


def scale_radius(radius, multiplier):
    """Scale the brush *diameter* (``2r + 1`` pixels) and return the new radius.

    Scaling the diameter keeps small brushes responsive: radius 1 (3 px)
    drops to a single pixel below half pressure instead of staying 3 px
    until the very end.
    """
    diameter = 2 * max(0, int(radius)) + 1
    scaled = max(1, int(diameter * max(0.0, multiplier) + 0.5))
    return (scaled - 1) // 2


@dataclass(frozen=True)
class PenPressure:
    pressure: float = 1.0
    channels: FrozenSet[str] = field(default_factory=frozenset)
    minimum: float = 0.0

    @property
    def multiplier(self):
        return factor(self.pressure, self.minimum)

    def uses(self, channel):
        return channel in self.channels

    def apply(self, radius, strength, alpha, modifier):
        """``(radius, strength, alpha, modifier)`` scaled for the enabled channels."""
        if not self.channels:
            return radius, strength, alpha, modifier
        m = self.multiplier
        if 'size' in self.channels:
            radius = scale_radius(radius, m)
        if 'strength' in self.channels:
            strength = strength * m
        if 'alpha' in self.channels:
            alpha = alpha * m
        if 'modifier' in self.channels:
            modifier = modifier * m
        return radius, strength, alpha, modifier


def from_settings(wm, state):
    """The current :class:`PenPressure` from WindowManager settings and shared state."""
    channels = frozenset(c for c in CHANNELS if getattr(wm, PROPERTY_PREFIX + c, False))
    return PenPressure(
        pressure=state.get('pen_pressure', 1.0) if channels else 1.0,
        channels=channels,
        minimum=getattr(wm, PROPERTY_PREFIX + 'min', 0.0),
    )
