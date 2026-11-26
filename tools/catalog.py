"""The registered Pixel Painter tools.

``TOOLS``: the selectable tools. Order = mode enum order = tool pie order =
Shift+1..8 shortcut order. To add a tool, implement it (see
:mod:`tools.base`) and list it here.

``global_tools()``: tools that receive events for the whole session no
matter which tool is selected (they run before the selected tool).
"""

from ..model import falloff
from .brushes.circle import CircleBrushTool
from .brushes.eraser import EraserTool
from .brushes.line import LineBrushTool
from .brushes.spray import SprayBrushTool
from .brushes.square import SquareBrushTool
from .filters.smear import SmearTool
from .filters.smooth import SmoothTool
from .mask.tool import MaskTool
from .pen.tool import PenBarTool
from .registry import ToolRegistry
from .selection.tool import SelectionTool
from .subtools.tool_switch import ToolSwitchShortcuts


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


def global_tools():
    return [
        PenBarTool(TOOLS),           # on-screen pen controls (screen space, runs first)
        MaskTool(),                  # paint mask: picking islands / parts on the canvas
        ToolSwitchShortcuts(TOOLS),  # Shift+1..9
    ]


def falloff_property_for(tool_id):
    """WindowManager property holding the falloff used by ``tool_id``."""
    return TOOLS.get(tool_id).falloff_property or falloff.DEFAULT_FALLOFF_PROPERTY
