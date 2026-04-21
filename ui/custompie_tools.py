import bpy
import time
import math

_custom_pie_items = [
    ('CIRCLE', 'Circle'),
    ('SQUARE', 'Square'),
    ('SPRAY', 'Spray'),
    ('SMOOTH', 'Smooth'),
    ('SMEAR', 'Smear'),
    ('LINE', 'Line'),
    ('ERASER', 'Eraser'),
]

_mode_icon_files = {
    'SQUARE': "Tool_Square.png",
    'CIRCLE': "Tool_Circle.png",
    'SPRAY': "Tool_Spray.png",
    'SMOOTH': "Tool_Smooth.png",
    'SMEAR': "Tool_Smear.png",
    'LINE': "Tool_Line.png",
    'ERASER': "Tool_Eraser.png",
}


from bpy.types import Operator
from .pie_utils import draw_circle, draw_text_centered, draw_rect, draw_rect_outline
from .custompie_tools_falloff import _falloff_pie_items
from .custompie_blending import _blend_labels
from .pie_grid import PieGrid
from .pie_operator import PieOperator

from .pie_menu_base import PieMenuBase

from .animated_pie_menu import AnimatedPieMenu

class PixelPainterModePie(AnimatedPieMenu):
    bl_idname = "PIXELPAINTER_MT_mode_pie"
    bl_label = "Drawing Mode"

    def __init__(self):
        super().__init__(
            items=_custom_pie_items,
            icons=_mode_icon_files,
            ref_func=lambda: bpy.context.window_manager.pixel_painter_mode,
            name="Drawing Mode Pie"
        )

    def draw(self, layout, cx=0, cy=0, ring_r=120, item_r=28, open_ease=1.0, close_alpha=1.0, is_closing=False, closing_index=None, close_ease=0.0):
        super().draw(layout, cx, cy, ring_r, item_r, open_ease, close_alpha, is_closing, closing_index, close_ease)

class PixelPainterModePieOperator(Operator):
    bl_idname = "wm.pixel_painter_mode_pie_oo"
    bl_label = "Pixel Painter Mode Pie (OO)"

    def __init__(self):
        self.menu = None
        self.cx = 0
        self.cy = 0
        self.ring_r = 120
        self.item_r = 28
        self.open_started_at = 0.0
        self.is_closing = False
        self.closing_index = None
        self.close_started_at = 0.0
        self.close_ease = 0.0
        self.hover_index = None
        self.handler = None

    def invoke(self, context, event):
        from .custompie_tools import _custom_pie_items, _mode_icon_files
        self.menu = AnimatedPieMenu(_custom_pie_items, icons=_mode_icon_files, ref_func=lambda: context.window_manager.pixel_painter_mode)
        self.cx = event.mouse_region_x
        self.cy = event.mouse_region_y
        self.open_started_at = time.perf_counter()
        self.is_closing = False
        self.closing_index = None
        self.close_started_at = 0.0
        self.close_ease = 0.0
        self.hover_index = None
        self.handler = bpy.types.SpaceImageEditor.draw_handler_add(self.draw_callback, (), 'WINDOW', 'POST_PIXEL')
        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            mx, my = event.mouse_region_x, event.mouse_region_y
            n = len(self.menu.operators)
            best_idx = None
            best_dist = 1e9
            for idx, op in enumerate(self.menu.operators):
                angle = (idx / n) * 2 * math.pi
                op_cx = self.cx + math.cos(angle) * self.ring_r
                op_cy = self.cy + math.sin(angle) * self.ring_r
                dist = (mx - op_cx) ** 2 + (my - op_cy) ** 2
                if dist < best_dist:
                    best_dist = dist
                    best_idx = idx
            self.menu.update_hover(best_idx if best_dist < (self.item_r * 2) ** 2 else None)
            self.menu.update_animations()
            context.area.tag_redraw()
        elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            self.is_closing = True
            self.closing_index = self.menu.hover_index
            self.close_started_at = time.perf_counter()
            context.area.tag_redraw()
        elif event.type == 'TIMER':
            context.area.tag_redraw()
        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            self.finish(context)
            return {'CANCELLED'}
        if self.is_closing:
            t = min(1.0, max(0.0, (time.perf_counter() - self.close_started_at) / 0.15))
            self.close_ease = t
            if t >= 1.0:
                self.finish(context)
                return {'FINISHED'}
        return {'RUNNING_MODAL'}

    def finish(self, context):
        if self.handler:
            bpy.types.SpaceImageEditor.draw_handler_remove(self.handler, 'WINDOW')
            self.handler = None
        context.area.tag_redraw()

    def draw_callback(self):
        now = time.perf_counter()
        open_t = min(1.0, max(0.0, (now - self.open_started_at) / 0.165))
        open_ease = AnimatedPieMenu.ease_in_out(open_t)
        close_alpha = 1.0 - self.close_ease if self.is_closing else 1.0
        self.menu.draw(None, self.cx, self.cy, self.ring_r, self.item_r, open_ease, close_alpha, self.is_closing, self.closing_index, self.close_ease)

