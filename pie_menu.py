"""Pie and custom radial menu UI for Pixel Painter."""
import math
import os
import time

import blf
import bpy
import bpy.utils.previews
import gpu
from bpy.types import Menu, Operator
from gpu_extras.batch import batch_for_shader
from gpu_extras.presets import draw_texture_2d


_preview_collection = None
_default_favorites = ('MIX', 'ADD', 'MUL', 'DARKEN', 'LIGHTEN', 'COLOR')
_blend_order = (
    'MIX', 'ADD', 'MUL', 'DARKEN', 'LIGHTEN', 'COLOR',
    'SCREEN', 'OVERLAY', 'SOFTLIGHT', 'HARDLIGHT',
    'SUB', 'DIFFERENCE', 'EXCLUSION', 'COLORDODGE', 'COLORBURN',
    'HUE', 'SATURATION', 'VALUE', 'LUMINOSITY',
)
_blend_labels = {
    'MIX': "Normal",
    'ADD': "Add",
    'MUL': "Multiply",
    'DARKEN': "Darken",
    'LIGHTEN': "Lighten",
    'COLOR': "Color",
    'SCREEN': "Screen",
    'OVERLAY': "Overlay",
    'SOFTLIGHT': "Soft Light",
    'HARDLIGHT': "Hard Light",
    'SUB': "Subtract",
    'DIFFERENCE': "Difference",
    'EXCLUSION': "Exclusion",
    'COLORDODGE': "Color Dodge",
    'COLORBURN': "Color Burn",
    'HUE': "Hue",
    'SATURATION': "Saturation",
    'VALUE': "Value",
    'LUMINOSITY': "Luminosity",
}

_custom_pie_state = {
    'running': False,
    'draw_handler': None,
    'center_x': 0,
    'center_y': 0,
    'start_mouse_x': 0,
    'start_mouse_y': 0,
    'mouse_x': 0,
    'mouse_y': 0,
    'hover_index': None,
    'hover_anim': [],
    'last_anim_time': 0.0,
    'curve_end_x': 0.0,
    'curve_end_y': 0.0,
    'curve_from_x': 0.0,
    'curve_from_y': 0.0,
    'curve_to_x': 0.0,
    'curve_to_y': 0.0,
    'curve_progress': 1.0,
    'curve_hover_index': None,
    'curve_initialized': False,
    'last_curve_time': 0.0,
    'open_started_at': 0.0,
    'is_closing': False,
    'close_started_at': 0.0,
    'closing_index': None,
    'timer': None,
}

_custom_pie_items = [
    ('CIRCLE', 'Circle'),
    ('SMOOTH', 'Smooth'),
    ('BLEND', 'Blend'),
    ('SPRAY', 'Spray'),
    ('SQUARE', 'Square'),
    ('SMEAR', 'Smear'),
]

_falloff_pie_items = [
    ('CONSTANT', 'Constant'),
    ('SMOOTH', 'Smooth'),
    ('CUSTOM', 'Custom'),
    ('LINEAR', 'Linear'),
    ('SPHERE', 'Sphere'),
    ('SHARPEN', 'Sharpen'),
]

_mode_icon_files = {
    'SQUARE': "Tool_Square.png",
    'CIRCLE': "Tool_Circle.png",
    'SPRAY': "Tool_Spray.png",
    'SMOOTH': "Tool_Smooth.png",
    'SMEAR': "Tool_Smear.png",
    'CONSTANT': "Falloff_Const.png",
    'LINEAR': "Falloff_Linea.png",
    'SMOOTH_FALLOFF': "Falloff_Smooth.png",
    'SPHERE': "Falloff_Sphere.png",
    'SHARPEN': "Falloff_Sharpen.png",
}

# left, right, bottom, top, top-left, top-right
_custom_pie_dirs = [
    (-1.0, 0.0),
    (1.0, 0.0),
    (0.0, -1.0),
    (0.0, 1.0),
    (-0.7, 0.7),
    (0.7, 0.7),
]


def register_icons():
    """Load custom tool icons from the addon textures folder."""
    global _preview_collection
    unregister_icons()

    pcoll = bpy.utils.previews.new()
    textures_dir = os.path.join(os.path.dirname(__file__), "textures")

    for key, filename in _mode_icon_files.items():
        path = os.path.join(textures_dir, filename)
        if os.path.exists(path):
            pcoll.load(key, path, 'IMAGE')

    _preview_collection = pcoll


