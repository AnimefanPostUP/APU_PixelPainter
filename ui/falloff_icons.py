"""Procedural falloff icons: a white disc whose alpha follows the falloff curve.

Each preset gets a :class:`FalloffIcon` generator for :class:`kit.icons.IconSet`.
The 'Custom' icon samples the active brush curve, so its signature changes
(and the icon re-renders) whenever the curve is edited; the 'Shape' icon follows
the falloff field's hardness / sharpness. :func:`shape_preview_key` icons show a
fixed Shape (the field's quadrant previews).
"""

import math

try:  # pragma: no cover
    import bpy
except ImportError:  # pragma: no cover
    bpy = None

from ..tools import falloff
from ..utils import math_utils


ICON_SIZE = 64
_LUT_STEPS = 128          # radial samples per render (interpolated per pixel)
_SIGNATURE_STEPS = 24     # samples used to detect custom-curve edits


# Fixed Shape previews (hardness, sharpness) drawn in the pen menu's falloff field.
SHAPE_PREVIEWS = ((0.6, 0.0), (0.0, 0.0), (0.6, 1.0), (0.0, 1.0))


def shape_preview_key(hardness, sharpness):
    return f"FALLOFF_SHAPE_PREVIEW_{int(round(hardness * 100))}_{int(round(sharpness * 100))}"


def _live_shape():
    """The field's current Shape key (the default outside Blender)."""
    wm = None
    if bpy is not None:
        try:
            wm = bpy.context.window_manager
        except Exception:
            wm = None
    values = falloff.shape_values(wm) if wm is not None else falloff.SHAPE_DEFAULT
    return falloff.shape_key(*values)


class FalloffIcon:
    """Icon generator for one falloff preset (``shape``: a fixed Shape key instead)."""

    def __init__(self, preset_id, shape=None):
        self.preset_id = preset_id
        self.shape = shape

    def _falloff_type(self):
        if self.shape is not None:
            return self.shape
        if self.preset_id == 'SHAPE':
            return _live_shape()
        return self.preset_id

    def _weight_fn(self):
        sampler = None
        if self.preset_id == 'CUSTOM' and bpy is not None:
            try:
                from ..utils.settings_service import PixelPainterSettingsService
                sampler = PixelPainterSettingsService().get_falloff_curve_sampler(bpy.context)
            except Exception:
                sampler = None
        falloff_type = self._falloff_type()
        return lambda t: math_utils.get_falloff(t, falloff_type, curve_sampler=sampler)

    def signature(self):
        """Cheap value that changes whenever the rendered icon would change."""
        if self.preset_id != 'CUSTOM':
            return self._falloff_type()
        weight = self._weight_fn()
        return tuple(round(weight(i / _SIGNATURE_STEPS), 3) for i in range(_SIGNATURE_STEPS + 1))

    def render(self, size=ICON_SIZE):
        """Return a flat list of straight-alpha RGBA floats (size x size, white disc)."""
        weight = self._weight_fn()
        lut = [weight(i / _LUT_STEPS) for i in range(_LUT_STEPS + 1)]
        radius = size * 0.5 - 1.0           # 1px margin so the anti-aliased rim isn't clipped
        center = (size - 1) * 0.5
        pixels = [0.0] * (size * size * 4)
        for y in range(size):
            dy = y - center
            for x in range(size):
                dist = math.hypot(x - center, dy)
                coverage = radius + 0.5 - dist   # anti-aliased edge
                if coverage <= 0.0:
                    continue
                f = min(dist / radius, 1.0) * _LUT_STEPS
                i = int(f)
                w = lut[i] if i >= _LUT_STEPS else lut[i] + (lut[i + 1] - lut[i]) * (f - i)
                alpha = max(0.0, min(1.0, w)) * min(1.0, coverage)
                idx = (y * size + x) * 4
                pixels[idx] = pixels[idx + 1] = pixels[idx + 2] = 1.0
                pixels[idx + 3] = alpha
        return pixels


def generators():
    """``icon_key -> FalloffIcon`` for every falloff preset and the Shape previews."""
    icons = {p.icon_key: FalloffIcon(p.id) for p in falloff.FALLOFF_PRESETS if p.icon_key}
    for hardness, sharpness in SHAPE_PREVIEWS:
        icons[shape_preview_key(hardness, sharpness)] = FalloffIcon(
            'SHAPE', shape=falloff.shape_key(hardness, sharpness))
    return icons
