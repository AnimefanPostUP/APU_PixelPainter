"""The Pixel Painter core: modal operator + tool manager.

The core does not know what tools do. Per event it
1. guards the session (right editor, right workspace tool),
2. keeps the settings in sync and tracks the hovered image pixel,
3. hands the event to :data:`MANAGER`, which offers it to every active tool
   until one consumes it (see :mod:`core.framework`).

Tool behaviour lives in ``tools/`` (main tools) and ``tools/subtools/``.
"""

import time
import traceback

import bpy
from bpy.types import Operator

from ..utils import blender_utils
from ..tools import blend_modes
from ..tools import draw_functions
from ..tools import draw_gridoverlay
from ..tools.catalog import TOOLS, falloff_property_for, global_tools
from . import history, view3d
from .context import ToolContext, is_shift_smooth_global
from .framework import InputEvent, ToolManager
from .state import SETTINGS, STATE, reset_session
from .variables import build_default_variable_store


# Kept under the old names for modules that reach into the core
# (properties.py, paint_selected_faces_uv.py, __init__.py).
_state = STATE
_settings = SETTINGS
_variable_store = build_default_variable_store()

# Workspace tool ids that run this operator (Image Editor and 3D Viewport).
TOOL_IDNAMES = frozenset({"image.pixel_painter_tool", "view3d.pixel_painter_tool"})


def _supported_space(context):
    """True in the Image Editor, and in the 3D Viewport while in Texture Paint mode."""
    space = context.space_data
    if space is None:
        return False
    if space.type == 'IMAGE_EDITOR':
        return True
    return space.type == 'VIEW_3D' and context.mode == 'PAINT_TEXTURE'


MANAGER = ToolManager()
MANAGER.register_all(TOOLS)
MANAGER.register_all(global_tools())


# ---------------------------------------------------------------------------
# Settings sync
# ---------------------------------------------------------------------------

def apply_active_tool_settings(context):
    """Load active tool settings (global/local aware) into runtime values."""
    mode = context.window_manager.pixel_painter_mode
    _settings.apply_tool_runtime_settings(context, mode, force_global=is_shift_smooth_global(context))
    _sync_variable_store(context)


def _sync_external_brush_size_into_tool_setting(context):
    """Capture external brush-size edits (e.g. F key) into the active tool setting."""
    raw_radius = blender_utils.get_raw_brush_image_radius(context)
    prev = _state.get('last_observed_raw_radius')
    if prev is not None and raw_radius != prev:
        mode = context.window_manager.pixel_painter_mode
        _settings.set_tool_size(context, mode, raw_radius, force_global=is_shift_smooth_global(context))
    _state['last_observed_raw_radius'] = raw_radius


def _sync_variable_store(context):
    mode = context.window_manager.pixel_painter_mode
    force_global = is_shift_smooth_global(context)
    values = {
        'size': _settings.get_tool_size(context, mode, force_global=force_global),
        'modifier': _settings.get_tool_modifier(context, mode, force_global=force_global),
        'falloff': getattr(context.window_manager, falloff_property_for(mode)),
    }
    for name, value in values.items():
        _variable_store.set_global(name, value)
        _variable_store.set_tool_value(mode, name, value)


# ---------------------------------------------------------------------------
# Undo (kept for external callers; see core/history.py)
# ---------------------------------------------------------------------------

def _undo_push(img):
    history.begin(img)


def _undo_commit(img, message="Pixel Paint"):
    return history.commit(img, message)


def _undo_clear():
    history.clear()


# ---------------------------------------------------------------------------
# Draw handler
# ---------------------------------------------------------------------------

def _register_draw_handler(space, context):
    def _callback(ctx):
        try:
            if view3d.is_view3d(ctx):
                # TODO(3D): real brush outline on the surface; placeholder for now.
                draw_functions.draw_view3d_placeholder_cursor(ctx, _state)
            else:
                draw_gridoverlay.draw_pixel_grid_overlay(ctx, ctx.window_manager.pixel_painter_grid_opacity)
                draw_functions.draw_test_tool_shape_outline(ctx, _state)
            draw_functions.draw_test_corner_label(ctx)
            MANAGER.draw(ToolContext(ctx, MANAGER))
        except Exception:
            traceback.print_exc()
    draw_functions.register_draw_handler(_state, space, context, _callback)


# ---------------------------------------------------------------------------
# Small operators
# ---------------------------------------------------------------------------

def set_active_tool(context, tool_id):
    """Switch the selected tool (used by the operator, pies and shortcuts).

    While the modal runs, the manager notices the mode change on the next event.
    """
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


# ---------------------------------------------------------------------------
# Modal operator
# ---------------------------------------------------------------------------

