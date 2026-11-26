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

from ..utils import blender_utils, pixel_io
from ..model import blend_modes
from ..overlays import brush_outline, cursor as cursor_overlays, handler as draw_handler
from ..overlays import grid as draw_gridoverlay
from ..tools.mask import overlay as mask_overlay
from ..tools.catalog import TOOLS, falloff_property_for, global_tools
from . import history
from .view3d import mesh as v3d_mesh, raycast
from ..overlays import view3d_outline as overlays_view3d
from .context import ToolContext, is_shift_smooth_global
from .framework import InputEvent, ToolManager
from .state import SETTINGS, STATE, declare as declare_state, reset_session
from .variables import build_default_variable_store


# Session state owned by the core (tools declare their own keys, see
# ToolFrame.state_defaults).
declare_state({
    'running':        False,  # True while the persistent modal is active
    'current_cx':     None,   # image pixel under the cursor
    'current_cy':     None,
    'mouse_region':   None,   # (x, y) mouse in WINDOW-region coords (last cursor update)
    'session_token':  None,   # token of the modal instance that owns the session
    'session_area':   None,   # area.as_pointer() of the editor the session runs in
    'outline_timer':  None,
    'last_observed_raw_radius': None,
    'view3d_uv_tile': (0, 0), # UDIM-less UV tile (floor(u), floor(v)) under the 3D cursor
    'view3d_hit_tri': None,   # loop-triangle under the 3D cursor (seed for Edge mode)
    'view3d_hit_local': None, # object-space surface point under the 3D cursor
    'view3d_texel_px': None,  # screen pixels per texel on the hovered face (brush size mapping)
    'view3d_written_size': None,  # Blender brush size last written by the 3D size sync
    'pen_pressure':   1.0,    # tablet pressure of the last pointer event (1.0 for a mouse)
    'pen_is_tablet':  False,
}, persistent=('outline_timer',))


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


MANAGER = ToolManager(declare_state=declare_state)
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


def _sync_brush_size_3d(context):
    """3D Viewport: map Blender's brush size (screen px) <-> tool radius (texels).

    Blender's size is a screen-pixel radius (F key). In 3D it is converted
    with the texel size on the hovered face, so the F circle matches the
    brush on the mesh: an outside change (F drag) sets the texel radius,
    and the size is kept at the brush's on-screen radius so F starts from it.
    """
    texel_px = _state.get('view3d_texel_px')
    if not texel_px:
        return
    mode = context.window_manager.pixel_painter_mode
    force_global = is_shift_smooth_global(context)
    size = blender_utils.get_raw_brush_size(context)
    written = _state.get('view3d_written_size')
    if written is not None and size != written:
        radius = max(0, min(64, int(round(size / texel_px - 0.5))))
        _settings.set_tool_size(context, mode, radius, force_global=force_global)
    radius = _settings.get_tool_size(context, mode, force_global=force_global)
    desired = max(1, min(blender_utils.BRUSH_SIZE_MAX, int(round((radius + 0.5) * texel_px))))
    if desired != size:
        blender_utils.set_raw_brush_size(context, desired)
    _state['view3d_written_size'] = blender_utils.get_raw_brush_size(context)
    _state['last_observed_raw_radius'] = blender_utils.get_raw_brush_image_radius(context)


def _restore_brush_size_2d(context):
    """After a 3D session: back to the Image Editor convention (size = radius + 1)."""
    if _state.get('view3d_written_size') is None:
        return
    try:
        mode = context.window_manager.pixel_painter_mode
        radius = _settings.get_tool_size(context, mode, force_global=is_shift_smooth_global(context))
        blender_utils.set_raw_brush_size(context, radius + 1)
    except Exception:
        pass


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

def _in_session_area(ctx):
    """Draw handlers are per editor *type*: only draw in the editor the session runs in."""
    area = getattr(ctx, 'area', None)
    return area is not None and area.as_pointer() == _state.get('session_area')


