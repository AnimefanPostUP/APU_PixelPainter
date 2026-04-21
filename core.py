"""Operator classes and module-level tool state."""
import colorsys
import time

import bpy
import numpy as np
from bpy.types import Operator

from . import math_utils
from . import blender_utils
from . import draw_functions
from .core_runtime import PixelPainterCoreRuntime
from .menu_controllers import MenuControllerRegistry
from .settings_service import PixelPainterSettingsService
from .tool_logic import DrawEnvironment, ToolRegistry
from .variables import build_default_variable_store


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
    'sub_orig_strength':   None,  # brush strength captured when entering STRENGTH mode
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
_COLOR_PICK_H_DIV = 500.0
_COLOR_PICK_V_DIV = 300.0
_COLOR_PICK_SHIFT_FACTOR = 10.0

_core_runtime = PixelPainterCoreRuntime()
_tool_registry = ToolRegistry()
_menu_registry = MenuControllerRegistry()
_settings = PixelPainterSettingsService()
_variable_store = build_default_variable_store()


def _sync_runtime_tool_info(context):
    """Keep core runtime, state, and variable-store tool info in sync."""
    mode = context.window_manager.pixel_painter_mode
    _core_runtime.set_current_tool(mode)
    _state['current_tool_id'] = _core_runtime.current_tool_id
    _state['previous_tool_id'] = _core_runtime.previous_tool_id

    radius = blender_utils.get_brush_image_radius(context)
    modifier = context.window_manager.pixel_painter_modifier
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


def _register_sub_mode_process(mode_name):
    """Register the active sub-mode process so ESC can interrupt it."""
    owner = _state.get('current_tool_id') or 'UNKNOWN'
    _core_runtime.register_process(f"SUB_MODE:{mode_name}", owner, {'ESC'})


def _clear_sub_mode_process(mode_name=None):
    """Clear one or all registered sub-mode processes."""
    if mode_name is None:
        _core_runtime.clear_process('SUB_MODE:STRENGTH')
        _core_runtime.clear_process('SUB_MODE:COLOR_PICK')
        return
    _core_runtime.clear_process(f"SUB_MODE:{mode_name}")


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
    return True


def _undo_clear():
    _undo_stack.clear()
    _redo_stack.clear()


# ---------------------------------------------------------------------------
# Draw handler helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Sub-mode helpers  (strength / color-pick interactive modes)
# ---------------------------------------------------------------------------

def _warp_cursor_to_sub_start(context):
    """Warp the OS cursor back to where the sub-mode was entered."""
    sx = _state.get('sub_start_screen_x')
    sy = _state.get('sub_start_screen_y')
    if sx is not None and sy is not None:
        try:
            context.window.cursor_warp(sx, sy)
        except Exception:
            pass


def _set_sub_start_to_event(event):
    """Store sub-mode start at the cursor position when sub-mode was opened."""
    _state['sub_start_screen_x'] = event.mouse_x
    _state['sub_start_screen_y'] = event.mouse_y
    _state['sub_start_region_x'] = event.mouse_region_x
    _state['sub_start_region_y'] = event.mouse_region_y


def _warp_cursor_to_color_pick_hv(context, h, v):
    """Warp cursor to nearest position that represents HSV relative to center.
    The sub-mode start position is treated as (H,V)=(0.5,0.5)."""
    h = float(h) % 1.0
    v = max(0.0, min(1.0, float(v)))
    delta_h = h - 0.5
    if delta_h < -0.5:
        delta_h += 1.0
    elif delta_h >= 0.5:
        delta_h -= 1.0
    dx = delta_h * _COLOR_PICK_H_DIV
    dy = (v - 0.5) * _COLOR_PICK_V_DIV

    sx = _state.get('sub_start_screen_x')
    sy = _state.get('sub_start_screen_y')
    rx = _state.get('sub_start_region_x')
    ry = _state.get('sub_start_region_y')
    if sx is None or sy is None or rx is None or ry is None:
        return

    target_sx = int(round(sx + dx))
    target_sy = int(round(sy + dy))
    target_rx = int(round(rx + dx))
    target_ry = int(round(ry + dy))

    # Keep warps inside window bounds.
    try:
        max_x = max(0, int(context.window.width) - 1)
        max_y = max(0, int(context.window.height) - 1)
        clamped_sx = max(0, min(max_x, target_sx))
        clamped_sy = max(0, min(max_y, target_sy))
        # Apply the same clamp delta to region-space tracking.
        target_rx += (clamped_sx - target_sx)
        target_ry += (clamped_sy - target_sy)
        target_sx = clamped_sx
        target_sy = clamped_sy
    except Exception:
        pass

    try:
        context.window.cursor_warp(target_sx, target_sy)
    except Exception:
        pass

    _state['sub_last_x'] = target_rx
    _state['sub_last_y'] = target_ry
    _state['sub_color_total_dx'] = dx
    _state['sub_color_total_dy'] = dy


