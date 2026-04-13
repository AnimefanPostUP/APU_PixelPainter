"""Operator classes and module-level tool state."""
import colorsys

import bpy
import numpy as np
from bpy.types import Operator

from . import math_utils
from . import blender_utils
from . import draw_functions


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
    'ctrl_line_active': False,  # True while Ctrl+LMB line draw is in progress
    'last_shape':         'SQUARE',
    'last_paint_cx':      None,
    'last_paint_cy':      None,
    'stroke_painted':     None,  # set of (px,py) painted this stroke (SQUARE / Pixel-mode guard)
    'stroke_weight_map':  None,  # dict (px,py)→max_weight for CIRCLE/SPRAY Free mode
    'stroke_back_buffer': None,  # pre-stroke image snapshot for CIRCLE/SPRAY Free mode
    'use_secondary':  False,  # True while RMB is held (paint with secondary color)
    # ---- interactive sub-modes (R = opacity, E = color pick) ----------------
    'sub_mode':           None,  # 'OPACITY' | 'COLOR_PICK' | None
    'sub_last_x':         None,  # mouse region X on last MOUSEMOVE in sub-mode
    'sub_last_y':         None,  # mouse region Y on last MOUSEMOVE in sub-mode
    'sub_orig_opacity':   None,  # brush strength captured when entering OPACITY mode
    'sub_orig_modifier':  None,  # modifier value captured when entering OPACITY mode
    'sub_total_delta':    0.0,   # accumulated real mouse displacement for OPACITY mode
    'sub_orig_color':     None,  # brush RGB tuple captured when entering COLOR_PICK mode
    'sub_color_h':        None,  # H component kept across mousemoves to avoid re-deriving from RGB
    'sub_color_s':        None,  # S component kept to prevent saturation loss when V clamps
    'sub_color_v':        None,  # V component
    'sub_start_screen_x': None,  # absolute screen X when entering sub-mode (for cursor warp)
    'sub_start_screen_y': None,  # absolute screen Y when entering sub-mode (for cursor warp)
    'sub_start_region_x': None,  # region X when entering sub-mode (for overlay drawing)
    'sub_start_region_y': None,  # region Y when entering sub-mode (for overlay drawing)
    # ---- shift eyedropper (hold Shift outside sub-mode) ----------------------
    'shift_pick_active':   False,
    'shift_hovered_color': None,  # (r,g,b) of image pixel under cursor
    'shift_region_x':      None,  # region X for the circle overlay
    'shift_region_y':      None,  # region Y for the circle overlay
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
# Sub-mode helpers  (opacity / color-pick interactive modes)
# ---------------------------------------------------------------------------

def _get_brush_opacity(context):
    try:
        ups   = context.tool_settings.unified_paint_settings
        brush = context.tool_settings.image_paint.brush
        return ups.strength if ups.use_unified_strength else (brush.strength if brush else 1.0)
    except Exception:
        return 1.0


def _set_brush_opacity(context, value):
    value = max(0.0, min(1.0, value))
    try:
        ups   = context.tool_settings.unified_paint_settings
        brush = context.tool_settings.image_paint.brush
        if ups.use_unified_strength:
            ups.strength = value
        elif brush:
            brush.strength = value
    except Exception:
        pass


def _get_brush_rgb(context):
    try:
        brush = context.tool_settings.image_paint.brush
        return tuple(brush.color[:3]) if brush else (1.0, 1.0, 1.0)
    except Exception:
        return (1.0, 1.0, 1.0)


def _get_modifier(context):
    try:
        return context.window_manager.pixel_painter_modifier
    except Exception:
        return 0.5


def _set_modifier(context, value):
    try:
        context.window_manager.pixel_painter_modifier = max(0.0, min(1.0, value))
    except Exception:
        pass


def _set_brush_rgb(context, r, g, b):
    try:
        brush = context.tool_settings.image_paint.brush
        if brush:
            brush.color = (r, g, b)
    except Exception:
        pass


