"""Operator classes and module-level tool state."""
import colorsys
import time
from dataclasses import dataclass

import bpy
import gpu
import numpy as np
from bpy.types import Operator

from ..utils import math_utils
from ..utils import blender_utils
from ..tools import draw_blending
from ..tools import draw_functions
from ..tools import draw_gridoverlay
from ..tools import overlays
from ..tools import overlays_selectmode
from .core_runtime import PixelPainterCoreRuntime
from ..utils.settings_service import PixelPainterSettingsService
from ..tools import blend_modes
from ..tools.base import DrawEnvironment
from ..tools.catalog import TOOLS, falloff_property_for
from .variables import build_default_variable_store
from ..ui.kit.events import number_key_index
from ..ui.selection_actions import SelectionActions
from .submodes.controller import SubModeController
from .submodes import selector


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
    'selection_box':       None,
    'selection_hover_handle': None,
    'selection_active_handle': None,
    'selection_drag_mode': None,
    'selection_drag_start': None,
    'selection_drag_origin_box': None,
    'selection_move_pixels': None,
    'selection_move_source_box': None,
    'selection_clipboard':  None,
    'selection_pending_action': None,
    'selection_pending_region': None,
    'selection_pending_source_box': None,
    'selection_preview_image_name': None,
    'selection_preview_texture': None,
    'selection_overlay_region': None,
    'selection_stencil_mode': False,
    'selection_stencil_region': None,
    'selection_stencil_restore_box': None,
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
_settings = PixelPainterSettingsService()
_sub_mode_controller = SubModeController(_state, _core_runtime, _settings)
_selection_actions = SelectionActions(_state)
_variable_store = build_default_variable_store()


@dataclass
class ModalEventContext:
    area: object
    region: object
    v2d: object
    mode: str
    cursor_in_image: bool


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
    falloff = getattr(context.window_manager, falloff_property_for(mode))

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
        draw_gridoverlay.draw_pixel_grid_overlay(ctx, grid_opacity)
        draw_functions.draw_test_tool_shape_outline(ctx, _state)
        overlays_selectmode.draw_selection_overlay(ctx, _state, _selection_actions)
        draw_functions.draw_test_corner_label(ctx)
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


def _tag_image_editors_redraw():
    try:
        for screen in bpy.data.screens:
            for area in screen.areas:
                if area.type in {'VIEW_3D', 'IMAGE_EDITOR'}:
                    area.tag_redraw()
    except Exception:
        pass


def _selection_set_preview(region):
    selector._selection_set_preview(_state, region)


def _selection_clear_pending_preview():
    selector._selection_clear_pending_preview(_state)


def _selection_apply_pending(context):
    return selector._selection_apply_pending(
        context,
        _state,
        _undo_push,
        _undo_stack,
        PixelPainterOperator._selection_blit_region_static,
    )


def _selection_clear_like_rmb(keep_clipboard=True):
    selector._selection_clear_like_rmb(_state, keep_clipboard=keep_clipboard)


def _selection_cancel_pending(context):
    _selection_clear_like_rmb(keep_clipboard=True)
    if context.area:
        context.area.tag_redraw()


def _selection_toggle_stencil_mode(context):
    return selector._selection_toggle_stencil_mode(
        context,
        _state,
        PixelPainterOperator._selection_extract_region,
    )


def _selection_update_paste_preview_position(context, cx, cy):
    return selector._selection_update_paste_preview_position(context, _state, cx, cy)


def _selection_center_box_for_region(region, cx, cy):
    return selector._selection_center_box_for_region(region, cx, cy)


def _selection_center_box_like_box(box, cx, cy):
    return selector._selection_center_box_like_box(box, cx, cy)


def _selection_box_center(box):
    return selector._selection_box_center(box)


def _selection_apply_stencil(context):
    return selector._selection_apply_stencil(
        context,
        _state,
        _undo_push,
        _undo_stack,
        PixelPainterOperator._selection_blit_region_static,
    )


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

def set_active_tool(context, tool_id):
    """Switch the active tool (used by the operator, pies and shortcuts)."""
    context.window_manager.pixel_painter_mode = tool_id
    if TOOLS.get(tool_id).usable_as_line_tip:
        _state['last_shape'] = tool_id
    apply_active_tool_settings(context)


class PixelPainterSetModeOperator(Operator):
    bl_idname = "image.pixel_painter_set_mode"
    bl_label  = "Set Pixel Painter Mode"

    mode: bpy.props.EnumProperty(items=TOOLS.enum_items())

    def execute(self, context):
        set_active_tool(context, self.mode)
        return {'FINISHED'}