def _wrap_cursor_at_window_edge(context, event):
    """If the cursor is within the wrap margin of any window edge, loop it to the
    opposite side.  Updates sub_last_x/y so the next delta stays correct.
    The margin is 10% of the image's current on-screen width."""
    win_w  = context.window.width
    win_h  = context.window.height

    # Derive margin from 10% of the image's current screen width.
    margin = 12  # fallback in pixels
    try:
        area = context.area
        if area:
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            space  = context.space_data
            if region and space and getattr(space, 'image', None):
                vd = region.view2d
                x0, _ = vd.view_to_region(0.0, 0.0, clip=False)
                x1, _ = vd.view_to_region(1.0, 0.0, clip=False)
                margin = max(8, int(abs(x1 - x0) * 0.1))
    except Exception:
        pass
    mx, my = event.mouse_x, event.mouse_y

    new_mx = mx
    new_my = my

    if mx <= margin:
        new_mx = win_w - margin - 1
    elif mx >= win_w - margin:
        new_mx = margin + 1

    if my <= margin:
        new_my = win_h - margin - 1
    elif my >= win_h - margin:
        new_my = margin + 1

    if new_mx != mx or new_my != my:
        try:
            context.window.cursor_warp(new_mx, new_my)
        except Exception:
            pass
        # Shift the tracked position by the wrap delta so the next event's
        # delta reflects only real user movement, not the teleport jump.
        if new_mx != mx:
            _state['sub_last_x'] = event.mouse_region_x + (new_mx - mx)
        if new_my != my:
            _state['sub_last_y'] = event.mouse_region_y + (new_my - my)


# ---------------------------------------------------------------------------
# Draw handler
# ---------------------------------------------------------------------------

