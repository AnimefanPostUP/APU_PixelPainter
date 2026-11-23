"""Tool interface for Pixel Painter.

Every tool is a :class:`ToolBase` subclass registered in
:data:`tools.catalog.TOOLS`. The registry is the single source of truth:
the mode enum, per-tool settings properties and their defaults, persistence
keys, the reset operator, the tool pie, Shift+number shortcuts, icons and
the settings panel are all generated from it.

Adding a tool
-------------
1. Subclass :class:`ToolBase` (or :class:`BrushTool` for painting tools)
   and set the metadata class attributes.
2. Implement :meth:`ToolBase.on_draw`.
3. Add an instance to the list in :mod:`tools.catalog`.
"""

from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple

import numpy as np

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

    def falloff(self, prop_name):
        """``(falloff_enum, curve_sampler_or_None)`` read from a WindowManager property."""
        falloff = getattr(self.wm, prop_name)
        sampler = self.curve_sampler_factory(self.context) if falloff == 'CUSTOM' else None
        return falloff, sampler

    def mark_painted(self):
        """Remember the cursor as the last painted position (for interpolation)."""
        self.state['last_paint_cx'] = self.cursor_x
        self.state['last_paint_cy'] = self.cursor_y


class ToolBase:
    """Interface every Pixel Painter tool implements."""

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
    shows_brush_outline: bool = True

    # ---- lifecycle hooks -----------------------------------------------------

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


class BrushTool(ToolBase):
    """Base class for tools that paint pixels."""