def unregister_icons():
    global _preview_collection
    if _preview_collection is not None:
        bpy.utils.previews.remove(_preview_collection)
        _preview_collection = None


def _tool_icon_value(mode_name):
    if mode_name == 'SMOOTH':
        mode_name = 'SMOOTH'
    if _preview_collection is None:
        return 0
    icon = _preview_collection.get(mode_name)
    return icon.icon_id if icon else 0


def _custom_pie_items_for_type(pie_type):
    return _falloff_pie_items if pie_type == 'FALLOFF' else _custom_pie_items


def _falloff_icon_key(item_id):
    if item_id == 'SMOOTH':
        return 'SMOOTH_FALLOFF'
    return item_id


def _active_falloff_value(context):
    wm = context.window_manager
    return wm.pixel_painter_spray_falloff if wm.pixel_painter_mode == 'SPRAY' else wm.pixel_painter_circle_falloff


def _get_favorites(context):
    raw = getattr(context.window_manager, "pixel_painter_blend_favorites", _default_favorites)
    if isinstance(raw, (set, list, tuple)):
        selected = set(raw)
    elif isinstance(raw, str):
        selected = {raw} if raw else set()
    else:
        selected = set()
    if not selected:
        selected = set(_default_favorites)
    return selected


def _draw_mode_operator_slot(pie, mode, label):
    icon_value = _tool_icon_value(mode)
    if icon_value:
        pie.operator("image.pixel_painter_set_mode", text=label, icon_value=icon_value).mode = mode
    else:
        pie.operator("image.pixel_painter_set_mode", text=label).mode = mode


def _add_blend_item(layout, label, blend, favorites):
    icon = 'CHECKMARK' if blend in favorites else 'BLANK1'
    layout.operator("image.pixel_painter_set_blend", text=label, icon=icon).blend = blend


def _draw_circle(cx, cy, radius, color, segments=36):
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    verts = []
    for i in range(segments):
        a = (i / segments) * math.tau
        verts.append((cx + math.cos(a) * radius, cy + math.sin(a) * radius))
    batch = batch_for_shader(shader, 'TRI_FAN', {'pos': verts})
    shader.bind()
    shader.uniform_float('color', color)
    batch.draw(shader)


def _get_arrow_data(cx, cy, mx, my):
    dx = mx - cx
    dy = my - cy
    d2 = dx * dx + dy * dy
    if d2 < 1e-4:
        return None

    d = math.sqrt(d2)
    ux = dx / d
    uy = dy / d
    px = -uy
    py = ux

    base_dist = 12.0
    tri_len = 22.0
    tri_half_w = 7.0
    bx = cx + ux * base_dist
    by = cy + uy * base_dist
    tx = bx + ux * tri_len
    ty = by + uy * tri_len
    lx = bx + px * tri_half_w
    ly = by + py * tri_half_w
    rx = bx - px * tri_half_w
    ry = by - py * tri_half_w

    return {
        'tip': (tx, ty),
        'left': (lx, ly),
        'right': (rx, ry),
        'dir': (ux, uy),
    }


def _draw_triangle_arrow(cx, cy, mx, my, color=(0.66, 0.44, 0.92, 0.92)):
    data = _get_arrow_data(cx, cy, mx, my)
    if data is None:
        return None

    tx, ty = data['tip']
    lx, ly = data['left']
    rx, ry = data['right']

    verts = [(tx, ty), (lx, ly), (rx, ry)]
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'TRI_FAN', {'pos': verts})
    shader.bind()
    shader.uniform_float('color', color)
    batch.draw(shader)
    return data


def _draw_bezier_curve(p0, p1, p2, p3, color=(0.66, 0.44, 0.92, 0.70), segments=20):
    verts = []
    for i in range(segments + 1):
        t = i / segments
        it = 1.0 - t
        x = (
            it * it * it * p0[0]
            + 3.0 * it * it * t * p1[0]
            + 3.0 * it * t * t * p2[0]
            + t * t * t * p3[0]
        )
        y = (
            it * it * it * p0[1]
            + 3.0 * it * it * t * p1[1]
            + 3.0 * it * t * t * p2[1]
            + t * t * t * p3[1]
        )
        verts.append((x, y))

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'LINE_STRIP', {'pos': verts})
    gpu.state.line_width_set(3.0)
    shader.bind()
    shader.uniform_float('color', color)
    batch.draw(shader)
    gpu.state.line_width_set(1.0)


