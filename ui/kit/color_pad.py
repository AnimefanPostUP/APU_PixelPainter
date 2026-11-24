"""ColorPad: the compact HSV sheet selector -- :class:`~.color_selector.ColorSelector`
with the 'SHEET' layout. Kept for callers that want exactly that look::

    [V]  [ hue -> / value ^ sheet ]  [S]
         [ hue bar               ]

All interaction (touchpad-like swiping, taps, live commits, cancel) lives in
:class:`~.color_selector.ColorSelector`; see there.

``hsv_for_rgb`` lets hosts keep the selector's HSV while the stored color is
still the one it wrote (RGB has no hue at grey and no hue / saturation at black).
"""

import colorsys

from .color_selector import ColorSelector, SheetShape


SHEET, HUE, VALUE, SATURATION = SheetShape.SHEET, SheetShape.HUE, SheetShape.VALUE, SheetShape.SATURATION
_SAME_RGB_EPS = 1e-4
_GREY_EPS = 1e-3


def hsv_for_rgb(rgb, remembered=None):
    """HSV for ``rgb``, given ``remembered = (rgb, hsv)`` last written by the pad.

    While the color is still the one written, the written HSV is returned
    (RGB loses hue at grey and hue + saturation at black). A color changed
    elsewhere is converted, borrowing only what its RGB cannot tell.
    """
    rgb = tuple(rgb)
    if remembered is not None and all(abs(a - b) <= _SAME_RGB_EPS for a, b in zip(rgb, remembered[0])):
        return tuple(remembered[1])
    h, s, v = colorsys.rgb_to_hsv(*rgb)
    if remembered is not None:
        old_h, old_s, _old_v = remembered[1]
        if v < _GREY_EPS:
            h, s = old_h, old_s
        elif s < _GREY_EPS:
            h = old_h
    return h, s, v


class ColorPad(ColorSelector):
    """HSV sheet selector. ``sheet_size`` = unscaled size of the hue / value sheet."""

    def __init__(self, get_hsv, set_hsv, *, sheet_size=(150.0, 96.0), **kwargs):
        kwargs.setdefault('layout', 'SHEET')
        super().__init__(get_hsv, set_hsv, area=sheet_size, **kwargs)
