"""Select tool: drag boxes, move / resize, copy / paste, stencil stamping."""

from bpy.types import Operator

from ...core.framework import Shortcut
from ...core.state import STATE
from ...ui.menus.selection_actions import SelectionActions
from . import geometry as ops
from ..base import SettingDefaults, ToolBase
from ..subtools.color_pick import ColorPickTool
from ..subtools.strength import StrengthTool
from ..subtools.tool_switch import TemporaryToolSwitch


class SelectionTool(ToolBase):
    tool_id = 'SELECT'
    label = "Select"
    description = "Select, move, resize, copy and paste pixel regions"
    icon = "Tool_Select.png"
    defaults = SettingDefaults(size=True, modifier=True, strength=True, alpha=True)
    uses_values = frozenset({'strength'})     # the opacity of pasted / stamped regions
    usable_as_line_tip = False
    shows_brush_outline = False

    state_defaults = {
        'selection_box':               None,
        'selection_hover_handle':      None,
        'selection_active_handle':     None,
        'selection_drag_mode':         None,
        'selection_drag_start':        None,
        'selection_drag_origin_box':   None,
        'selection_move_pixels':       None,
        'selection_move_source_box':   None,
        'selection_clipboard':         None,
        'selection_pending_action':    None,
        'selection_pending_region':    None,
        'selection_pending_source_box': None,
        'selection_preview_image_name': None,
        'selection_preview_texture':   None,
        'selection_overlay_region':    None,
        'selection_stencil_mode':      False,
        'selection_stencil_region':    None,
        'selection_stencil_restore_box': None,
    }
    persistent_state = ('selection_clipboard', 'selection_preview_image_name',
                        'selection_preview_texture')

    def __init__(self):
        super().__init__()
        self.actions = SelectionActions(STATE)  # on-canvas Copy / Apply / Stencil buttons
        self.dragging = False
        self.mirror_resize = False

    # ---- registration --------------------------------------------------------------

    def on_register(self):
        # Same modifiers as the brushes, minus Ctrl (copy/paste) and Shift (mirrored resize).
        self.add_subtool(TemporaryToolSwitch('LINE', 'ALT'))
        self.add_subtool(ColorPickTool())
        self.add_subtool(StrengthTool())

        self.bind(Shortcut('MOUSEMOVE', None), self._on_mouse_move)
        self.bind(Shortcut('LEFTMOUSE'), self._on_left_press)
        self.bind(Shortcut('LEFTMOUSE', 'RELEASE'), self._on_left_release)
        self.bind(Shortcut('RIGHTMOUSE'), self._on_right_press)
        self.bind(Shortcut('RIGHTMOUSE', 'RELEASE'), lambda ctx, ev: None)
        self.bind(Shortcut('C', ctrl=True), self._copy)
        self.bind(Shortcut('V', ctrl=True), self._paste)

    # ---- lifecycle -----------------------------------------------------------------

    def on_activate(self, ctx, event):
        self._reset_drag(ctx.state)

    def on_deactivate(self, ctx):
        self._reset_drag(ctx.state)
        self.actions.hide()

    def on_interrupt(self, ctx):
        self.dragging = False

    def on_session_end(self, ctx):
        ops.clear_like_rmb(ctx.state, keep_clipboard=True)
        self.actions.hide()

    def draw_overlay(self, ctx):
        if ctx.is_3d:
            return  # TODO(3D): selection overlay is Image Editor only for now
        from ...overlays import selection as overlays_selectmode
        overlays_selectmode.draw_selection_overlay(ctx.context, ctx.state, self.actions)

    def on_stroke_begin(self, env):
        pass

    def on_draw(self, env):
        return  # selection never paints through the brush path

    # ---- events ----------------------------------------------------------------------

    def _on_mouse_move(self, ctx, event):
        state = ctx.state
        self.actions.handle(event)  # hover tracking; never consumes moves
        if state.get('selection_stencil_mode'):
            centered = ops.center_box_like_box(state.get('selection_box'), *ctx.cursor)
            if centered is not None:
                state['selection_box'] = centered
        elif self.dragging:
            self.mirror_resize = bool(event.shift)
            self._update_drag(state, *ctx.cursor)
        self._update_hover(state)
        ctx.redraw()

    def _on_left_press(self, ctx, event):
        state = ctx.state
        if self.actions.handle(event):  # on-canvas buttons get the click first
            ctx.redraw()
            return
        if state.get('selection_stencil_mode'):
            ops.apply_stencil(ctx.context, state)
            ctx.redraw()
            return
        cx, cy = ctx.cursor
        if cx is None or cy is None:
            return

        box = state.get('selection_box')
        interaction = ops.pick_handle(box, cx, cy)
        self.dragging = True
        state['selection_drag_start'] = (cx, cy)
        if interaction == 'MOVE' and box is not None:
            state['selection_drag_mode'] = 'MOVE'
            state['selection_active_handle'] = 'MOVE'
            state['selection_drag_origin_box'] = box
            if state.get('selection_pending_action') is not None and state.get('selection_pending_region') is not None:
                state['selection_move_pixels'] = state['selection_pending_region'].copy()
                state['selection_move_source_box'] = box
            else:
                ops.clear_pending_preview(state)
                state['selection_move_pixels'] = None
                state['selection_move_source_box'] = None
        elif interaction is not None and box is not None:
            state['selection_drag_mode'] = 'RESIZE'
            state['selection_active_handle'] = interaction
            state['selection_drag_origin_box'] = box
        else:
            ops.clear_pending_preview(state)
            state['selection_drag_mode'] = 'CREATE'
            state['selection_active_handle'] = None
            state['selection_drag_origin_box'] = None
            state['selection_box'] = (cx, cy, cx, cy)

        self._update_hover(state)
        ctx.redraw()

    def _on_left_release(self, ctx, event):
        state = ctx.state
        if self.actions.handle(event):  # completes a button click
            ctx.redraw()
            return
        drag_mode = state.get('selection_drag_mode')
        if drag_mode == 'MOVE' and state.get('selection_pending_action') is None:
            region = state.get('selection_move_pixels')
            source_box = state.get('selection_move_source_box')
            dest_box = state.get('selection_box')
            if region is not None and source_box is not None and dest_box is not None and dest_box != source_box:
                state['selection_pending_action'] = 'MOVE'
                state['selection_pending_region'] = region.copy()
                state['selection_pending_source_box'] = source_box
                ops.set_preview(state, region)
            else:
                ops.clear_pending_preview(state)
        self._reset_drag(state)
        self._update_hover(state)
        ctx.redraw()

    def _on_right_press(self, ctx, event):
        state = ctx.state
        if state.get('selection_stencil_mode') and ops.toggle_stencil_mode(ctx.context, state):
            ctx.redraw()
            return
        ops.clear_like_rmb(state, keep_clipboard=True)
        ctx.redraw()

    def _copy(self, ctx, event):
        state = ctx.state
        img = ctx.image
        if state.get('selection_box') is None or img is None:
            return
        state['selection_clipboard'] = ops.extract_region(img, state['selection_box'])
        ctx.redraw()

    def _paste(self, ctx, event):
        state = ctx.state
        clipboard = state.get('selection_clipboard')
        if clipboard is None:
            return
        source_box = state.get('selection_box')
        anchor = ops.box_center(source_box)
        if anchor is None:
            cx, cy = ctx.cursor
            if cx is None or cy is None:
                return
            anchor = (cx, cy)
        ops.start_paste_preview(state, clipboard, anchor, source_box)
        ctx.redraw()

    # ---- helpers -----------------------------------------------------------------------

    def _reset_drag(self, state):
        self.dragging = False
        state['selection_drag_mode'] = None
        state['selection_drag_start'] = None
        state['selection_drag_origin_box'] = None
        state['selection_move_pixels'] = None
        state['selection_move_source_box'] = None
        state['selection_active_handle'] = None

    def _update_hover(self, state):
        if state.get('selection_drag_mode') or state.get('selection_stencil_mode'):
            return
        state['selection_hover_handle'] = ops.pick_handle(
            state.get('selection_box'), state.get('current_cx'), state.get('current_cy'))

    def _update_drag(self, state, cx, cy):
        box = state.get('selection_drag_origin_box')
        start = state.get('selection_drag_start')
        drag_mode = state.get('selection_drag_mode')
        if start is None or cx is None or cy is None or drag_mode is None:
            return
        if drag_mode == 'CREATE':
            state['selection_box'] = ops.normalize_box(start[0], start[1], cx, cy)
        elif drag_mode == 'MOVE' and box is not None:
            dx = int(cx - start[0])
            dy = int(cy - start[1])
            state['selection_box'] = (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy)
        elif drag_mode == 'RESIZE' and box is not None:
            handle = state.get('selection_active_handle', '')
            resize = ops.resize_box_mirrored if self.mirror_resize else ops.resize_box
            state['selection_box'] = resize(box, handle, cx, cy)

    # ---- settings UI -------------------------------------------------------------------

    def draw_settings(self, context, layout):
        wm = context.window_manager
        info = layout.box().column(align=True)
        info.label(text="Selection Tool")
        info.label(text="Drag LMB to create or move a box")
        info.label(text="Drag sides or corners to resize")
        info.label(text="Ctrl+C copies, Ctrl+V pastes at cursor")
        if (getattr(wm, "pixel_painter_selection_has_pending", False)
                and not getattr(wm, "pixel_painter_selection_stencil_mode", False)):
            row = info.row(align=True)
            row.operator("image.pixel_painter_selection_copy", text="Copy", icon='COPYDOWN')
            info.label(text="Copy the selection before pasting it elsewhere")
        info.separator()
        row = info.row(align=True)
        row.operator(
            "image.pixel_painter_selection_stencil_toggle",
            text="Stencil Mode",
            depress=getattr(wm, "pixel_painter_selection_stencil_mode", False),
            icon='SNAP_FACE_CENTER',
        )
        info.label(text="Stencil mode stamps on LMB and follows the mouse")