class PixelPainterOperator(Operator):
    """Persistent modal operator for the Pixel Painter workspace tool.

    Stays alive while the workspace tool is active and routes every event to
    the tool manager.
    """
    bl_idname  = "image.pixel_painter_operator"
    bl_label   = "Pixel Painter"
    bl_options = {'REGISTER'}

    # ---- editor helpers --------------------------------------------------------

    @staticmethod
    def _image_screen_bounds(ctx):
        """Region-space rect around the image (+10% margin), or None."""
        area, region, img = ctx.area, ctx.region, ctx.image
        if not area or area.type not in {"IMAGE_EDITOR", "VIEW_3D"} or not region or img is None:
            return None
        w, h = img.size
        if w == 0 or h == 0:
            return None
        vd = region.view2d
        t = 0.1
        corners = [vd.view_to_region(x, y, clip=False)
                   for x, y in ((-t, -t), (1.0 + t, -t), (1.0 + t, 1.0 + t), (-t, 1.0 + t))]
        xs, ys = zip(*corners)
        return max(min(xs), 0), max(min(ys), 0), min(max(xs), region.width), min(max(ys), region.height)

    def _cursor_over_image(self, ctx, event):
        if ctx.is_3d:
            # Off-mesh positions still count (cursor is None there), so a stroke
            # survives crossing empty space; only leaving the region ends it.
            region = ctx.region
            if region is None:
                return False
            return 0 <= event.mouse_region_x <= region.width and 0 <= event.mouse_region_y <= region.height
        bounds = self._image_screen_bounds(ctx)
        if bounds is None:
            return True
        xmin, ymin, xmax, ymax = bounds
        return xmin <= event.mouse_region_x <= xmax and ymin <= event.mouse_region_y <= ymax

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
        if getattr(self, '_cursor_is_custom', False):
            return
        try:
            context.window.cursor_modal_set('CROSSHAIR')
            self._cursor_is_custom = True
        except Exception:
            self._cursor_is_custom = False

    def _restore_modal_cursor(self, context):
        if not getattr(self, '_cursor_is_custom', False):
            return
        try:
            context.window.cursor_modal_restore()
        except Exception:
            pass
        self._cursor_is_custom = False

    # ---- lifecycle ---------------------------------------------------------------

    def _cleanup(self):
        try:
            MANAGER.end(ToolContext(bpy.context, MANAGER))  # tools restore temp modes, end strokes
        except Exception:
            traceback.print_exc()
        history.commit_all()
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
        reset_session()

    def _cursor_lost(self, ctx):
        """Cursor left the window/image: abort strokes and forget the hovered pixel."""
        MANAGER.interrupt(ctx)
        _state['current_cx'] = None
        _state['current_cy'] = None
        ctx.redraw()
        return {'PASS_THROUGH'}

    def _route(self, ctx, event):
        ev = InputEvent.from_blender(event)
        window = ctx.context.window
        if not (0 <= ev.mouse_x < window.width and 0 <= ev.mouse_y < window.height):
            return self._cursor_lost(ctx)

        # Capturing subtools (color pick, strength) get every event, wherever the cursor is.
        if not MANAGER.is_capturing() and ev.type != 'ESC':
            if ev.type == 'MOUSEMOVE':
                if not self._cursor_over_image(ctx, ev):
                    return self._cursor_lost(ctx)
            elif _state['current_cx'] is None and not self._cursor_over_image(ctx, ev):
                return {'PASS_THROUGH'}  # no commands while the cursor is off the image
            ctx.update_cursor(ev)

        MANAGER.dispatch(ctx, ev)
        if ev.consumed:
            ctx.redraw()
            return {'RUNNING_MODAL'}
        if ev.type == 'ESC' and ev.value == 'PRESS':
            self._cleanup()
            return {'CANCELLED'}
        if ev.type == 'MOUSEMOVE':
            ctx.redraw()
            return {'RUNNING_MODAL'}
        return {'PASS_THROUGH'}

    def modal(self, context, event):
        try:
            if not _supported_space(context):
                self._cleanup()
                return {'CANCELLED'}

            self._set_modal_cursor(context)

            from bl_ui.space_toolsystem_common import ToolSelectPanelHelper
            tool = ToolSelectPanelHelper.tool_active_from_context(context)
            if not tool or tool.idname not in TOOL_IDNAMES:
                self._cleanup()
                return {'CANCELLED'}

            # Every event, so the outline follows F-key resizing in real time.
            _sync_external_brush_size_into_tool_setting(context)
            apply_active_tool_settings(context)

            if event.type == 'TIMER':
                if context.area:
                    context.area.tag_redraw()
                return {'RUNNING_MODAL'}

            return self._route(ToolContext(context, MANAGER), event)
        except Exception:
            traceback.print_exc()
            self._cleanup()
            return {'CANCELLED'}

    def invoke(self, context, event):
        if not _supported_space(context):
            return {'CANCELLED'}

        # The tool keymap fires on every LMB press; a second modal instance
        # would reset the state mid-stroke.
        if _state['running']:
            return {'CANCELLED'}

        if view3d.is_view3d(context):
            if blender_utils.get_paint_image(context) is None:
                self.report({'WARNING'}, "Pixel Painter: no texture to paint on (add a paint slot / canvas)")
                return {'CANCELLED'}
            view3d.invalidate()  # the mesh may have changed since the last session

        reset_session()
        _state['running'] = True
        _state['outline_anim_start'] = time.perf_counter()
        _state['last_observed_raw_radius'] = blender_utils.get_raw_brush_image_radius(context)
        self._set_modal_cursor(context)
        self._disable_builtin_brush_overlay(context)

        ctx = ToolContext(context, MANAGER)
        MANAGER.begin(ctx)
        apply_active_tool_settings(context)

        # The press that started the operator is not re-delivered to modal():
        # route it now (modifier subtools see Ctrl/Alt/Shift on it).
        ev = InputEvent.from_blender(event)
        if ctx.update_cursor(ev) is not None:
            MANAGER.dispatch(ctx, ev)

        _register_draw_handler(context.space_data, context)
        _state['outline_timer'] = context.window_manager.event_timer_add(1.0 / 60.0, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}


classes = (
    PixelPainterSetModeOperator,
    PixelPainterSetBlendOperator,
    PixelPainterResetToolSettingsOperator,
    PixelPainterOperator,
)