class PixelPainterBlendPieOperator(Operator):
    bl_idname = "wm.pixel_painter_blend_pie_oo"
    bl_label = "Pixel Painter Blend Pie (OO)"

    def __init__(self):
        self.menu = None
        self.cx = 0
        self.cy = 0
        self.ring_r = 120
        self.item_r = 28
        self.open_started_at = 0.0
        self.is_closing = False
        self.closing_index = None
        self.close_started_at = 0.0
        self.close_ease = 0.0
        self.hover_index = None
        self.handler = None

    def invoke(self, context, event):
        from .custompie_blending import _blend_labels, _blend_order
        from .animated_pie_menu import AnimatedPieMenu
        items = [(blend, _blend_labels[blend]) for blend in _blend_order]
        self.menu = AnimatedPieMenu(items, icons=None, ref_func=lambda: context.window_manager.pixel_painter_blend)
        self.cx = event.mouse_region_x
        self.cy = event.mouse_region_y
        self.open_started_at = time.perf_counter()
        self.is_closing = False
        self.closing_index = None
        self.close_started_at = 0.0
        self.close_ease = 0.0
        self.hover_index = None
        self.handler = bpy.types.SpaceImageEditor.draw_handler_add(self.draw_callback, (), 'WINDOW', 'POST_PIXEL')
        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            mx, my = event.mouse_region_x, event.mouse_region_y
            n = len(self.menu.operators)
            best_idx = None
            best_dist = 1e9
            for idx, op in enumerate(self.menu.operators):
                angle = (idx / n) * 2 * math.pi
                op_cx = self.cx + math.cos(angle) * self.ring_r
                op_cy = self.cy + math.sin(angle) * self.ring_r
                dist = (mx - op_cx) ** 2 + (my - op_cy) ** 2
                if dist < best_dist:
                    best_dist = dist
                    best_idx = idx
            self.menu.update_hover(best_idx if best_dist < (self.item_r * 2) ** 2 else None)
            self.menu.update_animations()
            context.area.tag_redraw()
        elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            self.is_closing = True
            self.closing_index = self.menu.hover_index
            self.close_started_at = time.perf_counter()
            context.area.tag_redraw()
        elif event.type == 'TIMER':
            context.area.tag_redraw()
        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            self.finish(context)
            return {'CANCELLED'}
        if self.is_closing:
            t = min(1.0, max(0.0, (time.perf_counter() - self.close_started_at) / 0.15))
            self.close_ease = t
            if t >= 1.0:
                self.finish(context)
                return {'FINISHED'}
        return {'RUNNING_MODAL'}

    def finish(self, context):
        if self.handler:
            bpy.types.SpaceImageEditor.draw_handler_remove(self.handler, 'WINDOW')
            self.handler = None
        context.area.tag_redraw()

    def draw_callback(self):
        now = time.perf_counter()
        open_t = min(1.0, max(0.0, (now - self.open_started_at) / 0.165))
        open_ease = AnimatedPieMenu.ease_in_out(open_t)
        close_alpha = 1.0 - self.close_ease if self.is_closing else 1.0
        self.menu.draw(None, self.cx, self.cy, self.ring_r, self.item_r, open_ease, close_alpha, self.is_closing, self.closing_index, self.close_ease)

# Registrierung für Blender
classes = [PixelPainterModePieOperator, PixelPainterBlendPieOperator]
def register():
    for cls in classes:
        bpy.utils.register_class(cls)
def unregister():
    for cls in classes:
        bpy.utils.unregister_class(cls)