# ---------------------------------------------------------------------------
# Operators (on-canvas buttons + settings panel)
# ---------------------------------------------------------------------------

class PixelPainterSelectionApplyOperator(Operator):
    bl_idname = "image.pixel_painter_selection_apply"
    bl_label = "Apply Selection Preview"

    def execute(self, context):
        if not ops.apply_pending(context, STATE):
            self.report({'INFO'}, "No pending selection preview to apply")
            return {'CANCELLED'}
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


class PixelPainterSelectionCopyOperator(Operator):
    bl_idname = "image.pixel_painter_selection_copy"
    bl_label = "Copy Selection"

    def execute(self, context):
        selection_box = STATE.get('selection_box')
        space = context.space_data
        if selection_box is None or not space or not space.image:
            return {'CANCELLED'}
        STATE['selection_clipboard'] = ops.extract_region(space.image, selection_box)
        center = ops.box_center(selection_box)
        if STATE['selection_clipboard'] is not None and center is not None:
            ops.start_paste_preview(STATE, STATE['selection_clipboard'], center, selection_box)
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


class PixelPainterSelectionCancelOperator(Operator):
    bl_idname = "image.pixel_painter_selection_cancel"
    bl_label = "Cancel Selection Preview"

    def execute(self, context):
        ops.clear_like_rmb(STATE, keep_clipboard=True)
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


class PixelPainterSelectionStencilToggleOperator(Operator):
    bl_idname = "image.pixel_painter_selection_stencil_toggle"
    bl_label = "Toggle Selection Stencil Mode"

    def execute(self, context):
        if not ops.toggle_stencil_mode(context, STATE):
            self.report({'WARNING'}, "No selection source available for stencil mode")
            return {'CANCELLED'}
        return {'FINISHED'}


classes = (
    PixelPainterSelectionCopyOperator,
    PixelPainterSelectionApplyOperator,
    PixelPainterSelectionCancelOperator,
    PixelPainterSelectionStencilToggleOperator,
)