def _update_curve_endpoint(now, target_x, target_y, restart_transition=False):
    last = _custom_pie_state.get('last_curve_time', now)
    dt = max(0.0, min(0.1, now - last))
    _custom_pie_state['last_curve_time'] = now

    if not _custom_pie_state.get('curve_initialized', False):
        _custom_pie_state['curve_end_x'] = target_x
        _custom_pie_state['curve_end_y'] = target_y
        _custom_pie_state['curve_from_x'] = target_x
        _custom_pie_state['curve_from_y'] = target_y
        _custom_pie_state['curve_to_x'] = target_x
        _custom_pie_state['curve_to_y'] = target_y
        _custom_pie_state['curve_progress'] = 1.0
        _custom_pie_state['curve_initialized'] = True
        return target_x, target_y, 0.0

    cur_x = _custom_pie_state.get('curve_end_x', target_x)
    cur_y = _custom_pie_state.get('curve_end_y', target_y)
    to_x = _custom_pie_state.get('curve_to_x', target_x)
    to_y = _custom_pie_state.get('curve_to_y', target_y)

    # Only restart transition when explicitly requested (e.g. hover changed).
    if abs(target_x - to_x) > 1e-4 or abs(target_y - to_y) > 1e-4:
        if restart_transition:
            _custom_pie_state['curve_from_x'] = cur_x
            _custom_pie_state['curve_from_y'] = cur_y
            _custom_pie_state['curve_to_x'] = target_x
            _custom_pie_state['curve_to_y'] = target_y
            _custom_pie_state['curve_progress'] = 0.0
        else:
            _custom_pie_state['curve_from_x'] = target_x
            _custom_pie_state['curve_from_y'] = target_y
            _custom_pie_state['curve_to_x'] = target_x
            _custom_pie_state['curve_to_y'] = target_y
            _custom_pie_state['curve_progress'] = 1.0
            _custom_pie_state['curve_end_x'] = target_x
            _custom_pie_state['curve_end_y'] = target_y
            return target_x, target_y, 0.0

    progress = _custom_pie_state.get('curve_progress', 1.0)
    if progress < 1.0:
        progress = min(1.0, progress + (dt / 0.25 if dt > 0.0 else 0.0))

    from_x = _custom_pie_state.get('curve_from_x', cur_x)
    from_y = _custom_pie_state.get('curve_from_y', cur_y)
    to_x = _custom_pie_state.get('curve_to_x', target_x)
    to_y = _custom_pie_state.get('curve_to_y', target_y)
    nx = from_x + (to_x - from_x) * progress
    ny = from_y + (to_y - from_y) * progress

    _custom_pie_state['curve_end_x'] = nx
    _custom_pie_state['curve_end_y'] = ny
    _custom_pie_state['curve_progress'] = progress
    transition = 1.0 - progress
    return nx, ny, transition


def _update_hover_animation(now, hover_index, item_count):
    last = _custom_pie_state.get('last_anim_time', now)
    dt = max(0.0, min(0.1, now - last))
    _custom_pie_state['last_anim_time'] = now

    speed = dt / (0.4 / 6.0) if dt > 0.0 else 0.0
    anim = _custom_pie_state.get('hover_anim')
    if not isinstance(anim, list) or len(anim) != item_count:
        anim = [0.0] * item_count

    for i in range(len(anim)):
        target = 1.0 if i == hover_index else 0.0
        if anim[i] < target:
            anim[i] = min(target, anim[i] + speed)
        elif anim[i] > target:
            anim[i] = max(target, anim[i] - speed)

    _custom_pie_state['hover_anim'] = anim
    return anim


def _ease_in_out(t):
    t = max(0.0, min(1.0, t))
    # Smoothstep: ease-in-out with zero slope at both ends.
    return t * t * (3.0 - 2.0 * t)


def _ease_in(t):
    t = max(0.0, min(1.0, t))
    return t * t * t


def _ease_out(t):
    t = max(0.0, min(1.0, t))
    inv = 1.0 - t
    return 1.0 - inv * inv * inv


def _draw_text_centered(text, x, y, size=14, alpha=1.0):
    font_id = 0
    blf.size(font_id, size)
    w, h = blf.dimensions(font_id, text)
    blf.position(font_id, x - w * 0.5, y - h * 0.5, 0)
    blf.color(font_id, 1.0, 1.0, 1.0, alpha)
    blf.draw(font_id, text)


