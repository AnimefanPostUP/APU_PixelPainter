"""Color models of the color selectors: HSV, HSL and RGB.

Every color is a 3-tuple of floats in 0..1 in its model's channel order
(``CHANNELS``). Hue is channel 0 of HSV / HSL and wraps around.

Conversions go through RGB. Where the target model has no answer -- the hue
of a grey, the hue and saturation of black (and, for HSL, of white) -- the
value is borrowed from ``hint`` (a color in the target model), so a selector
dragging through grey or black keeps its hue and saturation.

Pure Python, no Blender dependency.
"""

import colorsys


HSV, HSL, RGB = 'HSV', 'HSL', 'RGB'
MODELS = (HSV, HSL, RGB)
CHANNELS = {HSV: ('H', 'S', 'V'), HSL: ('H', 'S', 'L'), RGB: ('R', 'G', 'B')}
CHANNEL_NAMES = {
    HSV: ("Hue", "Saturation", "Value"),
    HSL: ("Hue", "Saturation", "Lightness"),
    RGB: ("Red", "Green", "Blue"),
}
_EPS = 1e-4


def clamp01(x):
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def wraps(model, index):
    """True for channels that wrap around (hue) instead of clamping."""
    return index == 0 and model in (HSV, HSL)


def to_rgb(model, color):
    a, b, c = color
    if model == HSV:
        return colorsys.hsv_to_rgb(a, b, c)
    if model == HSL:
        return colorsys.hls_to_rgb(a, c, b)   # colorsys order: h, l, s
    return float(a), float(b), float(c)


def from_rgb(model, rgb, hint=None):
    """``rgb`` in ``model``; channels the color does not define come from ``hint``."""
    r, g, b = (clamp01(float(x)) for x in rgb)
    if model == RGB:
        return r, g, b
    if model == HSV:
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        no_sat = v < _EPS
    else:
        h, l, s = colorsys.rgb_to_hls(r, g, b)
        v = l
        no_sat = l < _EPS or l > 1.0 - _EPS
    if hint is not None:
        if no_sat:
            h, s = hint[0], hint[1]
        elif s < _EPS:
            h = hint[0]
    return h, s, v


def convert(color, src, dst, hint=None):
    """``color`` (in ``src``) in ``dst``; ``hint`` (in ``dst``) fills undefined channels."""
    if src == dst:
        return tuple(float(c) for c in color)
    return from_rgb(dst, to_rgb(src, color), hint)


def tone_weights(model, s, t):
    """(pure hue, white) weights of a color with saturation ``s`` and tone ``t``
    (value / lightness): rgb = hue_w * pure(h) + white_w * (1, 1, 1).

    Both models are linear in these weights, which makes them the barycentric
    coordinates of the hue / white / black triangle.
    """
    if model == HSL:
        chroma = s * (1.0 - abs(2.0 * t - 1.0))
        return chroma, t - chroma * 0.5
    return t * s, t * (1.0 - s)


def from_tone_weights(model, hue_w, white_w, old_s):
    """Inverse of :func:`tone_weights` -> (s, t); ``old_s`` where s is undefined."""
    hue_w, white_w = max(0.0, hue_w), max(0.0, white_w)
    if model == HSL:
        t = clamp01(white_w + hue_w * 0.5)
        denom = 1.0 - abs(2.0 * t - 1.0)
        s = clamp01(hue_w / denom) if denom > _EPS else old_s
        return s, t
    t = clamp01(hue_w + white_w)
    s = clamp01(hue_w / t) if t > _EPS else old_s
    return s, t


# ---- text codes (input fields, copy / paste) ------------------------------------------------

def to_hex(rgb):
    """``rgb`` (0..1) as ``#RRGGBB``."""
    return "#" + "".join(f"{int(round(clamp01(float(c)) * 255)):02X}" for c in rgb)


def parse_color(text):
    """RGB (0..1) from a color code, or None. Accepts ``#RRGGBB`` / ``RRGGBB`` /
    ``#RGB`` (with or without ``#`` / ``0x``) and three numbers separated by commas,
    spaces or semicolons: 0..255, or 0..1 when every number has a decimal point and
    none is above 1 (e.g. ``0.5, 0.2, 1.0``); an optional ``rgb( ... )`` around them."""
    if not text:
        return None
    t = text.strip().lower()
    if t.startswith("rgb(") and t.endswith(")"):
        t = t[4:-1]
    code = t[1:] if t.startswith("#") else t[2:] if t.startswith("0x") else t
    if len(code) in (3, 6) and all(c in "0123456789abcdef" for c in code):
        if len(code) == 3:
            code = "".join(c * 2 for c in code)
        return tuple(int(code[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    parts = [p for p in t.replace(";", " ").replace(",", " ").split() if p]
    if len(parts) != 3:
        return None
    try:
        values = [float(p) for p in parts]
    except ValueError:
        return None
    if all("." in p for p in parts) and all(v <= 1.0 for v in values):
        return tuple(clamp01(v) for v in values)
    return tuple(clamp01(v / 255.0) for v in values)
