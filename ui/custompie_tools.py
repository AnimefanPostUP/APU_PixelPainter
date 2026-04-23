from bpy.types import Operator
from .ring_segment_pie import RingSegmentPieOperator
# Alternativer Operator für Ringsegment-Pie-Menü
class PixelPainterRingSegmentPieOperator(Operator):
    bl_idname = "wm.pixel_painter_ring_segment_pie"
    bl_label = "Pixel Painter Ring Segment Pie"

    def __init__(self):
        self.menu = None
        self.cx = 0
        self.cy = 0
        self.ring_r_inner = 70
        self.ring_r_outer = 120
        self.active_index = None
        self.handler = None

    def invoke(self, context, event):
        self.cx = event.mouse_region_x
        self.cy = event.mouse_region_y
        segments = [
            {"label": label, "color": (0.3 + 0.1*i, 0.3, 0.7-0.1*i, 0.95)}
            for i, (id, label) in enumerate(_custom_pie_items)
        ]
        self.menu = RingSegmentPieOperator(self.cx, self.cy, self.ring_r_inner, self.ring_r_outer, segments)
        args = (self, context)
        self.handler = bpy.types.SpaceImageEditor.draw_handler_add(self.draw_callback, args, 'WINDOW', 'POST_PIXEL')
        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type in {'RIGHTMOUSE', 'ESC'}:
            self.finish(context)
            return {'CANCELLED'}
        if event.type == 'MOUSEMOVE':
            mx = event.mouse_region_x
            my = event.mouse_region_y
            # Segment-Hover-Logik (optional)
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            # Auswahl-Logik (optional)
            self.finish(context)
            return {'FINISHED'}
        return {'RUNNING_MODAL'}

    def finish(self, context):
        if self.handler:
            bpy.types.SpaceImageEditor.draw_handler_remove(self.handler, 'WINDOW')
            self.handler = None
        context.area.tag_redraw()

    def draw_callback(self, context):
        if self.menu:
            self.menu.draw()

# Optional: Menüfunktion zum einfachen Aufruf
def call_ring_segment_pie(self, context):
    bpy.ops.wm.pixel_painter_ring_segment_pie('INVOKE_DEFAULT')
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

    def draw(self, layout, cx=0, cy=0, ring_r=120, item_r=28, open_ease=1.0, close_alpha=1.0, is_closing=False, closing_index=None, close_ease=0.0, mx=None, my=None):
        print("[DEBUG] PixelPainterModePie.draw() called", flush=True)
        # Tools im Halbkreis anordnen (links bis rechts, oben)
        n = len(self.operators)
        if n == 0:
            return
        if mx is None:
            mx, my = cx, cy
        # Halbkreis: 0° (rechts) bis 180° (links), also 0 bis pi
        for i, op in enumerate(self.operators):
            angle = math.pi * (i / (n - 1))  # 0 (rechts) bis pi (links)
            r = ring_r * open_ease
            op_cx = cx + math.cos(angle) * r
            op_cy = cy + math.sin(angle) * r
            scale = 1.0
            is_selected = (i == self.direction_index)
            if is_selected:
                scale = 1.18
            closing_idx = closing_index if closing_index is not None else -1
            # PieOperator.draw erwartet: (cx, cy, item_r, open_ease, close_alpha, is_hovered, is_closing, closing_index, close_ease)
            op.draw(
                None, op_cx, op_cy, ring_r, item_r * scale, open_ease, close_alpha,
                is_selected, is_closing, closing_idx, close_ease
            )
        # Dann Falloff-Grid darunter
        from .custompie_tools_falloff import _falloff_pie_items, _mode_icon_files
        from ..ui.pie_menu import _get_falloff_grid_layout, _active_falloff_value, _draw_rect, _draw_rect_outline, _draw_mode_icon, _draw_text_centered
        import blf
        # Grid-Layout berechnen
        falloff_layout = _get_falloff_grid_layout(cx, cy)
        try:
            active_falloff = _active_falloff_value(bpy.context)
        except Exception:
            active_falloff = None
        # Überschrift
        panel_y1 = falloff_layout[0]['y0'] - 10.0 if falloff_layout else cy - 180.0
        blf.size(0, 12)
        blf.position(0, cx - 60, panel_y1, 0)
        blf.color(0, 1.0, 1.0, 1.0, 0.95 * close_alpha)
        blf.draw(0, "Brush Falloff")
        # Grid zeichnen
        for index, item in enumerate(falloff_layout):
            ix = item['cx']
            iy = item['cy']
            is_selected = (item['mode'] == active_falloff)
            button_size = item['size']
            half = button_size * 0.5
            x0 = ix - half
            y0 = iy - half
            x1 = ix + half
            y1 = iy + half
            # Farben
            if is_selected:
                fill = (0.66, 0.44, 0.92, 0.94 * close_alpha)
                border = (0.90, 0.80, 1.00, 0.95 * close_alpha)
                icon_alpha = 1.00 * close_alpha
            else:
                fill = (0.18, 0.18, 0.18, 0.92 * close_alpha)
                border = (0.30, 0.30, 0.30, 0.92 * close_alpha)
                icon_alpha = 0.78 * close_alpha
            _draw_rect(x0, y0, x1, y1, fill)
            _draw_rect_outline(x0, y0, x1, y1, border)
            icon_size = max(1, int(button_size * 0.62))
            icon_y = iy + (icon_size * 0.2)
            icon_key = item['mode'] if item['mode'] != 'SMOOTH' else 'SMOOTH_FALLOFF'
            icon_drawn = _draw_mode_icon(icon_key, ix, icon_y, icon_size, alpha=icon_alpha)
            label_alpha = max(0.72 * close_alpha, icon_alpha)
            if icon_drawn:
                label_y = iy - (button_size * 0.22)
            else:
                label_y = iy
            _draw_text_centered(item['label'], ix, label_y, size=10, alpha=label_alpha)

