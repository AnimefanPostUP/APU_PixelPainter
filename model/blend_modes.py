"""Brush blend modes (single source for enums, pies and the favorites selector).

Order matters: ``pixel_painter_blend_favorites`` is an ENUM_FLAG property whose
stored bits follow this order, so only append new modes at the end.
"""

# (id, label, group)
BLEND_MODES = (
    ('MIX', "Normal", 'COMMON'),
    ('ADD', "Add", 'COMMON'),
    ('MUL', "Multiply", 'COMMON'),
    ('DARKEN', "Darken", 'COMMON'),
    ('LIGHTEN', "Lighten", 'COMMON'),
    ('COLOR', "Color", 'COMMON'),
    ('SCREEN', "Screen", 'CONTRAST'),
    ('OVERLAY', "Overlay", 'CONTRAST'),
    ('SOFTLIGHT', "Soft Light", 'CONTRAST'),
    ('HARDLIGHT', "Hard Light", 'CONTRAST'),
    ('SUB', "Subtract", 'MATH'),
    ('DIFFERENCE', "Difference", 'MATH'),
    ('EXCLUSION', "Exclusion", 'MATH'),
    ('COLORDODGE', "Color Dodge", 'MATH'),
    ('COLORBURN', "Color Burn", 'MATH'),
    ('HUE', "Hue", 'HSL'),
    ('SATURATION', "Saturation", 'HSL'),
    ('VALUE', "Value", 'HSL'),
    ('LUMINOSITY', "Luminosity", 'HSL'),
)

DEFAULT_FAVORITES = frozenset(b for b, _label, group in BLEND_MODES if group == 'COMMON')

_LABELS = {b: label for b, label, _group in BLEND_MODES}

# Short names for the pen menu's small buttons (the full label where none is set).
SHORT_LABELS = {
    'MIX': "Norm", 'MUL': "Mul", 'DARKEN': "Dark", 'LIGHTEN': "Light", 'COLOR': "Col",
    'SCREEN': "Scre", 'OVERLAY': "Over", 'SOFTLIGHT': "Soft", 'HARDLIGHT': "Hard",
    'SUB': "Sub", 'DIFFERENCE': "Diff", 'EXCLUSION': "Excl", 'COLORDODGE': "Dodge",
    'COLORBURN': "Burn", 'SATURATION': "Sat", 'VALUE': "Val", 'LUMINOSITY': "Lumi",
}


def label(blend):
    return _LABELS.get(blend, blend)


def short_label(blend):
    return SHORT_LABELS.get(blend) or label(blend)


def enum_items():
    return [(b, lbl, f"{lbl} blend") for b, lbl, _group in BLEND_MODES]


def ids(group=None):
    return [b for b, _lbl, g in BLEND_MODES if group is None or g == group]