class PixelPainterResetToolSettingsOperator(Operator):
    """Reset all Pixel Painter tool settings to their default values."""
    bl_idname = "image.pixel_painter_reset_tool_settings"
    bl_label = "Reset Tool Settings"

    def execute(self, context):
        from .. import properties
        properties.reset_tool_settings(context.window_manager)
        self.report({'INFO'}, "Pixel Painter tool settings reset to defaults.")
        return {'FINISHED'}


class PixelPainterSetBlendOperator(Operator):
    bl_idname = "image.pixel_painter_set_blend"
    bl_label  = "Set Pixel Painter Blend Mode"

    blend: bpy.props.EnumProperty(items=blend_modes.enum_items())

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


class PixelPainterSelectionApplyOperator(Operator):
    bl_idname = "image.pixel_painter_selection_apply"
    bl_label = "Apply Selection Preview"

    def execute(self, context):
        if not _selection_apply_pending(context):
            self.report({'INFO'}, "No pending selection preview to apply")
            return {'CANCELLED'}
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


class PixelPainterSelectionCopyOperator(Operator):
    bl_idname = "image.pixel_painter_selection_copy"
    bl_label = "Copy Selection"

    def execute(self, context):
        selection_box = _state.get('selection_box')
        space = context.space_data
        if selection_box is None or not space or not space.image:
            return {'CANCELLED'}
        _state['selection_clipboard'] = PixelPainterOperator._selection_extract_region(space.image, selection_box)
        center = _selection_box_center(selection_box)
        if _state['selection_clipboard'] is not None and center is not None:
            centered = _selection_center_box_for_region(_state['selection_clipboard'], center[0], center[1])
            if centered is not None:
                _state['selection_pending_source_box'] = selection_box
                _state['selection_box'] = centered
                _state['selection_pending_action'] = 'PASTE'
                _state['selection_pending_region'] = _state['selection_clipboard'].copy()
                _selection_set_preview(_state['selection_clipboard'])
                _state['selection_hover_handle'] = None
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


class PixelPainterSelectionCancelOperator(Operator):
    bl_idname = "image.pixel_painter_selection_cancel"
    bl_label = "Cancel Selection Preview"

    def execute(self, context):
        _selection_cancel_pending(context)
        return {'FINISHED'}