# --- Richtungscurve und Dreieck wie im AnimatedPieMenu ---
        dx = mx - cx
        dy = my - cy
        if n > 0 and (dx != 0 or dy != 0):
            d = math.sqrt(dx * dx + dy * dy)
            ux = dx / d
            uy = dy / d
            base_cx = cx + ux * 7.0
            base_cy = cy + uy * 7.0
            if hasattr(self, 'draw_triangle_arrow'):
                arrow_data = self.draw_triangle_arrow(base_cx, base_cy, mx, my, color=(0.66, 0.44, 0.92, 0.92 * close_alpha))
            else:
                arrow_data = None
            # Curve nur zeichnen, wenn draw_bezier_curve vorhanden und arrow_data existiert
            if arrow_data is not None and hasattr(self, 'draw_bezier_curve'):
                tx, ty = arrow_data['tip']
                ux, uy = arrow_data['dir']
                # Zielpunkt auf Tool-Kreis
                sel_idx = self.direction_index if self.direction_index is not None else 0
                angle = math.pi * (sel_idx / (n - 1))
                hix = cx + math.cos(angle) * ring_r * open_ease
                hiy = cy + math.sin(angle) * r * open_ease
                # Endpunkt etwas vor dem Tool-Kreis
                ex = hix - ux * 12.0
                ey = hiy - uy * 12.0
                p0 = (tx, ty)
                p1 = (tx + ux * 52.0, ty + uy * 52.0)
                p2 = (ex - ux * 4.0, ey - uy * 4.0)
                p3 = (ex, ey)
                self.draw_bezier_curve(p0, p1, p2, p3, color=(0.66, 0.44, 0.92, 0.70 * close_alpha))

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
        self.direction_index = None
        self.handler = None
        self.last_mx = None
        self.last_my = None
        self.falloff_hover_index = None

    def invoke(self, context, event):
        self.menu = PixelPainterModePie()
        self.cx = event.mouse_region_x
        self.cy = event.mouse_region_y
        self.last_mx = event.mouse_region_x
        self.last_my = event.mouse_region_y
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
        from ..ui.pie_menu import _get_falloff_grid_layout, _pick_falloff_grid_index, _falloff_pie_items
        if event.type == 'MOUSEMOVE':
            mx, my = event.mouse_region_x, event.mouse_region_y
            self.last_mx = mx
            self.last_my = my
            cx, cy = self.cx, self.cy
            # Prüfe ob Maus im Falloff-Grid ist
            falloff_idx = _pick_falloff_grid_index(mx, my, cx, cy)
            if falloff_idx is not None:
                self.falloff_hover_index = falloff_idx
            else:
                self.falloff_hover_index = None
            # Tool-Kreis Richtung
            n = len(self.menu.operators)
            sel_idx = None
            dx = mx - cx
            dy = my - cy
            if n > 0 and falloff_idx is None:
                if dx != 0 or dy != 0:
                    angle = math.atan2(dy, dx)
                    # Clamp auf [0, pi] für Halbkreis rechts->links
                    angle = max(0, min(math.pi, angle))
                    sel_idx = int((angle / math.pi) * (n - 1) + 0.5)
            self.menu.update_direction(sel_idx)
            self.menu.update_animations()
            context.area.tag_redraw()
        elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            # Auswahl im Falloff-Grid
            if self.falloff_hover_index is not None:
                idx = self.falloff_hover_index
                mode = _falloff_pie_items[idx][0]
                wm = context.window_manager
                if wm.pixel_painter_mode == 'SPRAY':
                    wm.pixel_painter_spray_falloff = mode
                else:
                    wm.pixel_painter_circle_falloff = mode
                self.is_closing = True
                self.closing_index = None
                self.close_started_at = time.perf_counter()
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}
            # Sonst Tool-Kreis-Auswahl
            self.is_closing = True
            self.closing_index = self.menu.direction_index
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
        mx = self.last_mx if self.last_mx is not None else self.cx
        my = self.last_my if self.last_my is not None else self.cy
        self.menu.draw(None, self.cx, self.cy, self.ring_r, self.item_r, open_ease, close_alpha, self.is_closing, self.closing_index, self.close_ease, mx=mx, my=my)

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
        self.direction_index = None
        self.handler = None
        self.last_mx = None
        self.last_my = None

    def invoke(self, context, event):
        from .custompie_blending import _blend_labels, _blend_order
        from .animated_pie_menu import AnimatedPieMenu
        items = [(blend, _blend_labels[blend]) for blend in _blend_order]
        self.menu = AnimatedPieMenu(items, icons=None, ref_func=lambda: context.window_manager.pixel_painter_blend)
        self.cx = event.mouse_region_x
        self.cy = event.mouse_region_y
        self.last_mx = event.mouse_region_x
        self.last_my = event.mouse_region_y
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
            self.last_mx = mx
            self.last_my = my
            cx, cy = self.cx, self.cy
            n = len(self.menu.operators)
            sel_idx = None
            dx = mx - cx
            dy = my - cy
            if n > 0:
                if dx != 0 or dy != 0:
                    angle = math.atan2(dy, dx)
                    # Clamp auf [0, pi] für Halbkreis rechts->links
                    angle = max(0, min(math.pi, angle))
                    sel_idx = int((angle / math.pi) * (n - 1) + 0.5)
            self.menu.update_direction(sel_idx)
            self.menu.update_animations()
            context.area.tag_redraw()
        elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            self.is_closing = True
            self.closing_index = self.menu.direction_index
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
        mx = self.last_mx if self.last_mx is not None else self.cx
        my = self.last_my if self.last_my is not None else self.cy
        self.menu.draw(None, self.cx, self.cy, self.ring_r, self.item_r, open_ease, close_alpha, self.is_closing, self.closing_index, self.close_ease, mx=mx, my=my)

# Registrierung für Blender
classes = [PixelPainterModePieOperator, PixelPainterBlendPieOperator]
def register():
    for cls in classes:
        bpy.utils.register_class(cls)
def unregister():
    for cls in classes:
        bpy.utils.unregister_class(cls)