def _register_draw_handler(space, context):
    def _callback(ctx):
        try:
            if not _in_session_area(ctx):
                return
            if raycast.is_view3d(ctx):
                cursor_overlays.draw_view3d_offmesh_cursor(ctx, _state)
            else:
                tctx = ToolContext(ctx, MANAGER)
                mask_overlay.draw_2d(ctx, tctx.v2d, tctx.image)
                wm = ctx.window_manager
                if wm.pixel_painter_grid_show:
                    draw_gridoverlay.draw_pixel_grid_overlay(ctx, wm.pixel_painter_grid_opacity)
                brush_outline.draw_brush_outline(ctx, _state)
            cursor_overlays.draw_test_corner_label(ctx)
            MANAGER.draw(ToolContext(ctx, MANAGER))
        except Exception:
            traceback.print_exc()
    def _view_callback(ctx):
        try:
            if _in_session_area(ctx):
                image = blender_utils.get_paint_image(ctx)
                wm = ctx.window_manager
                if wm.pixel_painter_grid_show:
                    draw_gridoverlay.draw_pixel_grid_overlay_3d(ctx, image, wm.pixel_painter_grid_opacity)
                mask_overlay.draw_3d(ctx, image)
                overlays_view3d.draw_brush_outline_3d(ctx, _state)
        except Exception:
            traceback.print_exc()

    draw_handler.register_draw_handler(
        _state, space, context, _callback,
        view_callback=_view_callback if space.type == 'VIEW_3D' else None)


# Session handover token: a newer session (e.g. started in another editor)
# replaces the running one; the old modal sees the token change and exits.
_session_counter = 0

# Addon load generation, kept outside the addon's modules (driver_namespace
# survives module reloads / re-imports). register() starts a new generation;
# a modal session from an older one is stale code and shuts itself down
# instead of running next to the new session (two tool managers, two pickers).
_GENERATION_KEY = 'apu_pixel_painter_generation'


def current_generation():
    try:
        return bpy.app.driver_namespace.get(_GENERATION_KEY)
    except Exception:
        return None


def new_generation():
    """Called by register(): sessions started before are stale from now on."""
    try:
        bpy.app.driver_namespace[_GENERATION_KEY] = time.perf_counter_ns()
    except Exception:
        pass

# Built-in brush overlay settings to restore when the session ends. Module
# level so a session that takes over keeps the original values.
_brush_overlay_restore = []


def _mouse_in_area(area, event):
    if area is None:
        return False
    return (area.x <= event.mouse_x < area.x + area.width
            and area.y <= event.mouse_y < area.y + area.height)


def _end_session():
    """Stop the running session (state, handlers, timer); not the operator instance."""
    try:
        MANAGER.end(ToolContext(bpy.context, MANAGER))  # tools restore temp modes, end strokes
    except Exception:
        traceback.print_exc()
    pixel_io.end_stroke()   # never keep a working buffer past the session
    history.commit_all()
    try:
        bpy.context.window_manager.pixel_painter_temp_smooth_force_global = False
    except Exception:
        pass
    _restore_builtin_brush_overlay()
    _restore_brush_size_2d(bpy.context)
    timer = _state.get('outline_timer')
    if timer is not None:
        try:
            bpy.context.window_manager.event_timer_remove(timer)
        except Exception:
            pass
        _state['outline_timer'] = None
    draw_handler.remove_draw_handler(_state)
    reset_session()


def _disable_builtin_brush_overlay(context):
    if _brush_overlay_restore:
        return  # already disabled by a session that was taken over
    try:
        image_paint = context.tool_settings.image_paint
    except Exception:
        image_paint = None

    brush = getattr(image_paint, 'brush', None) if image_paint else None
    if brush is not None:
        for attr in ('use_cursor_overlay', 'use_cursor_overlay_override'):
            if hasattr(brush, attr):
                try:
                    _brush_overlay_restore.append((brush, attr, getattr(brush, attr)))
                    setattr(brush, attr, False)
                except Exception:
                    pass

    if image_paint is not None and hasattr(image_paint, 'show_brush'):
        try:
            _brush_overlay_restore.append((image_paint, 'show_brush', getattr(image_paint, 'show_brush')))
            image_paint.show_brush = False
        except Exception:
            pass