def _get_mode_gpu_texture(mode):
    filename = _mode_icon_files.get(mode)
    if not filename:
        return None
    path = os.path.join(os.path.dirname(__file__), "textures", filename)
    if not os.path.exists(path):
        return None

    cache = _custom_pie_state.setdefault('gpu_textures', {})
    if mode in cache:
        return cache[mode]

    try:
        img = bpy.data.images.load(path, check_existing=True)
        # Ensure PNG alpha is interpreted correctly for overlay drawing.
        if hasattr(img, "alpha_mode"):
            img.alpha_mode = 'PREMUL'
        tex = gpu.texture.from_image(img)
        cache[mode] = tex
        return tex
    except Exception:
        return None


def _draw_mode_icon(mode, cx, cy, size, alpha=1.0):
    tex = _get_mode_gpu_texture(mode)
    if tex is None or size <= 1.0 or alpha <= 0.05:
        return False
    x = cx - size * 0.5
    y = cy - size * 0.5
    try:
        gpu.state.blend_set('ALPHA_PREMULT')
        draw_texture_2d(tex, (x, y), size, size)
        gpu.state.blend_set('ALPHA')
        return True
    except Exception:
        gpu.state.blend_set('ALPHA')
        return False


def _draw_bubble_text_only(label, cx, cy, scale=1.0, alpha=1.0):
    _draw_text_centered(label, cx, cy, max(1, int(12 * scale)), alpha)


def _draw_bubble_icon_text(mode, label, cx, cy, item_r, scale=1.0, alpha=1.0):
    content_y_offset = item_r * 0.2 * scale
    icon_size = max(1, int(32 * scale))
    if _draw_mode_icon(mode, cx, cy + content_y_offset, icon_size, alpha):
        _draw_text_centered(label, cx, cy - 20 * scale + content_y_offset, max(1, int(10 * scale)), alpha)
        return
    _draw_text_centered(label, cx, cy + content_y_offset, max(1, int(12 * scale)), alpha)


def _pick_custom_pie_index(mx, my):
    cx = _custom_pie_state['center_x']
    cy = _custom_pie_state['center_y']
    dx = mx - cx
    dy = my - cy
    dist2 = dx * dx + dy * dy
    if dist2 < 16 * 16:
        return None

    dlen = math.sqrt(dist2)
    ux, uy = dx / dlen, dy / dlen
    best_i = None
    best_dot = -2.0
    for i, (vx, vy) in enumerate(_custom_pie_dirs):
        dot = ux * vx + uy * vy
        if dot > best_dot:
            best_dot = dot
            best_i = i
    return best_i


