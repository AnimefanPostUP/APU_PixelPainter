import bpy
import time
import math
from bpy.types import Operator
from ..ui.pie_menu_base import PieMenuBase
from ..ui.pie_operator import PieOperator
from ..ui.pie_grid import PieGrid
from ..ui.pie_utils import draw_circle, draw_text_centered, draw_rect, draw_rect_outline

class AnimatedPieMenu(PieMenuBase):
    def __init__(self, items, icons=None, ref_func=None, name="Animated Pie Menu"):
        super().__init__(name=name)
        self.operators = [
            PieOperator(label, (icons or {}).get(id), idx, id, ref_func=ref_func)
            for idx, (id, label) in enumerate(items)
        ]
        self.update_hover(None)
        self.update_animations()

    def draw(self, layout, cx, cy, ring_r, item_r, open_ease=1.0, close_alpha=1.0, is_closing=False, closing_index=None, close_ease=0.0):
        # Zeichnet alle Operatoren im Kreis mit Animationen
        n = len(self.operators)
        for idx, op in enumerate(self.operators):
            angle = (idx / n) * 2 * math.pi
            op_cx = cx + math.cos(angle) * ring_r * open_ease
            op_cy = cy + math.sin(angle) * ring_r * open_ease
            op.draw(layout, op_cx, op_cy, ring_r, item_r, open_ease, close_alpha, idx == self.hover_index, is_closing, closing_index, close_ease)
        self.draw_shapes(layout)
        self.draw_active_line(layout)

class AnimatedPieMenuOperator(Operator):
    bl_idname = "wm.animated_pie_menu"
    bl_label = "Animated Pie Menu (OO)"

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
        # Beispiel: Mode-Pie
        from ..ui.custompie_tools import _custom_pie_items, _mode_icon_files
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
            # Hover-Logik: Finde Index des nächsten Operators
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
            # Auswahl/Schließen
            self.is_closing = True
            self.closing_index = self.menu.hover_index
            self.close_started_at = time.perf_counter()
            context.area.tag_redraw()
        elif event.type == 'TIMER':
            context.area.tag_redraw()
        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            self.finish(context)
            return {'CANCELLED'}
        # Closing-Animation
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
        open_ease = PieMenuBase.ease_in_out(open_t)
        close_alpha = 1.0 - self.close_ease if self.is_closing else 1.0
        self.menu.draw(None, self.cx, self.cy, self.ring_r, self.item_r, open_ease, close_alpha, self.is_closing, self.closing_index, self.close_ease)

# Registrierung für Blender
classes = [AnimatedPieMenuOperator]
def register():
    for cls in classes:
        bpy.utils.register_class(cls)
def unregister():
    for cls in classes:
        bpy.utils.unregister_class(cls)
