"""APU UI kit: small retained-mode widget toolkit for Blender POST_PIXEL overlays.

The kit is addon-agnostic: it knows nothing about Pixel Painter. Compose
widgets, hand the root to an :class:`Overlay` (or subclass
:class:`~.modal.OverlayOperator`) and the kit handles layout, hit-testing,
hover/press/click, keyboard, animation and drawing.

Modules
-------
geometry  Rect and 2D helpers                    (pure Python)
anim      easing and timing helpers              (pure Python)
theme     colors, metrics, timings, UI scaling   (pure Python)
events    UIEvent and result constants           (pure Python)
widget    Widget base, DrawContext, Row/Column/Grid layouts
widgets   Label, Button, BubbleButton, Panel
color_models  HSV / HSL / RGB conversions           (pure Python)
color_selector ColorSelector: swipeable color selector, layouts
              Sheet / Square / Triangle / Wheel, HSV / HSL, sliders (pens)
color_pad ColorPad: the selector with the Sheet layout
radial    RadialMenu (pie)
curve     CurveEditor: anchors of a 0..1 curve, moved / added / drawn by pen
ring      Dial, RingSegment, RingSlider, CornerSegment: center widget + rings of pie segments
overlay   Overlay interaction controller         (no bpy)
draw      GPU primitives (the only gpu/blf user)
icons     IconSet: image icons for layouts and overlays
modal     OverlayOperator mixin + draw handler/timer session (bpy)

``modal`` and ``icons`` need ``bpy`` and are imported explicitly by callers.
"""

from .geometry import Rect
from .theme import Theme
from .events import UIEvent
from .widget import Column, DrawContext, Grid, Row, Widget
from .widgets import BubbleButton, Button, ColorBubble, DragBubble, Label, Panel, RoundButton
from .radial import RadialMenu
from .curve import CurveEditor
from .ring import CornerSegment, Dial, RingSegment, RingSlider
from .color_selector import ColorSelector, ColorShape
from .color_pad import ColorPad, hsv_for_rgb
from .overlay import Overlay

__all__ = (
    'Rect', 'Theme', 'UIEvent',
    'Widget', 'DrawContext', 'Row', 'Column', 'Grid',
    'Label', 'Button', 'BubbleButton', 'RoundButton', 'DragBubble', 'ColorBubble', 'Panel',
    'RadialMenu', 'CurveEditor', 'Dial', 'RingSegment', 'CornerSegment', 'RingSlider', 'ColorSelector', 'ColorShape', 'ColorPad', 'hsv_for_rgb', 'Overlay',
)