def _restore_builtin_brush_overlay():
    for owner, attr, value in _brush_overlay_restore:
        try:
            setattr(owner, attr, value)
        except Exception:
            pass
    _brush_overlay_restore.clear()


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

    def _set_modal_cursor(self, context):
        # State 'cursor_hidden': a UI element drawing its own pointer (e.g. the pen menu's
        # falloff field while dragged) hides the OS cursor.
        kind = 'NONE' if _state.get('cursor_hidden') else 'CROSSHAIR'
        if getattr(self, '_cursor_is_custom', False) and getattr(self, '_cursor_kind', None) == kind:
            return
        try:
            context.window.cursor_modal_set(kind)
            self._cursor_is_custom = True
            self._cursor_kind = kind
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
        self._cursor_kind = None

    # ---- lifecycle ---------------------------------------------------------------

    def _cleanup(self):
        try:
            self._restore_modal_cursor(bpy.context)
        except Exception:
            pass
        if self._owns_session():
            _end_session()

    def _owns_session(self):
        return bool(_state.get('running')) and getattr(self, '_token', None) == _state.get('session_token')

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
        ctx.update_pen(ev)

        # On-screen UI (pen bar) first: it sits anywhere in the editor, also off the image.
        if MANAGER.dispatch_screen(ctx, ev):
            ctx.redraw()
            return {'RUNNING_MODAL'}

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

    def _leave_if_stale(self, context):
        """True when the addon was reloaded since this session started.

        Same module re-executed (reload): the new load already cleaned up the
        runtime -- just leave. Modules replaced (re-install / re-enable): these
        globals are the old load's -- end that old session (its draw handler,
        tool manager, timer) before leaving.
        """
        same_state = getattr(self, '_state_ref', None) is _state
        if same_state and getattr(self, '_generation', None) == current_generation():
            return False
        if same_state and self._owns_session():
            _end_session()
        self._restore_modal_cursor(context)
        return True

    def modal(self, context, event):
        try:
            if self._leave_if_stale(context):
                return {'CANCELLED', 'PASS_THROUGH'}
            if not self._owns_session():
                # Replaced by a session in another editor: leave quietly
                # (the new session owns the state, handlers and cursor).
                return {'CANCELLED', 'PASS_THROUGH'}

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
            if raycast.is_view3d(context):
                _sync_brush_size_3d(context)
            else:
                _sync_external_brush_size_into_tool_setting(context)
            apply_active_tool_settings(context)

            if event.type == 'TIMER':
                if context.area:
                    context.area.tag_redraw()
                return {'RUNNING_MODAL'}

            # The modal keeps the context of the editor it started in. Events
            # over other editors are not ours: pass them on, so e.g. the 3D
            # tool's click can start (take over) a session there.
            if not MANAGER.is_capturing() and not _mouse_in_area(context.area, event):
                return self._cursor_lost(ToolContext(context, MANAGER))

            return self._route(ToolContext(context, MANAGER), event)
        except Exception:
            traceback.print_exc()
            self._cleanup()
            return {'CANCELLED'}

    def invoke(self, context, event):
        if not _supported_space(context):
            return {'CANCELLED'}

        # The tool keymap fires on every LMB press; a second modal instance
        # in the same editor would reset the state mid-stroke.
        if _state['running']:
            if _state.get('session_area') == context.area.as_pointer():
                return {'CANCELLED'}
            _end_session()  # started in another editor: take the session over

        if raycast.is_view3d(context):
            if blender_utils.get_paint_image(context) is None:
                self.report({'WARNING'}, "Pixel Painter: no texture to paint on (add a paint slot / canvas)")
                return {'CANCELLED'}
            v3d_mesh.invalidate()  # the mesh may have changed since the last session

        global _session_counter
        reset_session()
        _session_counter += 1
        self._token = _session_counter
        self._state_ref = _state
        self._generation = current_generation()
        _state['session_token'] = self._token
        _state['session_area'] = context.area.as_pointer()
        _state['running'] = True
        _state['cursor_hidden'] = False
        _state['outline_anim_start'] = time.perf_counter()
        _state['last_observed_raw_radius'] = blender_utils.get_raw_brush_image_radius(context)
        self._set_modal_cursor(context)
        _disable_builtin_brush_overlay(context)

        ctx = ToolContext(context, MANAGER)
        MANAGER.begin(ctx)
        apply_active_tool_settings(context)

        # The press that started the operator is not re-delivered to modal():
        # route it now (modifier subtools see Ctrl/Alt/Shift on it).
        # (The pen bar was not visible before this press, so it does not get it.)
        ev = InputEvent.from_blender(event)
        ctx.update_pen(ev)
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
