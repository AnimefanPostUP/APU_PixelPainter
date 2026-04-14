# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####
# Created by Kushiro

import bpy
import importlib

from .utils import generic_utils
from .utils import math_utils
from .utils import blender_utils
from .tools import draw_functions
from .tools import overlays
from .core import variables
from .utils import settings_service
from .core import core_runtime
from .tools import tool_logic
from .ui import menu_controllers
from .core import core
from .ui import user_interface
from .ui import pie_menu
from .ui import tool_settings_ui


bl_info = {
    "name": "Pixel Painter",
    "description": "Paint pixel-perfect strokes in the Image Editor",
    "author": "Kushiro",
    "version": (1, 0, 0),
    "blender": (2, 83, 0),
    "location": "Image Editor > Paint mode toolbar",
    "category": "Image Editor",
}


_FALLOFF_TO_CURVE_PRESET = {
    'CONSTANT': 'MAX',
    'LINEAR': 'LINE',
    'SMOOTH': 'SMOOTH',
    'SPHERE': 'ROUND',
    'SHARPEN': 'SHARP',
}


def _apply_curve_preset_from_falloff(context, falloff_value):
    """Map Pixel Painter falloff enum to brush curve preset."""
    try:
        brush = context.tool_settings.image_paint.brush
        if not brush or not hasattr(brush, 'curve_preset'):
            return
        preset = _FALLOFF_TO_CURVE_PRESET.get(falloff_value)
        if preset:
            brush.curve_preset = preset
    except Exception:
        pass


def _update_circle_falloff(self, context):
    _apply_curve_preset_from_falloff(context, self.pixel_painter_circle_falloff)


def _update_spray_falloff(self, context):
    _apply_curve_preset_from_falloff(context, self.pixel_painter_spray_falloff)


def register():
    # Clean up old custom-pie handlers/timers before reloading module code.
    try:
        pie_menu.force_cleanup()
    except Exception:
        pass

    importlib.reload(generic_utils)
    importlib.reload(math_utils)
    importlib.reload(blender_utils)
    importlib.reload(draw_functions)
    importlib.reload(overlays)
    importlib.reload(variables)
    importlib.reload(settings_service)
    importlib.reload(core_runtime)
    importlib.reload(tool_logic)
    importlib.reload(menu_controllers)
    importlib.reload(core)
    importlib.reload(user_interface)
    importlib.reload(pie_menu)
    importlib.reload(tool_settings_ui)
    pie_menu.register_icons()

    # Clear any stale state from a previous addon reload
    draw_functions.remove_draw_handler(core._state)
    core._undo_clear()
    core._state['running']    = False
    core._state['current_cx'] = None
    core._state['current_cy'] = None

    bpy.types.WindowManager.pixel_painter_radius = bpy.props.IntProperty(
        name="Radius", description="Brush radius in pixels", min=0, max=64, default=1,
    )
    bpy.types.WindowManager.pixel_painter_mode = bpy.props.EnumProperty(
        name="Mode",
        items=[
            ('SQUARE',  "Square",  "Square brush shape"),
            ('CIRCLE',  "Circle",  "Circle brush shape with falloff"),
            ('SPRAY',   "Spray",   "Randomised spray within a circle"),
            ('LINE',    "Line",    "Draw a straight line (V key)"),
            ('SMOOTH',  "Smooth",  "Blur pixels — Spread sets kernel size, Opacity sets blend strength"),
            ('SMEAR',   "Smear",   "Drag pixels — Spread sets reach, Opacity sets blend strength"),
        ],
        default='SQUARE',
    )

    _falloff_items = [
        ('CONSTANT', "Constant", "Uniform strength across the brush"),
        ('LINEAR',   "Linear",   "Linearly fades from centre to edge"),
        ('SMOOTH',   "Smooth",   "Smooth ease-in/out fade"),
        ('SPHERE',   "Sphere",   "Spherical dome-shaped falloff"),
        ('SHARPEN',  "Sharpen",  "Quadratic — drops off quickly toward the edge"),
        ('CUSTOM',   "Custom",   "Use the custom brush curve from Tool Settings"),
    ]
    bpy.types.WindowManager.pixel_painter_circle_falloff = bpy.props.EnumProperty(
        name="Circle Falloff", items=_falloff_items, default='CONSTANT',
        update=_update_circle_falloff,
    )
    bpy.types.WindowManager.pixel_painter_spray_falloff = bpy.props.EnumProperty(
        name="Spray Falloff", items=_falloff_items, default='LINEAR',
        update=_update_spray_falloff,
    )
    bpy.types.WindowManager.pixel_painter_spray_strength = bpy.props.FloatProperty(
        name="Spray Density",
        description="Fraction of the circle area painted per frame (0 = sparse, 1 = full fill)",
        min=0.01, max=1.0, default=0.1, subtype='FACTOR',
    )
    bpy.types.WindowManager.pixel_painter_spacing = bpy.props.EnumProperty(
        name="Spacing",
        description="When to paint: continuously (Free) or once per unique pixel position (Pixel)",
        items=[
            ('FREE',  "Free",  "Paint continuously as the mouse moves, with stroke interpolation"),
            ('PIXEL', "Pixel", "Paint only when the cursor moves to a new pixel — no repeated stamps"),
        ],
        default='FREE',
    )
    bpy.types.WindowManager.pixel_painter_modifier = bpy.props.FloatProperty(
        name="Modifier",
        description="Generic modifier value (currently used as Spread)",
        min=0.0, max=1.0, default=0.5, subtype='FACTOR',
    )
    _blend_items = [
        ('MIX',        "Normal",      "Normal blend"),
        ('ADD',        "Add",         "Add blend"),
        ('MUL',        "Multiply",    "Multiply blend"),
        ('DARKEN',     "Darken",      "Darken blend"),
        ('LIGHTEN',    "Lighten",     "Lighten blend"),
        ('COLOR',      "Color",       "Color blend"),
        ('SCREEN',     "Screen",      "Screen blend"),
        ('OVERLAY',    "Overlay",     "Overlay blend"),
        ('SOFTLIGHT',  "Soft Light",  "Soft Light blend"),
        ('HARDLIGHT',  "Hard Light",  "Hard Light blend"),
        ('SUB',        "Subtract",    "Subtract blend"),
        ('DIFFERENCE', "Difference",  "Difference blend"),
        ('EXCLUSION',  "Exclusion",   "Exclusion blend"),
        ('COLORDODGE', "Color Dodge", "Color Dodge blend"),
        ('COLORBURN',  "Color Burn",  "Color Burn blend"),
        ('HUE',        "Hue",         "Hue blend"),
        ('SATURATION', "Saturation",  "Saturation blend"),
        ('VALUE',      "Value",       "Value blend"),
        ('LUMINOSITY', "Luminosity",  "Luminosity blend"),
    ]
    bpy.types.WindowManager.pixel_painter_blend_favorites = bpy.props.EnumProperty(
        name="Blend Favorites",
        description="Select blend modes shown in the Favorites block",
        items=_blend_items,
        options={'ENUM_FLAG'},
        default={'MIX', 'ADD', 'MUL', 'DARKEN', 'LIGHTEN', 'COLOR'},
    )
    bpy.types.WindowManager.pixel_painter_ui_show_settings = bpy.props.BoolProperty(
        name="Show Settings", default=True,
    )
    bpy.types.WindowManager.pixel_painter_ui_show_blend_mode = bpy.props.BoolProperty(
        name="Show Blend Mode", default=False,
    )
    bpy.types.WindowManager.pixel_painter_ui_show_shortcuts = bpy.props.BoolProperty(
        name="Show Shortcuts", default=True,
    )

    bpy.utils.register_class(core.PixelPainterSetModeOperator)
    bpy.utils.register_class(core.PixelPainterSetBlendOperator)
    bpy.utils.register_class(pie_menu.PixelPainterCustomPieOperator)
    bpy.utils.register_class(core.PixelPainterUndoOperator)
    bpy.utils.register_class(core.PixelPainterRedoOperator)
    bpy.utils.register_class(pie_menu.PixelPainterModePie)
    bpy.utils.register_class(pie_menu.PixelPainterBlendPie)
    bpy.utils.register_class(core.PixelPainterOperator)
    bpy.utils.register_tool(user_interface.PixelPainterTool)


