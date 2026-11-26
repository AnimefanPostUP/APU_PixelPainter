"""Color palettes (pure Python).

* A **palette** is ``{"name": str, "colors": [rgb or None] * PALETTE_SIZE}``.
* A **project** (stored per .blend file, see ``tools.pen_bar``) holds
  ``PROJECT_SLOTS`` palette slots (palette or None) and the index of the active one:
  ``{"active": int, "palettes": [...]}``. The pen menu's palette band shows the
  active palette's colors, or -- in its palette view -- the palettes themselves.
* The **library** is a list of palettes in a JSON file shared by all projects
  (``utils/palette_library.py``). Project and library are not synced: palettes are
  copied between them (drag & drop in the pen menu).
* **Clipboard text**: JSON with hex colors (:func:`to_text`); :func:`from_text`
  also accepts any text containing ``#rrggbb`` codes (e.g. a palette from the web).

All functions return new data; inputs are not modified.
"""

import copy
import json
import re

PALETTE_SIZE = 24          # colors per palette
PROJECT_SLOTS = 24         # palettes per project
_HEX = re.compile(r'#?\b([0-9a-fA-F]{6})\b')


# ---- colors ---------------------------------------------------------------------------

def _rgb(value):
    """RGB tuple from a list / tuple of 3+ numbers or a hex string; None otherwise."""
    if value is None:
        return None
    if isinstance(value, str):
        match = _HEX.search(value)
        return hex_to_rgb(match.group(1)) if match else None
    try:
        return tuple(max(0.0, min(1.0, float(c))) for c in list(value)[:3]) if len(value) >= 3 else None
    except (TypeError, ValueError):
        return None


def hex_to_rgb(text):
    text = text.lstrip('#')
    return tuple(int(text[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return '#' + ''.join(f"{max(0, min(255, round(c * 255))):02x}" for c in rgb[:3])


# ---- palettes ---------------------------------------------------------------------------

def empty_palette(name="Palette"):
    return {"name": name, "colors": [None] * PALETTE_SIZE}


def normalize(obj, name="Palette"):
    """A palette from a dict ``{"name", "colors"}`` or a plain list of colors; None if unusable."""
    if isinstance(obj, dict):
        colors, name = obj.get("colors"), str(obj.get("name") or name)
    elif isinstance(obj, list):
        colors = obj
    else:
        return None
    if not isinstance(colors, list):
        return None
    slots = [_rgb(c) for c in colors[:PALETTE_SIZE]]
    return {"name": name, "colors": slots + [None] * (PALETTE_SIZE - len(slots))}


def is_empty(palette):
    return palette is None or not any(palette["colors"])


def filled(palette):
    """The palette's colors without the empty slots."""
    return [c for c in (palette or {}).get("colors", []) if c is not None]


def with_color(palette, index, rgb):
    out = copy.deepcopy(palette)
    if 0 <= index < PALETTE_SIZE:
        out["colors"][index] = _rgb(rgb)
    return out


def with_swapped_colors(palette, i, j):
    out = copy.deepcopy(palette)
    c = out["colors"]
    if 0 <= i < len(c) and 0 <= j < len(c):
        c[i], c[j] = c[j], c[i]
    return out


# ---- project --------------------------------------------------------------------------------

def empty_project():
    return {"active": 0, "palettes": [None] * PROJECT_SLOTS}


def decode_project(text):
    try:
        raw = json.loads(text) if text else {}
    except (TypeError, ValueError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    pals = raw.get("palettes") if isinstance(raw.get("palettes"), list) else []
    slots = [normalize(p) if p is not None else None for p in pals[:PROJECT_SLOTS]]
    slots += [None] * (PROJECT_SLOTS - len(slots))
    try:
        active = int(raw.get("active", 0))
    except (TypeError, ValueError):
        active = 0
    return {"active": max(0, min(PROJECT_SLOTS - 1, active)), "palettes": slots}


def _encode_palette(palette):
    if palette is None:
        return None
    return {"name": palette["name"], "colors": [[round(v, 4) for v in c] if c else None for c in palette["colors"]]}


def encode_project(project):
    return json.dumps({"active": project["active"], "palettes": [_encode_palette(p) for p in project["palettes"]]})


def next_name(project, prefix="Palette"):
    names = {p["name"] for p in project["palettes"] if p}
    n = 1
    while f"{prefix} {n}" in names:
        n += 1
    return f"{prefix} {n}"


def active_palette(project):
    """The active palette, or None when its slot is empty."""
    return project["palettes"][project["active"]]


def with_active(project, index):
    out = copy.deepcopy(project)
    out["active"] = max(0, min(PROJECT_SLOTS - 1, index))
    return out


def with_palette(project, index, palette):
    """Slot ``index`` set to (a copy of) ``palette`` (None empties it)."""
    out = copy.deepcopy(project)
    if 0 <= index < PROJECT_SLOTS:
        out["palettes"][index] = copy.deepcopy(palette)
    return out


def with_swapped_palettes(project, i, j):
    out = copy.deepcopy(project)
    p = out["palettes"]
    if 0 <= i < len(p) and 0 <= j < len(p):
        p[i], p[j] = p[j], p[i]
        if out["active"] in (i, j):
            out["active"] = j if out["active"] == i else i   # the active palette moves along
    return out


def edit_active(project, change):
    """``change(palette) -> palette`` applied to the active palette (created when its slot is empty)."""
    out = copy.deepcopy(project)
    index = out["active"]
    palette = out["palettes"][index] or empty_palette(next_name(out))
    out["palettes"][index] = change(palette)
    return out


# ---- library ---------------------------------------------------------------------------------

def decode_library(text):
    try:
        raw = json.loads(text) if text else []
    except (TypeError, ValueError):
        raw = []
    if isinstance(raw, dict):
        raw = raw.get("palettes", [])
    return [p for p in (normalize(x) for x in raw if x is not None) if p is not None] if isinstance(raw, list) else []


def encode_library(palettes):
    return json.dumps({"palettes": [_encode_palette(p) for p in palettes]}, indent=2)


# ---- clipboard -----------------------------------------------------------------------------

def to_text(palette):
    """Clipboard text: JSON with hex colors (empty slots: null)."""
    return json.dumps({"name": palette["name"],
                       "colors": [rgb_to_hex(c) if c else None for c in palette["colors"]]})


def from_text(text, name="Pasted Palette"):
    """A palette from clipboard text: our JSON (or any palette JSON), else every
    ``#rrggbb`` code in the text in order. None when there are no colors."""
    text = (text or "").strip()
    try:
        palette = normalize(json.loads(text), name)
    except (TypeError, ValueError):
        palette = None
    if palette is None:
        codes = _HEX.findall(text)
        palette = normalize([hex_to_rgb(c) for c in codes], name) if codes else None
    return None if is_empty(palette) else palette
