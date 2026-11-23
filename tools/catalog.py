"""The registered Pixel Painter tools.

Order = mode enum order = tool pie order = Shift+1..8 shortcut order.
To add a tool, implement it (see :mod:`tools.base`) and list it here.
"""

from . import falloff
from .brushes import CircleBrushTool, EraserTool, LineBrushTool, SprayBrushTool, SquareBrushTool
from .filters import SmearTool, SmoothTool
from .registry import ToolRegistry
from .selection import SelectionTool


TOOLS = ToolRegistry(
    [
        CircleBrushTool(),
        SquareBrushTool(),
        SprayBrushTool(),
        SmoothTool(),
        SmearTool(),
        LineBrushTool(),
        EraserTool(),
        SelectionTool(),
    ],
    default_id='SQUARE',
)


def falloff_property_for(tool_id):
    """WindowManager property holding the falloff used by ``tool_id``."""
    return TOOLS.get(tool_id).falloff_property or falloff.DEFAULT_FALLOFF_PROPERTY