def _draw_custom_pie_overlay():
    if not _custom_pie_state['running']:
        return

    cx = _custom_pie_state['center_x']
    cy = _custom_pie_state['center_y']
    mx = _custom_pie_state.get('mouse_x', cx)
    my = _custom_pie_state.get('mouse_y', cy)
    hover = _custom_pie_state['hover_index']
    pie_type = _custom_pie_state.get('pie_type', 'MODE')
    pie_items = _custom_pie_items_for_type(pie_type)
    try:
        current_mode = bpy.context.window_manager.pixel_painter_mode
        active_falloff = _active_falloff_value(bpy.context)
    except Exception:
        current_mode = None
        active_falloff = None

    ring_r = 120
    item_r = 28
    now = time.perf_counter()
    open_t = min(1.0, max(0.0, (now - _custom_pie_state.get('open_started_at', now)) / 0.165))
    open_ease = _ease_out(open_t)

    is_closing = _custom_pie_state.get('is_closing', False)
    close_t = 0.0
    close_ease = 0.0
    close_alpha = 1.0
    closing_index = _custom_pie_state.get('closing_index')
    if is_closing:
        close_t = min(1.0, max(0.0, (now - _custom_pie_state.get('close_started_at', now)) / 0.125))
        close_ease = _ease_out(close_t)
        close_alpha = 1.0 - close_t
        hover = closing_index

    anim = _update_hover_animation(now, hover if not is_closing else None, len(pie_items))

    gpu.state.blend_set('ALPHA')

    _draw_circle(cx, cy, 22, (0.12, 0.12, 0.12, 0.95 * close_alpha))
    _draw_circle(cx, cy, 7, (0.66, 0.44, 0.92, 0.95 * close_alpha))
    arrow_data = _draw_triangle_arrow(cx, cy, mx, my, color=(0.66, 0.44, 0.92, 0.92 * close_alpha))

    if hover is not None and arrow_data is not None:
        hvx, hvy = _custom_pie_dirs[hover]
        hix = cx + hvx * ring_r
        hiy = cy + hvy * ring_r
        ht = anim[hover] if hover < len(anim) else 0.0
        hte = _ease_in_out(ht)
        hradius = item_r * (1.0 + 0.18 * hte)

        tx, ty = arrow_data['tip']
        ux, uy = arrow_data['dir']

        cdx = tx - hix
        cdy = ty - hiy
        cd2 = cdx * cdx + cdy * cdy
        if cd2 > 1e-6:
            cdl = math.sqrt(cd2)
            nx = cdx / cdl
            ny = cdy / cdl

            # End point is on hovered bubble rim, pointing toward the arrow.
            target_ex = hix + nx * hradius
            target_ey = hiy + ny * hradius
            prev_hover = _custom_pie_state.get('curve_hover_index')
            hover_changed = (prev_hover != hover)
            ex, ey, transition = _update_curve_endpoint(
                now, target_ex, target_ey, restart_transition=hover_changed)
            _custom_pie_state['curve_hover_index'] = hover

            # Pull back toward center only while fading to a new target.
            center_mix = 0.2 * transition
            ex = ex * (1.0 - center_mix) + cx * center_mix
            ey = ey * (1.0 - center_mix) + cy * center_mix

            # Use the animated endpoint direction for smooth curve attachment.
            edx = ex - hix
            edy = ey - hiy
            el2 = edx * edx + edy * edy
            if el2 > 1e-6:
                el = math.sqrt(el2)
                enx = edx / el
                eny = edy / el
            else:
                enx, eny = nx, ny

            # Make the end tangent face the curve start a bit more to avoid
            # overly sharp bending near the target bubble.
            esx = tx - ex
            esy = ty - ey
            es2 = esx * esx + esy * esy
            if es2 > 1e-6:
                esl = math.sqrt(es2)
                tsx = esx / esl
                tsy = esy / esl
            else:
                tsx, tsy = enx, eny

            efx = enx * 0.55 + tsx * 0.45
            efy = eny * 0.55 + tsy * 0.45

            # Mix with outward-center direction only during transition.
            ocx = ex - cx
            ocy = ey - cy
            oc2 = ocx * ocx + ocy * ocy
            if oc2 > 1e-6 and transition > 0.0:
                ocl = math.sqrt(oc2)
                ocx /= ocl
                ocy /= ocl
                orient_mix = 0.2 * transition
                efx = efx * (1.0 - orient_mix) + ocx * orient_mix
                efy = efy * (1.0 - orient_mix) + ocy * orient_mix

            ef2 = efx * efx + efy * efy
            if ef2 > 1e-6:
                efl = math.sqrt(ef2)
                efx /= efl
                efy /= efl
            else:
                efx, efy = enx, eny

            # Smooth attachment: soften the start tangent by blending arrow
            # direction with the live direction to the animated endpoint.
            sdx = ex - tx
            sdy = ey - ty
            sl2 = sdx * sdx + sdy * sdy
            if sl2 > 1e-6:
                sl = math.sqrt(sl2)
                tux = sdx / sl
                tuy = sdy / sl
            else:
                tux, tuy = ux, uy

            sux = ux * 0.55 + tux * 0.45
            suy = uy * 0.55 + tuy * 0.45
            su2 = sux * sux + suy * suy
            if su2 > 1e-6:
                sul = math.sqrt(su2)
                sux /= sul
                suy /= sul
            else:
                sux, suy = ux, uy

            p0 = (tx, ty)
            p1 = (tx + sux * 52.0, ty + suy * 52.0)
            p2 = (ex - efx * 4.0, ey - efy * 4.0)
            p3 = (ex, ey)
            _draw_bezier_curve(p0, p1, p2, p3, color=(0.66, 0.44, 0.92, 0.70 * close_alpha))
    else:
        _custom_pie_state['curve_initialized'] = False
        _custom_pie_state['curve_hover_index'] = None

    for i, (mode, label) in enumerate(pie_items):
        vx, vy = _custom_pie_dirs[i]
        ix = cx + vx * ring_r * open_ease
        iy = cy + vy * ring_r * open_ease
        if pie_type == 'FALLOFF':
            is_selected = (mode == active_falloff)
        else:
            is_selected = (mode != 'BLEND' and mode == current_mode)

        t = anim[i] if i < len(anim) else 0.0
        te = _ease_in_out(t)
        base_scale = 0.5 + 0.5 * open_ease
        radius = item_r * base_scale * (1.0 + 0.18 * te)

        bubble_alpha = close_alpha
        content_scale = base_scale
        content_alpha = close_alpha

        if is_closing:
            if i == closing_index:
                selected_target = item_r * 1.6
                radius = radius + (selected_target - radius) * close_ease
                content_scale = max(base_scale, radius / max(item_r, 1e-4))
            else:
                radius = radius * (1.0 - close_ease)
                content_scale = content_scale * (1.0 - close_ease)
            if radius <= 0.25 or bubble_alpha <= 0.01:
                continue

        if te > 0.0:
            # Thinner, softer bright outline.
            _draw_circle(ix, iy, radius + 1.9, (0.66, 0.44, 0.92, te * bubble_alpha))
            if is_selected:
                col = (0.66, 0.44, 0.92, 0.95 * bubble_alpha)
            else:
                col = (0.30 + 0.025 * te, 0.30 + 0.025 * te, 0.30 + 0.025 * te, (0.94 + 0.02 * te) * bubble_alpha)
        elif is_selected:
            col = (0.66, 0.44, 0.92, 0.95 * bubble_alpha)
        else:
            col = (0.18, 0.18, 0.18, 0.9 * bubble_alpha)

        _draw_circle(ix, iy, radius, col)
        if mode in {'BLEND', 'FALLOFF'}:
            _draw_bubble_text_only(label, ix, iy, scale=content_scale, alpha=content_alpha)
        else:
            icon_key = _falloff_icon_key(mode) if pie_type == 'FALLOFF' else mode
            _draw_bubble_icon_text(icon_key, label, ix, iy, item_r, scale=content_scale, alpha=content_alpha)

    gpu.state.blend_set('NONE')


