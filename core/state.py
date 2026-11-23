"""Shared runtime state ("blackboard") read by tools and canvas overlays.

The draw handler must NOT hold a reference to the operator instance because
Blender frees the instance while the handler may still be registered, so
everything the overlays draw lives in this module-level dict. Tools write the
keys they own; overlays in ``tools/draw_functions.py`` / ``tools/overlays*.py``
read them.
"""

from ..utils.settings_service import PixelPainterSettingsService


_DEFAULTS = {
    # ---- core / session ------------------------------------------------------
    'running':        False,  # True while the persistent modal is active
    'current_cx':     None,   # image pixel under the cursor
    'current_cy':     None,
    'draw_handler':   None,
    'draw_space':     None,
    'outline_timer':  None,
    'last_observed_raw_radius': None,
    'mouse_region':   None,   # (x, y) mouse in WINDOW-region coords (last cursor update)
    # ---- stroke tools ----------------------------------------------------------
    'start_position':     None,  # (cx, cy) when a LINE stroke started
    'back_buffer':        None,  # pixel snapshot for clean line preview
    'last_shape':         'SQUARE',  # tip shape used by LINE
    'last_paint_cx':      None,
    'last_paint_cy':      None,
    'last_paint_mouse':   None,  # region mouse at the last paint (3D: screen-space interpolation)
    'stroke_painted':     None,  # set of (px,py) painted this stroke (SQUARE / Pixel-mode guard)
    'stroke_weight_map':  None,  # dict (px,py)->max_weight for CIRCLE/SPRAY Pixel mode
    'stroke_back_buffer': None,  # pre-stroke image snapshot for CIRCLE/SPRAY Pixel mode
    'use_secondary':      False,  # True while painting with the secondary color (RMB)
    'outline_immediate':  False,  # outline follows the cursor without tweening
    # ---- sub-mode overlays (color pick / strength) -----------------------------
    'sub_mode':           None,  # 'STRENGTH' | 'COLOR_PICK' | None
    'sub_last_x':         None,
    'sub_last_y':         None,
    'sub_fake_cursor_x':  None,
    'sub_fake_cursor_y':  None,
    'sub_strength_virtual_x': None,
    'sub_strength_virtual_y': None,
    'sub_strength_hover_target': 'STRENGTH',
    'sub_edit_button':    'LMB',  # which button's settings STRENGTH edits
    'sub_orig_strength':  None,
    'sub_orig_alpha':     None,
    'sub_orig_modifier':  None,
    'sub_total_delta':    0.0,
    'sub_orig_color':     None,
    'sub_orig_color_secondary': None,
    'sub_color_target':   'PRIMARY',
    'sub_color_h':        None,
    'sub_color_s':        None,
    'sub_color_v':        None,
    'sub_color_start_h':  None,
    'sub_color_start_v':  None,
    'sub_color_total_dx': 0.0,
    'sub_color_total_dy': 0.0,
    'sub_start_screen_x': None,
    'sub_start_screen_y': None,
    'sub_start_region_x': None,
    'sub_start_region_y': None,
    # ---- hold-Ctrl eyedropper --------------------------------------------------
    'ctrl_pick_active':   False,
    'ctrl_hovered_color': None,
    'ctrl_region_x':      None,
    'ctrl_region_y':      None,
    # ---- outline position tween ----------------------------------------------
    'outline_display_cx': None,
    'outline_display_cy': None,
    'outline_from_cx':    None,
    'outline_from_cy':    None,
    'outline_to_cx':      None,
    'outline_to_cy':      None,
    'outline_anim_start': 0.0,
    # ---- selection tool --------------------------------------------------------
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

# Survive the end of a modal session (handles are cleaned up explicitly).
_PERSISTENT_KEYS = frozenset({
    'draw_handler', 'draw_space', 'outline_timer',
    'last_shape', 'selection_clipboard',
    'selection_preview_image_name', 'selection_preview_texture',
})


STATE = dict(_DEFAULTS)
SETTINGS = PixelPainterSettingsService()


def reset_session():
    """Reset all per-session keys to their defaults."""
    for key, value in _DEFAULTS.items():
        if key not in _PERSISTENT_KEYS:
            STATE[key] = value
