"""Color palette: a fixed number of slots (RGB or empty), filled by dragging colors
onto them in the pen menu. Stored as JSON in ``pixel_painter_pen_palette`` (so it
is saved with the other settings). Pure Python.
"""

import json

PALETTE_SIZE = 12


def decode(text, size=PALETTE_SIZE):
    """Slots from the stored JSON (unknown / broken entries become empty)."""
    try:
        raw = json.loads(text) if text else []
    except (TypeError, ValueError):
        raw = []
    slots = []
    for entry in list(raw)[:size] if isinstance(raw, list) else []:
        try:
            slots.append(tuple(max(0.0, min(1.0, float(c))) for c in entry[:3]) if entry else None)
        except (TypeError, ValueError):
            slots.append(None)
    return slots + [None] * (size - len(slots))


def encode(slots):
    return json.dumps([[round(c, 4) for c in rgb[:3]] if rgb else None for rgb in slots])


def set_slot(slots, index, rgb):
    out = list(slots)
    if 0 <= index < len(out):
        out[index] = tuple(float(c) for c in rgb[:3]) if rgb is not None else None
    return out


def swap(slots, i, j):
    out = list(slots)
    if 0 <= i < len(out) and 0 <= j < len(out):
        out[i], out[j] = out[j], out[i]
    return out