def _register_draw_handler(space, context):
    def _callback(ctx):
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
            ('ERASER',  "Eraser",  "Erase alpha by strength"),
        ]
    )

    def execute(self, context):
        context.window_manager.pixel_painter_mode = self.mode
        if self.mode != 'LINE':
            _state['last_shape'] = self.mode
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
        desired = 'NONE' if _state.get('sub_mode') == 'COLOR_PICK' else 'CROSSHAIR'
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
        color   = self._get_brush_color(context)
        blend   = blender_utils.get_brush_blend_mode(context)
        strength = blender_utils.get_brush_strength(context)
        radius  = blender_utils.get_brush_image_radius(context)
        wm      = context.window_manager
        spacing = wm.pixel_painter_spacing
        env = DrawEnvironment(
            context=context,
            state=_state,
            img=img,
            mode=mode,
            color=color,
            blend=blend,
            opacity=strength,
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
        _state['sub_orig_strength']   = None
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
        _clear_sub_mode_process()
        _core_runtime.clear_all_processes()
        self.button_down       = False
        self.button_right_down = False

    def modal(self, context, event):

        # Guard: exit if we've left the Image Editor
        if context.space_data is None or context.space_data.type != 'IMAGE_EDITOR':
            self._cleanup()
            return {'CANCELLED'}
        
        # Pie-Menüs auf J/K (jetzt als Operator)
        if event.type == 'J' and event.value == 'PRESS':
            print("[DEBUG] Shortcut J erkannt, versuche wm.pixel_painter_mode_pie_oo zu öffnen")
            try:
                bpy.ops.wm.pixel_painter_mode_pie_oo('INVOKE_DEFAULT')
            except Exception as e:
                print(f"[DEBUG] Fehler beim Öffnen von wm.pixel_painter_mode_pie_oo: {e}")
            return {'RUNNING_MODAL'}
        if event.type == 'K' and event.value == 'PRESS':
            print("[DEBUG] Shortcut K erkannt, versuche wm.pixel_painter_blend_pie_oo zu öffnen")
            try:
                bpy.ops.wm.pixel_painter_blend_pie_oo('INVOKE_DEFAULT')
            except Exception as e:
                print(f"[DEBUG] Fehler beim Öffnen von wm.pixel_painter_blend_pie_oo: {e}")
            return {'RUNNING_MODAL'}
        
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

        if event.type == 'TIMER':
            if context.area:
                context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        area   = context.area
        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
        v2d    = region.view2d if region else None
        mode   = context.window_manager.pixel_painter_mode
        _sync_runtime_tool_info(context)

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
            if _state['sub_mode'] is not None:
                # restore original values and leave sub-mode
                if _state['sub_mode'] == 'STRENGTH' and _state['sub_orig_strength'] is not None:
                    _settings.set_brush_strength(context, _state['sub_orig_strength'])
                elif _state['sub_mode'] == 'COLOR_PICK' and _state['sub_orig_color'] is not None:
                    _settings.set_brush_rgb(context, *_state['sub_orig_color'])
                    if _state['sub_orig_color_secondary'] is not None:
                        _settings.set_brush_secondary_rgb(context, *_state['sub_orig_color_secondary'])
                _state['sub_mode'] = None
                _clear_sub_mode_process()
                _warp_cursor_to_sub_start(context)
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}
            self._cleanup()
            return {'CANCELLED'}

        # ------------------------------------------------------------------ #
        # Sub-mode: R = strength picker, E = color picker                      #
        # While a sub-mode is active all events are consumed here; painting   #
        # is blocked until the sub-mode is exited.                            #
        # ------------------------------------------------------------------ #
        sub = _state['sub_mode']

        if sub == 'STRENGTH':
            if event.type == 'MOUSEMOVE':
                dx = event.mouse_region_x - _state['sub_last_x']
                dy = event.mouse_region_y - _state['sub_last_y']
                _state['sub_last_x'] = event.mouse_region_x
                _state['sub_last_y'] = event.mouse_region_y
                # Accumulate real user movement (wrap correction happens after, so
                # the teleport jump never enters sub_total_delta).
                _state['sub_total_delta'] += dx + dy
                divisor  = 3000.0 if event.shift else 300.0
                orig_op  = _state['sub_orig_strength'] or 0.0
                _settings.set_brush_strength(context, orig_op + _state['sub_total_delta'] / divisor)
                _wrap_cursor_at_window_edge(context, event)
                context.area.tag_redraw()
            elif event.type == 'WHEELUPMOUSE':
                step = 0.01 if event.shift else 0.05
                _settings.set_modifier(context, _settings.get_modifier(context) + step)
                context.area.tag_redraw()
            elif event.type == 'WHEELDOWNMOUSE':
                step = 0.01 if event.shift else 0.05
                _settings.set_modifier(context, _settings.get_modifier(context) - step)
                context.area.tag_redraw()
            elif event.type == 'LEFTMOUSE' and event.value == 'PRESS':
                _state['sub_mode'] = None          # keep new values
                _clear_sub_mode_process('STRENGTH')
                _warp_cursor_to_sub_start(context)
                context.area.tag_redraw()
            elif event.type == 'RIGHTMOUSE' and event.value == 'PRESS':
                _settings.set_brush_strength(context, _state['sub_orig_strength'])
                _settings.set_modifier(context, _state['sub_orig_modifier'])
                _state['sub_mode'] = None
                _clear_sub_mode_process('STRENGTH')
                _warp_cursor_to_sub_start(context)
                context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        if sub == 'COLOR_PICK':
            if event.type == 'MOUSEMOVE':
                dx = event.mouse_region_x - _state['sub_last_x']
                dy = event.mouse_region_y - _state['sub_last_y']
                _state['sub_last_x'] = event.mouse_region_x
                _state['sub_last_y'] = event.mouse_region_y
                sensitivity = _COLOR_PICK_SHIFT_FACTOR if event.shift else 1.0
                _state['sub_color_total_dx'] += dx / sensitivity
                _state['sub_color_total_dy'] += dy / sensitivity
                _state['sub_color_h'] = (0.5 + _state['sub_color_total_dx'] / _COLOR_PICK_H_DIV) % 1.0
                _state['sub_color_v'] = max(0.0, min(1.0, 0.5 + _state['sub_color_total_dy'] / _COLOR_PICK_V_DIV))
                rgb = colorsys.hsv_to_rgb(_state['sub_color_h'], _state['sub_color_s'], _state['sub_color_v'])
                if _state.get('sub_color_target') == 'SECONDARY':
                    _settings.set_brush_secondary_rgb(context, *rgb)
                else:
                    _settings.set_brush_rgb(context, *rgb)
                if event.shift:
                    _warp_cursor_to_color_pick_hv(context, _state['sub_color_h'], _state['sub_color_v'])
                _wrap_cursor_at_window_edge(context, event)
                context.area.tag_redraw()
            elif event.type in {'LEFT_SHIFT', 'RIGHT_SHIFT'} and event.value in {'PRESS', 'RELEASE'}:
                # Keep color stable when switching precision mode by remapping
                # cursor position to the current HSV under the new sensitivity.
                _warp_cursor_to_color_pick_hv(context, _state.get('sub_color_h') or 0.5,
                                              _state.get('sub_color_v') or 0.5)
                context.area.tag_redraw()
            elif event.type == 'WHEELUPMOUSE':
                step = 0.01 if event.shift else 0.05
                _state['sub_color_s'] = min(1.0, _state['sub_color_s'] + step)
                rgb = colorsys.hsv_to_rgb(_state['sub_color_h'], _state['sub_color_s'], _state['sub_color_v'])
                if _state.get('sub_color_target') == 'SECONDARY':
                    _settings.set_brush_secondary_rgb(context, *rgb)
                else:
                    _settings.set_brush_rgb(context, *rgb)
                if event.shift:
                    _warp_cursor_to_color_pick_hv(context, _state['sub_color_h'], _state['sub_color_v'])
                context.area.tag_redraw()
            elif event.type == 'WHEELDOWNMOUSE':
                step = 0.01 if event.shift else 0.05
                _state['sub_color_s'] = max(0.0, _state['sub_color_s'] - step)
                rgb = colorsys.hsv_to_rgb(_state['sub_color_h'], _state['sub_color_s'], _state['sub_color_v'])
                if _state.get('sub_color_target') == 'SECONDARY':
                    _settings.set_brush_secondary_rgb(context, *rgb)
                else:
                    _settings.set_brush_rgb(context, *rgb)
                if event.shift:
                    _warp_cursor_to_color_pick_hv(context, _state['sub_color_h'], _state['sub_color_v'])
                context.area.tag_redraw()
            elif event.type == 'E' and event.value == 'PRESS':
                if _state.get('sub_color_target') == 'SECONDARY':
                    if _state.get('sub_orig_color_secondary') is not None:
                        _settings.set_brush_secondary_rgb(context, *_state['sub_orig_color_secondary'])
                    _state['sub_color_target'] = 'PRIMARY'
                    rgb = _settings.get_brush_rgb(context)
                else:
                    if _state.get('sub_orig_color') is not None:
                        _settings.set_brush_rgb(context, *_state['sub_orig_color'])
                    _state['sub_color_target'] = 'SECONDARY'
                    rgb = _settings.get_brush_secondary_rgb(context)
                h_new, s_new, v_new = colorsys.rgb_to_hsv(*rgb)
                if s_new > 0.01:
                    _state['sub_color_h'] = h_new
                _state['sub_color_s'] = s_new
                _state['sub_color_v'] = v_new
                _state['sub_color_start_h'] = _state['sub_color_h']
                _state['sub_color_start_v'] = _state['sub_color_v']
                _warp_cursor_to_color_pick_hv(context, _state['sub_color_h'], _state['sub_color_v'])
                context.area.tag_redraw()
            elif event.type == 'LEFTMOUSE' and event.value == 'PRESS':
                _state['sub_mode'] = None          # keep new color
                _clear_sub_mode_process('COLOR_PICK')
                _warp_cursor_to_sub_start(context)
                context.area.tag_redraw()
            elif event.type == 'RIGHTMOUSE' and event.value == 'PRESS':
                _settings.set_brush_rgb(context, *_state['sub_orig_color'])
                if _state['sub_orig_color_secondary'] is not None:
                    _settings.set_brush_secondary_rgb(context, *_state['sub_orig_color_secondary'])
                _state['sub_mode'] = None
                _clear_sub_mode_process('COLOR_PICK')
                _warp_cursor_to_sub_start(context)
                context.area.tag_redraw()
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
                context.window_manager.pixel_painter_mode = 'SMOOTH'
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
                    if not _state['temp_alt_mode_active']:
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

        # Right mouse press: Eraser (unless Shift for Smooth)
        elif event.type == 'RIGHTMOUSE' and event.value == 'PRESS':
            if event.shift and not event.ctrl and not event.alt:
                # Shift+RMB = Smooth
                if not _state['temp_shift_mode_active']:
                    _state['temp_shift_prev_mode'] = context.window_manager.pixel_painter_mode
                    _state['temp_shift_mode_active'] = True
                context.window_manager.pixel_painter_mode = 'SMOOTH'
                active_mode = 'SMOOTH'
            else:
                # RMB = Eraser
                _state['prev_mode_before_eraser'] = context.window_manager.pixel_painter_mode
                context.window_manager.pixel_painter_mode = 'ERASER'
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
                    if not _state['temp_alt_mode_active']:
                        context.window_manager.pixel_painter_mode = _state['last_shape']
                    _state['start_position'] = None
                    _state['back_buffer']    = None
                # Restore previous mode if we switched to Eraser
                if getattr(_state, 'prev_mode_before_eraser', None) is not None and context.window_manager.pixel_painter_mode == 'ERASER':
                    context.window_manager.pixel_painter_mode = _state['prev_mode_before_eraser']
                    _state['prev_mode_before_eraser'] = None
            _state['last_paint_cx'] = None
            _state['last_paint_cy'] = None
            _state['use_secondary'] = False
            self.button_right_down = False
            _state['outline_immediate'] = False
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        # Number keys: quick tool switching
        elif event.type in {'ONE','TWO','THREE','FOUR','FIVE','SIX','SEVEN','EIGHT','NINE'} and event.value == 'PRESS':
            tool_map = {
                'ONE': 'SQUARE',
                'TWO': 'CIRCLE',
                'THREE': 'SPRAY',
                'FOUR': 'LINE',
                'FIVE': 'SMOOTH',
                'SIX': 'SMEAR',
                'SEVEN': 'ERASER',
                # Add more if you add more tools
            }
            tool_id = tool_map.get(event.type)
            if tool_id:
                context.window_manager.pixel_painter_mode = tool_id
                _sync_runtime_tool_info(context)
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
            context.window_manager.pixel_painter_mode = 'SMOOTH'

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

        # R key: enter opacity picker sub-mode
        elif event.type == 'R' and event.value == 'PRESS':
            _state['sub_mode']           = 'OPACITY'
            _state['sub_last_x']         = event.mouse_region_x
            _state['sub_last_y']         = event.mouse_region_y
            _state['sub_orig_opacity']   = _settings.get_brush_opacity(context)
            _state['sub_orig_modifier']  = _settings.get_modifier(context)
            _state['sub_total_delta']    = 0.0
            _state['sub_start_screen_x'] = event.mouse_x
            _state['sub_start_screen_y'] = event.mouse_y
            _state['sub_start_region_x'] = event.mouse_region_x
            _state['sub_start_region_y'] = event.mouse_region_y
            _register_sub_mode_process('OPACITY')
            context.area.tag_redraw()

        # E key: enter color picker sub-mode
        elif event.type == 'E' and event.value == 'PRESS':
            if _state['sub_mode'] == 'COLOR_PICK':
                return {'PASS_THROUGH'}

            rgb = _settings.get_brush_rgb(context)
            sec_rgb = _settings.get_brush_secondary_rgb(context)
            h_new, s_new, v_new = colorsys.rgb_to_hsv(*rgb)
            if _state['sub_color_s'] is None:
                # First entry: derive all three from brush
                _state['sub_color_h'] = h_new
                _state['sub_color_s'] = s_new
                _state['sub_color_v'] = v_new
            else:
                # Re-entry: keep stored S (and H if current color is near-achromatic)
                if s_new > 0.01:
                    _state['sub_color_h'] = h_new
                _state['sub_color_v'] = v_new
                # sub_color_s is intentionally left unchanged
            _state['sub_mode']           = 'COLOR_PICK'
            _state['sub_color_target']   = 'PRIMARY'
            _state['sub_orig_color']     = rgb
            _state['sub_orig_color_secondary'] = sec_rgb
            _state['sub_color_start_h']  = _state['sub_color_h']
            _state['sub_color_start_v']  = _state['sub_color_v']
            _set_sub_start_to_event(event)
            _warp_cursor_to_color_pick_hv(context, _state['sub_color_h'], _state['sub_color_v'])
            _register_sub_mode_process('COLOR_PICK')
            context.area.tag_redraw()

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
            context.window_manager.pixel_painter_mode = 'SMOOTH'

        _sync_runtime_tool_info(context)

        self.button_down       = (not is_rmb) and not start_with_picker and not start_with_shift_override
        self.button_right_down = is_rmb and not start_with_picker and not start_with_shift_override
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
