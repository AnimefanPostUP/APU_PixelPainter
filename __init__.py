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
# Addon Recoded and Drastically Expanded by AnimefanPostUP 

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
from .core.submodes import base as submode_base
from .core.submodes import helpers as submode_helpers
from .core.submodes import opacity as submode_opacity
from .core.submodes import color_pick as submode_color_pick
from .core.submodes import controller as submode_controller
from .tools import tool_logic
from .ui import menu_controllers
from .core import core
from .ui import user_interface
from .ui import pie_menu
from .ui import tool_settings_ui
from .ui import paint_selected_faces_uv


bl_info = {
    "name": "APU Pixel Painter",
    "description": "All in One Tool for Pixelpainting",
    "author": "Kushiro, AnimefanPostUP",
    "version": (1, 0, 4),
    "blender": (4, 2, 0),
    "location": "Image Editor > Toolbar",
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


def _update_mode(self, context):
    """When the tool mode changes, load effective tool settings for that mode."""
    try:
        core.apply_active_tool_settings(context)
    except Exception:
        pass


def _get_active_size(self):
    try:
        ctx = bpy.context
        svc = settings_service.PixelPainterSettingsService()
        mode = getattr(self, 'pixel_painter_mode', 'SQUARE')
        force_global = bool(mode == 'SMOOTH' and getattr(self, 'pixel_painter_temp_smooth_force_global', False))
        return int(svc.get_tool_size(ctx, mode, force_global=force_global))
    except Exception:
        return int(getattr(self, 'pixel_painter_radius', 1))


def _set_active_size(self, value):
    try:
        ctx = bpy.context
        svc = settings_service.PixelPainterSettingsService()
        mode = getattr(self, 'pixel_painter_mode', 'SQUARE')
        force_global = bool(mode == 'SMOOTH' and getattr(self, 'pixel_painter_temp_smooth_force_global', False))
        svc.set_tool_size(ctx, mode, value, force_global=force_global)
        core.apply_active_tool_settings(ctx)
    except Exception:
        pass


def _get_active_strength(self):
    try:
        ctx = bpy.context
        svc = settings_service.PixelPainterSettingsService()
        mode = getattr(self, 'pixel_painter_mode', 'SQUARE')
        force_global = bool(mode == 'SMOOTH' and getattr(self, 'pixel_painter_temp_smooth_force_global', False))
        return float(svc.get_tool_strength(ctx, mode, force_global=force_global))
    except Exception:
        return 1.0


def _set_active_strength(self, value):
    try:
        ctx = bpy.context
        svc = settings_service.PixelPainterSettingsService()
        mode = getattr(self, 'pixel_painter_mode', 'SQUARE')
        force_global = bool(mode == 'SMOOTH' and getattr(self, 'pixel_painter_temp_smooth_force_global', False))
        svc.set_tool_strength(ctx, mode, value, force_global=force_global)
        core.apply_active_tool_settings(ctx)
    except Exception:
        pass


def _get_active_alpha(self):
    try:
        ctx = bpy.context
        svc = settings_service.PixelPainterSettingsService()
        mode = getattr(self, 'pixel_painter_mode', 'SQUARE')
        force_global = bool(mode == 'SMOOTH' and getattr(self, 'pixel_painter_temp_smooth_force_global', False))
        return float(svc.get_tool_alpha(ctx, mode, force_global=force_global))
    except Exception:
        return 1.0


def _set_active_alpha(self, value):
    try:
        ctx = bpy.context
        svc = settings_service.PixelPainterSettingsService()
        mode = getattr(self, 'pixel_painter_mode', 'SQUARE')
        force_global = bool(mode == 'SMOOTH' and getattr(self, 'pixel_painter_temp_smooth_force_global', False))
        svc.set_tool_alpha(ctx, mode, value, force_global=force_global)
        core.apply_active_tool_settings(ctx)
    except Exception:
        pass


def _get_active_modifier(self):
    try:
        ctx = bpy.context
        svc = settings_service.PixelPainterSettingsService()
        mode = getattr(self, 'pixel_painter_mode', 'SQUARE')
        force_global = bool(mode == 'SMOOTH' and getattr(self, 'pixel_painter_temp_smooth_force_global', False))
        return float(svc.get_tool_modifier(ctx, mode, force_global=force_global))
    except Exception:
        return 0.5


def _set_active_modifier(self, value):
    try:
        ctx = bpy.context
        svc = settings_service.PixelPainterSettingsService()
        mode = getattr(self, 'pixel_painter_mode', 'SQUARE')
        force_global = bool(mode == 'SMOOTH' and getattr(self, 'pixel_painter_temp_smooth_force_global', False))
        svc.set_tool_modifier(ctx, mode, value, force_global=force_global)
        core.apply_active_tool_settings(ctx)
    except Exception:
        pass


def register():
    import bmesh
    paint_selected_faces_uv.set_bmesh_module(bmesh)
    paint_selected_faces_uv.register()
    # Force delete pixel_painter_mode EnumProperty before re-registering
    try:
        del bpy.types.WindowManager.pixel_painter_mode
        print("[PixelPainter] pixel_painter_mode property deleted before re-registering.")
    except Exception:
        pass
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
    importlib.reload(submode_base)
    importlib.reload(submode_helpers)
    importlib.reload(submode_opacity)
    importlib.reload(submode_color_pick)
    importlib.reload(submode_controller)
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
    print("[PixelPainter][DEBUG] Registered IntProperty: pixel_painter_radius")
    bpy.types.WindowManager.pixel_painter_mode = bpy.props.EnumProperty(
        name="Mode",
        items=[
            ('SQUARE',  "Square",  "Square brush shape"),
            ('CIRCLE',  "Circle",  "Circle brush shape with falloff"),
            ('SPRAY',   "Spray",   "Randomised spray within a circle"),
            ('LINE',    "Line",    "Draw a straight line (V key)"),
            ('SMOOTH',  "Smooth",  "Blur pixels — Spread sets kernel size, Strength sets blend strength"),
            ('SMEAR',   "Smear",   "Drag pixels — Spread sets reach, Strength sets blend strength"),
            ('ERASER',  "Eraser",  "Erase alpha by strength"),
        ],
        default='SQUARE',
        update=_update_mode,
    )
    print("[PixelPainter][DEBUG] Registered EnumProperty: pixel_painter_mode with items SQUARE, CIRCLE, SPRAY, LINE, SMOOTH, SMEAR, ERASER")

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
    print(f"[PixelPainter][DEBUG] Registered EnumProperty: pixel_painter_circle_falloff with items: {[i[0] for i in _falloff_items]}")
    bpy.types.WindowManager.pixel_painter_spray_falloff = bpy.props.EnumProperty(
        name="Spray Falloff", items=_falloff_items, default='LINEAR',
        update=_update_spray_falloff,
    )
    print(f"[PixelPainter][DEBUG] Registered EnumProperty: pixel_painter_spray_falloff with items: {[i[0] for i in _falloff_items]}")
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
    print("[PixelPainter][DEBUG] Registered EnumProperty: pixel_painter_spacing with items FREE, PIXEL")
    bpy.types.WindowManager.pixel_painter_modifier = bpy.props.FloatProperty(
        name="Modifier",
        description="Generic modifier value (currently used as Spread)",
        min=0.0, max=1.0, default=0.5, subtype='FACTOR',
    )
    bpy.types.WindowManager.pixel_painter_global_modifier = bpy.props.FloatProperty(
        name="Global Modifier",
        min=0.0, max=1.0, default=0.5, subtype='FACTOR', options={'HIDDEN'},
    )
    bpy.types.WindowManager.pixel_painter_global_strength = bpy.props.FloatProperty(
        name="Global Strength",
        min=0.0, max=1.0, default=1.0, subtype='FACTOR', options={'HIDDEN'},
    )
    bpy.types.WindowManager.pixel_painter_global_alpha = bpy.props.FloatProperty(
        name="Global Alpha",
        min=0.0, max=1.0, default=1.0, subtype='FACTOR', options={'HIDDEN'},
    )
    # RMB global settings
    bpy.types.WindowManager.pixel_painter_global_strength_rmb = bpy.props.FloatProperty(
        name="Global Strength RMB",
        min=0.0, max=1.0, default=1.0, subtype='FACTOR', options={'HIDDEN'},
    )
    bpy.types.WindowManager.pixel_painter_global_modifier_rmb = bpy.props.FloatProperty(
        name="Global Modifier RMB",
        min=0.0, max=1.0, default=0.5, subtype='FACTOR', options={'HIDDEN'},
    )
    bpy.types.WindowManager.pixel_painter_global_alpha_rmb = bpy.props.FloatProperty(
        name="Global Alpha RMB",
        min=0.0, max=1.0, default=1.0, subtype='FACTOR', options={'HIDDEN'},
    )
    bpy.types.WindowManager.pixel_painter_temp_smooth_force_global = bpy.props.BoolProperty(
        name="Temp Smooth Force Global",
        default=False,
        options={'HIDDEN'},
    )
    bpy.types.WindowManager.pixel_painter_active_size = bpy.props.IntProperty(
        name="Size",
        description="Active size setter routing to global or local value for current tool",
        min=0,
        max=64,
        get=_get_active_size,
        set=_set_active_size,
    )
    bpy.types.WindowManager.pixel_painter_active_strength = bpy.props.FloatProperty(
        name="Strength",
        description="Active strength setter routing to global or local value for current tool",
        min=0.0,
        max=1.0,
        subtype='FACTOR',
        get=_get_active_strength,
        set=_set_active_strength,
    )
    bpy.types.WindowManager.pixel_painter_active_modifier = bpy.props.FloatProperty(
        name="Modifier",
        description="Active modifier setter routing to global or local value for current tool",
        min=0.0,
        max=1.0,
        subtype='FACTOR',
        get=_get_active_modifier,
        set=_set_active_modifier,
    )
    bpy.types.WindowManager.pixel_painter_active_alpha = bpy.props.FloatProperty(
        name="Alpha",
        description="Active alpha setter routing to global or local value for current tool",
        min=0.0,
        max=1.0,
        subtype='FACTOR',
        get=_get_active_alpha,
        set=_set_active_alpha,
    )
    
    # Per-tool settings: Size, Modifier, Strength, Alpha with global/per-tool toggles
    # Defaults:
    # - Size: SQUARE, CIRCLE, SMOOTH, SMEAR use global; SPRAY, LINE use local
    # - Strength: SQUARE, CIRCLE use global; SPRAY, LINE, SMOOTH, SMEAR use local
    # - Modifier: SMOOTH, SMEAR use global; SQUARE, CIRCLE, SPRAY, LINE use local
    # - Alpha: SQUARE, CIRCLE use global; SPRAY, LINE, SMOOTH, SMEAR use local
    
    _size_use_global = {'SQUARE': True, 'CIRCLE': True, 'SPRAY': False, 'LINE': False, 'SMOOTH': True, 'SMEAR': True, 'ERASER': True}
    _modifier_use_global = {'SQUARE': False, 'CIRCLE': False, 'SPRAY': False, 'LINE': False, 'SMOOTH': True, 'SMEAR': True, 'ERASER': False}
    _strength_use_global = {'SQUARE': True, 'CIRCLE': True, 'SPRAY': False, 'LINE': False, 'SMOOTH': False, 'SMEAR': False, 'ERASER': False}
    _alpha_use_global = {'SQUARE': True, 'CIRCLE': True, 'SPRAY': False, 'LINE': False, 'SMOOTH': False, 'SMEAR': False, 'ERASER': False}

    # Register per-tool properties for all tools, including ERASER
    for tool in ['SQUARE', 'CIRCLE', 'SPRAY', 'LINE', 'SMOOTH', 'SMEAR', 'ERASER']:
        try:
            # Size settings
            setattr(bpy.types.WindowManager, f'pixel_painter_{tool}_size',
                    bpy.props.IntProperty(name=f"{tool} Size", min=0, max=64, default=1))
            setattr(bpy.types.WindowManager, f'pixel_painter_{tool}_use_global_size',
                    bpy.props.BoolProperty(name=f"{tool} Use Global Size", default=_size_use_global.get(tool, True)))

            # Modifier settings
            setattr(bpy.types.WindowManager, f'pixel_painter_{tool}_modifier',
                    bpy.props.FloatProperty(name=f"{tool} Modifier", min=0.0, max=1.0, default=0.5, subtype='FACTOR'))
            setattr(bpy.types.WindowManager, f'pixel_painter_{tool}_use_global_modifier',
                    bpy.props.BoolProperty(name=f"{tool} Use Global Modifier", default=_modifier_use_global.get(tool, True)))

            # Strength settings
            setattr(bpy.types.WindowManager, f'pixel_painter_{tool}_strength',
                    bpy.props.FloatProperty(name=f"{tool} Strength", min=0.0, max=1.0, default=1.0, subtype='FACTOR'))
            setattr(bpy.types.WindowManager, f'pixel_painter_{tool}_use_global_strength',
                    bpy.props.BoolProperty(name=f"{tool} Use Global Strength", default=_strength_use_global.get(tool, True)))

            # Alpha settings
            setattr(bpy.types.WindowManager, f'pixel_painter_{tool}_alpha',
                bpy.props.FloatProperty(name=f"{tool} Alpha", min=0.0, max=1.0, default=1.0, subtype='FACTOR'))
            setattr(bpy.types.WindowManager, f'pixel_painter_{tool}_use_global_alpha',
                bpy.props.BoolProperty(name=f"{tool} Use Global Alpha", default=_alpha_use_global.get(tool, True)))

            # RMB per-tool settings
            setattr(bpy.types.WindowManager, f'pixel_painter_{tool}_strength_rmb',
                bpy.props.FloatProperty(name=f"{tool} Strength RMB", min=0.0, max=1.0, default=1.0, subtype='FACTOR'))
            setattr(bpy.types.WindowManager, f'pixel_painter_{tool}_use_global_strength_rmb',
                bpy.props.BoolProperty(name=f"{tool} Use Global Strength RMB", default=_strength_use_global.get(tool, True)))
            setattr(bpy.types.WindowManager, f'pixel_painter_{tool}_modifier_rmb',
                bpy.props.FloatProperty(name=f"{tool} Modifier RMB", min=0.0, max=1.0, default=0.5, subtype='FACTOR'))
            setattr(bpy.types.WindowManager, f'pixel_painter_{tool}_use_global_modifier_rmb',
                bpy.props.BoolProperty(name=f"{tool} Use Global Modifier RMB", default=_modifier_use_global.get(tool, True)))
            setattr(bpy.types.WindowManager, f'pixel_painter_{tool}_alpha_rmb',
                bpy.props.FloatProperty(name=f"{tool} Alpha RMB", min=0.0, max=1.0, default=1.0, subtype='FACTOR'))
            setattr(bpy.types.WindowManager, f'pixel_painter_{tool}_use_global_alpha_rmb',
                bpy.props.BoolProperty(name=f"{tool} Use Global Alpha RMB", default=_alpha_use_global.get(tool, True)))
            print(f"[PixelPainter][DEBUG] Registered per-tool properties for {tool}")
        except Exception as e:
            print(f"[PixelPainter] Failed to register properties for tool {tool}: {e}")
    
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
    bpy.types.WindowManager.pixel_painter_ui_show_tool_settings = bpy.props.BoolProperty(
        name="Show Tool Settings", default=False,
    )
    bpy.types.WindowManager.pixel_painter_grid_opacity = bpy.props.FloatProperty(
        name="Grid Opacity",
        description="Opacity of the pixel grid overlay (0 = hidden, 1 = fully opaque)",
        min=0.0, max=1.0, default=0.0, subtype='FACTOR',
    )

    bpy.utils.register_class(core.PixelPainterSetModeOperator)
    bpy.utils.register_class(core.PixelPainterSetBlendOperator)
    bpy.utils.register_class(core.PixelPainterUndoOperator)
    bpy.utils.register_class(core.PixelPainterRedoOperator)
    bpy.utils.register_class(core.PixelPainterResetToolSettingsOperator)
    bpy.utils.register_class(pie_menu.PixelPainterOpenBlendPieOperator)
    bpy.utils.register_class(pie_menu.PixelPainterCustomPieOperator)
    bpy.utils.register_class(pie_menu.PixelPainterModePie)
    bpy.utils.register_class(pie_menu.PixelPainterBlendPie)
    bpy.utils.register_class(core.PixelPainterOperator)
    bpy.utils.register_tool(user_interface.PixelPainterTool)
    try:
        svc = settings_service.PixelPainterSettingsService()
        bpy.context.window_manager.pixel_painter_global_strength = svc.get_brush_strength(bpy.context)
    except Exception:
        pass
    try:
        core.apply_active_tool_settings(bpy.context)
    except Exception:
        pass


def unregister():
    paint_selected_faces_uv.unregister()
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
    del bpy.types.WindowManager.pixel_painter_global_modifier
    del bpy.types.WindowManager.pixel_painter_global_strength
    del bpy.types.WindowManager.pixel_painter_global_alpha
    del bpy.types.WindowManager.pixel_painter_global_strength_rmb
    del bpy.types.WindowManager.pixel_painter_global_modifier_rmb
    del bpy.types.WindowManager.pixel_painter_global_alpha_rmb
    del bpy.types.WindowManager.pixel_painter_temp_smooth_force_global
    del bpy.types.WindowManager.pixel_painter_active_size
    del bpy.types.WindowManager.pixel_painter_active_strength
    del bpy.types.WindowManager.pixel_painter_active_modifier
    del bpy.types.WindowManager.pixel_painter_active_alpha
    del bpy.types.WindowManager.pixel_painter_blend_favorites
    del bpy.types.WindowManager.pixel_painter_ui_show_settings
    del bpy.types.WindowManager.pixel_painter_ui_show_blend_mode
    del bpy.types.WindowManager.pixel_painter_ui_show_shortcuts
    del bpy.types.WindowManager.pixel_painter_ui_show_tool_settings
    del bpy.types.WindowManager.pixel_painter_grid_opacity
    
    # Delete per-tool settings
    _tools = ['SQUARE', 'CIRCLE', 'SPRAY', 'LINE', 'SMOOTH', 'SMEAR', 'ERASER']
    for tool in _tools:
        if hasattr(bpy.types.WindowManager, f'pixel_painter_{tool}_size'):
            delattr(bpy.types.WindowManager, f'pixel_painter_{tool}_size')
        if hasattr(bpy.types.WindowManager, f'pixel_painter_{tool}_use_global_size'):
            delattr(bpy.types.WindowManager, f'pixel_painter_{tool}_use_global_size')
        if hasattr(bpy.types.WindowManager, f'pixel_painter_{tool}_modifier'):
            delattr(bpy.types.WindowManager, f'pixel_painter_{tool}_modifier')
        if hasattr(bpy.types.WindowManager, f'pixel_painter_{tool}_use_global_modifier'):
            delattr(bpy.types.WindowManager, f'pixel_painter_{tool}_use_global_modifier')
        if hasattr(bpy.types.WindowManager, f'pixel_painter_{tool}_strength'):
            delattr(bpy.types.WindowManager, f'pixel_painter_{tool}_strength')
        if hasattr(bpy.types.WindowManager, f'pixel_painter_{tool}_use_global_strength'):
            delattr(bpy.types.WindowManager, f'pixel_painter_{tool}_use_global_strength')
        if hasattr(bpy.types.WindowManager, f'pixel_painter_{tool}_alpha'):
            delattr(bpy.types.WindowManager, f'pixel_painter_{tool}_alpha')
        if hasattr(bpy.types.WindowManager, f'pixel_painter_{tool}_use_global_alpha'):
            delattr(bpy.types.WindowManager, f'pixel_painter_{tool}_use_global_alpha')
        if hasattr(bpy.types.WindowManager, f'pixel_painter_{tool}_strength_rmb'):
            delattr(bpy.types.WindowManager, f'pixel_painter_{tool}_strength_rmb')
        if hasattr(bpy.types.WindowManager, f'pixel_painter_{tool}_use_global_strength_rmb'):
            delattr(bpy.types.WindowManager, f'pixel_painter_{tool}_use_global_strength_rmb')
        if hasattr(bpy.types.WindowManager, f'pixel_painter_{tool}_modifier_rmb'):
            delattr(bpy.types.WindowManager, f'pixel_painter_{tool}_modifier_rmb')
        if hasattr(bpy.types.WindowManager, f'pixel_painter_{tool}_use_global_modifier_rmb'):
            delattr(bpy.types.WindowManager, f'pixel_painter_{tool}_use_global_modifier_rmb')
        if hasattr(bpy.types.WindowManager, f'pixel_painter_{tool}_alpha_rmb'):
            delattr(bpy.types.WindowManager, f'pixel_painter_{tool}_alpha_rmb')
        if hasattr(bpy.types.WindowManager, f'pixel_painter_{tool}_use_global_alpha_rmb'):
            delattr(bpy.types.WindowManager, f'pixel_painter_{tool}_use_global_alpha_rmb')

    bpy.utils.unregister_tool(user_interface.PixelPainterTool)
    bpy.utils.unregister_class(core.PixelPainterOperator)
    bpy.utils.unregister_class(pie_menu.PixelPainterBlendPie)
    bpy.utils.unregister_class(pie_menu.PixelPainterModePie)
    bpy.utils.unregister_class(core.PixelPainterRedoOperator)
    bpy.utils.unregister_class(core.PixelPainterUndoOperator)
    bpy.utils.unregister_class(pie_menu.PixelPainterCustomPieOperator)
    bpy.utils.unregister_class(pie_menu.PixelPainterOpenBlendPieOperator)
    bpy.utils.unregister_class(core.PixelPainterSetBlendOperator)
    bpy.utils.unregister_class(core.PixelPainterSetModeOperator)


if __name__ == "__main__":
    register()
