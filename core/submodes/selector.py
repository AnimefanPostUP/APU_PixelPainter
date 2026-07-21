import bpy

from ...utils import blender_utils


def _selection_dispose_preview(state):
    image_name = state.get('selection_preview_image_name')
    state['selection_preview_texture'] = None
    state['selection_preview_image_name'] = None
    state['selection_overlay_region'] = None
    if not image_name:
        return
    image = bpy.data.images.get(image_name)
    if image is not None:
        try:
            bpy.data.images.remove(image)
        except Exception:
            pass


def _selection_set_preview(state, region):
    if region is None:
        return
    height, width = region.shape[:2]
    if width <= 0 or height <= 0:
        return
    try:
        state['selection_preview_texture'] = None
        state['selection_preview_image_name'] = None
        state['selection_pending_region'] = region.copy()
        state['selection_overlay_region'] = None
    except Exception:
        _selection_dispose_preview(state)


def _selection_clear_pending_preview(state):
    state['selection_pending_action'] = None
    state['selection_pending_region'] = None
    state['selection_pending_source_box'] = None
    state['selection_apply_button_bounds'] = None
    state['selection_cancel_button_bounds'] = None
    state['selection_copy_button_bounds'] = None
    state['selection_stencil_button_bounds'] = None
    _selection_dispose_preview(state)


def _selection_apply_pending(context, state, undo_push, undo_stack, blit_region_static):
    action = state.get('selection_pending_action')
    region = state.get('selection_pending_region')
    dest_box = state.get('selection_box')
    clipboard = state.get('selection_clipboard')
    space = context.space_data
    if action is None or region is None or dest_box is None or not space or not space.image:
        return False

    blend = blender_utils.get_brush_blend_mode(context)
    strength = float(getattr(context.window_manager, 'pixel_painter_active_strength', 1.0))

    undo_push(space.image)

    new_box = blit_region_static(
        space.image,
        region,
        dest_box[0],
        dest_box[1],
        dest_box=dest_box,
        blend=blend,
        opacity=strength,
    )

    if new_box is None:
        if undo_stack:
            undo_stack.pop()
        return False
    state['selection_box'] = new_box
    _selection_clear_pending_preview(state)
    if action == 'PASTE' and clipboard is not None:
        state['selection_pending_source_box'] = new_box
        state['selection_pending_action'] = 'PASTE'
        state['selection_pending_region'] = clipboard.copy()
        _selection_set_preview(state, clipboard)
    return True


def _selection_clear_like_rmb(state, keep_clipboard=True):
    _selection_clear_pending_preview(state)
    state['selection_box'] = None
    state['selection_hover_handle'] = None
    state['selection_active_handle'] = None
    state['selection_drag_mode'] = None
    state['selection_drag_start'] = None
    state['selection_drag_origin_box'] = None
    state['selection_move_pixels'] = None
    state['selection_move_source_box'] = None
    state['selection_stencil_mode'] = False
    state['selection_stencil_region'] = None
    state['selection_stencil_restore_box'] = None
    if not keep_clipboard:
        state['selection_clipboard'] = None


def _selection_toggle_stencil_mode(context, state, extract_region_fn):
    if state.get('selection_stencil_mode'):
        state['selection_stencil_mode'] = False
        state['selection_stencil_region'] = None
        restore_box = state.get('selection_stencil_restore_box')
        if restore_box is not None:
            state['selection_box'] = restore_box
        state['selection_stencil_restore_box'] = None
        state['selection_hover_handle'] = None
        state['selection_active_handle'] = None
        if context.area:
            context.area.tag_redraw()
        return True

    region = state.get('selection_pending_region')
    if region is None:
        clipboard = state.get('selection_clipboard')
        if clipboard is not None:
            region = clipboard.copy()
        else:
            selection_box = state.get('selection_box')
            space = context.space_data
            if selection_box is not None and space and space.image:
                region = extract_region_fn(space.image, selection_box)

    if region is None:
        return False

    _selection_clear_pending_preview(state)
    state['selection_stencil_restore_box'] = state.get('selection_box')
    state['selection_stencil_mode'] = True
    state['selection_stencil_region'] = region.copy()
    state['selection_hover_handle'] = None
    state['selection_active_handle'] = None
    cx = state.get('current_cx')
    cy = state.get('current_cy')
    centered = _selection_center_box_like_box(state['selection_stencil_restore_box'], cx, cy)
    if centered is not None:
        state['selection_box'] = centered
    if context.area:
        context.area.tag_redraw()
    return True


def _selection_update_paste_preview_position(context, state, cx, cy):
    region = state.get('selection_pending_region')
    if state.get('selection_pending_action') != 'PASTE' or region is None:
        return False
    anchor_center = _selection_box_center(state.get('selection_pending_source_box'))
    if anchor_center is None:
        if cx is None or cy is None:
            return False
        anchor_center = (cx, cy)
    centered = _selection_center_box_for_region(region, anchor_center[0], anchor_center[1])
    if centered is None:
        return False
    state['selection_box'] = centered
    if context.area:
        context.area.tag_redraw()
    return True


def _selection_button_hit(px, py, bounds):
    if bounds is None or px is None or py is None:
        return False
    x0, y0, x1, y1 = bounds
    return x0 <= px <= x1 and y0 <= py <= y1


def _selection_center_box_for_region(region, cx, cy):
    if region is None or cx is None or cy is None:
        return None
    region_h, region_w = region.shape[:2]
    if region_w <= 0 or region_h <= 0:
        return None
    left = int(round(cx - (region_w - 1) * 0.5))
    bottom = int(round(cy - (region_h - 1) * 0.5))
    return (left, bottom, left + region_w - 1, bottom + region_h - 1)


def _selection_center_box_like_box(box, cx, cy):
    if box is None or cx is None or cy is None:
        return None
    left, bottom, right, top = box
    width = max(1, int(right) - int(left) + 1)
    height = max(1, int(top) - int(bottom) + 1)
    centered_left = int(round(cx - (width - 1) * 0.5))
    centered_bottom = int(round(cy - (height - 1) * 0.5))
    return (centered_left, centered_bottom, centered_left + width - 1, centered_bottom + height - 1)


def _selection_box_center(box):
    if box is None:
        return None
    left, bottom, right, top = box
    return ((left + right) * 0.5, (bottom + top) * 0.5)


def _selection_apply_stencil(context, state, undo_push, undo_stack, blit_region_static):
    region = state.get('selection_stencil_region')
    dest_box = state.get('selection_box')
    space = context.space_data
    if region is None or dest_box is None or not space or not space.image:
        return False

    state['selection_box'] = dest_box

    blend = blender_utils.get_brush_blend_mode(context)
    strength = float(getattr(context.window_manager, 'pixel_painter_active_strength', 1.0))

    undo_push(space.image)
    new_box = blit_region_static(
        space.image,
        region,
        dest_box[0],
        dest_box[1],
        dest_box=dest_box,
        blend=blend,
        opacity=strength,
    )
    if new_box is None:
        if undo_stack:
            undo_stack.pop()
        return False
    state['selection_box'] = new_box
    return True
