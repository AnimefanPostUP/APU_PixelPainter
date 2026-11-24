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
    FalloffPreset('PLATEAU', "Plateau", "Full-strength core with a smooth outer fade", None),
    FalloffPreset('ROOT', "Root", "Square root — stays strong, drops steeply at the edge", 'ROOT'),
    FalloffPreset('SPIKE', "Spike", "Fourth power — a sharp point in the centre", 'POW4'),
    FalloffPreset('STEPPED', "Stepped", "Linear fade in hard steps (4 levels)", None),
    FalloffPreset('RING', "Ring", "Hollow: strongest in a band near the edge", None),
    FalloffPreset('INVERTED', "Inverted", "Inverted smooth: empty centre, full strength at the edge", None),
)

# Hard to soft to sharp, then the special shapes. Order of the grid in the tool
# pie / settings panels (3 rows of 4).
PICKER_ORDER = ('CONSTANT', 'PLATEAU', 'SPHERE', 'ROOT',
                'SMOOTH', 'LINEAR', 'SHARPEN', 'SPIKE',
                'STEPPED', 'RING', 'INVERTED', 'CUSTOM')

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
