import bpy
import numpy as np
from bpy.types import Operator


class PixelPainterResetToolSettingsOperatorV2(Operator):
    """Reset all Pixel Painter tool settings to their default values (neue Version)."""
    bl_idname = "image.pixel_painter_reset_tool_settings_v2"
    bl_label = "Reset Tool Settings (Neu)"

    def execute(self, context):
        wm = context.window_manager
        # Reset global settings
        wm.pixel_painter_radius = 1
        wm.pixel_painter_mode = 'SQUARE'
        wm.pixel_painter_circle_falloff = 'CONSTANT'
        wm.pixel_painter_spray_falloff = 'LINEAR'
        wm.pixel_painter_spray_strength = 0.1
        wm.pixel_painter_spacing = 'FREE'
        wm.pixel_painter_modifier = 0.5
        wm.pixel_painter_global_modifier = 0.5
        wm.pixel_painter_global_strength = 1.0
        wm.pixel_painter_global_alpha = 1.0
        wm.pixel_painter_global_strength_rmb = 1.0
        wm.pixel_painter_global_modifier_rmb = 0.5
        wm.pixel_painter_global_alpha_rmb = 1.0
        wm.pixel_painter_temp_smooth_force_global = False
        wm.pixel_painter_grid_opacity = 0.0
        # Reset per-tool settings
        for tool in ['SQUARE', 'CIRCLE', 'SPRAY', 'LINE', 'SMOOTH', 'SMEAR', 'ERASER']:
            setattr(wm, f'pixel_painter_{tool}_size', 1)
            setattr(wm, f'pixel_painter_{tool}_use_global_size', tool in ['SQUARE', 'CIRCLE', 'SMOOTH', 'SMEAR', 'ERASER'])
            setattr(wm, f'pixel_painter_{tool}_modifier', 0.5)
            setattr(wm, f'pixel_painter_{tool}_use_global_modifier', tool in ['SMOOTH', 'SMEAR'])
            setattr(wm, f'pixel_painter_{tool}_strength', 1.0)
            setattr(wm, f'pixel_painter_{tool}_use_global_strength', tool in ['SQUARE', 'CIRCLE'])
            setattr(wm, f'pixel_painter_{tool}_alpha', 1.0)
            setattr(wm, f'pixel_painter_{tool}_use_global_alpha', tool in ['SQUARE', 'CIRCLE'])
            # RMB
            setattr(wm, f'pixel_painter_{tool}_strength_rmb', 1.0)
            setattr(wm, f'pixel_painter_{tool}_use_global_strength_rmb', tool in ['SQUARE', 'CIRCLE'])
            setattr(wm, f'pixel_painter_{tool}_modifier_rmb', 0.5)
            setattr(wm, f'pixel_painter_{tool}_use_global_modifier_rmb', tool in ['SMOOTH', 'SMEAR'])
            setattr(wm, f'pixel_painter_{tool}_alpha_rmb', 1.0)
            setattr(wm, f'pixel_painter_{tool}_use_global_alpha_rmb', tool in ['SQUARE', 'CIRCLE'])
        self.report({'INFO'}, "Pixel Painter tool settings reset to defaults.")
        return {'FINISHED'}
"""Operator classes and module-level tool state."""
import colorsys
import time

import bpy
import numpy as np
from bpy.types import Operator

from ..utils import math_utils
from ..utils import blender_utils
from ..tools import draw_functions
from .core_runtime import PixelPainterCoreRuntime
from ..ui.menu_controllers import MenuControllerRegistry
from ..utils.settings_service import PixelPainterSettingsService
from ..tools.tool_logic import DrawEnvironment, ToolRegistry
from .variables import build_default_variable_store
from .submodes.controller import SubModeController


# ---------------------------------------------------------------------------
# Module-level tool state shared between the operator and the draw handler.
# The draw handler must NOT hold a reference to the operator instance because
# Blender frees the instance while the handler may still be registered.
# ---------------------------------------------------------------------------

_state = {
    'running':        False,  # True while the persistent modal is active
    'current_cx':     None,
    'current_cy':     None,
    'draw_handler':   None,
    'draw_space':     None,
    'start_position':   None,   # (cx, cy) when LMB pressed in LINE mode
    'back_buffer':      None,   # pixel array snapshot for clean line preview
    'last_shape':         'SQUARE',
    'last_paint_cx':      None,
    'last_paint_cy':      None,
    'stroke_painted':     None,  # set of (px,py) painted this stroke (SQUARE / Pixel-mode guard)
    'stroke_weight_map':  None,  # dict (px,py)→max_weight for CIRCLE/SPRAY Free mode
    'stroke_back_buffer': None,  # pre-stroke image snapshot for CIRCLE/SPRAY Free mode
    'use_secondary':  False,  # True while RMB is held (paint with secondary color)
    # ---- interactive sub-modes (R = strength, E = color pick) ----------------
    'sub_mode':           None,  # 'STRENGTH' | 'COLOR_PICK' | None
    'sub_last_x':         None,  # mouse region X on last MOUSEMOVE in sub-mode
    'sub_last_y':         None,  # mouse region Y on last MOUSEMOVE in sub-mode
    'sub_fake_cursor_x':  None,  # fake cursor X for sub-mode precision display
    'sub_fake_cursor_y':  None,  # fake cursor Y for sub-mode precision display
    'sub_strength_virtual_x': None,  # virtual strength cursor X (shift-slow)
    'sub_strength_virtual_y': None,  # virtual strength cursor Y (shift-slow)
    'sub_strength_hover_target': 'STRENGTH',
    'sub_edit_button':    'LMB',  # 'LMB' | 'RMB' — which button's settings are shown in STRENGTH sub-mode
    'sub_orig_strength':   None,  # brush strength captured when entering STRENGTH mode
    'sub_orig_alpha':      None,  # canvas alpha captured when entering STRENGTH mode
    'sub_orig_modifier':  None,  # modifier value captured when entering STRENGTH mode
    'sub_total_delta':    0.0,   # accumulated real mouse displacement for STRENGTH mode
    'sub_orig_color':     None,  # brush RGB tuple captured when entering COLOR_PICK mode
    'sub_orig_color_secondary': None,  # secondary RGB captured when entering COLOR_PICK mode
    'sub_color_target':   'PRIMARY',  # active COLOR_PICK target: PRIMARY | SECONDARY
    'sub_color_h':        None,  # H component kept across mousemoves to avoid re-deriving from RGB
    'sub_color_s':        None,  # S component kept to prevent saturation loss when V clamps
    'sub_color_v':        None,  # V component
    'sub_color_start_h':  None,  # COLOR_PICK H captured at target entry/toggle
    'sub_color_start_v':  None,  # COLOR_PICK V captured at target entry/toggle
    'sub_color_total_dx': 0.0,   # accumulated X displacement for absolute COLOR_PICK mapping
    'sub_color_total_dy': 0.0,   # accumulated Y displacement for absolute COLOR_PICK mapping
    'sub_start_screen_x': None,  # absolute screen X when entering sub-mode (for cursor warp)
    'sub_start_screen_y': None,  # absolute screen Y when entering sub-mode (for cursor warp)
    'sub_start_region_x': None,  # region X when entering sub-mode (for overlay drawing)
    'sub_start_region_y': None,  # region Y when entering sub-mode (for overlay drawing)
    # ---- hold-Ctrl eyedropper ------------------------------------------------
    'ctrl_pick_active':    False,
    'ctrl_hovered_color':  None,
    'ctrl_region_x':       None,
    'ctrl_region_y':       None,
    # ---- temporary Alt mode override -----------------------------------------
    'temp_alt_mode_active': False,
    'temp_alt_prev_mode':   None,
    # ---- temporary Shift mode override ---------------------------------------
    'temp_shift_mode_active': False,
    'temp_shift_prev_mode':   None,
    'outline_immediate':   False,
    # ---- outline position tween --------------------------------------------
    'outline_display_cx':  None,
    'outline_display_cy':  None,
    'outline_from_cx':     None,
    'outline_from_cy':     None,
    'outline_to_cx':       None,
    'outline_to_cy':       None,
    'outline_anim_start':  0.0,
    'outline_timer':       None,
    'current_tool_id':     None,
    'previous_tool_id':    None,
    'last_observed_raw_radius': None,
}

