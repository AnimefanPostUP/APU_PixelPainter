"""WorkspaceTool definitions and pie menus."""
import math
import os

import blf
import bpy
import bpy.utils.previews
import gpu
from bpy.types import WorkSpaceTool, Menu, Operator
from gpu_extras.batch import batch_for_shader
from gpu_extras.presets import draw_texture_2d

from . import tool_settings_ui


_preview_collection = None
_mode_icon_scale = 2.7
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
    'hover_index': None,
}

_custom_pie_items = [
    ('CIRCLE', 'Circle'),
    ('SMOOTH', 'Smooth'),
    ('BLEND', 'Blend'),
    ('SPRAY', 'Spray'),
    ('SQUARE', 'Square'),
    ('SMEAR', 'Smear'),
]

_mode_icon_files = {
    'SQUARE': "Tool_Square.png",
    'CIRCLE': "Tool_Circle.png",
    'SPRAY': "Tool_Spray.png",
    'SMOOTH': "Tool_Smooth.png",
    'SMEAR': "Tool_Smear.png",
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


def _draw_text_centered(text, x, y, size=14):
    font_id = 0
    blf.size(font_id, size)
    w, h = blf.dimensions(font_id, text)
    blf.position(font_id, x - w * 0.5, y - h * 0.5, 0)
    blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
    blf.draw(font_id, text)


def _get_mode_gpu_texture(mode):
    path = None
    filename = _mode_icon_files.get(mode)
    if filename:
        path = os.path.join(os.path.dirname(__file__), "textures", filename)
    if not path or not os.path.exists(path):
        return None

    cache = _custom_pie_state.setdefault('gpu_textures', {})
    if mode in cache:
        return cache[mode]

    try:
        img = bpy.data.images.load(path, check_existing=True)
        tex = gpu.texture.from_image(img)
        cache[mode] = tex
        return tex
    except Exception:
        return None


def _draw_mode_icon(mode, cx, cy, size):
    tex = _get_mode_gpu_texture(mode)
    if tex is None:
        return False
    x = cx - size * 0.5
    y = cy - size * 0.5
    try:
        draw_texture_2d(tex, (x, y), size, size)
        return True
    except Exception:
        return False


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
    hover = _custom_pie_state['hover_index']
    try:
        current_mode = bpy.context.window_manager.pixel_painter_mode
    except Exception:
        current_mode = None
    ring_r = 95
    item_r = 28

    _draw_circle(cx, cy, 22, (0.12, 0.12, 0.12, 0.95))

    for i, (mode, label) in enumerate(_custom_pie_items):
        vx, vy = _custom_pie_dirs[i]
        ix = cx + vx * ring_r
        iy = cy + vy * ring_r
        if i == hover:
            col = (0.26, 0.52, 0.95, 0.95)
        elif mode != 'BLEND' and mode == current_mode:
            col = (0.16, 0.62, 0.32, 0.95)
        else:
            col = (0.18, 0.18, 0.18, 0.9)
        _draw_circle(ix, iy, item_r, col)
        if not _draw_mode_icon(mode, ix, iy, 32):
            _draw_text_centered(label, ix, iy, 12)
        else:
            _draw_text_centered(label, ix, iy - 30, 10)


def _remove_custom_pie_draw_handler():
    handler = _custom_pie_state.get('draw_handler')
    if handler is not None:
        try:
            bpy.types.SpaceImageEditor.draw_handler_remove(handler, 'WINDOW')
        except Exception:
            pass
        _custom_pie_state['draw_handler'] = None
    _custom_pie_state['gpu_textures'] = {}


class PixelPainterCustomPieOperator(Operator):
    bl_idname = "image.pixel_painter_custom_pie"
    bl_label = "Pixel Painter Custom Pie"

    def _apply_selection(self, context):
        idx = _custom_pie_state.get('hover_index')
        if idx is None:
            return
        mode = _custom_pie_items[idx][0]
        if mode == 'BLEND':
            bpy.ops.wm.call_menu_pie(name="PIXELPAINTER_MT_blend_pie")
        else:
            bpy.ops.image.pixel_painter_set_mode(mode=mode)

    def _finish(self, context):
        _custom_pie_state['running'] = False
        _custom_pie_state['hover_index'] = None
        _remove_custom_pie_draw_handler()
        if context.area:
            context.area.tag_redraw()

    def invoke(self, context, event):
        if not context.area or context.area.type != 'IMAGE_EDITOR':
            return {'CANCELLED'}

        _custom_pie_state['running'] = True
        _custom_pie_state['center_x'] = event.mouse_region_x
        _custom_pie_state['center_y'] = event.mouse_region_y
        _custom_pie_state['hover_index'] = None

        _remove_custom_pie_draw_handler()
        _custom_pie_state['draw_handler'] = bpy.types.SpaceImageEditor.draw_handler_add(
            _draw_custom_pie_overlay, (), 'WINDOW', 'POST_PIXEL')

        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if not context.area or context.area.type != 'IMAGE_EDITOR':
            self._finish(context)
            return {'CANCELLED'}

        if event.type == 'MOUSEMOVE':
            _custom_pie_state['hover_index'] = _pick_custom_pie_index(
                event.mouse_region_x, event.mouse_region_y)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        if event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            self._finish(context)
            return {'CANCELLED'}

        # Keep menu open until explicit left-click selection.
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            if _custom_pie_state.get('hover_index') is not None:
                self._apply_selection(context)
                self._finish(context)
                return {'FINISHED'}
            return {'RUNNING_MODAL'}

        # Optional keyboard confirm
        if event.type in {'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            if _custom_pie_state.get('hover_index') is not None:
                self._apply_selection(context)
                self._finish(context)
                return {'FINISHED'}
            return {'RUNNING_MODAL'}

        return {'RUNNING_MODAL'}


def register_icons():
    """Load custom tool icons from the addon textures folder."""
    global _preview_collection
    unregister_icons()

    pcoll = bpy.utils.previews.new()
    textures_dir = os.path.join(os.path.dirname(__file__), "textures")

    icon_files = {
        'SQUARE': "Tool_Square.png",
        'CIRCLE': "Tool_Circle.png",
        'SPRAY':  "Tool_Spray.png",
        'SMOOTH': "Tool_Smooth.png",
        'SMEAR':  "Tool_Smear.png",
    }

    for key, filename in icon_files.items():
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
    if _preview_collection is None:
        return 0
    icon = _preview_collection.get(mode_name)
    return icon.icon_id if icon else 0


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


class PixelPainterModePie(Menu):
    bl_idname = "PIXELPAINTER_MT_mode_pie"
    bl_label  = "Drawing Mode"

    def draw(self, context):
        layout = self.layout
        pie    = layout.menu_pie()
        pie.scale_x = 1.0
        pie.scale_y = 1.0

        _draw_mode_operator_slot(pie, 'CIRCLE', "Circle")
        _draw_mode_operator_slot(pie, 'SMOOTH', "Smooth")
        op = pie.operator("wm.call_menu_pie", text="Blend")
        op.name = "PIXELPAINTER_MT_blend_pie"
        _draw_mode_operator_slot(pie, 'SPRAY', "Spray")
        _draw_mode_operator_slot(pie, 'SQUARE', "Square")
        _draw_mode_operator_slot(pie, 'SMEAR', "Smear")


def _add_blend_item(layout, label, blend, favorites):
    icon = 'CHECKMARK' if blend in favorites else 'BLANK1'
    layout.operator("image.pixel_painter_set_blend", text=label, icon=icon).blend = blend


class PixelPainterBlendPie(Menu):
    bl_idname = "PIXELPAINTER_MT_blend_pie"
    bl_label  = "Blend Mode"

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

        # Keep the final two slots empty.
        pie.separator()
        pie.separator()


class PixelPainterTool(WorkSpaceTool):
    bl_space_type   = 'IMAGE_EDITOR'
    bl_context_mode = 'PAINT'

    bl_idname      = "image.pixel_painter_tool"
    bl_label       = "Pixel Painter"
    bl_description = "Paint pixel-perfect strokes in the Image Editor"
    bl_icon        = "ops.generic.select_box"
    bl_operator    = "image.pixel_painter_operator"

    bl_keymap = (
        ("image.pixel_painter_operator", {"type": 'LEFTMOUSE',  "value": 'PRESS'}, None),
        ("image.pixel_painter_operator", {"type": 'RIGHTMOUSE', "value": 'PRESS'}, None),
        ("image.pixel_painter_undo",     {"type": 'Z', "value": 'PRESS', "ctrl": True}, None),
        ("image.pixel_painter_redo",     {"type": 'Z', "value": 'PRESS', "ctrl": True, "shift": True}, None),
        ("image.pixel_painter_custom_pie", {"type": 'W', "value": 'PRESS'}, None),
    )

    def draw_settings(context, layout, _tool):
        tool_settings_ui.draw_tool_settings(context, layout)
