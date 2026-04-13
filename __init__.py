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

from . import generic_utils
from . import math_utils
from . import blender_utils
from . import draw_functions
from . import core
from . import user_interface


bl_info = {
    "name": "Pixel Painter",
    "description": "Paint pixel-perfect strokes in the Image Editor",
    "author": "Kushiro",
    "version": (1, 0, 0),
    "blender": (2, 83, 0),
    "location": "Image Editor > Paint mode toolbar",
    "category": "Image Editor",
}


def register():
    importlib.reload(generic_utils)
    importlib.reload(math_utils)
    importlib.reload(blender_utils)
    importlib.reload(draw_functions)
    importlib.reload(core)
    importlib.reload(user_interface)

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
    ]
    bpy.types.WindowManager.pixel_painter_circle_falloff = bpy.props.EnumProperty(
        name="Circle Falloff", items=_falloff_items, default='CONSTANT',
    )
    bpy.types.WindowManager.pixel_painter_spray_falloff = bpy.props.EnumProperty(
        name="Spray Falloff", items=_falloff_items, default='LINEAR',
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

    bpy.utils.register_class(core.PixelPainterSetModeOperator)
    bpy.utils.register_class(core.PixelPainterSetBlendOperator)
    bpy.utils.register_class(core.PixelPainterUndoOperator)
    bpy.utils.register_class(core.PixelPainterRedoOperator)
    bpy.utils.register_class(user_interface.PixelPainterModePie)
    bpy.utils.register_class(user_interface.PixelPainterBlendPie)
    bpy.utils.register_class(core.PixelPainterOperator)
    bpy.utils.register_tool(user_interface.PixelPainterTool)


def unregister():
    # Remove the persistent GPU draw handler and clear the undo stack.
    draw_functions.remove_draw_handler(core._state)
    core._undo_clear()

    del bpy.types.WindowManager.pixel_painter_radius
    del bpy.types.WindowManager.pixel_painter_mode
    del bpy.types.WindowManager.pixel_painter_spacing
    del bpy.types.WindowManager.pixel_painter_circle_falloff
    del bpy.types.WindowManager.pixel_painter_spray_falloff
    del bpy.types.WindowManager.pixel_painter_spray_strength
    del bpy.types.WindowManager.pixel_painter_modifier

    bpy.utils.unregister_tool(user_interface.PixelPainterTool)
    bpy.utils.unregister_class(core.PixelPainterOperator)
    bpy.utils.unregister_class(user_interface.PixelPainterBlendPie)
    bpy.utils.unregister_class(user_interface.PixelPainterModePie)
    bpy.utils.unregister_class(core.PixelPainterRedoOperator)
    bpy.utils.unregister_class(core.PixelPainterUndoOperator)
    bpy.utils.unregister_class(core.PixelPainterSetBlendOperator)
    bpy.utils.unregister_class(core.PixelPainterSetModeOperator)


if __name__ == "__main__":
    register()