# ---------------------------------------------------------------------------
# Module-level undo stack for image pixels.
#
# Blender's built-in undo (bl_options UNDO / ed.undo_push) does NOT capture
# raw image.pixels — that lives in a separate C-level paint undo system with
# no Python API.  We maintain our own stack here at module level so it
# survives tool switches and operator instance teardown.
# ---------------------------------------------------------------------------

_undo_stack = []
_redo_stack = []
_MAX_UNDO   = 100

_core_runtime = PixelPainterCoreRuntime()
_tool_registry = ToolRegistry()
_menu_registry = MenuControllerRegistry()
_settings = PixelPainterSettingsService()
_sub_mode_controller = SubModeController(_state, _core_runtime, _settings)
_variable_store = build_default_variable_store()


def _is_shift_smooth_global(context):
    try:
        wm = context.window_manager
        return bool(wm.pixel_painter_mode == 'SMOOTH' and getattr(wm, 'pixel_painter_temp_smooth_force_global', False))
    except Exception:
        return False


def apply_active_tool_settings(context):
    """Load active tool settings (global/local aware) into runtime values."""
    mode = context.window_manager.pixel_painter_mode
    force_global = _is_shift_smooth_global(context)
    _settings.apply_tool_runtime_settings(context, mode, force_global=force_global)
    _sync_runtime_tool_info(context)


def _sync_external_brush_size_into_tool_setting(context):
    """Capture external brush-size edits (e.g. F key) into active tool/global-local setting."""
    mode = context.window_manager.pixel_painter_mode
    force_global = _is_shift_smooth_global(context)
    raw_radius = blender_utils.get_raw_brush_image_radius(context)
    prev = _state.get('last_observed_raw_radius')

    if prev is None:
        _state['last_observed_raw_radius'] = raw_radius
        return

    if raw_radius != prev:
        _settings.set_tool_size(context, mode, raw_radius, force_global=force_global)
        _state['last_observed_raw_radius'] = raw_radius


def _sync_runtime_tool_info(context):
    """Keep core runtime, state, and variable-store tool info in sync."""
    mode = context.window_manager.pixel_painter_mode
    force_global = _is_shift_smooth_global(context)
    _core_runtime.set_current_tool(mode)
    _state['current_tool_id'] = _core_runtime.current_tool_id
    _state['previous_tool_id'] = _core_runtime.previous_tool_id

    radius = _settings.get_tool_size(context, mode, force_global=force_global)
    modifier = _settings.get_tool_modifier(context, mode, force_global=force_global)
    falloff = (
        context.window_manager.pixel_painter_spray_falloff
        if mode == 'SPRAY'
        else context.window_manager.pixel_painter_circle_falloff
    )

    _variable_store.set_global('size', radius)
    _variable_store.set_global('modifier', modifier)
    _variable_store.set_global('falloff', falloff)
    _variable_store.set_tool_value(mode, 'size', radius)
    _variable_store.set_tool_value(mode, 'modifier', modifier)
    _variable_store.set_tool_value(mode, 'falloff', falloff)


def _undo_push(img):
    """Snapshot the current pixel state of *img* before a stroke begins.
    Clears the redo stack — a new action invalidates any undone history."""
    if len(_undo_stack) >= _MAX_UNDO:
        _undo_stack.pop(0)
    _undo_stack.append((img.name, np.array(img.pixels, dtype=np.float32)))
    _redo_stack.clear()


def _undo_pop(context):
    """Restore the previous pixel state, pushing current state onto redo stack."""
    if not _undo_stack:
        return False
    space = context.space_data
    if not space or not space.image:
        return False
    img = space.image
    name, pixels = _undo_stack[-1]
    if img.name != name:
        _undo_stack.clear()
        _redo_stack.clear()
        return False
    # Save current state to redo stack before overwriting
    _redo_stack.append((img.name, np.array(img.pixels, dtype=np.float32)))
    _undo_stack.pop()
    img.pixels.foreach_set(pixels)
    img.update()
    # Force refresh of all 3D Viewports and Image Editors
    try:
        for screen in bpy.data.screens:
            for area in screen.areas:
                if area.type in {'VIEW_3D', 'IMAGE_EDITOR'}:
                    area.tag_redraw()
    except Exception:
        pass
    return True


