"""Selection box geometry and pixel-region operations used by the Select tool."""

import bpy
import numpy as np

from ..core import history
from ..utils import blender_utils, native, pixel_io
from . import draw_blending


# ---------------------------------------------------------------------------
# Box geometry
# ---------------------------------------------------------------------------

def normalize_box(x0, y0, x1, y1):
    return (min(int(x0), int(x1)), min(int(y0), int(y1)), max(int(x0), int(x1)), max(int(y0), int(y1)))


def pick_handle(box, px, py, tolerance=1):
    """Handle under ``(px, py)``: 'N','NE',...,'MOVE' or None."""
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


def resize_box(box, handle, px, py):
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


def resize_box_mirrored(box, handle, px, py):
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


def center_box_for_region(region, cx, cy):
    if region is None or cx is None or cy is None:
        return None
    region_h, region_w = region.shape[:2]
    if region_w <= 0 or region_h <= 0:
        return None
    left = int(round(cx - (region_w - 1) * 0.5))
    bottom = int(round(cy - (region_h - 1) * 0.5))
    return (left, bottom, left + region_w - 1, bottom + region_h - 1)


def center_box_like_box(box, cx, cy):
    if box is None or cx is None or cy is None:
        return None
    left, bottom, right, top = box
    width = max(1, int(right) - int(left) + 1)
    height = max(1, int(top) - int(bottom) + 1)
    centered_left = int(round(cx - (width - 1) * 0.5))
    centered_bottom = int(round(cy - (height - 1) * 0.5))
    return (centered_left, centered_bottom, centered_left + width - 1, centered_bottom + height - 1)


def box_center(box):
    if box is None:
        return None
    left, bottom, right, top = box
    return ((left + right) * 0.5, (bottom + top) * 0.5)


# ---------------------------------------------------------------------------
# Pixel regions
# ---------------------------------------------------------------------------

def _tag_image_editors_redraw():
    try:
        for screen in bpy.data.screens:
            for area in screen.areas:
                if area.type in {'VIEW_3D', 'IMAGE_EDITOR'}:
                    area.tag_redraw()
    except Exception:
        pass


def extract_region(img, box):
    if img is None or box is None:
        return None
    width, height = img.size
    left = max(0, min(width - 1, int(box[0])))
    bottom = max(0, min(height - 1, int(box[1])))
    right = max(0, min(width - 1, int(box[2])))
    top = max(0, min(height - 1, int(box[3])))
    if right < left or top < bottom:
        return None
    arr = pixel_io.buffer(img).reshape(height, width, 4)   # read only
    return arr[bottom:top + 1, left:right + 1, :].copy()


def _write_image(img, arr):
    pixel_io.write(img, arr)   # uploads + tags image views for redraw


def blit_region(img, region, dest_left, dest_bottom, dest_box=None, clear_box=None, blend='MIX', opacity=1.0):
    """Blend ``region`` into ``img`` (scaled to ``dest_box``); returns the clipped box."""
    if img is None or region is None:
        return None
    width, height = img.size
    region_h, region_w = region.shape[:2]
    if region_w == 0 or region_h == 0:
        return None

    arr = pixel_io.read(img).reshape(height, width, 4)
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
    if native.enabled():
        flat = arr.reshape(-1)
        if native.blit_region(flat, width, height, region, dest_left, dest_bottom, dest_width, dest_height,
                              (clip_left, clip_bottom, clip_right, clip_top), blend, opacity) is not None:
            _write_image(img, flat)
            return clip_left, clip_bottom, clip_right, clip_top
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
    _write_image(img, arr)
    return clip_left, clip_bottom, clip_right, clip_top


# ---------------------------------------------------------------------------
# State operations (shared by the Select tool and its operators)
# ---------------------------------------------------------------------------

def dispose_preview(state):
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


def set_preview(state, region):
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
        dispose_preview(state)


def clear_pending_preview(state):
    state['selection_pending_action'] = None
    state['selection_pending_region'] = None
    state['selection_pending_source_box'] = None
    dispose_preview(state)


def clear_like_rmb(state, keep_clipboard=True):
    clear_pending_preview(state)
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


def start_paste_preview(state, region, anchor_center, source_box):
    """Show ``region`` as a pending PASTE centered on ``anchor_center``."""
    centered = center_box_for_region(region, anchor_center[0], anchor_center[1])
    if centered is None:
        return False
    state['selection_pending_source_box'] = source_box
    state['selection_box'] = centered
    state['selection_pending_action'] = 'PASTE'
    state['selection_pending_region'] = region.copy()
    set_preview(state, region)
    state['selection_hover_handle'] = None
    return True


def _blit_pending(context, state, region, dest_box, message):
    space = context.space_data
    blend = blender_utils.get_brush_blend_mode(context)
    strength = float(getattr(context.window_manager, 'pixel_painter_active_strength', 1.0))
    history.begin(space.image)
    new_box = blit_region(space.image, region, dest_box[0], dest_box[1],
                          dest_box=dest_box, blend=blend, opacity=strength)
    history.commit(space.image, message)
    return new_box


def apply_pending(context, state):
    """Write the pending MOVE / PASTE preview into the image (one undo step)."""
    action = state.get('selection_pending_action')
    region = state.get('selection_pending_region')
    dest_box = state.get('selection_box')
    clipboard = state.get('selection_clipboard')
    space = context.space_data
    if action is None or region is None or dest_box is None or not space or not space.image:
        return False

    new_box = _blit_pending(context, state, region, dest_box, "Pixel Painter Paste")
    if new_box is None:
        return False
    state['selection_box'] = new_box
    clear_pending_preview(state)
    if action == 'PASTE' and clipboard is not None:
        state['selection_pending_source_box'] = new_box
        state['selection_pending_action'] = 'PASTE'
        state['selection_pending_region'] = clipboard.copy()
        set_preview(state, clipboard)
    return True


def apply_stencil(context, state):
    """Stamp the stencil region at the current box (one undo step)."""
    region = state.get('selection_stencil_region')
    dest_box = state.get('selection_box')
    space = context.space_data
    if region is None or dest_box is None or not space or not space.image:
        return False
    new_box = _blit_pending(context, state, region, dest_box, "Pixel Painter Stencil")
    if new_box is None:
        return False
    state['selection_box'] = new_box
    return True


def toggle_stencil_mode(context, state):
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
                region = extract_region(space.image, selection_box)

    if region is None:
        return False

    clear_pending_preview(state)
    state['selection_stencil_restore_box'] = state.get('selection_box')
    state['selection_stencil_mode'] = True
    state['selection_stencil_region'] = region.copy()
    state['selection_hover_handle'] = None
    state['selection_active_handle'] = None
    centered = center_box_like_box(state['selection_stencil_restore_box'],
                                   state.get('current_cx'), state.get('current_cy'))
    if centered is not None:
        state['selection_box'] = centered
    if context.area:
        context.area.tag_redraw()
    return True
