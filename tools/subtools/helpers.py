"""Shared helper functions used by sub-mode handlers."""


# State shared by the modal sub-modes (color pick / strength); each sub-mode
# merges this into its own ``state_defaults``.
SUB_MODE_STATE = {
    'sub_mode':           None,  # 'STRENGTH' | 'COLOR_PICK' | None
    'sub_last_x':         None,
    'sub_last_y':         None,
    'sub_fake_cursor_x':  None,
    'sub_fake_cursor_y':  None,
    'sub_start_screen_x': None,
    'sub_start_screen_y': None,
    'sub_start_region_x': None,
    'sub_start_region_y': None,
}


def set_sub_start_to_event(state, event):
    """Store sub-mode start at the cursor position when sub-mode was opened."""
    state['sub_start_screen_x'] = event.mouse_x
    state['sub_start_screen_y'] = event.mouse_y
    state['sub_start_region_x'] = event.mouse_region_x
    state['sub_start_region_y'] = event.mouse_region_y


def warp_cursor_to_sub_start(state, context):
    """Warp OS cursor back to where the sub-mode was entered."""
    sx = state.get('sub_start_screen_x')
    sy = state.get('sub_start_screen_y')
    if sx is not None and sy is not None:
        try:
            context.window.cursor_warp(sx, sy)
        except Exception:
            pass


def wrap_cursor_at_window_edge(state, context, event):
    """Loop cursor to opposite edge when near bounds; preserve smooth deltas."""
    win_w = context.window.width
    win_h = context.window.height

    margin = 12
    try:
        area = context.area
        if area:
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            space = context.space_data
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
        if new_mx != mx:
            state['sub_last_x'] = event.mouse_region_x + (new_mx - mx)
        if new_my != my:
            state['sub_last_y'] = event.mouse_region_y + (new_my - my)
