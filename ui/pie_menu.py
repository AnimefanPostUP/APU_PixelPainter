"""Pixel Painter's custom radial menus, built on the generic UI kit.

The kit provides the behaviour (layout, picking, animation, interaction);
this module only decides *what* is shown and *what happens* on click:

* :class:`FalloffPicker` - grid of falloff preset buttons (a kit ``Panel``)
* :class:`ToolPie`       - tool bubbles on an arc + the falloff picker below
* :class:`FalloffPie`    - falloff presets as a pie of their own
* :class:`PixelPainterCustomPieOperator` - the W-key operator showing them
"""

import bpy
from bpy.types import Operator

from .icons import ICONS
from .kit import BubbleButton, Button, Grid, Panel, RadialMenu
from .kit.modal import OverlayOperator, force_cleanup
from ..tools import falloff
from ..tools.catalog import TOOLS, falloff_property_for


def _wm():
    return bpy.context.window_manager


def _active_falloff_property():
    return falloff_property_for(_wm().pixel_painter_mode)


def _falloff_is_active(preset_id):
    return lambda: getattr(_wm(), _active_falloff_property()) == preset_id


def _set_falloff(preset_id):
    return lambda: setattr(_wm(), _active_falloff_property(), preset_id)


def _tool_is_active(tool_id):
    return lambda: _wm().pixel_painter_mode == tool_id


def _set_tool(tool_id):
    return lambda: bpy.ops.image.pixel_painter_set_mode(mode=tool_id)


class FalloffPicker(Panel):
    """Falloff preset buttons, bound to the active tool's falloff property."""

    def __init__(self, columns=3, button_size=46.0, **kwargs):
        grid = Grid(columns=columns, gap=12.0)
        for preset in falloff.picker_presets():
            grid.add(Button(
                preset.label,
                key=f"FALLOFF_{preset.id}",
                icon=preset.icon_key,
                icons=ICONS,
                size=(button_size, button_size),
                selected=_falloff_is_active(preset.id),
                on_click=_set_falloff(preset.id),
            ))
        kwargs.setdefault('title', "Brush Falloff")
        super().__init__(grid, **kwargs)


class ToolPie(RadialMenu):
    """Every registered tool on the upper arc, falloff picker underneath."""

    def __init__(self, **kwargs):
        super().__init__(arc=(180.0, 0.0), **kwargs)
        for tool in TOOLS:
            self.add_item(BubbleButton(
                tool.label,
                key=tool.tool_id,
                icon=tool.tool_id if tool.icon else None,
                icons=ICONS,
                selected=_tool_is_active(tool.tool_id),
                on_click=_set_tool(tool.tool_id),
            ))
        self.attach_below(FalloffPicker())


# left, right, bottom, top, top-left, top-right
_FALLOFF_PIE_DIRECTIONS = ((-1.0, 0.0), (1.0, 0.0), (0.0, -1.0), (0.0, 1.0), (-0.7, 0.7), (0.7, 0.7))


class FalloffPie(RadialMenu):
    """Falloff presets as a stand-alone pie."""

    def __init__(self, **kwargs):
        super().__init__(directions=_FALLOFF_PIE_DIRECTIONS, **kwargs)
        for preset in falloff.picker_presets():
            self.add_item(BubbleButton(
                preset.label,
                key=f"FALLOFF_{preset.id}",
                icon=preset.icon_key,
                icons=ICONS,
                selected=_falloff_is_active(preset.id),
                on_click=_set_falloff(preset.id),
            ))


_PIES = {
    'MODE': ToolPie,
    'FALLOFF': FalloffPie,
}


class PixelPainterCustomPieOperator(OverlayOperator, Operator):
    """Open the Pixel Painter radial menu"""

    bl_idname = "image.pixel_painter_custom_pie"
    bl_label = "Pixel Painter Custom Pie"

    pie_type: bpy.props.EnumProperty(
        name="Pie Type",
        items=[
            ('MODE', "Mode", "Tool selection pie"),
            ('FALLOFF', "Falloff", "Falloff selection pie"),
        ],
        default='MODE',
    )

    def build_overlay(self, context, event):
        return _PIES[self.pie_type]()

    def pass_through(self, context, event):
        # Let undo/redo reach the paint operators instead of being swallowed.
        return event.type == 'Z' and event.value == 'PRESS' and event.ctrl


classes = (
    PixelPainterCustomPieOperator,
)


__all__ = ('FalloffPicker', 'ToolPie', 'FalloffPie', 'PixelPainterCustomPieOperator', 'force_cleanup')
