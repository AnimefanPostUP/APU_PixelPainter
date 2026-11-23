"""Brush falloff presets (single source for enum items, curve presets and icons)."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class FalloffPreset:
    id: str
    label: str
    description: str
    curve_preset: Optional[str]   # Blender brush.curve_preset to apply, None = keep curve
    icon_key: Optional[str] = None
    icon_file: Optional[str] = None


FALLOFF_PRESETS = (
    FalloffPreset('CONSTANT', "Constant", "Uniform strength across the brush", 'MAX',
                  'CONSTANT', "Falloff_Const.png"),
    FalloffPreset('LINEAR', "Linear", "Linearly fades from centre to edge", 'LINE',
                  'LINEAR', "Falloff_Linea.png"),
    FalloffPreset('SMOOTH', "Smooth", "Smooth ease-in/out fade", 'SMOOTH',
                  'SMOOTH_FALLOFF', "Falloff_Smooth.png"),
    FalloffPreset('SPHERE', "Sphere", "Spherical dome-shaped falloff", 'ROUND',
                  'SPHERE', "Falloff_Sphere.png"),
    FalloffPreset('SHARPEN', "Sharpen", "Quadratic — drops off quickly toward the edge", 'SHARP',
                  'SHARPEN', "Falloff_Sharpen.png"),
    FalloffPreset('CUSTOM', "Custom", "Use the custom brush curve from Tool Settings", None),
)

# Order of the 3x2 grid in the tool pie / settings panel.
PICKER_ORDER = ('CONSTANT', 'SMOOTH', 'CUSTOM', 'LINEAR', 'SPHERE', 'SHARPEN')

# Falloff property edited when the active tool has none of its own.
DEFAULT_FALLOFF_PROPERTY = 'pixel_painter_circle_falloff'

_BY_ID = {p.id: p for p in FALLOFF_PRESETS}


def get(preset_id):
    return _BY_ID.get(preset_id)


def enum_items():
    return [(p.id, p.label, p.description) for p in FALLOFF_PRESETS]


def picker_presets():
    return [_BY_ID[i] for i in PICKER_ORDER]


def icon_files():
    return {p.icon_key: p.icon_file for p in FALLOFF_PRESETS if p.icon_key and p.icon_file}