def _get_falloff_curve_sampler(context):
    """Return a callable t->[0,1] sampled from the active brush curve, or None."""
    try:
        wm = context.window_manager
        if not getattr(wm, 'pixel_painter_use_curve_falloff', False):
            return None
        brush = context.tool_settings.image_paint.brush
        curve = getattr(brush, 'curve', None) if brush else None
        if curve is None:
            return None

        try:
            curve.initialize()
        except Exception:
            pass

        def _sample(t):
            t = max(0.0, min(1.0, float(t)))
            try:
                return curve.evaluate(t)
            except Exception:
                return curve.evaluate(0, t)

        return _sample
    except Exception:
        return None


def _get_image_pixel_color(context, cx, cy):
    """Read the RGB color of image pixel (cx, cy). Returns (r,g,b) or None."""
    try:
        space = context.space_data
        if not space or not space.image:
            return None
        img = space.image
        w, h = img.size
        if not (0 <= cx < w and 0 <= cy < h):
            return None
        idx = (cy * w + cx) * 4
        return (img.pixels[idx], img.pixels[idx + 1], img.pixels[idx + 2])
    except Exception:
        return None


def _warp_cursor_to_sub_start(context):
    """Warp the OS cursor back to where the sub-mode was entered."""
    sx = _state.get('sub_start_screen_x')
    sy = _state.get('sub_start_screen_y')
    if sx is not None and sy is not None:
        try:
            context.window.cursor_warp(sx, sy)
        except Exception:
            pass


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
        draw_functions.draw_shift_pick_overlay(ctx, _state)
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

    # ---- drawing -------------------------------------------------------------

    def draw_pixels(self, context):
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
        opacity = blender_utils.get_brush_opacity(context)
        radius  = blender_utils.get_brush_image_radius(context)
        wm      = context.window_manager
        spacing = wm.pixel_painter_spacing
        curve_sampler = _get_falloff_curve_sampler(context)

        # Reset per-stroke tracking at the start of each new stroke
        if _state['last_paint_cx'] is None:
            _state['stroke_painted']     = set()
            _state['stroke_weight_map']  = {}
            _state['stroke_back_buffer'] = np.array(img.pixels, dtype=np.float32)

        # Pixel spacing: skip if the cursor hasn't moved to a new pixel
        if (spacing == 'PIXEL'
                and mode not in {'LINE'}
                and not _state['ctrl_line_active']
                and cx == _state['last_paint_cx']
                and cy == _state['last_paint_cy']):
            return

        def _steps():
            return _interpolation_steps(cx, cy)

        if mode == 'LINE' or _state['ctrl_line_active']:
            if _state['start_position'] is None or _state['back_buffer'] is None:
                return
            shape     = _state['last_shape']
            tip_shape = 'CIRCLE' if shape == 'SPRAY' else shape
            x0, y0    = _state['start_position']
            all_pixels = set()
            for (lx, ly) in math_utils.get_line_pixels(x0, y0, cx, cy):
                all_pixels |= math_utils.get_pixels_in_shape(lx, ly, radius, tip_shape)
            draw_functions.write_pixels_to_image(img, all_pixels, color,
                                                 base_buffer=_state['back_buffer'],
                                                 blend=blend, opacity=opacity)

        elif mode == 'SPRAY':
            spray_strength = wm.pixel_painter_spray_strength
            spray_falloff  = wm.pixel_painter_spray_falloff
            if spacing == 'PIXEL':
                # Pixel: accumulate max weight, re-render from back-buffer each call
                swm = _state['stroke_weight_map']
                for (sx, sy) in _steps():
                    px_list, pw_list = math_utils.get_spray_pixels(sx, sy, radius,
                                                                    spray_strength, spray_falloff,
                                                                    curve_sampler=curve_sampler)
                    for px, w in zip(px_list, pw_list):
                        if w > swm.get(px, 0.0):
                            swm[px] = w
                if swm:
                    draw_functions.write_pixels_to_image(
                        img, list(swm.keys()), color,
                        base_buffer=_state['stroke_back_buffer'],
                        blend=blend, opacity=opacity,
                        pixel_weights=list(swm.values()))
            else:
                # Free: local dedup per call only, paint directly
                pixel_weight_map = {}
                for (sx, sy) in _steps():
                    px_list, pw_list = math_utils.get_spray_pixels(sx, sy, radius,
                                                                    spray_strength, spray_falloff,
                                                                    curve_sampler=curve_sampler)
                    for px, w in zip(px_list, pw_list):
                        if w > pixel_weight_map.get(px, 0.0):
                            pixel_weight_map[px] = w
                if pixel_weight_map:
                    draw_functions.write_pixels_to_image(img, list(pixel_weight_map.keys()), color,
                                                         blend=blend, opacity=opacity,
                                                         pixel_weights=list(pixel_weight_map.values()))
            _state['last_paint_cx'] = cx
            _state['last_paint_cy'] = cy

        elif mode == 'CIRCLE':
            circle_falloff = wm.pixel_painter_circle_falloff
            if spacing == 'PIXEL':
                # Pixel: accumulate max weight, re-render from back-buffer each call
                swm = _state['stroke_weight_map']
                for (sx, sy) in _steps():
                    px_list, pw_list = math_utils.get_pixels_in_circle_weighted(sx, sy, radius,
                                                                                  circle_falloff,
                                                                                  curve_sampler=curve_sampler)
                    for px, w in zip(px_list, pw_list):
                        if w > swm.get(px, 0.0):
                            swm[px] = w
                if swm:
                    draw_functions.write_pixels_to_image(
                        img, list(swm.keys()), color,
                        base_buffer=_state['stroke_back_buffer'],
                        blend=blend, opacity=opacity,
                        pixel_weights=list(swm.values()))
            else:
                # Free: local dedup per call only, paint directly
                pixel_weight_map = {}
                for (sx, sy) in _steps():
                    px_list, pw_list = math_utils.get_pixels_in_circle_weighted(sx, sy, radius,
                                                                                  circle_falloff,
                                                                                  curve_sampler=curve_sampler)
                    for px, w in zip(px_list, pw_list):
                        if w > pixel_weight_map.get(px, 0.0):
                            pixel_weight_map[px] = w
                if pixel_weight_map:
                    draw_functions.write_pixels_to_image(img, list(pixel_weight_map.keys()), color,
                                                         blend=blend, opacity=opacity,
                                                         pixel_weights=list(pixel_weight_map.values()))
            _state['last_paint_cx'] = cx
            _state['last_paint_cy'] = cy

        elif mode == 'SMOOTH':
            modifier      = wm.pixel_painter_modifier
            smooth_radius = max(1, int(modifier * max(1, radius)))
            all_pixels = set()
            for (sx, sy) in _steps():
                all_pixels |= math_utils.get_pixels_in_shape(sx, sy, radius, 'CIRCLE')
            draw_functions.smooth_pixels_in_image(img, list(all_pixels),
                                                  smooth_radius, opacity)
            _state['last_paint_cx'] = cx
            _state['last_paint_cy'] = cy

        elif mode == 'SMEAR':
            modifier = wm.pixel_painter_modifier
            steps    = _steps()
            prev_x   = _state['last_paint_cx']
            prev_y   = _state['last_paint_cy']
            for i, (sx, sy) in enumerate(steps):
                ox = (prev_x if prev_x is not None else sx) if i == 0 else steps[i - 1][0]
                oy = (prev_y if prev_y is not None else sy) if i == 0 else steps[i - 1][1]
                ddx = sx - ox
                ddy = sy - oy
                smear_reach = modifier * max(1, radius)
                draw_functions.smear_pixels_in_image(
                    img, list(math_utils.get_pixels_in_shape(sx, sy, radius, 'CIRCLE')),
                    ddx, ddy, smear_reach, opacity)
            _state['last_paint_cx'] = cx
            _state['last_paint_cy'] = cy

        else:  # SQUARE
            if spacing == 'PIXEL':
                # Pixel: guard against re-painting across calls using stroke_painted
                painted = _state['stroke_painted']
                for (sx, sy) in _steps():
                    step_pixels = math_utils.get_pixels_in_shape(sx, sy, radius, mode) - painted
                    if step_pixels:
                        draw_functions.write_pixels_to_image(img, step_pixels, color,
                                                             blend=blend, opacity=opacity)
                        painted |= step_pixels
            else:
                # Free: local dedup within this call only, paint directly
                all_pixels = set()
                for (sx, sy) in _steps():
                    all_pixels |= math_utils.get_pixels_in_shape(sx, sy, radius, mode)
                if all_pixels:
                    draw_functions.write_pixels_to_image(img, all_pixels, color,
                                                         blend=blend, opacity=opacity)
            _state['last_paint_cx'] = cx
            _state['last_paint_cy'] = cy

    # ---- lifecycle -----------------------------------------------------------

    def _cleanup(self):
        self._restore_builtin_brush_overlay()
        draw_functions.remove_draw_handler(_state)
        _state['running']          = False
        _state['current_cx']       = None
        _state['current_cy']       = None
        _state['start_position']   = None
        _state['back_buffer']      = None
        _state['ctrl_line_active'] = False
        _state['last_paint_cx']       = None
        _state['last_paint_cy']       = None
        _state['stroke_painted']      = None
        _state['stroke_weight_map']   = None
        _state['stroke_back_buffer']  = None
        _state['use_secondary']       = False
        _state['sub_mode']           = None
        _state['sub_orig_opacity']   = None
        _state['sub_orig_modifier']  = None
        _state['sub_total_delta']    = 0.0
        _state['sub_orig_color']     = None
        _state['sub_color_h']        = None
        _state['sub_color_s']        = None
        _state['sub_color_v']        = None
        _state['sub_start_screen_x'] = None
        _state['sub_start_screen_y'] = None
        _state['sub_start_region_x'] = None
        _state['sub_start_region_y'] = None
        _state['shift_pick_active']   = False
        _state['shift_hovered_color'] = None
        _state['shift_region_x']      = None
        _state['shift_region_y']      = None
        self.button_down       = False
        self.button_right_down = False

    def modal(self, context, event):
        # Guard: exit if we've left the Image Editor
        if context.space_data is None or context.space_data.type != 'IMAGE_EDITOR':
            self._cleanup()
            return {'CANCELLED'}

        # Guard: stop if the user switched to a different tool
        from bl_ui.space_toolsystem_common import ToolSelectPanelHelper
        tool = ToolSelectPanelHelper.tool_active_from_context(context)
        if not tool or tool.idname != "image.pixel_painter_tool":
            self._cleanup()
            return {'CANCELLED'}

        area   = context.area
        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
        v2d    = region.view2d if region else None
        mode   = context.window_manager.pixel_painter_mode

        # If the cursor has left the OS window, cancel any active stroke and
        # ignore all input until it returns.
        win_w = context.window.width
        win_h = context.window.height
        cursor_outside = not (0 <= event.mouse_x < win_w and 0 <= event.mouse_y < win_h)
        if cursor_outside:
            if self.button_down or self.button_right_down:
                if _state['ctrl_line_active']:
                    space = context.space_data
                    if space and space.image and _state['back_buffer'] is not None:
                        space.image.pixels.foreach_set(_state['back_buffer'])
                        space.image.update()
                    _state['ctrl_line_active'] = False
                    _state['start_position']   = None
                    _state['back_buffer']      = None
                elif mode == 'LINE':
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
            _state['shift_pick_active']   = False
            _state['shift_hovered_color'] = None
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

        # Q / ESC: stop the modal (or exit sub-mode first)
        if event.type in {'Q', 'ESC'}:
            if _state['sub_mode'] is not None:
                # restore original values and leave sub-mode
                if _state['sub_mode'] == 'OPACITY' and _state['sub_orig_opacity'] is not None:
                    _set_brush_opacity(context, _state['sub_orig_opacity'])
                elif _state['sub_mode'] == 'COLOR_PICK' and _state['sub_orig_color'] is not None:
                    _set_brush_rgb(context, *_state['sub_orig_color'])
                _state['sub_mode'] = None
                _warp_cursor_to_sub_start(context)
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}
            self._cleanup()
            return {'CANCELLED'}

        # ------------------------------------------------------------------ #
        # Sub-mode: R = opacity picker, E = color picker                      #
        # While a sub-mode is active all events are consumed here; painting   #
        # is blocked until the sub-mode is exited.                            #
        # ------------------------------------------------------------------ #
        sub = _state['sub_mode']

        if sub == 'OPACITY':
            if event.type == 'MOUSEMOVE':
                dx = event.mouse_region_x - _state['sub_last_x']
                dy = event.mouse_region_y - _state['sub_last_y']
                _state['sub_last_x'] = event.mouse_region_x
                _state['sub_last_y'] = event.mouse_region_y
                # Accumulate real user movement (wrap correction happens after, so
                # the teleport jump never enters sub_total_delta).
                _state['sub_total_delta'] += dx + dy
                divisor  = 3000.0 if event.shift else 300.0
                orig_op  = _state['sub_orig_opacity'] or 0.0
                _set_brush_opacity(context, orig_op + _state['sub_total_delta'] / divisor)
                _wrap_cursor_at_window_edge(context, event)
                context.area.tag_redraw()
            elif event.type == 'WHEELUPMOUSE':
                step = 0.01 if event.shift else 0.05
                _set_modifier(context, _get_modifier(context) + step)
                context.area.tag_redraw()
            elif event.type == 'WHEELDOWNMOUSE':
                step = 0.01 if event.shift else 0.05
                _set_modifier(context, _get_modifier(context) - step)
                context.area.tag_redraw()
            elif event.type == 'LEFTMOUSE' and event.value == 'PRESS':
                _state['sub_mode'] = None          # keep new values
                _warp_cursor_to_sub_start(context)
                context.area.tag_redraw()
            elif event.type == 'RIGHTMOUSE' and event.value == 'PRESS':
                _set_brush_opacity(context, _state['sub_orig_opacity'])
                _set_modifier(context, _state['sub_orig_modifier'])
                _state['sub_mode'] = None
                _warp_cursor_to_sub_start(context)
                context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        if sub == 'COLOR_PICK':
            if event.type == 'MOUSEMOVE':
                dx = event.mouse_region_x - _state['sub_last_x']
                dy = event.mouse_region_y - _state['sub_last_y']
                _state['sub_last_x'] = event.mouse_region_x
                _state['sub_last_y'] = event.mouse_region_y
                div_h = 5000.0 if event.shift else 500.0
                div_v = 3000.0 if event.shift else 300.0
                _state['sub_color_h'] = (_state['sub_color_h'] + dx / div_h) % 1.0
                _state['sub_color_v'] = max(0.0, min(1.0, _state['sub_color_v'] + dy / div_v))
                _set_brush_rgb(context, *colorsys.hsv_to_rgb(
                    _state['sub_color_h'], _state['sub_color_s'], _state['sub_color_v']))
                _wrap_cursor_at_window_edge(context, event)
                context.area.tag_redraw()
            elif event.type == 'WHEELUPMOUSE':
                step = 0.01 if event.shift else 0.05
                _state['sub_color_s'] = min(1.0, _state['sub_color_s'] + step)
                _set_brush_rgb(context, *colorsys.hsv_to_rgb(
                    _state['sub_color_h'], _state['sub_color_s'], _state['sub_color_v']))
                context.area.tag_redraw()
            elif event.type == 'WHEELDOWNMOUSE':
                step = 0.01 if event.shift else 0.05
                _state['sub_color_s'] = max(0.0, _state['sub_color_s'] - step)
                _set_brush_rgb(context, *colorsys.hsv_to_rgb(
                    _state['sub_color_h'], _state['sub_color_s'], _state['sub_color_v']))
                context.area.tag_redraw()
            elif event.type == 'LEFTMOUSE' and event.value == 'PRESS':
                _state['sub_mode'] = None          # keep new color
                _warp_cursor_to_sub_start(context)
                context.area.tag_redraw()
            elif event.type == 'RIGHTMOUSE' and event.value == 'PRESS':
                _set_brush_rgb(context, *_state['sub_orig_color'])
                _state['sub_mode'] = None
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
                        if _state['ctrl_line_active']:
                            space = context.space_data
                            if space and space.image and _state['back_buffer'] is not None:
                                space.image.pixels.foreach_set(_state['back_buffer'])
                                space.image.update()
                            _state['ctrl_line_active'] = False
                            _state['start_position']   = None
                            _state['back_buffer']      = None
                        elif mode == 'LINE':
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
                    _state['shift_pick_active']   = False
                    _state['shift_hovered_color'] = None
                    context.area.tag_redraw()
                    return {'PASS_THROUGH'}

            result = self.get_hovered_pixel(context, event)
            if result:
                _state['current_cx'], _state['current_cy'] = result[0], result[1]
            else:
                _state['current_cx'] = _state['current_cy'] = None

            # Shift eyedropper: sample color under cursor while shift is held
            if event.shift and not self.button_down and not self.button_right_down:
                _state['shift_pick_active'] = True
                _state['shift_region_x']    = event.mouse_region_x
                _state['shift_region_y']    = event.mouse_region_y
                cx, cy = _state['current_cx'], _state['current_cy']
                _state['shift_hovered_color'] = (
                    _get_image_pixel_color(context, cx, cy) if cx is not None else None)
            else:
                _state['shift_pick_active']   = False
                _state['shift_hovered_color'] = None

            if (self.button_down or self.button_right_down) and v2d:
                self.draw_pixels(context)
            context.area.tag_redraw()

        # Left mouse press: primary color stroke (or eyedropper pick)
        elif event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            if event.alt:
                return {'PASS_THROUGH'}

            # Ctrl+LMB: start a one-shot line draw (press = start, release = end).
            if event.ctrl:
                self.button_down         = True
                _state['use_secondary']  = False
                _state['last_paint_cx']  = None
                _state['last_paint_cy']  = None
                _state['ctrl_line_active'] = True
                space = context.space_data
                if space and space.image:
                    _undo_push(space.image)
                result = self.get_hovered_pixel(context, event)
                if result:
                    _state['current_cx'], _state['current_cy'] = result[0], result[1]
                if space and space.image and _state['current_cx'] is not None:
                    _state['back_buffer']    = np.array(space.image.pixels, dtype=np.float32)
                    _state['start_position'] = (_state['current_cx'], _state['current_cy'])
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}

            if _state['shift_pick_active'] and _state['shift_hovered_color'] is not None:
                picked = _state['shift_hovered_color']
                _set_brush_rgb(context, *picked)
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
            if mode == 'LINE':
                if space and space.image and _state['current_cx'] is not None:
                    _state['back_buffer']    = np.array(space.image.pixels, dtype=np.float32)
                    _state['start_position'] = (_state['current_cx'], _state['current_cy'])
            elif v2d:
                self.draw_pixels(context)

        # Left mouse release
        elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            if self.button_down:
                if _state['ctrl_line_active']:
                    if _state['start_position'] is not None:
                        self.draw_pixels(context)
                    _state['ctrl_line_active'] = False
                    _state['start_position']   = None
                    _state['back_buffer']      = None
                elif mode == 'LINE':
                    if _state['start_position'] is not None:
                        self.draw_pixels(context)
                    context.window_manager.pixel_painter_mode = _state['last_shape']
                    _state['start_position'] = None
                    _state['back_buffer']    = None
            _state['last_paint_cx'] = None
            _state['last_paint_cy'] = None
            _state['use_secondary'] = False
            self.button_down = False

        # Right mouse press: secondary color stroke
        elif event.type == 'RIGHTMOUSE' and event.value == 'PRESS':
            if event.ctrl or event.alt:
                return {'PASS_THROUGH'}

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
            if mode == 'LINE':
                if space and space.image and _state['current_cx'] is not None:
                    _state['back_buffer']    = np.array(space.image.pixels, dtype=np.float32)
                    _state['start_position'] = (_state['current_cx'], _state['current_cy'])
            elif v2d:
                self.draw_pixels(context)

        # Right mouse release
        elif event.type == 'RIGHTMOUSE' and event.value == 'RELEASE':
            if self.button_right_down:
                if mode == 'LINE':
                    if _state['start_position'] is not None:
                        self.draw_pixels(context)
                    context.window_manager.pixel_painter_mode = _state['last_shape']
                    _state['start_position'] = None
                    _state['back_buffer']    = None
            _state['last_paint_cx'] = None
            _state['last_paint_cy'] = None
            _state['use_secondary'] = False
            self.button_right_down = False

        # Ctrl / Alt PRESS while painting: cancel the active stroke immediately
        # so that shortcuts like Ctrl+Z don't keep painting on the next move.
        elif event.type in {'LEFT_CTRL', 'RIGHT_CTRL',
                            'LEFT_ALT',  'RIGHT_ALT'} and event.value == 'PRESS':
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

        # Shift PRESS: cancel any active stroke, then immediately activate the
        # eyedropper so the overlay appears without requiring a mouse move first.
        elif event.type in {'LEFT_SHIFT', 'RIGHT_SHIFT'} and event.value == 'PRESS':
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
            else:
                # Not painting — activate the eyedropper immediately using the
                # current cursor position (keyboard events carry mouse coords).
                cx, cy = _state['current_cx'], _state['current_cy']
                _state['shift_pick_active'] = True
                _state['shift_region_x']    = event.mouse_region_x
                _state['shift_region_y']    = event.mouse_region_y
                _state['shift_hovered_color'] = (
                    _get_image_pixel_color(context, cx, cy) if cx is not None else None)
            context.area.tag_redraw()

        # Shift RELEASE: clear the eyedropper overlay.
        elif event.type in {'LEFT_SHIFT', 'RIGHT_SHIFT'} and event.value == 'RELEASE':
            _state['shift_pick_active']   = False
            _state['shift_hovered_color'] = None
            context.area.tag_redraw()

        # V key: switch to line mode
        elif event.type == 'V' and event.value == 'PRESS':
            context.window_manager.pixel_painter_mode = 'LINE'

        # R key: enter opacity picker sub-mode
        elif event.type == 'R' and event.value == 'PRESS':
            _state['sub_mode']           = 'OPACITY'
            _state['sub_last_x']         = event.mouse_region_x
            _state['sub_last_y']         = event.mouse_region_y
            _state['sub_orig_opacity']   = _get_brush_opacity(context)
            _state['sub_orig_modifier']  = _get_modifier(context)
            _state['sub_total_delta']    = 0.0
            _state['sub_start_screen_x'] = event.mouse_x
            _state['sub_start_screen_y'] = event.mouse_y
            _state['sub_start_region_x'] = event.mouse_region_x
            _state['sub_start_region_y'] = event.mouse_region_y
            context.area.tag_redraw()

        # E key: enter color picker sub-mode
        elif event.type == 'E' and event.value == 'PRESS':
            rgb = _get_brush_rgb(context)
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
            _state['sub_last_x']         = event.mouse_region_x
            _state['sub_last_y']         = event.mouse_region_y
            _state['sub_orig_color']     = rgb
            _state['sub_start_screen_x'] = event.mouse_x
            _state['sub_start_screen_y'] = event.mouse_y
            _state['sub_start_region_x'] = event.mouse_region_x
            _state['sub_start_region_y'] = event.mouse_region_y
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
        self.button_down       = not is_rmb
        self.button_right_down = is_rmb
        self._disable_builtin_brush_overlay(context)
        _state['running']        = True
        _state['use_secondary']  = is_rmb
        _state['current_cx']     = None
        _state['current_cy']     = None
        _state['start_position'] = None
        _state['back_buffer']    = None
        _state['last_paint_cx']  = None
        _state['last_paint_cy']  = None

        # Push undo for the FIRST stroke — the press that triggered invoke is
        # not re-delivered to the modal, so the modal PRESS handler won't fire.
        space = context.space_data
        if space and space.image:
            _undo_push(space.image)

        # Paint the initial pixel under the cursor on press.
        mode   = context.window_manager.pixel_painter_mode
        result = self.get_hovered_pixel(context, event)
        if result:
            _state['current_cx'], _state['current_cy'] = result[0], result[1]
            if mode == 'LINE':
                if space and space.image:
                    _state['back_buffer']    = np.array(space.image.pixels, dtype=np.float32)
                    _state['start_position'] = (_state['current_cx'], _state['current_cy'])
            else:
                self.draw_pixels(context)

        _register_draw_handler(context.space_data, context)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}
