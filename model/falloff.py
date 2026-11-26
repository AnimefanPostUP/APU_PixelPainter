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
        """Key of the generated falloff icon (see ``ui/icons/falloff_icons.py``)."""
        return f"FALLOFF_ICON_{self.id}"


FALLOFF_PRESETS = (
    FalloffPreset('SHAPE', "Shape", "Hardness / sharpness from the pen menu's falloff field", None),
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

# The field shape first, then hard to soft to sharp, then the special shapes. Order
# of the grid in the tool pie / settings panels.
PICKER_ORDER = ('SHAPE', 'CONSTANT', 'PLATEAU', 'SPHERE', 'ROOT',
                'SMOOTH', 'LINEAR', 'SHARPEN', 'SPIKE',
                'STEPPED', 'RING', 'INVERTED', 'CUSTOM')

# ---- Shape: the pen menu's 2D falloff field --------------------------------------------
# hardness 0 (soft) .. 1 (hard = constant): full strength out to that distance, then a fade;
# sharpness 0 (linear fade) .. 1 (sharp: the fade is (1 - u) ** SHAPE_MAX_POWER).
# The values are global WindowManager properties; tools read them through
# ``DrawEnvironment.falloff`` as a hashable key (``shape_key``), so kernel caches see changes.
SHAPE_HARDNESS_PROPERTY = 'pixel_painter_falloff_hardness'
SHAPE_SHARPNESS_PROPERTY = 'pixel_painter_falloff_sharpness'
SHAPE_DEFAULT = (0.0, 0.0)          # (hardness, sharpness): a linear fade
SHAPE_DECIMALS = 2                  # field values are rounded to this (bounded kernel caches)


def shape_key(hardness, sharpness):
    """Falloff type of a Shape falloff: ``('SHAPE', hardness, sharpness)`` (clamped, rounded)."""
    def norm(v):
        return round(max(0.0, min(1.0, float(v))), SHAPE_DECIMALS)
    return ('SHAPE', norm(hardness), norm(sharpness))


def shape_values(wm):
    """``(hardness, sharpness)`` from the WindowManager (defaults when not registered)."""
    return (float(getattr(wm, SHAPE_HARDNESS_PROPERTY, SHAPE_DEFAULT[0])),
            float(getattr(wm, SHAPE_SHARPNESS_PROPERTY, SHAPE_DEFAULT[1])))


# ---- Custom curve presets --------------------------------------------------------------
# The falloffs the Shape field does not cover, as anchors the custom curve can load (the
# curve flyout's preset buttons): (x = distance from the center, y = weight, handle type).
_A, _V = 'AUTO_CLAMPED', 'VECTOR'
CURVE_PRESETS = (
    ('SMOOTH', "Smooth", ((0.0, 1.0, _A), (0.25, 0.94, _A), (0.75, 0.06, _A), (1.0, 0.0, _A))),
    ('SPHERE', "Sphere", ((0.0, 1.0, _A), (0.5, 0.866, _A), (0.75, 0.661, _A), (0.9, 0.436, _A), (1.0, 0.0, _A))),
    ('ROOT', "Root", ((0.0, 1.0, _A), (0.5, 0.707, _A), (0.75, 0.5, _A), (0.9, 0.316, _A), (1.0, 0.0, _A))),
    ('PLATEAU', "Plateau", ((0.0, 1.0, _A), (0.5, 1.0, _A), (0.75, 0.5, _A), (1.0, 0.0, _A))),
    ('STEPPED', "Stepped", ((0.0, 1.0, _V), (0.25, 1.0, _V), (0.26, 0.75, _V), (0.5, 0.75, _V),
                            (0.51, 0.5, _V), (0.75, 0.5, _V), (0.76, 0.25, _V), (0.99, 0.25, _V),
                            (1.0, 0.0, _V))),
    ('RING', "Ring", ((0.0, 0.0, _A), (0.3, 0.0, _A), (0.475, 0.5, _A), (0.65, 1.0, _A),
                      (0.825, 0.5, _A), (1.0, 0.0, _A))),
    ('INVERTED', "Inverted", ((0.0, 0.0, _A), (0.25, 0.06, _A), (0.75, 0.94, _A), (1.0, 1.0, _A))),
)
_CURVE_PRESETS = {pid: points for pid, _label, points in CURVE_PRESETS}


def curve_preset_points(preset_id):
    """Anchors ``(x, y, handle_type)`` of a curve preset (None if unknown)."""
    return _CURVE_PRESETS.get(preset_id)


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
