from bpy.types import Operator
from .ring_segment_pie import RingSegmentPieOperator
# GPU drawing imports
import gpu
from gpu_extras.batch import batch_for_shader
# Gruppen-Definition für Blendmodes (mit Farben)
_blend_groups = [
    {
        'name': 'Basic',
        'modes': ['MIX', 'ADD', 'MUL', 'DARKEN', 'LIGHTEN', 'COLOR'],
        'border_color': (0.7, 0.7, 1.0, 1.0)
    },
    {
        'name': 'Contrast',
        'modes': ['SCREEN', 'OVERLAY', 'SOFTLIGHT', 'HARDLIGHT'],
        'border_color': (1.0, 0.8, 0.3, 1.0)
    },
    {
        'name': 'Math',
        'modes': ['SUB', 'DIFFERENCE', 'EXCLUSION', 'COLORDODGE', 'COLORBURN'],
        'border_color': (0.8, 0.4, 0.4, 1.0)
    },
    {
        'name': 'HSL/HSV',
        'modes': ['HUE', 'SATURATION', 'VALUE', 'LUMINOSITY'],
        'border_color': (0.4, 0.8, 0.4, 1.0)
    },
]

# Operator für Ringsegment-Pie mit Gruppenabstand und Randfarben
class PixelPainterBlendRingSegmentPieOperator(Operator):
    bl_idname = "wm.pixel_painter_blend_ring_segment_pie"
    bl_label = "Pixel Painter Blend Ring Segment Pie"

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
        # Segment-Liste mit Gruppenabstand und Randfarben erzeugen
        segments = []
        border_colors = []
        for group in _blend_groups:
            for mode in group['modes']:
                segments.append({
                    'label': _blend_labels[mode],
                    'color': (0.5, 0.5, 0.5, 0.95),  # Grau statt Blau
                    'border_color': group['border_color'],
                })
            # Füge Dummy-Segment für Abstand hinzu (transparent, keine Linie)
            segments.append({'label': '', 'color': (0,0,0,0), 'border_color': (0,0,0,0), 'is_gap': True})
        if segments and segments[-1].get('is_gap'):
            segments.pop()  # Letzten Abstand entfernen
        self.menu = BlendRingSegmentPieMenu(self.cx, self.cy, self.ring_r_inner, self.ring_r_outer, segments)
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

    def draw_callback(self, context, *args):
        if self.menu:
            self.menu.draw()

