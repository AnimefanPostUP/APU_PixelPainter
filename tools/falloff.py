"""Brush falloff presets (single source for enum items, curve presets and icon keys)."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class FalloffPreset:
    id: str
    label: str
    description: str
    curve_preset: Optional[str]   # Blender brush.curve_preset to apply, None = keep curve

    @property
    def icon_key(self):
        """Key of the generated falloff icon (see ``ui/falloff_icons.py``)."""
        return f"FALLOFF_ICON_{self.id}"


FALLOFF_PRESETS = (
    FalloffPreset('CONSTANT', "Constant", "Uniform strength across the brush", 'MAX'),
    FalloffPreset('LINEAR', "Linear", "Linearly fades from centre to edge", 'LINE'),
    FalloffPreset('SMOOTH', "Smooth", "Smooth ease-in/out fade", 'SMOOTH'),
    FalloffPreset('SPHERE', "Sphere", "Spherical dome-shaped falloff", 'ROUND'),
    FalloffPreset('SHARPEN', "Sharpen", "Quadratic — drops off quickly toward the edge", 'SHARP'),
    FalloffPreset('CUSTOM', "Custom", "Use the custom brush curve from Tool Settings", None),
)

# Order of the 3x2 grid in the tool pie / settings panel.
PICKER_ORDER = ('CONSTANT', 'SMOOTH', 'CUSTOM', 'LINEAR', 'SPHERE', 'SHARPEN')

# Anchors (x = distance from the center, y = weight) the custom curve resets to: a smooth fade.
CUSTOM_DEFAULT_POINTS = ((0.0, 1.0), (0.5, 0.5), (1.0, 0.0))

# Falloff property edited when the active tool has none of its own.
DEFAULT_FALLOFF_PROPERTY = 'pixel_painter_circle_falloff'

_BY_ID = {p.id: p for p in FALLOFF_PRESETS}


def get(preset_id):
    return _BY_ID.get(preset_id)


def enum_items():
    return [(p.id, p.label, p.description) for p in FALLOFF_PRESETS]


def picker_presets():
    return [_BY_ID[i] for i in PICKER_ORDER]