def _redo_pop(context):
    """Re-apply a previously undone pixel state."""
    if not _redo_stack:
        return False
    space = context.space_data
    if not space or not space.image:
        return False
    img = space.image
    name, pixels = _redo_stack[-1]
    if img.name != name:
        _redo_stack.clear()
        return False
    # Save current state to undo stack so the user can undo the redo
    _undo_stack.append((img.name, np.array(img.pixels, dtype=np.float32)))
    _redo_stack.pop()
    img.pixels.foreach_set(pixels)
    img.update()
    # Force refresh of all 3D Viewports and Image Editors
    try:
        for screen in bpy.data.screens:
            for area in screen.areas:
                if area.type in {'VIEW_3D', 'IMAGE_EDITOR'}:
                    area.tag_redraw()
    except Exception:
        pass
    return True


def _undo_clear():
    _undo_stack.clear()
    _redo_stack.clear()


# ---------------------------------------------------------------------------
# Draw handler helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Draw handler
# ---------------------------------------------------------------------------

def _register_draw_handler(space, context):
    def _callback(ctx):
        grid_opacity = ctx.window_manager.pixel_painter_grid_opacity
        draw_functions.draw_pixel_grid_overlay(ctx, grid_opacity)
        draw_functions.draw_test_tool_shape_outline(ctx, _state)
        draw_functions.draw_sub_mode_overlay(ctx, _state)
        draw_functions.draw_ctrl_pick_overlay(ctx, _state)
    draw_functions.register_draw_handler(_state, space, context, _callback)


def _interpolation_steps(cx, cy):
    """Bresenham walk from the last painted pixel to (cx, cy).

    The start pixel is excluded because it was already painted on the previous
    call — including it would double-stamp every position along a stroke.
    """
    px = _state['last_paint_cx']
    py = _state['last_paint_cy']
    if px is None or py is None or (px == cx and py == cy):
        return [(cx, cy)]
    steps = math_utils.get_line_pixels(px, py, cx, cy)
    return steps[1:]  # skip start pixel — already painted in the previous call


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class PixelPainterSetModeOperator(Operator):
    bl_idname = "image.pixel_painter_set_mode"
    bl_label  = "Set Pixel Painter Mode"

    mode: bpy.props.EnumProperty(
        items=[
            ('SQUARE',  "Square",  ""),
            ('CIRCLE',  "Circle",  ""),
            ('SPRAY',   "Spray",   ""),
            ('LINE',    "Line",    ""),
            ('SMOOTH',  "Smooth",  ""),
            ('SMEAR',   "Smear",   ""),
            ('ERASER',  "Eraser",  ""),
        ]
    )

    def execute(self, context):
        context.window_manager.pixel_painter_mode = self.mode
        if self.mode != 'LINE':
            _state['last_shape'] = self.mode
        apply_active_tool_settings(context)
        return {'FINISHED'}


class PixelPainterSetBlendOperator(Operator):
    bl_idname = "image.pixel_painter_set_blend"
    bl_label  = "Set Pixel Painter Blend Mode"

    blend: bpy.props.EnumProperty(
        items=[
            ('MIX',     "Normal",   "Normal blend"),
            ('ADD',     "Add",      "Add blend"),
            ('MUL',     "Multiply", "Multiply blend"),
            ('DARKEN',  "Darken",   "Darken blend"),
            ('LIGHTEN', "Lighten",  "Lighten blend"),
            ('SCREEN',    "Screen",     "Screen blend"),
            ('OVERLAY',   "Overlay",    "Overlay blend"),
            ('SOFTLIGHT', "Soft Light", "Soft Light blend"),
            ('HARDLIGHT', "Hard Light", "Hard Light blend"),
            ('SUB',       "Subtract",   "Subtract blend"),
            ('DIFFERENCE', "Difference", "Difference blend"),
            ('EXCLUSION',  "Exclusion",  "Exclusion blend"),
            ('COLORDODGE', "Color Dodge", "Color Dodge blend"),
            ('COLORBURN',  "Color Burn",  "Color Burn blend"),
            ('HUE',        "Hue",         "Hue blend"),
            ('SATURATION', "Saturation",  "Saturation blend"),
            ('VALUE',      "Value",       "Value blend"),
            ('LUMINOSITY', "Luminosity",  "Luminosity blend"),
            ('COLOR',   "Color",    "Color blend"),
        ]
    )

    def execute(self, context):
        try:
            brush = context.tool_settings.image_paint.brush
            if not brush:
                self.report({'WARNING'}, "No active image paint brush")
                return {'CANCELLED'}
            brush.blend = self.blend
            return {'FINISHED'}
        except Exception:
            self.report({'WARNING'}, "Could not set blend mode")
            return {'CANCELLED'}


class PixelPainterUndoOperator(Operator):
    """Undo the last Pixel Painter stroke."""
    bl_idname = "image.pixel_painter_undo"
    bl_label  = "Pixel Painter Undo"

    def execute(self, context):
        if not _undo_pop(context):
            self.report({'INFO'}, "Nothing to undo")
        return {'FINISHED'}


class PixelPainterRedoOperator(Operator):
    """Redo the last undone Pixel Painter stroke."""
    bl_idname = "image.pixel_painter_redo"
    bl_label  = "Pixel Painter Redo"

    def execute(self, context):
        if not _redo_pop(context):
            self.report({'INFO'}, "Nothing to redo")
        return {'FINISHED'}