# Erweiterte Menüklasse für Segment-Gruppen und Randfarben
class BlendRingSegmentPieMenu(RingSegmentPieOperator):
    def draw(self):
        n = len(self.segments)
        # Berechne effektive Segmente (inkl. Gaps)
        angle_step = 2 * math.pi / n
        for i, seg in enumerate(self.segments):
            if seg.get('is_gap'):
                continue  # Lücke lassen
            angle_start = i * angle_step + 0.04  # kleiner Abstand links
            angle_end = (i + 1) * angle_step - 0.04  # kleiner Abstand rechts
            color = seg.get('color', (0.5, 0.5, 0.5, 1.0))
            border_color = seg.get('border_color', (0.1, 0.1, 0.1, 1.0))
            highlight = (i == self.active_index)
            self.draw_ring_segment(angle_start, angle_end, color, highlight, border_color=border_color)
            if 'label' in seg and seg['label']:
                self.draw_label_in_segment(angle_start, angle_end, seg['label'])

    def draw_ring_segment(self, angle_start, angle_end, color, highlight=False, steps=32, border_color=(0.1,0.1,0.1,1.0)):
        cx, cy = self.cx, self.cy
        inner_r = self.inner_radius
        outer_r = self.outer_radius
        inner_points = [
            (cx + math.cos(a) * inner_r, cy + math.sin(a) * inner_r)
            for a in self.linspace(angle_start, angle_end, steps)
        ]
        outer_points = [
            (cx + math.cos(a) * outer_r, cy + math.sin(a) * outer_r)
            for a in self.linspace(angle_end, angle_start, steps)
        ]
        verts = inner_points + outer_points
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        batch = batch_for_shader(shader, 'TRI_FAN', {'pos': verts})
        shader.bind()
        if highlight:
            color = (min(color[0]+0.2,1.0), min(color[1]+0.2,1.0), min(color[2]+0.2,1.0), color[3])
        shader.uniform_float('color', color)
        batch.draw(shader)
        # Border lines
        self.draw_segment_borders(angle_start, angle_end, inner_r, outer_r, border_color)

    def draw_segment_borders(self, angle_start, angle_end, inner_r, outer_r, border_color):
        cx, cy = self.cx, self.cy
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        # Two radial lines (dickere Outline)
        gpu.state.line_width_set(4.0)
        for angle in (angle_start, angle_end):
            p1 = (cx + math.cos(angle) * inner_r, cy + math.sin(angle) * inner_r)
            p2 = (cx + math.cos(angle) * outer_r, cy + math.sin(angle) * outer_r)
            batch = batch_for_shader(shader, 'LINES', {'pos': [p1, p2]})
            shader.bind()
            shader.uniform_float('color', border_color)
            batch.draw(shader)
        # Outer arc
        steps = 48
        arc_points = [
            (cx + math.cos(a) * outer_r, cy + math.sin(a) * outer_r)
            for a in self.linspace(angle_start, angle_end, steps)
        ]
        batch = batch_for_shader(shader, 'LINE_STRIP', {'pos': arc_points})
        shader.bind()
        shader.uniform_float('color', border_color)
        batch.draw(shader)
        gpu.state.line_width_set(1.0)

    def draw_label_in_segment(self, angle_start, angle_end, label):
        # Text entlang des Bogens zeichnen, auf linker/rechter Seite um 180° drehen
        import blf
        cx, cy = self.cx, self.cy
        r = (self.inner_radius + self.outer_radius) * 0.5
        angle_mid = (angle_start + angle_end) * 0.5
        # Entscheide, ob Text gedreht werden muss (linke/rechte Seite)
        angle_deg = math.degrees(angle_mid)
        flip = angle_deg > 90 and angle_deg < 270
        font_id = 0
        blf.size(font_id, 14)
        text = label
        # Textbreite bestimmen
        text_width, text_height = blf.dimensions(font_id, text)
        # Position auf dem Bogen
        tx = cx + math.cos(angle_mid) * (r + 10)
        ty = cy + math.sin(angle_mid) * (r + 10)
        blf.position(font_id, tx, ty, 0)
        blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
        blf.enable(font_id, blf.ROTATION)
        rot = angle_mid + (math.pi if flip else 0)
        blf.rotation(font_id, rot)
        blf.draw(font_id, text)
        blf.disable(font_id, blf.ROTATION)
        # Two arcs (inner and outer)
        for r in (inner_r, outer_r):
            arc_points = [
                (cx + math.cos(a) * r, cy + math.sin(a) * r)
                for a in self.linspace(angle_start, angle_end, 32)
            ]
            batch = batch_for_shader(shader, 'LINE_STRIP', {'pos': arc_points})
            shader.bind()
            shader.uniform_float('color', border_color)
            batch.draw(shader)
import bpy
from bpy.types import Operator
import time
import math

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

_blend_order = (
    'MIX', 'ADD', 'MUL', 'DARKEN', 'LIGHTEN', 'COLOR',
    'SCREEN', 'OVERLAY', 'SOFTLIGHT', 'HARDLIGHT',
    'SUB', 'DIFFERENCE', 'EXCLUSION', 'COLORDODGE', 'COLORBURN',
    'HUE', 'SATURATION', 'VALUE', 'LUMINOSITY',
)

_default_favorites = ('MIX', 'ADD', 'MUL', 'DARKEN', 'LIGHTEN', 'COLOR')

from .pie_grid import PieGrid
from .pie_operator import PieOperator

from .pie_menu_base import PieMenuBase

from .animated_pie_menu import AnimatedPieMenu

# === AnimatedPieMenu für Falloff Pie ===
_falloff_pie_items = [
    ('CONSTANT', 'Constant'),
    ('SMOOTH', 'Smooth'),
    ('CUSTOM', 'Custom'),
    ('LINEAR', 'Linear'),
    ('SPHERE', 'Sphere'),
    ('SHARPEN', 'Sharpen'),
]
_mode_icon_files = {
    'CONSTANT': "Falloff_Const.png",
    'LINEAR': "Falloff_Linea.png",
    'SMOOTH_FALLOFF': "Falloff_Smooth.png",
    'SMOOTH': "Falloff_Smooth.png",
    'SPHERE': "Falloff_Sphere.png",
    'SHARPEN': "Falloff_Sharpen.png",
}
def _falloff_icon_key(item_id):
    if item_id == 'SMOOTH':
        return 'SMOOTH_FALLOFF'
    return item_id