def _remove_custom_pie_draw_handler():
    handler = _custom_pie_state.get('draw_handler')
    if handler is not None:
        try:
            bpy.types.SpaceImageEditor.draw_handler_remove(handler, 'WINDOW')
        except Exception:
            pass
        _custom_pie_state['draw_handler'] = None
    _custom_pie_state['gpu_textures'] = {}


def force_cleanup(window_manager=None):
    """Best-effort cleanup used during addon reload/unregister."""
    _custom_pie_state['running'] = False
    _custom_pie_state['hover_index'] = None
    _custom_pie_state['curve_initialized'] = False
    _custom_pie_state['curve_progress'] = 1.0
    _custom_pie_state['curve_hover_index'] = None
    _custom_pie_state['is_closing'] = False
    _custom_pie_state['closing_index'] = None

    wm = window_manager
    if wm is None:
        try:
            wm = bpy.context.window_manager
        except Exception:
            wm = None

    timer = _custom_pie_state.get('timer')
    if timer is not None and wm is not None:
        try:
            wm.event_timer_remove(timer)
        except Exception:
            pass
    _custom_pie_state['timer'] = None

    _remove_custom_pie_draw_handler()


class PixelPainterCustomPieOperator(Operator):
    bl_idname = "image.pixel_painter_custom_pie"
    bl_label = "Pixel Painter Custom Pie"

    pie_type: bpy.props.EnumProperty(
        name="Pie Type",
        items=[
            ('MODE', "Mode", "Mode selection pie"),
            ('FALLOFF', "Falloff", "Falloff selection pie"),
        ],
        default='MODE',
    )

    def execute(self, context):
        # UI button clicks call execute (no event), so re-invoke modal pie via timer.
        pie_type = self.pie_type

        def _open_custom_pie():
            try:
                bpy.ops.image.pixel_painter_custom_pie('INVOKE_DEFAULT', pie_type=pie_type)
            except Exception:
                pass
            return None

        bpy.app.timers.register(_open_custom_pie, first_interval=0.01)
        return {'FINISHED'}

    def _apply_selection(self, context):
        idx = _custom_pie_state.get('hover_index')
        if idx is None:
            return
        pie_type = _custom_pie_state.get('pie_type', 'MODE')
        pie_items = _custom_pie_items_for_type(pie_type)
        mode = pie_items[idx][0]
        if pie_type == 'FALLOFF':
            wm = context.window_manager
            if wm.pixel_painter_mode == 'SPRAY':
                wm.pixel_painter_spray_falloff = mode
            else:
                wm.pixel_painter_circle_falloff = mode
            return
        if mode == 'FALLOFF':
            def _open_falloff_pie():
                try:
                    bpy.ops.image.pixel_painter_custom_pie('INVOKE_DEFAULT', pie_type='FALLOFF')
                except Exception:
                    pass
                return None

            bpy.app.timers.register(_open_falloff_pie, first_interval=0.01)
        elif mode == 'BLEND':
            # Defer opening so the click that selected this entry cannot leak
            # into the freshly opened Blender pie menu.
            def _open_blend_pie():
                try:
                    bpy.ops.wm.call_menu_pie(name="PIXELPAINTER_MT_blend_pie")
                except Exception:
                    pass
                return None

            bpy.app.timers.register(_open_blend_pie, first_interval=0.01)
        else:
            bpy.ops.image.pixel_painter_set_mode(mode=mode)

    def _warp_cursor_to_start(self, context):
        start_x = _custom_pie_state.get('start_mouse_x')
        start_y = _custom_pie_state.get('start_mouse_y')
        if start_x is None or start_y is None:
            return
        try:
            context.window.cursor_warp(int(start_x), int(start_y))
        except Exception:
            pass

    def _finish(self, context, warp_to_start=False):
        """Clean up pie menu state."""
        if warp_to_start:
            self._warp_cursor_to_start(context)
        _custom_pie_state['running'] = False
        _custom_pie_state['hover_index'] = None
        _custom_pie_state['curve_initialized'] = False
        _custom_pie_state['is_closing'] = False
        _custom_pie_state['closing_index'] = None
        timer = _custom_pie_state.get('timer')
        if timer is not None:
            try:
                context.window_manager.event_timer_remove(timer)
            except Exception:
                pass
            _custom_pie_state['timer'] = None
        _remove_custom_pie_draw_handler()
        if context.area:
            context.area.tag_redraw()

    def invoke(self, context, event):
        if not context.area or context.area.type != 'IMAGE_EDITOR':
            return {'CANCELLED'}

        _custom_pie_state['running'] = True
        _custom_pie_state['center_x'] = event.mouse_region_x
        _custom_pie_state['center_y'] = event.mouse_region_y
        _custom_pie_state['start_mouse_x'] = event.mouse_x
        _custom_pie_state['start_mouse_y'] = event.mouse_y
        _custom_pie_state['mouse_x'] = event.mouse_region_x
        _custom_pie_state['mouse_y'] = event.mouse_region_y
        _custom_pie_state['hover_index'] = None
        _custom_pie_state['pie_type'] = self.pie_type
        _custom_pie_state['hover_anim'] = [0.0] * len(_custom_pie_items_for_type(self.pie_type))
        _custom_pie_state['last_anim_time'] = time.perf_counter()
        _custom_pie_state['curve_initialized'] = False
        _custom_pie_state['last_curve_time'] = _custom_pie_state['last_anim_time']
        _custom_pie_state['open_started_at'] = _custom_pie_state['last_anim_time']
        _custom_pie_state['is_closing'] = False
        _custom_pie_state['closing_index'] = None

        _remove_custom_pie_draw_handler()
        _custom_pie_state['draw_handler'] = bpy.types.SpaceImageEditor.draw_handler_add(
            _draw_custom_pie_overlay, (), 'WINDOW', 'POST_PIXEL')
        _custom_pie_state['timer'] = context.window_manager.event_timer_add(1.0 / 60.0, window=context.window)

        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if not context.area or context.area.type != 'IMAGE_EDITOR':
            self._finish(context)
            return {'CANCELLED'}

        if _custom_pie_state.get('is_closing'):
            if event.type == 'TIMER':
                close_t = min(1.0, max(0.0, (time.perf_counter() - _custom_pie_state.get('close_started_at', 0.0)) / 0.075))
                context.area.tag_redraw()
                if close_t >= 1.0:
                    self._apply_selection(context)
                    self._finish(context, warp_to_start=True)
                    return {'FINISHED'}
                return {'RUNNING_MODAL'}
            return {'RUNNING_MODAL'}

        if event.type == 'MOUSEMOVE':
            _custom_pie_state['mouse_x'] = event.mouse_region_x
            _custom_pie_state['mouse_y'] = event.mouse_region_y
            _custom_pie_state['hover_index'] = _pick_custom_pie_index(
                event.mouse_region_x, event.mouse_region_y)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        if event.type == 'TIMER':
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        if event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            self._finish(context)
            return {'CANCELLED'}

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            if _custom_pie_state.get('hover_index') is not None:
                _custom_pie_state['is_closing'] = True
                _custom_pie_state['closing_index'] = _custom_pie_state.get('hover_index')
                _custom_pie_state['close_started_at'] = time.perf_counter()
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}
            return {'RUNNING_MODAL'}

        if event.type in {'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            if _custom_pie_state.get('hover_index') is not None:
                _custom_pie_state['is_closing'] = True
                _custom_pie_state['closing_index'] = _custom_pie_state.get('hover_index')
                _custom_pie_state['close_started_at'] = time.perf_counter()
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}
            return {'RUNNING_MODAL'}

        return {'RUNNING_MODAL'}


