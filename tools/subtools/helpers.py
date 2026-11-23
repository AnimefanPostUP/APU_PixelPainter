"""Shared helper functions used by sub-mode handlers."""


COLOR_PICK_H_DIV = 500.0
COLOR_PICK_V_DIV = 300.0

# Saturation slider to the right of the color-pick sheet (region px, relative to
# the sheet; the sheet is COLOR_PICK_H_DIV x COLOR_PICK_V_DIV around the start).
SAT_BAR_GAP = 6.0
SAT_BAR_W = 24.0
SAT_BAR_HIT_MARGIN = 10.0   # extra grab area around the bar (pens are imprecise)
SAT_TAP_TRAVEL = 4.0        # less pointer travel than this = a tap (jump to the spot)

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


def color_pick_offset(h, v):
    """``(dx, dy)`` from the picker center to the spot that represents ``h``/``v``."""
    h = float(h) % 1.0
    v = max(0.0, min(1.0, float(v)))
    delta_h = h - 0.5
    if delta_h < -0.5:
        delta_h += 1.0
    elif delta_h >= 0.5:
        delta_h -= 1.0
    return delta_h * COLOR_PICK_H_DIV, (v - 0.5) * COLOR_PICK_V_DIV


def sat_bar_rect(state):
    """``(x0, y0, x1, y1)`` of the saturation slider, or None before the picker is placed."""
    rx = state.get('sub_start_region_x')
    ry = state.get('sub_start_region_y')
    if rx is None or ry is None:
        return None
    x0 = rx + COLOR_PICK_H_DIV * 0.5 + SAT_BAR_GAP
    return x0, ry - COLOR_PICK_V_DIV * 0.5, x0 + SAT_BAR_W, ry + COLOR_PICK_V_DIV * 0.5


def over_sat_bar(state, x, y, margin=SAT_BAR_HIT_MARGIN):
    """Whether region point ``x``/``y`` grabs the saturation slider."""
    rect = sat_bar_rect(state)
    if rect is None or x is None or y is None:
        return False
    x0, y0, x1, y1 = rect
    return x0 - margin <= x <= x1 + margin and y0 - margin <= y <= y1 + margin


def in_sat_column(state, x):
    """Whether ``x`` lies in the strip between the sheet's right edge and the slider's
    grab area -- the pointer is heading for the slider, so hue / value hold still."""
    rect = sat_bar_rect(state)
    if rect is None or x is None:
        return False
    return rect[0] - SAT_BAR_GAP <= x <= rect[2] + SAT_BAR_HIT_MARGIN


def sat_at(state, y):
    """Saturation shown at height ``y`` on the slider (clamped to 0..1)."""
    rect = sat_bar_rect(state)
    if rect is None:
        return None
    return max(0.0, min(1.0, (y - rect[1]) / (rect[3] - rect[1])))


def warp_cursor_to_color_pick_hv(state, context, h, v, warp=False):
    """Place the picker cursor at the position that represents ``h``/``v`` relative to center.

    Always updates the tracked (fake) cursor; with ``warp=True`` the OS cursor
    is moved there as well.
    """
    dx, dy = color_pick_offset(h, v)

    sx = state.get('sub_start_screen_x')
    sy = state.get('sub_start_screen_y')
    rx = state.get('sub_start_region_x')
    ry = state.get('sub_start_region_y')
    if sx is None or sy is None or rx is None or ry is None:
        return

    target_sx = int(round(sx + dx))
    target_sy = int(round(sy + dy))
    target_rx = int(round(rx + dx))
    target_ry = int(round(ry + dy))

    try:
        max_x = max(0, int(context.window.width) - 1)
        max_y = max(0, int(context.window.height) - 1)
        clamped_sx = max(0, min(max_x, target_sx))
        clamped_sy = max(0, min(max_y, target_sy))
        target_rx += (clamped_sx - target_sx)
        target_ry += (clamped_sy - target_sy)
        target_sx = clamped_sx
        target_sy = clamped_sy
    except Exception:
        pass

    if warp:
        try:
            context.window.cursor_warp(target_sx, target_sy)
        except Exception:
            pass

    state['sub_last_x'] = target_rx
    state['sub_last_y'] = target_ry
    state['sub_color_total_dx'] = dx
    state['sub_color_total_dy'] = dy


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
