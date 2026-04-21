import math
import time
from .pie_operator import PieOperator
from .pie_grid import PieGrid
from .pie_utils import draw_circle, draw_text_centered, draw_rect, draw_rect_outline

class PieMenuBase:
    # --- Utility: Bubble/Icon/Text ---
    def draw_bubble_icon_text(self, mode, label, cx, cy, item_r, scale=1.0, alpha=1.0):
        # Versuche das Icon zu zeichnen wie in _draw_bubble_icon_text
        try:
            from . import pie_menu
            icon_drawn = False
            if hasattr(pie_menu, '_draw_mode_icon'):
                icon_drawn = pie_menu._draw_mode_icon(mode, cx, cy + item_r * 0.2 * scale, max(1, int(32 * scale)), alpha)
            if icon_drawn:
                draw_text_centered(label, cx, cy - 20 * scale + item_r * 0.2 * scale, max(1, int(10 * scale)), alpha)
                return
        except Exception:
            pass
        draw_text_centered(label, cx, cy + item_r * 0.2 * scale, max(1, int(12 * scale)), alpha)

    # --- Utility: Arrow/Curve/Panel/Grid-Layout (Platzhalter, können nach Bedarf erweitert werden) ---
    # Diese Methoden können aus pie_menu.py übernommen und ggf. angepasst werden.
    # Beispiel: Panel-Layout, Arrow, Curve, etc.
    # def get_falloff_grid_layout(...): ...
    # def draw_triangle_arrow(...): ...
    # def draw_bezier_curve(...): ...
    # def get_panel_layout(...): ...
    # def is_point_in_rect(...): ...
    # def pick_grid_index(...): ...
    # ...
    def __init__(self, name="Pie Menu"):
        self.name = name
        self.operators = []
        self.grids = []
        self.shapes = []
        self.active_element = None
        self.hover_index = None
        self.anim = []
        self.last_anim_time = time.perf_counter()
        self.open_started_at = self.last_anim_time
        self.is_closing = False
        self.close_started_at = 0.0
        self.closing_index = None
        self.curve_initialized = False
        self.curve_progress = 1.0
        self.curve_hover_index = None
        self.curve_end_x = 0.0
        self.curve_end_y = 0.0
        self.curve_from_x = 0.0
        self.curve_from_y = 0.0
        self.curve_to_x = 0.0
        self.curve_to_y = 0.0
        self.last_curve_time = self.last_anim_time

    def add_operator(self, operator: PieOperator):
        self.operators.append(operator)

    def add_grid(self, grid: PieGrid):
        self.grids.append(grid)

    def add_shape(self, shape_type, position, label=None):
        self.shapes.append({
            "type": shape_type,
            "position": position,
            "label": label,
        })

    def set_active_element(self, index, position):
        self.active_element = {"index": index, "position": position}

    def update_hover(self, hover_index):
        self.hover_index = hover_index

    def update_animations(self):
        now = time.perf_counter()
        dt = max(0.0, min(0.1, now - self.last_anim_time))
        self.last_anim_time = now
        if not self.anim or len(self.anim) != len(self.operators):
            self.anim = [0.0] * len(self.operators)
        speed = dt / (0.4 / 6.0) if dt > 0.0 else 0.0
        for i in range(len(self.anim)):
            target = 1.0 if i == self.hover_index else 0.0
            if self.anim[i] < target:
                self.anim[i] = min(target, self.anim[i] + speed)
            elif self.anim[i] > target:
                self.anim[i] = max(target, self.anim[i] - speed)
        for idx, op in enumerate(self.operators):
            op.update_anim(idx == self.hover_index, dt)

    @staticmethod
    def ease_in_out(t):
        t = max(0.0, min(1.0, t))
        return t * t * (3.0 - 2.0 * t)

    def draw(self, layout, cx, cy, ring_r, item_r, open_ease=1.0, close_alpha=1.0, is_closing=False, closing_index=None, close_ease=0.0):
        # Zeichnet alle Operatoren im Kreis
        n = len(self.operators)
        for idx, op in enumerate(self.operators):
            angle = (idx / n) * 2 * math.pi
            op_cx = cx + math.cos(angle) * ring_r * open_ease
            op_cy = cy + math.sin(angle) * ring_r * open_ease
            op.draw(layout, op_cx, op_cy, ring_r, item_r, open_ease, close_alpha, idx == self.hover_index, is_closing, closing_index, close_ease)
        # Shapes und aktive Linie
        self.draw_shapes(layout)
        self.draw_active_line(layout)

    def draw_shapes(self, layout):
        for shape in self.shapes:
            if shape["type"] == "circle":
                draw_circle(shape["position"][0], shape["position"][1], 20, (0.8, 0.8, 0.8, 1.0))
            elif shape["type"] == "square":
                x, y = shape["position"]
                draw_rect(x-20, y-20, x+20, y+20, (0.8, 0.8, 0.8, 1.0))

    def draw_active_line(self, layout):
        if self.active_element:
            # Hier könnte draw_line(x0, y0, x1, y1, color) stehen, falls in pie_utils vorhanden
            pass

    # Event-Handling (z.B. für Modal Operator)
    def handle_event(self, event):
        pass