class PixelPainterModePie(Menu):
    bl_idname = "PIXELPAINTER_MT_mode_pie"
    bl_label = "Drawing Mode"

    def draw(self, context):
        layout = self.layout
        pie = layout.menu_pie()
        pie.scale_x = 1.0
        pie.scale_y = 1.0

        # Explicitly fill pie slots so both Blend and Falloff are always shown.
        # Order: left, right, bottom, top, top-left, top-right, bottom-left, bottom-right
        _draw_mode_operator_slot(pie, 'CIRCLE', "Circle")
        _draw_mode_operator_slot(pie, 'SMOOTH', "Smooth")
        blend_op = pie.operator("wm.call_menu_pie", text="Blend")
        blend_op.name = "PIXELPAINTER_MT_blend_pie"
        pie.operator_context = 'INVOKE_DEFAULT'
        pie.operator("image.pixel_painter_custom_pie", text="Falloff").pie_type = 'FALLOFF'
        _draw_mode_operator_slot(pie, 'SPRAY', "Spray")
        _draw_mode_operator_slot(pie, 'SQUARE', "Square")
        _draw_mode_operator_slot(pie, 'SMEAR', "Smear")
        pie.separator()


class PixelPainterBlendPie(Menu):
    bl_idname = "PIXELPAINTER_MT_blend_pie"
    bl_label = "Blend Mode"

    def draw(self, context):
        layout = self.layout
        pie = layout.menu_pie()
        favorites = _get_favorites(context)

        contrast = pie.column(align=True)
        contrast.label(text="Contrast")
        _add_blend_item(contrast, "Screen", 'SCREEN', favorites)
        _add_blend_item(contrast, "Overlay", 'OVERLAY', favorites)
        _add_blend_item(contrast, "Soft Light", 'SOFTLIGHT', favorites)
        _add_blend_item(contrast, "Hard Light", 'HARDLIGHT', favorites)

        hsl = pie.column(align=True)
        hsl.label(text="HSL/HSV")
        _add_blend_item(hsl, "Hue", 'HUE', favorites)
        _add_blend_item(hsl, "Saturation", 'SATURATION', favorites)
        _add_blend_item(hsl, "Value", 'VALUE', favorites)
        _add_blend_item(hsl, "Luminosity", 'LUMINOSITY', favorites)

        math_col = pie.column(align=True)
        math_col.label(text="Math")
        math_grid = math_col.grid_flow(row_major=True, columns=3, even_columns=True, even_rows=True, align=True)
        _add_blend_item(math_grid, "Subtract", 'SUB', favorites)
        _add_blend_item(math_grid, "Difference", 'DIFFERENCE', favorites)
        _add_blend_item(math_grid, "Exclusion", 'EXCLUSION', favorites)
        _add_blend_item(math_grid, "Color Dodge", 'COLORDODGE', favorites)
        _add_blend_item(math_grid, "Color Burn", 'COLORBURN', favorites)
        math_grid.label(text="")

        common = pie.column(align=True)
        common.label(text="Favorites")
        common_grid = common.grid_flow(row_major=True, columns=3, even_columns=True, even_rows=True, align=True)
        for blend in _blend_order:
            if blend in favorites:
                _add_blend_item(common_grid, _blend_labels[blend], blend, favorites)

        pie.separator()
        pie.separator()