class PixelPainterOperator(Operator):
    """Persistent modal operator for the Pixel Painter tool.

    Stays alive while the tool is active so the cursor outline is always
    updated.  Each LEFTMOUSE press snapshots the image pixels before
    painting begins, giving one independent undo step per stroke.
    """
    bl_idname  = "image.pixel_painter_operator"
    bl_label   = "Pixel Painter"
    bl_options = {'REGISTER'}

    # ---- helpers -------------------------------------------------------------

    def get_hovered_pixel(self, context, event):
        area = context.area
        if not area:
            return None
        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
        if not region:
            return None
        rx = event.mouse_x - region.x
        ry = event.mouse_y - region.y
        u, v = region.view2d.region_to_view(rx, ry)
        space = context.space_data
        if not space or not space.image:
            return None
        w, h = space.image.size
        if w == 0 or h == 0:
            return None
        return int(u * w), int(v * h), w, h, region.view2d

    def _get_brush_color(self, context):
        try:
            brush = context.tool_settings.image_paint.brush
            if not brush:
                return (1.0, 1.0, 1.0)
            return brush.secondary_color if _state['use_secondary'] else brush.color
        except Exception:
            return (1.0, 1.0, 1.0)

    def get_image_screen_bounds(self, context):
        area = context.area
        if not area or area.type not in {"IMAGE_EDITOR", "VIEW_3D"}:
            return None
        region = next((r for r in area.regions if r.type == "WINDOW"), None)
        if not region:
            return None
        space = context.space_data
        if not getattr(space, "image", None):
            return None
        w, h = space.image.size
        if w == 0 or h == 0:
            return None
        vd = region.view2d
        t = 0.1
        img_corners = [
            (0.0 - t, 0.0 - t),
            (1.0 + t, 0.0 - t),
            (1.0 + t, 1.0 + t),
            (0.0 - t, 1.0 + t),
        ]
        reg_corners = [vd.view_to_region(x, y, clip=False) for x, y in img_corners]
        xs, ys = zip(*reg_corners)
        xmin = max(min(xs), 0)
        ymin = max(min(ys), 0)
        xmax = min(max(xs), region.width)
        ymax = min(max(ys), region.height)
        return xmin, ymin, xmax, ymax, region, vd

    def _disable_builtin_brush_overlay(self, context):
        self._brush_overlay_restore = []
        try:
            image_paint = context.tool_settings.image_paint
        except Exception:
            image_paint = None

        brush = getattr(image_paint, 'brush', None) if image_paint else None
        if brush is not None:
            for attr in ('use_cursor_overlay', 'use_cursor_overlay_override'):
                if hasattr(brush, attr):
                    try:
                        self._brush_overlay_restore.append((brush, attr, getattr(brush, attr)))
                        setattr(brush, attr, False)
                    except Exception:
                        pass

        if image_paint is not None and hasattr(image_paint, 'show_brush'):
            try:
                self._brush_overlay_restore.append((image_paint, 'show_brush', getattr(image_paint, 'show_brush')))
                image_paint.show_brush = False
            except Exception:
                pass

    def _restore_builtin_brush_overlay(self):
        for owner, attr, value in getattr(self, '_brush_overlay_restore', []):
            try:
                setattr(owner, attr, value)
            except Exception:
                pass
        self._brush_overlay_restore = []

    def _set_modal_cursor(self, context):
        desired = 'NONE' if _state.get('sub_mode') in {'COLOR_PICK', 'STRENGTH'} else 'CROSSHAIR'
        if getattr(self, '_cursor_mode', None) == desired and getattr(self, '_cursor_is_custom', False):
            return
        self._cursor_is_custom = False
        try:
            context.window.cursor_modal_set(desired)
            self._cursor_is_custom = True
            self._cursor_mode = desired
        except Exception:
            pass

    def _restore_modal_cursor(self, context):
        if not getattr(self, '_cursor_is_custom', False):
            return
        try:
            context.window.cursor_modal_restore()
        except Exception:
            pass
        self._cursor_is_custom = False
        self._cursor_mode = None

    # ---- drawing -------------------------------------------------------------

    def draw_pixels(self, context):
        """Dispatch paint drawing to the active class-based tool implementation."""
        cx = _state['current_cx']
        cy = _state['current_cy']
        if cx is None:
            return
        space = context.space_data
        if not space or not space.image:
            return
        img = space.image
        w, h = img.size
        if w == 0 or h == 0:
            return

        mode    = context.window_manager.pixel_painter_mode
        force_global = _is_shift_smooth_global(context)
        button  = 'RMB' if _state.get('use_secondary') else 'LMB'

        # Special case: Shift+RightClick Eraser should always use Eraser tool's RMB settings
        if _state.get('temp_shift_mode_active') and mode == 'ERASER' and button == 'RMB':
            settings_mode = 'ERASER'
            settings_button = 'RMB'
        else:
            settings_mode = mode
            settings_button = button

        color   = self._get_brush_color(context)
        blend   = blender_utils.get_brush_blend_mode(context)
        strength = _settings.get_tool_strength(context, settings_mode, force_global=force_global, button=settings_button)
        modifier = _settings.get_tool_modifier(context, settings_mode, force_global=force_global, button=settings_button)
        alpha_opacity = _settings.get_tool_alpha(context, settings_mode, force_global=force_global, button=settings_button)
        radius  = _settings.get_tool_size(context, settings_mode, force_global=force_global)
        wm      = context.window_manager
        spacing = wm.pixel_painter_spacing
        # Apply button-specific modifier so tools that read wm.pixel_painter_modifier see the correct value.
        wm.pixel_painter_modifier = modifier
        env = DrawEnvironment(
            context=context,
            state=_state,
            img=img,
            mode=mode,
            color=color,
            blend=blend,
            opacity=strength,
            alpha_opacity=alpha_opacity,
            radius=radius,
            spacing=spacing,
            wm=wm,
            cursor_x=cx,
            cursor_y=cy,
            interpolation_steps=lambda: _interpolation_steps(cx, cy),
            curve_sampler_factory=_settings.get_falloff_curve_sampler,
        )

        # Prepare stroke caches on the first draw call of a stroke.
        _tool_registry.ensure_stroke_state(env)

        # Pixel spacing: skip if the cursor hasn't moved to a new pixel
        if (spacing == 'PIXEL'
            and mode not in {'LINE'}
            and cx == _state['last_paint_cx']
            and cy == _state['last_paint_cy']):
            return

        _tool_registry.draw_active_tool(env)

    # ---- lifecycle -----------------------------------------------------------

    def _cleanup(self):
        if _state['temp_alt_mode_active'] and _state['temp_alt_prev_mode'] is not None:
            try:
                bpy.context.window_manager.pixel_painter_mode = _state['temp_alt_prev_mode']
            except Exception:
                pass
        if _state['temp_shift_mode_active'] and _state['temp_shift_prev_mode'] is not None:
            try:
                bpy.context.window_manager.pixel_painter_mode = _state['temp_shift_prev_mode']
            except Exception:
                pass
        try:
            self._restore_modal_cursor(bpy.context)
        except Exception:
            pass
        try:
            bpy.context.window_manager.pixel_painter_temp_smooth_force_global = False
        except Exception:
            pass
        self._restore_builtin_brush_overlay()
        timer = _state.get('outline_timer')
        if timer is not None:
            try:
                bpy.context.window_manager.event_timer_remove(timer)
            except Exception:
                pass
            _state['outline_timer'] = None
        draw_functions.remove_draw_handler(_state)
        _state['running']          = False
        _state['current_cx']       = None
        _state['current_cy']       = None
        _state['start_position']   = None
        _state['back_buffer']      = None
        _state['last_paint_cx']       = None
        _state['last_paint_cy']       = None
        _state['stroke_painted']      = None
        _state['stroke_weight_map']   = None
        _state['stroke_back_buffer']  = None
        _state['use_secondary']       = False
        _state['sub_mode']           = None
        _state['sub_fake_cursor_x']  = None
        _state['sub_fake_cursor_y']  = None
        _state['sub_strength_virtual_x'] = None
        _state['sub_strength_virtual_y'] = None
        _state['sub_strength_hover_target'] = 'STRENGTH'
        _state['sub_orig_strength']   = None
        _state['sub_orig_alpha']      = None
        _state['sub_orig_modifier']  = None
        _state['sub_total_delta']    = 0.0
        _state['sub_orig_color']     = None
        _state['sub_orig_color_secondary'] = None
        _state['sub_color_target']   = 'PRIMARY'
        _state['sub_color_h']        = None
        _state['sub_color_s']        = None
        _state['sub_color_v']        = None
        _state['sub_color_start_h']  = None
        _state['sub_color_start_v']  = None
        _state['sub_color_total_dx'] = 0.0
        _state['sub_color_total_dy'] = 0.0
        _state['sub_start_screen_x'] = None
        _state['sub_start_screen_y'] = None
        _state['sub_start_region_x'] = None
        _state['sub_start_region_y'] = None
        _state['ctrl_pick_active']    = False
        _state['ctrl_hovered_color']  = None
        _state['ctrl_region_x']       = None
        _state['ctrl_region_y']       = None
        _state['temp_alt_mode_active'] = False
        _state['temp_alt_prev_mode']   = None
        _state['temp_shift_mode_active'] = False
        _state['temp_shift_prev_mode']   = None
        _state['outline_immediate']   = False
        _state['outline_display_cx']  = None
        _state['outline_display_cy']  = None
        _state['outline_from_cx']     = None
        _state['outline_from_cy']     = None
        _state['outline_to_cx']       = None
        _state['outline_to_cy']       = None
        _state['outline_anim_start']  = 0.0
        _state['current_tool_id']     = None
        _state['previous_tool_id']    = None
        _state['last_observed_raw_radius'] = None
        _sub_mode_controller.clear_processes()
        _core_runtime.clear_all_processes()
        self.button_down       = False
        self.button_right_down = False

    def modal(self, context, event):
        # Guard: exit if we've left the Image Editor
        if context.space_data is None or context.space_data.type != 'IMAGE_EDITOR':
            self._cleanup()
            return {'CANCELLED'}

        # Blender may reset modal cursor after certain transient tools
        # (e.g. brush size with F). Re-apply ours while this operator runs.
        self._set_modal_cursor(context)

        # Guard: stop if the user switched to a different tool
        from bl_ui.space_toolsystem_common import ToolSelectPanelHelper
        tool = ToolSelectPanelHelper.tool_active_from_context(context)
        if not tool or tool.idname != "image.pixel_painter_tool":
            self._cleanup()
            return {'CANCELLED'}

        _state['outline_immediate'] = self.button_down or self.button_right_down

        # Sync external brush size changes (e.g. F-key) and apply tool settings on EVERY event
        # so the outline updates in real-time during F-key resizing.
        _sync_external_brush_size_into_tool_setting(context)
        apply_active_tool_settings(context)

        if event.type == 'TIMER':
            if context.area:
                context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        area   = context.area
        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
        v2d    = region.view2d if region else None
        mode   = context.window_manager.pixel_painter_mode

        def _cancel_temp_shift_override_for_shortcut():
            """Exit temporary Shift->SMOOTH override before opening E/W shortcuts."""
            if not _state['temp_shift_mode_active']:
                return
            restore_mode = _state['temp_shift_prev_mode'] or 'SQUARE'
            context.window_manager.pixel_painter_mode = restore_mode
            _state['temp_shift_mode_active'] = False
            _state['temp_shift_prev_mode'] = None
            context.window_manager.pixel_painter_temp_smooth_force_global = False
            apply_active_tool_settings(context)

        # If the cursor has left the OS window, cancel any active stroke and
        # ignore all input until it returns.
        win_w = context.window.width
        win_h = context.window.height
        cursor_outside = not (0 <= event.mouse_x < win_w and 0 <= event.mouse_y < win_h)
        if cursor_outside:
            if self.button_down or self.button_right_down:
                if mode == 'LINE':
                    space = context.space_data
                    if space and space.image and _state['back_buffer'] is not None:
                        space.image.pixels.foreach_set(_state['back_buffer'])
                        space.image.update()
                    _state['start_position'] = None
                    _state['back_buffer']    = None
                _state['last_paint_cx'] = None
                _state['last_paint_cy'] = None
                _state['use_secondary'] = False
                self.button_down       = False
                self.button_right_down = False
            _state['current_cx']          = None
            _state['current_cy']          = None
            _state['ctrl_pick_active']    = False
            _state['ctrl_hovered_color']  = None
            context.area.tag_redraw()
            return {'PASS_THROUGH'}

        # Whether the cursor is currently over the image — used to gate key
        # commands so they only fire when the cursor is inside the image.
        # Reuse the same bounds logic that hides the brush outline.
        # Sub-modes are exempt: they grab mouse movement across the whole window.
        _bounds = self.get_image_screen_bounds(context)
        cursor_in_image = (
            _state['current_cx'] is not None or (
                _bounds is not None and
                _bounds[0] <= event.mouse_region_x <= _bounds[2] and
                _bounds[1] <= event.mouse_region_y <= _bounds[3]
            )
        )

        # ESC: stop the modal (or exit sub-mode first)
        if event.type == 'ESC':
            if _sub_mode_controller.has_active_mode():
                _sub_mode_controller.cancel_active_mode(context)
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}
            self._cleanup()
            return {'CANCELLED'}

        if _sub_mode_controller.handle_active_event(context, event):
            return {'RUNNING_MODAL'}

        # Block all non-movement commands when the cursor is outside the image.
        if event.type != 'MOUSEMOVE' and not cursor_in_image:
            return {'PASS_THROUGH'}

        # Mouse move: always update cursor; paint if either button is held
        if event.type == 'MOUSEMOVE':
            bounds = self.get_image_screen_bounds(context)
            if bounds:
                xmin, ymin, xmax, ymax = bounds[:4]
                if not (xmin <= event.mouse_region_x <= xmax and
                        ymin <= event.mouse_region_y <= ymax):
                    if self.button_down or self.button_right_down:
                        if mode == 'LINE':
                            space = context.space_data
                            if space and space.image and _state['back_buffer'] is not None:
                                space.image.pixels.foreach_set(_state['back_buffer'])
                                space.image.update()
                            _state['start_position'] = None
                            _state['back_buffer']    = None
                        _state['last_paint_cx'] = None
                        _state['last_paint_cy'] = None
                        _state['use_secondary'] = False
                        self.button_down        = False
                        self.button_right_down  = False
                    _state['current_cx']          = None
                    _state['current_cy']           = None
                    _state['ctrl_pick_active']    = False
                    _state['ctrl_hovered_color']  = None
                    context.area.tag_redraw()
                    return {'PASS_THROUGH'}

            result = self.get_hovered_pixel(context, event)
            if result:
                _state['current_cx'], _state['current_cy'] = result[0], result[1]
            else:
                _state['current_cx'] = _state['current_cy'] = None

            if _state['ctrl_pick_active'] and not self.button_down and not self.button_right_down:
                _state['ctrl_region_x'] = event.mouse_region_x
                _state['ctrl_region_y'] = event.mouse_region_y
                cx, cy = _state['current_cx'], _state['current_cy']
                _state['ctrl_hovered_color'] = (
                    _settings.get_image_pixel_color(context, cx, cy) if cx is not None else None)

            if (self.button_down or self.button_right_down) and v2d:
                self.draw_pixels(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Left mouse press: primary color stroke
        elif event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            active_mode = mode
            if event.shift and not event.ctrl and not event.alt:
                if not _state['temp_shift_mode_active']:
                    _state['temp_shift_prev_mode'] = context.window_manager.pixel_painter_mode
                    _state['temp_shift_mode_active'] = True
                context.window_manager.pixel_painter_temp_smooth_force_global = True
                context.window_manager.pixel_painter_mode = 'SMOOTH'
                apply_active_tool_settings(context)
                active_mode = 'SMOOTH'

            if event.ctrl or _state['ctrl_pick_active']:
                if _state['ctrl_hovered_color'] is None:
                    result = self.get_hovered_pixel(context, event)
                    if result:
                        _state['current_cx'], _state['current_cy'] = result[0], result[1]
                        _state['ctrl_hovered_color'] = _settings.get_image_pixel_color(
                            context, _state['current_cx'], _state['current_cy'])
                picked = _state['ctrl_hovered_color']
                if picked is None:
                    return {'RUNNING_MODAL'}
                _settings.set_brush_rgb(context, *picked)
                h, s, v = colorsys.rgb_to_hsv(*picked)
                _state['sub_color_h'] = h
                _state['sub_color_s'] = s
                _state['sub_color_v'] = v
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}

            self.button_down         = True
            _state['use_secondary']  = False
            _state['last_paint_cx']  = None
            _state['last_paint_cy']  = None
            space = context.space_data
            if space and space.image:
                _undo_push(space.image)
            result = self.get_hovered_pixel(context, event)
            if result:
                _state['current_cx'], _state['current_cy'] = result[0], result[1]
                context.area.tag_redraw()
            if active_mode == 'LINE':
                if space and space.image and _state['current_cx'] is not None:
                    _state['back_buffer']    = np.array(space.image.pixels, dtype=np.float32)
                    _state['start_position'] = (_state['current_cx'], _state['current_cy'])
            elif v2d:
                self.draw_pixels(context)
            return {'RUNNING_MODAL'}

        # Left mouse release
        elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            if self.button_down:
                if mode == 'LINE':
                    if _state['start_position'] is not None:
                        self.draw_pixels(context)
                    # Only switch back to previous tool if Line was activated via Alt and ALT is no longer pressed
                    if _state['temp_alt_mode_active'] and not event.alt:
                        context.window_manager.pixel_painter_mode = _state['last_shape']
                    _state['start_position'] = None
                    _state['back_buffer']    = None
            _state['last_paint_cx'] = None
            _state['last_paint_cy'] = None
            _state['use_secondary'] = False
            self.button_down = False
            _state['outline_immediate'] = False
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Right mouse press: secondary color stroke
        elif event.type == 'RIGHTMOUSE' and event.value == 'PRESS':
            active_mode = mode
            if event.shift and not event.ctrl and not event.alt:
                if not _state['temp_shift_mode_active']:
                    _state['temp_shift_prev_mode'] = context.window_manager.pixel_painter_mode
                    _state['temp_shift_mode_active'] = True
                context.window_manager.pixel_painter_mode = 'ERASER'
                apply_active_tool_settings(context)
                active_mode = 'ERASER'

            if event.ctrl or _state['ctrl_pick_active']:
                if _state['ctrl_hovered_color'] is None:
                    result = self.get_hovered_pixel(context, event)
                    if result:
                        _state['current_cx'], _state['current_cy'] = result[0], result[1]
                        _state['ctrl_hovered_color'] = _settings.get_image_pixel_color(
                            context, _state['current_cx'], _state['current_cy'])
                picked = _state['ctrl_hovered_color']
                if picked is None:
                    return {'RUNNING_MODAL'}
                _settings.set_brush_secondary_rgb(context, *picked)
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}

            self.button_right_down   = True
            _state['use_secondary']  = True
            _state['last_paint_cx']  = None
            _state['last_paint_cy']  = None
            space = context.space_data
            if space and space.image:
                _undo_push(space.image)
            result = self.get_hovered_pixel(context, event)
            if result:
                _state['current_cx'], _state['current_cy'] = result[0], result[1]
                context.area.tag_redraw()
            if active_mode == 'LINE':
                if space and space.image and _state['current_cx'] is not None:
                    _state['back_buffer']    = np.array(space.image.pixels, dtype=np.float32)
                    _state['start_position'] = (_state['current_cx'], _state['current_cy'])
            elif v2d:
                self.draw_pixels(context)
            return {'RUNNING_MODAL'}

        # Right mouse release
        elif event.type == 'RIGHTMOUSE' and event.value == 'RELEASE':
            if self.button_right_down:
                if mode == 'LINE':
                    if _state['start_position'] is not None:
                        self.draw_pixels(context)
                    # Only switch back to previous tool if Line was activated via Alt and ALT is no longer pressed
                    if _state['temp_alt_mode_active'] and not event.alt:
                        context.window_manager.pixel_painter_mode = _state['last_shape']
                    _state['start_position'] = None
                    _state['back_buffer']    = None
            _state['last_paint_cx'] = None
            _state['last_paint_cy'] = None
            _state['use_secondary'] = False
            self.button_right_down = False
            _state['outline_immediate'] = False
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Ctrl PRESS: activate the eyedropper while held.
        elif event.type in {'LEFT_CTRL', 'RIGHT_CTRL'} and event.value == 'PRESS':
            if self.button_down or self.button_right_down:
                if mode == 'LINE':
                    space = context.space_data
                    if space and space.image and _state['back_buffer'] is not None:
                        space.image.pixels.foreach_set(_state['back_buffer'])
                        space.image.update()
                    _state['start_position'] = None
                    _state['back_buffer']    = None
                _state['last_paint_cx'] = None
                _state['last_paint_cy'] = None
                _state['use_secondary'] = False
                self.button_down       = False
                self.button_right_down = False

            cx, cy = _state['current_cx'], _state['current_cy']
            _state['ctrl_pick_active']   = True
            _state['ctrl_region_x']      = event.mouse_region_x
            _state['ctrl_region_y']      = event.mouse_region_y
            _state['ctrl_hovered_color'] = (
                _settings.get_image_pixel_color(context, cx, cy) if cx is not None else None)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Ctrl RELEASE: clear the eyedropper overlay.
        elif event.type in {'LEFT_CTRL', 'RIGHT_CTRL'} and event.value == 'RELEASE':
            if event.ctrl:
                return {'RUNNING_MODAL'}

            _state['ctrl_pick_active']   = False
            _state['ctrl_hovered_color'] = None
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Alt PRESS: temporarily switch to Line while held.
        elif event.type in {'LEFT_ALT', 'RIGHT_ALT'} and event.value == 'PRESS':
            if not _state['temp_alt_mode_active']:
                _state['temp_alt_prev_mode'] = context.window_manager.pixel_painter_mode
                _state['temp_alt_mode_active'] = True
            context.window_manager.pixel_painter_mode = 'LINE'

            if self.button_down or self.button_right_down:
                if mode == 'LINE':
                    space = context.space_data
                    if space and space.image and _state['back_buffer'] is not None:
                        space.image.pixels.foreach_set(_state['back_buffer'])
                        space.image.update()
                    _state['start_position'] = None
                    _state['back_buffer']    = None
                _state['last_paint_cx'] = None
                _state['last_paint_cy'] = None
                _state['use_secondary'] = False
                self.button_down       = False
                self.button_right_down = False
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Shift PRESS: temporarily switch to Smooth while held.
        elif event.type in {'LEFT_SHIFT', 'RIGHT_SHIFT'} and event.value == 'PRESS':
            if not _state['temp_shift_mode_active']:
                _state['temp_shift_prev_mode'] = context.window_manager.pixel_painter_mode
                _state['temp_shift_mode_active'] = True
            context.window_manager.pixel_painter_temp_smooth_force_global = True
            context.window_manager.pixel_painter_mode = 'SMOOTH'
            apply_active_tool_settings(context)

            if self.button_down or self.button_right_down:
                if mode == 'LINE':
                    space = context.space_data
                    if space and space.image and _state['back_buffer'] is not None:
                        space.image.pixels.foreach_set(_state['back_buffer'])
                        space.image.update()
                    _state['start_position'] = None
                    _state['back_buffer']    = None
                _state['last_paint_cx'] = None
                _state['last_paint_cy'] = None
                _state['use_secondary'] = False
                self.button_down       = False
                self.button_right_down = False
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Shift RELEASE: restore the mode that was active before the override.
        elif event.type in {'LEFT_SHIFT', 'RIGHT_SHIFT'} and event.value == 'RELEASE':
            if event.shift:
                return {'RUNNING_MODAL'}

            if self.button_down or self.button_right_down:
                if mode == 'LINE':
                    space = context.space_data
                    if space and space.image and _state['back_buffer'] is not None:
                        space.image.pixels.foreach_set(_state['back_buffer'])
                        space.image.update()
                    _state['start_position'] = None
                    _state['back_buffer']    = None
                _state['last_paint_cx'] = None
                _state['last_paint_cy'] = None
                _state['use_secondary'] = False
                self.button_down       = False
                self.button_right_down = False

            if _state['temp_shift_mode_active']:
                restore_mode = _state['temp_shift_prev_mode'] or 'SQUARE'
                context.window_manager.pixel_painter_mode = restore_mode
                _state['temp_shift_mode_active'] = False
                _state['temp_shift_prev_mode'] = None
            context.window_manager.pixel_painter_temp_smooth_force_global = False
            apply_active_tool_settings(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Alt RELEASE: restore the mode that was active before the override.
        elif event.type in {'LEFT_ALT', 'RIGHT_ALT'} and event.value == 'RELEASE':
            if event.alt:
                return {'RUNNING_MODAL'}

            if self.button_down or self.button_right_down:
                if mode == 'LINE':
                    space = context.space_data
                    if space and space.image and _state['back_buffer'] is not None:
                        space.image.pixels.foreach_set(_state['back_buffer'])
                        space.image.update()
                    _state['start_position'] = None
                    _state['back_buffer']    = None
                _state['last_paint_cx'] = None
                _state['last_paint_cy'] = None
                _state['use_secondary'] = False
                self.button_down       = False
                self.button_right_down = False

            if _state['temp_alt_mode_active']:
                restore_mode = _state['temp_alt_prev_mode'] or 'SQUARE'
                context.window_manager.pixel_painter_mode = restore_mode
                _state['temp_alt_mode_active'] = False
                _state['temp_alt_prev_mode'] = None
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}


        # Shift+1 bis Shift+7: Toolwechsel nur für Nummerntasten (kein Pie, kein Submode)
        elif event.value == 'PRESS' and event.shift and not _sub_mode_controller.has_active_mode() and event.type in {'ONE','TWO','THREE','FOUR','FIVE','SIX','SEVEN'}:
            number_map = {
                'ONE': 'CIRCLE',
                'TWO': 'SQUARE',
                'THREE': 'SPRAY',
                'FOUR': 'SMOOTH',
                'FIVE': 'SMEAR',
                'SIX': 'LINE',
                'SEVEN': 'ERASER',
            }
            tool_id = number_map.get(event.type)
            if tool_id is not None:
                context.window_manager.pixel_painter_mode = tool_id
                apply_active_tool_settings(context)
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}

        # Shift+E: enter strength picker sub-mode
        elif event.type == 'E' and event.value == 'PRESS' and event.shift:
            _cancel_temp_shift_override_for_shortcut()
            if _sub_mode_controller.enter_strength_mode(context, event):
                context.area.tag_redraw()

        # E key: enter color picker sub-mode
        elif event.type == 'E' and event.value == 'PRESS' and not event.shift:
            _cancel_temp_shift_override_for_shortcut()
            if _sub_mode_controller.active_mode_name() == 'COLOR_PICK':
                return {'PASS_THROUGH'}
            if _sub_mode_controller.enter_color_pick_mode(context, event):
                context.area.tag_redraw()

        # W key: open pie menu; ensure temporary smooth override is cleared first.
        elif event.type == 'W' and event.value == 'PRESS':
            _cancel_temp_shift_override_for_shortcut()
            return {'PASS_THROUGH'}

        # Pie-Menüs auf J/K
        if event.type == 'J' and event.value == 'PRESS':
            print("[DEBUG] Shortcut J erkannt, versuche PIXELPAINTER_MT_mode_pie zu öffnen")
            try:
                import bpy
                bpy.ops.wm.call_menu(name="PIXELPAINTER_MT_mode_pie")
            except Exception as e:
                print(f"[DEBUG] Fehler beim Öffnen von PIXELPAINTER_MT_mode_pie: {e}")
            return {'RUNNING_MODAL'}
        if event.type == 'K' and event.value == 'PRESS':
            print("[DEBUG] Shortcut K erkannt, versuche PIXELPAINTER_MT_blend_pie zu öffnen")
            try:
                import bpy
                bpy.ops.wm.call_menu(name="PIXELPAINTER_MT_blend_pie")
            except Exception as e:
                print(f"[DEBUG] Fehler beim Öffnen von PIXELPAINTER_MT_blend_pie: {e}")
            return {'RUNNING_MODAL'}

        return {'PASS_THROUGH'}

    def invoke(self, context, event):  # event required by Blender operator API
        if context.space_data is None or context.space_data.type != 'IMAGE_EDITOR':
            return {'CANCELLED'}

        # Block re-invocation while the modal is already running.
        # (The tool keymap fires on every LMB press; without this guard a second
        # modal instance would start, resetting _state mid-stroke.)
        if _state['running']:
            return {'CANCELLED'}

        is_rmb = (event.type == 'RIGHTMOUSE')
        start_with_picker = event.ctrl
        start_with_shift_override = event.shift and not start_with_picker and not event.alt
        if event.alt and not start_with_picker and not _state['temp_alt_mode_active']:
            _state['temp_alt_prev_mode'] = context.window_manager.pixel_painter_mode
            _state['temp_alt_mode_active'] = True
            context.window_manager.pixel_painter_mode = 'LINE'
        if start_with_shift_override and not _state['temp_shift_mode_active']:
            _state['temp_shift_prev_mode'] = context.window_manager.pixel_painter_mode
            _state['temp_shift_mode_active'] = True
            context.window_manager.pixel_painter_temp_smooth_force_global = True
            context.window_manager.pixel_painter_mode = 'SMOOTH'

        apply_active_tool_settings(context)

        self.button_down       = (not is_rmb) and not start_with_picker
        self.button_right_down = is_rmb and not start_with_picker
        _state['outline_immediate'] = self.button_down or self.button_right_down
        self._set_modal_cursor(context)
        self._disable_builtin_brush_overlay(context)
        _state['running']        = True
        _state['use_secondary']  = self.button_right_down
        _state['current_cx']     = None
        _state['current_cy']     = None
        _state['start_position'] = None
        _state['back_buffer']    = None
        _state['last_paint_cx']  = None
        _state['last_paint_cy']  = None
        _state['outline_display_cx'] = None
        _state['outline_display_cy'] = None
        _state['outline_from_cx'] = None
        _state['outline_from_cy'] = None
        _state['outline_to_cx'] = None
        _state['outline_to_cy'] = None
        _state['outline_anim_start'] = time.perf_counter()
        _state['last_observed_raw_radius'] = blender_utils.get_raw_brush_image_radius(context)

        _state['ctrl_pick_active']   = start_with_picker
        _state['ctrl_hovered_color'] = None
        _state['ctrl_region_x']      = event.mouse_region_x
        _state['ctrl_region_y']      = event.mouse_region_y

        # Push undo for the FIRST stroke — the press that triggered invoke is
        # not re-delivered to the modal, so the modal PRESS handler won't fire.
        space = context.space_data
        if space and space.image and (self.button_down or self.button_right_down):
            _undo_push(space.image)

        # Paint the initial pixel under the cursor on press.
        mode   = context.window_manager.pixel_painter_mode
        result = self.get_hovered_pixel(context, event)
        if result:
            _state['current_cx'], _state['current_cy'] = result[0], result[1]
            if start_with_picker:
                _state['ctrl_hovered_color'] = _settings.get_image_pixel_color(
                    context, _state['current_cx'], _state['current_cy'])
                picked = _state['ctrl_hovered_color']
                if picked is not None:
                    if is_rmb:
                        _settings.set_brush_secondary_rgb(context, *picked)
                    else:
                        _settings.set_brush_rgb(context, *picked)
            elif mode == 'LINE':
                if space and space.image:
                    _state['back_buffer']    = np.array(space.image.pixels, dtype=np.float32)
                    _state['start_position'] = (_state['current_cx'], _state['current_cy'])
            elif self.button_down or self.button_right_down:
                self.draw_pixels(context)

        _register_draw_handler(context.space_data, context)
        _state['outline_timer'] = context.window_manager.event_timer_add(1.0 / 60.0, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}