class PixelPainterSelectionStencilToggleOperator(Operator):
    bl_idname = "image.pixel_painter_selection_stencil_toggle"
    bl_label = "Toggle Selection Stencil Mode"

    def execute(self, context):
        if not _selection_toggle_stencil_mode(context):
            self.report({'WARNING'}, "No selection source available for stencil mode")
            return {'CANCELLED'}
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
        mode = context.window_manager.pixel_painter_mode
        desired = 'CROSSHAIR'
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

    @staticmethod
    def _selection_normalize_box(x0, y0, x1, y1):
        return (min(int(x0), int(x1)), min(int(y0), int(y1)), max(int(x0), int(x1)), max(int(y0), int(y1)))

    @staticmethod
    def _selection_pick_handle(box, px, py, tolerance=1):
        if not box or px is None or py is None:
            return None
        left, bottom, right, top = box
        near_left = abs(px - left) <= tolerance
        near_right = abs(px - right) <= tolerance
        near_bottom = abs(py - bottom) <= tolerance
        near_top = abs(py - top) <= tolerance
        within_x = left <= px <= right
        within_y = bottom <= py <= top

        if near_left and near_top:
            return 'NW'
        if near_right and near_top:
            return 'NE'
        if near_right and near_bottom:
            return 'SE'
        if near_left and near_bottom:
            return 'SW'
        if near_top and within_x:
            return 'N'
        if near_right and within_y:
            return 'E'
        if near_bottom and within_x:
            return 'S'
        if near_left and within_y:
            return 'W'
        if within_x and within_y:
            return 'MOVE'
        return None

    @staticmethod
    def _selection_resize_box(box, handle, px, py):
        left, bottom, right, top = box
        if 'W' in handle:
            left = min(int(px), right)
        if 'E' in handle:
            right = max(int(px), left)
        if 'S' in handle:
            bottom = min(int(py), top)
        if 'N' in handle:
            top = max(int(py), bottom)
        return left, bottom, right, top

    @staticmethod
    def _selection_resize_box_mirrored(box, handle, px, py):
        left, bottom, right, top = box
        center_x = (left + right) * 0.5
        center_y = (bottom + top) * 0.5

        if 'W' in handle or 'E' in handle:
            half_width = abs(float(px) - center_x)
            left = int(round(center_x - half_width))
            right = int(round(center_x + half_width))

        if 'S' in handle or 'N' in handle:
            half_height = abs(float(py) - center_y)
            bottom = int(round(center_y - half_height))
            top = int(round(center_y + half_height))

        return left, bottom, right, top

    @staticmethod
    def _selection_extract_region(img, box):
        if img is None or box is None:
            return None
        width, height = img.size
        left = max(0, min(width - 1, int(box[0])))
        bottom = max(0, min(height - 1, int(box[1])))
        right = max(0, min(width - 1, int(box[2])))
        top = max(0, min(height - 1, int(box[3])))
        if right < left or top < bottom:
            return None
        arr = np.array(img.pixels, dtype=np.float32).reshape(height, width, 4)
        return arr[bottom:top + 1, left:right + 1, :].copy()

    @staticmethod
    def _selection_write_image(img, arr):
        img.pixels.foreach_set(arr.ravel())
        img.update()
        _tag_image_editors_redraw()

    @staticmethod
    def _selection_blit_region_static(img, region, dest_left, dest_bottom, dest_box=None, clear_box=None, blend='MIX', opacity=1.0):
        if img is None or region is None:
            return None
        width, height = img.size
        region_h, region_w = region.shape[:2]
        if region_w == 0 or region_h == 0:
            return None

        arr = np.array(img.pixels, dtype=np.float32).reshape(height, width, 4)
        if clear_box is not None:
            src_left = max(0, min(width - 1, int(clear_box[0])))
            src_bottom = max(0, min(height - 1, int(clear_box[1])))
            src_right = max(0, min(width - 1, int(clear_box[2])))
            src_top = max(0, min(height - 1, int(clear_box[3])))
            if src_right >= src_left and src_top >= src_bottom:
                arr[src_bottom:src_top + 1, src_left:src_right + 1, :] = 0.0

        dest_left = int(dest_left)
        dest_bottom = int(dest_bottom)
        if dest_box is None:
            dest_right = dest_left + region_w - 1
            dest_top = dest_bottom + region_h - 1
        else:
            dest_right = int(dest_box[2])
            dest_top = int(dest_box[3])
        clip_left = max(0, dest_left)
        clip_bottom = max(0, dest_bottom)
        clip_right = min(width - 1, dest_right)
        clip_top = min(height - 1, dest_top)
        if clip_right < clip_left or clip_top < clip_bottom:
            return None

        dest_width = max(1, dest_right - dest_left + 1)
        dest_height = max(1, dest_top - dest_bottom + 1)
        for y in range(clip_bottom, clip_top + 1):
            dest_y = y - dest_bottom
            src_y = int(round((dest_y / max(1, dest_height - 1)) * max(0, region_h - 1))) if dest_height > 1 else 0
            src_y = max(0, min(region_h - 1, src_y))
            for x in range(clip_left, clip_right + 1):
                dest_x = x - dest_left
                src_x = int(round((dest_x / max(1, dest_width - 1)) * max(0, region_w - 1))) if dest_width > 1 else 0
                src_x = max(0, min(region_w - 1, src_x))
                blended = draw_blending.blend_region_pixels(
                    arr[y:y + 1, x:x + 1, :],
                    region[src_y:src_y + 1, src_x:src_x + 1, :],
                    blend,
                    opacity,
                )
                arr[y, x, :] = blended[0, 0, :]
        PixelPainterOperator._selection_write_image(img, arr)
        return clip_left, clip_bottom, clip_right, clip_top

    def _selection_blit_region(self, img, region, dest_left, dest_bottom, clear_box=None):
        return self._selection_blit_region_static(img, region, dest_left, dest_bottom, clear_box=clear_box)

    def _selection_clear(self, keep_clipboard=True):
        _selection_clear_like_rmb(keep_clipboard=keep_clipboard)

    def _selection_update_hover(self):
        if _state['selection_drag_mode'] or _state.get('selection_stencil_mode'):
            return
        _state['selection_hover_handle'] = self._selection_pick_handle(
            _state.get('selection_box'),
            _state.get('current_cx'),
            _state.get('current_cy'),
        )

    def _selection_update_stencil_box(self):
        if not _state.get('selection_stencil_mode'):
            return
        cx = _state.get('current_cx')
        cy = _state.get('current_cy')
        centered = _selection_center_box_like_box(_state.get('selection_box'), cx, cy)
        if centered is not None:
            _state['selection_box'] = centered

    def _selection_update_paste_preview(self, context):
        if _state.get('selection_pending_action') != 'PASTE':
            return
        _selection_update_paste_preview_position(context, _state.get('current_cx'), _state.get('current_cy'))

    def _selection_update_drag(self):
        box = _state.get('selection_drag_origin_box')
        start = _state.get('selection_drag_start')
        cx = _state.get('current_cx')
        cy = _state.get('current_cy')
        drag_mode = _state.get('selection_drag_mode')
        if start is None or cx is None or cy is None or drag_mode is None:
            return

        if drag_mode == 'CREATE':
            _state['selection_box'] = self._selection_normalize_box(start[0], start[1], cx, cy)
        elif drag_mode == 'MOVE' and box is not None:
            dx = int(cx - start[0])
            dy = int(cy - start[1])
            _state['selection_box'] = (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy)
        elif drag_mode == 'RESIZE' and box is not None:
            handle = _state.get('selection_active_handle', '')
            if self._selection_should_mirror_resize():
                _state['selection_box'] = self._selection_resize_box_mirrored(box, handle, cx, cy)
            else:
                _state['selection_box'] = self._selection_resize_box(box, handle, cx, cy)

    def _selection_should_mirror_resize(self):
        return bool(getattr(self, '_selection_resize_shift_held', False))

    def _selection_begin_left_press(self, context):
        cx = _state.get('current_cx')
        cy = _state.get('current_cy')
        if cx is None or cy is None:
            return {'RUNNING_MODAL'}

        selection_box = _state.get('selection_box')
        interaction = self._selection_pick_handle(selection_box, cx, cy)
        self.button_down = True

        if interaction == 'MOVE' and selection_box is not None:
            _state['selection_drag_mode'] = 'MOVE'
            _state['selection_active_handle'] = 'MOVE'
            _state['selection_drag_start'] = (cx, cy)
            _state['selection_drag_origin_box'] = selection_box
            if _state.get('selection_pending_action') is not None and _state.get('selection_pending_region') is not None:
                _state['selection_move_pixels'] = _state['selection_pending_region'].copy()
                _state['selection_move_source_box'] = selection_box
            else:
                _selection_clear_pending_preview()
                _state['selection_move_pixels'] = None
                _state['selection_move_source_box'] = None
        elif interaction is not None and selection_box is not None:
            _state['selection_drag_mode'] = 'RESIZE'
            _state['selection_active_handle'] = interaction
            _state['selection_drag_start'] = (cx, cy)
            _state['selection_drag_origin_box'] = selection_box
        else:
            _selection_clear_pending_preview()
            _state['selection_drag_mode'] = 'CREATE'
            _state['selection_active_handle'] = None
            _state['selection_drag_start'] = (cx, cy)
            _state['selection_drag_origin_box'] = None
            _state['selection_box'] = (cx, cy, cx, cy)

        self._selection_update_hover()
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def _selection_finish_left_release(self, context):
        drag_mode = _state.get('selection_drag_mode')
        if drag_mode in {'MOVE', 'RESIZE', 'CREATE'} and _state.get('selection_pending_action') is None:
            region = _state.get('selection_move_pixels')
            source_box = _state.get('selection_move_source_box')
            dest_box = _state.get('selection_box')
            if drag_mode == 'MOVE' and region is not None and source_box is not None and dest_box is not None and dest_box != source_box:
                _state['selection_pending_action'] = 'MOVE'
                _state['selection_pending_region'] = region.copy()
                _state['selection_pending_source_box'] = source_box
                _selection_set_preview(region)
            elif drag_mode == 'MOVE':
                _selection_clear_pending_preview()
        self.button_down = False
        _state['selection_drag_mode'] = None
        _state['selection_drag_start'] = None
        _state['selection_drag_origin_box'] = None
        _state['selection_move_pixels'] = None
        _state['selection_move_source_box'] = None
        _state['selection_active_handle'] = None
        self._selection_update_hover()
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def _selection_copy(self, context):
        selection_box = _state.get('selection_box')
        space = context.space_data
        if selection_box is None or not space or not space.image:
            return {'RUNNING_MODAL'}
        _state['selection_clipboard'] = self._selection_extract_region(space.image, selection_box)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def _selection_copy_and_preview(self, context):
        selection_box = _state.get('selection_box')
        result = self._selection_copy(context)
        clipboard = _state.get('selection_clipboard')
        center = _selection_box_center(selection_box)
        if clipboard is None or center is None:
            return result
        centered = _selection_center_box_for_region(clipboard, center[0], center[1])
        if centered is None:
            return result
        _state['selection_pending_source_box'] = selection_box
        _state['selection_box'] = centered
        _state['selection_pending_action'] = 'PASTE'
        _state['selection_pending_region'] = clipboard.copy()
        _selection_set_preview(clipboard)
        _state['selection_hover_handle'] = None
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def _selection_paste(self, context):
        clipboard = _state.get('selection_clipboard')
        cx = _state.get('current_cx')
        cy = _state.get('current_cy')
        source_box = _state.get('selection_box')
        anchor_center = _selection_box_center(source_box)
        if clipboard is None:
            return {'RUNNING_MODAL'}
        if anchor_center is None:
            if cx is None or cy is None:
                return {'RUNNING_MODAL'}
            anchor_center = (cx, cy)
        centered = _selection_center_box_for_region(clipboard, anchor_center[0], anchor_center[1])
        if centered is None:
            return {'RUNNING_MODAL'}
        _state['selection_pending_source_box'] = source_box
        _state['selection_box'] = centered
        _state['selection_pending_action'] = 'PASTE'
        _state['selection_pending_region'] = clipboard.copy()
        _selection_set_preview(clipboard)
        _state['selection_hover_handle'] = None
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

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
            protect_transparent=getattr(wm, 'pixel_painter_protect_transparent', False),
            radius=radius,
            spacing=spacing,
            wm=wm,
            cursor_x=cx,
            cursor_y=cy,
            interpolation_steps=lambda: _interpolation_steps(cx, cy),
            curve_sampler_factory=_settings.get_falloff_curve_sampler,
        )

        tool = TOOLS.get(mode)

        # First draw call of a stroke: let the tool prepare its caches.
        if _state['last_paint_cx'] is None:
            tool.on_stroke_begin(env)

        # Pixel spacing: skip if the cursor hasn't moved to a new pixel
        if (spacing == 'PIXEL'
            and tool.respects_pixel_spacing
            and cx == _state['last_paint_cx']
            and cy == _state['last_paint_cy']):
            return

        tool.on_draw(env)

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
        _state['selection_box']       = None
        _state['selection_hover_handle'] = None
        _state['selection_active_handle'] = None
        _state['selection_drag_mode'] = None
        _state['selection_drag_start'] = None
        _state['selection_drag_origin_box'] = None
        _state['selection_move_pixels'] = None
        _state['selection_move_source_box'] = None
        _selection_clear_pending_preview()
        _state['selection_stencil_mode'] = False
        _state['selection_stencil_region'] = None
        _state['selection_stencil_restore_box'] = None
        _selection_actions.hide()
        _sub_mode_controller.clear_processes()
        _core_runtime.clear_all_processes()
        self.button_down       = False
        self.button_right_down = False

    def _cancel_temp_shift_override_for_shortcut(self, context):
        """Exit temporary Shift->SMOOTH override before opening E/W shortcuts."""
        if not _state['temp_shift_mode_active']:
            return
        restore_mode = _state['temp_shift_prev_mode'] or 'SQUARE'
        context.window_manager.pixel_painter_mode = restore_mode
        _state['temp_shift_mode_active'] = False
        _state['temp_shift_prev_mode'] = None
        context.window_manager.pixel_painter_temp_smooth_force_global = False
        apply_active_tool_settings(context)

    def _cancel_active_stroke(self, context, mode):
        if self.button_down or self.button_right_down:
            if mode == 'LINE':
                space = context.space_data
                if space and space.image and _state['back_buffer'] is not None:
                    space.image.pixels.foreach_set(_state['back_buffer'])
                    space.image.update()
                _state['start_position'] = None
                _state['back_buffer'] = None
            _state['last_paint_cx'] = None
            _state['last_paint_cy'] = None
            _state['use_secondary'] = False
            self.button_down = False
            self.button_right_down = False

    def _build_modal_event_context(self, context, event):
        area = context.area
        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
        v2d = region.view2d if region else None
        mode = context.window_manager.pixel_painter_mode
        bounds = self.get_image_screen_bounds(context)
        cursor_in_image = (
            _state['current_cx'] is not None or (
                bounds is not None and
                bounds[0] <= event.mouse_region_x <= bounds[2] and
                bounds[1] <= event.mouse_region_y <= bounds[3]
            )
        )
        return ModalEventContext(
            area=area,
            region=region,
            v2d=v2d,
            mode=mode,
            cursor_in_image=cursor_in_image,
        )

    def _handle_cursor_outside_window(self, context, event, modal_ctx):
        win_w = context.window.width
        win_h = context.window.height
        cursor_outside = not (0 <= event.mouse_x < win_w and 0 <= event.mouse_y < win_h)
        if not cursor_outside:
            return None

        self._cancel_active_stroke(context, modal_ctx.mode)
        _state['current_cx'] = None
        _state['current_cy'] = None
        _state['ctrl_pick_active'] = False
        _state['ctrl_hovered_color'] = None
        context.area.tag_redraw()
        return {'PASS_THROUGH'}

    def _handle_escape_and_submode(self, context, event):
        if event.type == 'ESC':
            if _sub_mode_controller.has_active_mode():
                _sub_mode_controller.cancel_active_mode(context)
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}
            self._cleanup()
            return {'CANCELLED'}

        if _sub_mode_controller.handle_active_event(context, event):
            return {'RUNNING_MODAL'}

        return None

    def _handle_mousemove_event(self, context, event, modal_ctx):
        if event.type != 'MOUSEMOVE':
            return None

        _selection_actions.handle(event)  # hover tracking; never consumes moves
        bounds = self.get_image_screen_bounds(context)
        if bounds:
            xmin, ymin, xmax, ymax = bounds[:4]
            if not (xmin <= event.mouse_region_x <= xmax and ymin <= event.mouse_region_y <= ymax):
                self._cancel_active_stroke(context, modal_ctx.mode)
                _state['current_cx'] = None
                _state['current_cy'] = None
                _state['ctrl_pick_active'] = False
                _state['ctrl_hovered_color'] = None
                context.area.tag_redraw()
                return {'PASS_THROUGH'}

        result = self.get_hovered_pixel(context, event)
        if result:
            _state['current_cx'], _state['current_cy'] = result[0], result[1]
        else:
            _state['current_cx'] = _state['current_cy'] = None

        if modal_ctx.mode == 'SELECT':
            if _state.get('selection_stencil_mode'):
                self._selection_update_stencil_box()
            elif self.button_down:
                self._selection_resize_shift_held = bool(event.shift)
                self._selection_update_drag()
            self._selection_update_hover()
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        if _state['ctrl_pick_active'] and not self.button_down and not self.button_right_down:
            _state['ctrl_region_x'] = event.mouse_region_x
            _state['ctrl_region_y'] = event.mouse_region_y
            cx, cy = _state['current_cx'], _state['current_cy']
            _state['ctrl_hovered_color'] = (
                _settings.get_image_pixel_color(context, cx, cy) if cx is not None else None)

        if (self.button_down or self.button_right_down) and modal_ctx.v2d:
            self.draw_pixels(context)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def _handle_left_mouse_press_event(self, context, event, modal_ctx):
        if event.type != 'LEFTMOUSE' or event.value != 'PRESS':
            return None

        if modal_ctx.mode == 'SELECT':
            # On-canvas Copy / Apply / Stencil buttons get the click first.
            if _selection_actions.handle(event):
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}
            if _state.get('selection_stencil_mode'):
                _selection_apply_stencil(context)
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}
            return self._selection_begin_left_press(context)

        active_mode = modal_ctx.mode
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

        self.button_down = True
        _state['use_secondary'] = False
        _state['last_paint_cx'] = None
        _state['last_paint_cy'] = None
        space = context.space_data
        if space and space.image:
            _undo_push(space.image)
        result = self.get_hovered_pixel(context, event)
        if result:
            _state['current_cx'], _state['current_cy'] = result[0], result[1]
            context.area.tag_redraw()
        if active_mode == 'LINE':
            if space and space.image and _state['current_cx'] is not None:
                _state['back_buffer'] = np.array(space.image.pixels, dtype=np.float32)
                _state['start_position'] = (_state['current_cx'], _state['current_cy'])
        elif modal_ctx.v2d:
            self.draw_pixels(context)
        return {'RUNNING_MODAL'}

    def _handle_left_mouse_release_event(self, context, event, modal_ctx):
        if event.type != 'LEFTMOUSE' or event.value != 'RELEASE':
            return None

        if modal_ctx.mode == 'SELECT':
            if _selection_actions.handle(event):  # completes a button click
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}
            return self._selection_finish_left_release(context)
        if self.button_down and modal_ctx.mode == 'LINE':
            if _state['start_position'] is not None:
                self.draw_pixels(context)
            # Only switch back to previous tool if Line was activated via Alt and ALT is no longer pressed
            if _state['temp_alt_mode_active'] and not event.alt:
                context.window_manager.pixel_painter_mode = _state['last_shape']
            _state['start_position'] = None
            _state['back_buffer'] = None
        _state['last_paint_cx'] = None
        _state['last_paint_cy'] = None
        _state['use_secondary'] = False
        self.button_down = False
        _state['outline_immediate'] = False
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def _handle_right_mouse_press_event(self, context, event, modal_ctx):
        if event.type != 'RIGHTMOUSE' or event.value != 'PRESS':
            return None

        if modal_ctx.mode == 'SELECT':
            if _state.get('selection_stencil_mode'):
                if _selection_toggle_stencil_mode(context):
                    self.button_right_down = False
                    context.area.tag_redraw()
                    return {'RUNNING_MODAL'}
            self._selection_clear(keep_clipboard=True)
            self.button_right_down = True
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        active_mode = modal_ctx.mode
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

        self.button_right_down = True
        _state['use_secondary'] = True
        _state['last_paint_cx'] = None
        _state['last_paint_cy'] = None
        space = context.space_data
        if space and space.image:
            _undo_push(space.image)
        result = self.get_hovered_pixel(context, event)
        if result:
            _state['current_cx'], _state['current_cy'] = result[0], result[1]
            context.area.tag_redraw()
        if active_mode == 'LINE':
            if space and space.image and _state['current_cx'] is not None:
                _state['back_buffer'] = np.array(space.image.pixels, dtype=np.float32)
                _state['start_position'] = (_state['current_cx'], _state['current_cy'])
        elif modal_ctx.v2d:
            self.draw_pixels(context)
        return {'RUNNING_MODAL'}

    def _handle_right_mouse_release_event(self, context, event, modal_ctx):
        if event.type != 'RIGHTMOUSE' or event.value != 'RELEASE':
            return None

        if modal_ctx.mode == 'SELECT':
            self.button_right_down = False
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        if self.button_right_down and modal_ctx.mode == 'LINE':
            if _state['start_position'] is not None:
                self.draw_pixels(context)
            # Only switch back to previous tool if Line was activated via Alt and ALT is no longer pressed
            if _state['temp_alt_mode_active'] and not event.alt:
                context.window_manager.pixel_painter_mode = _state['last_shape']
            _state['start_position'] = None
            _state['back_buffer'] = None
        _state['last_paint_cx'] = None
        _state['last_paint_cy'] = None
        _state['use_secondary'] = False
        self.button_right_down = False
        _state['outline_immediate'] = False
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def _handle_select_copy_paste_shortcuts(self, context, event, modal_ctx):
        if modal_ctx.mode == 'SELECT' and event.value == 'PRESS' and event.ctrl and event.type == 'C':
            return self._selection_copy(context)
        if modal_ctx.mode == 'SELECT' and event.value == 'PRESS' and event.ctrl and event.type == 'V':
            return self._selection_paste(context)
        return None

    def _handle_ctrl_modifier_event(self, context, event, modal_ctx):
        if event.type in {'LEFT_CTRL', 'RIGHT_CTRL'} and event.value == 'PRESS':
            if modal_ctx.mode == 'SELECT':
                return {'RUNNING_MODAL'}
            self._cancel_active_stroke(context, modal_ctx.mode)

            cx, cy = _state['current_cx'], _state['current_cy']
            _state['ctrl_pick_active'] = True
            _state['ctrl_region_x'] = event.mouse_region_x
            _state['ctrl_region_y'] = event.mouse_region_y
            _state['ctrl_hovered_color'] = (
                _settings.get_image_pixel_color(context, cx, cy) if cx is not None else None)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        if event.type in {'LEFT_CTRL', 'RIGHT_CTRL'} and event.value == 'RELEASE':
            if modal_ctx.mode == 'SELECT':
                return {'RUNNING_MODAL'}
            if event.ctrl:
                return {'RUNNING_MODAL'}

            _state['ctrl_pick_active'] = False
            _state['ctrl_hovered_color'] = None
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        return None

    def _handle_alt_modifier_event(self, context, event, modal_ctx):
        if event.type in {'LEFT_ALT', 'RIGHT_ALT'} and event.value == 'PRESS':
            if not _state['temp_alt_mode_active']:
                _state['temp_alt_prev_mode'] = context.window_manager.pixel_painter_mode
                _state['temp_alt_mode_active'] = True
            context.window_manager.pixel_painter_mode = 'LINE'

            self._cancel_active_stroke(context, modal_ctx.mode)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        if event.type in {'LEFT_ALT', 'RIGHT_ALT'} and event.value == 'RELEASE':
            if event.alt:
                return {'RUNNING_MODAL'}

            self._cancel_active_stroke(context, modal_ctx.mode)

            if _state['temp_alt_mode_active']:
                restore_mode = _state['temp_alt_prev_mode'] or 'SQUARE'
                context.window_manager.pixel_painter_mode = restore_mode
                _state['temp_alt_mode_active'] = False
                _state['temp_alt_prev_mode'] = None
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        return None

    def _handle_shift_modifier_event(self, context, event, modal_ctx):
        if event.type in {'LEFT_SHIFT', 'RIGHT_SHIFT'} and event.value == 'PRESS':
            if modal_ctx.mode != 'SELECT':
                if not _state['temp_shift_mode_active']:
                    _state['temp_shift_prev_mode'] = context.window_manager.pixel_painter_mode
                    _state['temp_shift_mode_active'] = True
                context.window_manager.pixel_painter_temp_smooth_force_global = True
                context.window_manager.pixel_painter_mode = 'SMOOTH'
                apply_active_tool_settings(context)
                self._cancel_active_stroke(context, modal_ctx.mode)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        if event.type in {'LEFT_SHIFT', 'RIGHT_SHIFT'} and event.value == 'RELEASE':
            if modal_ctx.mode != 'SELECT':
                if event.shift:
                    return {'RUNNING_MODAL'}

                self._cancel_active_stroke(context, modal_ctx.mode)

                if _state['temp_shift_mode_active']:
                    restore_mode = _state['temp_shift_prev_mode'] or 'SQUARE'
                    context.window_manager.pixel_painter_mode = restore_mode
                    _state['temp_shift_mode_active'] = False
                    _state['temp_shift_prev_mode'] = None
                context.window_manager.pixel_painter_temp_smooth_force_global = False
                apply_active_tool_settings(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        return None

    def _handle_shift_number_shortcuts(self, context, event):
        if not (event.value == 'PRESS' and event.shift and not _sub_mode_controller.has_active_mode()):
            return None
        index = number_key_index(event.type, include_numpad=False)
        tool = TOOLS.by_shortcut_index(index) if index is not None else None
        if tool is None:
            return None
        context.window_manager.pixel_painter_mode = tool.tool_id
        apply_active_tool_settings(context)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def _handle_e_w_shortcuts(self, context, event):
        if event.type == 'E' and event.value == 'PRESS' and event.shift:
            self._cancel_temp_shift_override_for_shortcut(context)
            if _sub_mode_controller.enter_strength_mode(context, event):
                context.area.tag_redraw()
            return None

        if event.type == 'E' and event.value == 'PRESS' and not event.shift:
            self._cancel_temp_shift_override_for_shortcut(context)
            if _sub_mode_controller.active_mode_name() == 'COLOR_PICK':
                return {'PASS_THROUGH'}
            if _sub_mode_controller.enter_color_pick_mode(context, event):
                context.area.tag_redraw()
            return None

        if event.type == 'W' and event.value == 'PRESS':
            self._cancel_temp_shift_override_for_shortcut(context)
            return {'PASS_THROUGH'}

        return None

    def modal(self, context, event):
        try:
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

            modal_ctx = self._build_modal_event_context(context, event)

            result = self._handle_cursor_outside_window(context, event, modal_ctx)
            if result is not None:
                return result

            result = self._handle_escape_and_submode(context, event)
            if result is not None:
                return result

            # Block all non-movement commands when the cursor is outside the image.
            if event.type != 'MOUSEMOVE' and not modal_ctx.cursor_in_image:
                return {'PASS_THROUGH'}

            result = self._handle_mousemove_event(context, event, modal_ctx)
            if result is not None:
                return result

            result = self._handle_left_mouse_press_event(context, event, modal_ctx)
            if result is not None:
                return result

            result = self._handle_left_mouse_release_event(context, event, modal_ctx)
            if result is not None:
                return result

            result = self._handle_right_mouse_press_event(context, event, modal_ctx)
            if result is not None:
                return result

            result = self._handle_right_mouse_release_event(context, event, modal_ctx)
            if result is not None:
                return result

            result = self._handle_select_copy_paste_shortcuts(context, event, modal_ctx)
            if result is not None:
                return result

            result = self._handle_ctrl_modifier_event(context, event, modal_ctx)
            if result is not None:
                return result

            result = self._handle_alt_modifier_event(context, event, modal_ctx)
            if result is not None:
                return result

            result = self._handle_shift_modifier_event(context, event, modal_ctx)
            if result is not None:
                return result

            result = self._handle_shift_number_shortcuts(context, event)
            if result is not None:
                return result

            result = self._handle_e_w_shortcuts(context, event)
            if result is not None:
                return result

            return {'PASS_THROUGH'}
        except Exception:
            self._cleanup()
            return {'CANCELLED'}

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
        if start_with_shift_override and context.window_manager.pixel_painter_mode != 'SELECT' and not _state['temp_shift_mode_active']:
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

        if context.window_manager.pixel_painter_mode == 'SELECT':
            _state['selection_drag_mode'] = None
            _state['selection_drag_start'] = None
            _state['selection_drag_origin_box'] = None
            _state['selection_move_pixels'] = None
            _state['selection_move_source_box'] = None

        # Push undo for the FIRST stroke — the press that triggered invoke is
        # not re-delivered to the modal, so the modal PRESS handler won't fire.
        space = context.space_data
        if context.window_manager.pixel_painter_mode != 'SELECT' and space and space.image and (self.button_down or self.button_right_down):
            _undo_push(space.image)

        # Paint the initial pixel under the cursor on press.
        mode   = context.window_manager.pixel_painter_mode
        result = self.get_hovered_pixel(context, event)
        if result:
            _state['current_cx'], _state['current_cy'] = result[0], result[1]
            if mode == 'SELECT':
                if is_rmb:
                    self._selection_clear(keep_clipboard=True)
                else:
                    self._selection_begin_left_press(context)
            elif start_with_picker:
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


classes = (
    PixelPainterSetModeOperator,
    PixelPainterSetBlendOperator,
    PixelPainterUndoOperator,
    PixelPainterRedoOperator,
    PixelPainterSelectionCopyOperator,
    PixelPainterSelectionApplyOperator,
    PixelPainterSelectionCancelOperator,
    PixelPainterSelectionStencilToggleOperator,
    PixelPainterResetToolSettingsOperator,
    PixelPainterOperator,
)