class PixelPainterBlendPie(AnimatedPieMenu):
    bl_idname = "PIXELPAINTER_MT_blend_pie"
    bl_label = "Blend Mode"

    def __init__(self):
        super().__init__(
            items=[(blend, _blend_labels[blend]) for blend in _blend_order],
            icons=None,
            ref_func=lambda: bpy.context.window_manager.pixel_painter_blend,
            name="Blend Mode Pie"
        )

    def draw(self, layout, cx=0, cy=0, ring_r=120, item_r=28, open_ease=1.0, close_alpha=1.0, is_closing=False, closing_index=None, close_ease=0.0):
        super().draw(layout, cx, cy, ring_r, item_r, open_ease, close_alpha, is_closing, closing_index, close_ease)

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
                    if angle < 0:
                        angle += 2 * math.pi
                    sel_idx = int((angle / (2 * math.pi)) * n + 0.5) % n
            self.menu.update_hover(sel_idx)
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
        if not hasattr(self, 'open_started_at'):
            return
        now = time.perf_counter()
        open_t = min(1.0, max(0.0, (now - self.open_started_at) / 0.165))
        open_ease = PieMenuBase.ease_in_out(open_t)
        close_alpha = 1.0 - self.close_ease if self.is_closing else 1.0
        mx = self.last_mx if self.last_mx is not None else self.cx
        my = self.last_my if self.last_my is not None else self.cy
        self.menu.draw(None, self.cx, self.cy, self.ring_r, self.item_r, open_ease, close_alpha, self.is_closing, self.closing_index, self.close_ease, mx=mx, my=my)

class PixelPainterFalloffPie(AnimatedPieMenu):
    bl_idname = "PIXELPAINTER_MT_falloff_pie_oo"
    bl_label = "Brush Falloff"

    def __init__(self):
        super().__init__(
            items=_falloff_pie_items,
            icons=_mode_icon_files,
            ref_func=lambda: bpy.context.window_manager.pixel_painter_falloff,
            name="Brush Falloff Pie"
        )

    def draw(self, layout, cx=0, cy=0, ring_r=120, item_r=28, open_ease=1.0, close_alpha=1.0, is_closing=False, closing_index=None, close_ease=0.0):
        super().draw(layout, cx, cy, ring_r, item_r, open_ease, close_alpha, is_closing, closing_index, close_ease)

class PixelPainterFalloffPieOperator(Operator):
    bl_idname = "wm.pixel_painter_falloff_pie_oo"
    bl_label = "Pixel Painter Falloff Pie (OO)"

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
        self.handler = None
        self.last_mx = None
        self.last_my = None

    def invoke(self, context, event):
        self.menu = PixelPainterFalloffPie()
        self.cx = event.mouse_region_x
        self.cy = event.mouse_region_y
        self.last_mx = event.mouse_region_x
        self.last_my = event.mouse_region_y
        self.open_started_at = time.perf_counter()
        self.is_closing = False
        self.closing_index = None
        self.close_started_at = 0.0
        self.close_ease = 0.0
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
                    if angle < 0:
                        angle += 2 * math.pi
                    sel_idx = int((angle / (2 * math.pi)) * n + 0.5) % n
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
        if not hasattr(self, 'open_started_at'):
            return
        now = time.perf_counter()
        open_t = min(1.0, max(0.0, (now - self.open_started_at) / 0.165))
        open_ease = AnimatedPieMenu.ease_in_out(open_t)
        close_alpha = 1.0 - self.close_ease if self.is_closing else 1.0
        mx = self.last_mx if self.last_mx is not None else self.cx
        my = self.last_my if self.last_my is not None else self.cy
        self.menu.draw(None, self.cx, self.cy, self.ring_r, self.item_r, open_ease, close_alpha, self.is_closing, self.closing_index, self.close_ease, mx=mx, my=my)

# Registrierung für Blender
classes = [PixelPainterBlendPieOperator, PixelPainterFalloffPieOperator]
def register():
    for cls in classes:
        bpy.utils.register_class(cls)
def unregister():
    for cls in classes:
        bpy.utils.unregister_class(cls)