def unregister():
    # Remove the persistent GPU draw handler and clear the undo stack.
    draw_functions.remove_draw_handler(core._state)
    core._undo_clear()
    try:
        pie_menu.force_cleanup()
    except Exception:
        pass
    pie_menu.unregister_icons()

    del bpy.types.WindowManager.pixel_painter_radius
    del bpy.types.WindowManager.pixel_painter_mode
    del bpy.types.WindowManager.pixel_painter_spacing
    del bpy.types.WindowManager.pixel_painter_circle_falloff
    del bpy.types.WindowManager.pixel_painter_spray_falloff
    del bpy.types.WindowManager.pixel_painter_spray_strength
    del bpy.types.WindowManager.pixel_painter_modifier
    del bpy.types.WindowManager.pixel_painter_blend_favorites
    del bpy.types.WindowManager.pixel_painter_ui_show_settings
    del bpy.types.WindowManager.pixel_painter_ui_show_blend_mode
    del bpy.types.WindowManager.pixel_painter_ui_show_shortcuts

    bpy.utils.unregister_tool(user_interface.PixelPainterTool)
    bpy.utils.unregister_class(core.PixelPainterOperator)
    bpy.utils.unregister_class(pie_menu.PixelPainterBlendPie)
    bpy.utils.unregister_class(pie_menu.PixelPainterModePie)
    bpy.utils.unregister_class(core.PixelPainterRedoOperator)
    bpy.utils.unregister_class(core.PixelPainterUndoOperator)
    bpy.utils.unregister_class(pie_menu.PixelPainterCustomPieOperator)
    bpy.utils.unregister_class(core.PixelPainterSetBlendOperator)
    bpy.utils.unregister_class(core.PixelPainterSetModeOperator)


if __name__ == "__main__":
    register()
