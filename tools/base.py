"""Tool interface for Pixel Painter.

Every selectable tool is a :class:`ToolBase` subclass registered in
:data:`tools.catalog.TOOLS`. ``ToolBase`` is a
:class:`core.framework.ToolFrame`, so a tool owns its own input handling
(``on_register`` / ``on_activate`` / subtools); the registry metadata drives
the mode enum, per-tool settings properties and their defaults, persistence
keys, the reset operator, the tool pie, icons and the settings panel.

Adding a tool
-------------
1. Subclass :class:`tools.stroke.StrokeTool` (painting tools: stroke input
   and the standard modifier subtools come for free) or :class:`ToolBase`
   (tools with their own interaction, see :mod:`tools.selection`).
2. Set the metadata class attributes and implement :meth:`ToolBase.on_draw`
   and/or ``on_register``.
3. Add an instance to the list in :mod:`tools.catalog`.
"""

from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple

import numpy as np

from ..core.framework import ToolFrame
from ..utils import math_utils


@dataclass(frozen=True)
class SettingDefaults:
    """Whether each per-tool channel follows the shared *global* value by default."""

    size: bool = True
    modifier: bool = False
    strength: bool = True
    alpha: bool = True


@dataclass
class DrawEnvironment:
    """All draw-time inputs a tool's :meth:`ToolBase.on_draw` needs."""

    context: object
    state: Dict[str, object]
    img: object
    mode: str
    color: object
    blend: str
    opacity: float
    alpha_opacity: float
    protect_transparent: bool
    radius: int
    spacing: str
    wm: object
    cursor_x: int
    cursor_y: int
    interpolation_steps: Callable[[], object]
    curve_sampler_factory: Callable[[object], object]
    # (x, y, pixels, weights|None) -> (pixels, weights): maps one stamp's
    # footprint onto the image. Identity except in the 3D Viewport's Edge
    # mode, where it carries the stamp over UV seams.
    expand_stamp: Optional[Callable[..., Tuple[list, list]]] = None
    edge_mode: bool = False   # 3D Viewport, Edge mode
    modifier: float = 0.5     # tool modifier (button-specific, pen pressure applied)

    def expand(self, x, y, pixels, weights=None):
        """Footprint of a stamp at ``(x, y)`` -> ``(pixels, weights)`` lists to write."""
        if self.expand_stamp is not None:
            return self.expand_stamp(x, y, pixels, weights)
        pixels = list(pixels)
        return pixels, (list(weights) if weights is not None else [1.0] * len(pixels))

    def falloff(self, prop_name):
        """``(falloff_enum, curve_sampler_or_None)`` read from a WindowManager property."""
        falloff = getattr(self.wm, prop_name)
        sampler = self.curve_sampler_factory(self.context) if falloff == 'CUSTOM' else None
        return falloff, sampler

    def mark_painted(self):
        """Remember the cursor as the last painted position (for interpolation)."""
        self.state['last_paint_cx'] = self.cursor_x
        self.state['last_paint_cy'] = self.cursor_y
        self.state['last_paint_mouse'] = self.state.get('mouse_region')


class ToolBase(ToolFrame):
    """Interface every selectable Pixel Painter tool implements."""

    # ---- identity / presentation -------------------------------------------
    tool_id: str = 'BASE'
    label: str = 'Base'
    description: str = ''
    icon: Optional[str] = None            # image file in textures/
    outline_color: Tuple[float, float, float, float] = (1.0, 1.0, 0.0, 0.9)
    outline_shape: str = 'CIRCLE'         # 'SQUARE' or 'CIRCLE'

    # ---- behaviour flags -----------------------------------------------------
    defaults: SettingDefaults = SettingDefaults()
    falloff_property: Optional[str] = None  # WindowManager enum holding this tool's falloff
    usable_as_line_tip: bool = True         # remembered as the Line tool's tip shape
    line_tip_shape: str = 'CIRCLE'          # tip used by Line: 'SQUARE' | 'CIRCLE' | 'FALLOFF'
    respects_pixel_spacing: bool = True     # obey 'Pixel' spacing (skip repeated stamps)
    uses_pen_pressure: bool = True          # pen pressure scales the enabled channels
    shows_brush_outline: bool = True

    # ---- painting hooks (see tools.stroke.StrokeTool) -------------------------

    def on_stroke_begin(self, env: DrawEnvironment) -> None:
        """Called before the first :meth:`on_draw` of a stroke. Prepares stroke caches."""
        env.state['stroke_painted'] = set()
        env.state['stroke_weight_map'] = {}
        env.state['stroke_back_buffer'] = np.array(env.img.pixels, dtype=np.float32)

    def on_draw(self, env: DrawEnvironment) -> None:
        """Apply one step of the tool at ``env.cursor_x/y`` into ``env.img``."""
        raise NotImplementedError

    # ---- presentation hooks --------------------------------------------------

    def outline_pixels(self, state, x, y, radius):
        """Image pixels outlined by the cursor preview at ``(x, y)``."""
        return math_utils.get_pixels_in_shape(x, y, radius, self.outline_shape)

    def draw_settings(self, context, layout) -> None:
        """Draw tool-specific controls in the tool header / N-panel."""

    def __repr__(self):
        return f"<{type(self).__name__} {self.tool_id}>"

