
import math
from .pie_utils import draw_circle, draw_text_centered

class PieOperator:
    def __init__(self, label, icon, position, id, ref_func=None):
        self.label = label
        self.icon = icon
        self.position = position
        self.id = id
        self.ref_func = ref_func  # Callable returning current value
        self.anim = 0.0  # Fading/hover animation state

    def is_selected(self):
        return self.id == self.ref_func() if self.ref_func else False

    def update_anim(self, hover, dt):
        target = 1.0 if hover else 0.0
        speed = dt / (0.4 / 6.0) if dt > 0.0 else 0.0
        if self.anim < target:
            self.anim = min(target, self.anim + speed)
        elif self.anim > target:
            self.anim = max(target, self.anim - speed)

    @staticmethod
    def ease_in_out(t):
        t = max(0.0, min(1.0, t))
        return t * t * (3.0 - 2.0 * t)

    def draw(self, layout, cx, cy, ring_r, item_r, open_ease, close_alpha, is_hovered, is_closing, closing_index, close_ease):
        # Animation/Fading/Selektion-Logik
        t = self.anim
        te = self.ease_in_out(t)
        base_scale = 0.5 + 0.5 * open_ease
        radius = item_r * base_scale * (1.0 + 0.18 * te)
        bubble_alpha = close_alpha
        content_scale = base_scale
        content_alpha = close_alpha
        idx = self.position
        # Closing-Animation
        if is_closing:
            if idx == closing_index:
                selected_target = item_r * 1.6
                radius = radius + (selected_target - radius) * close_ease
                content_scale = max(base_scale, radius / max(item_r, 1e-4))
            else:
                radius = radius * (1.0 - close_ease)
                content_scale = content_scale * (1.0 - close_ease)
            if radius <= 0.25 or bubble_alpha <= 0.01:
                return
        # Farben
        if te > 0.0:
            # Thinner, softer bright outline.
            draw_circle(cx, cy, radius + 1.9, (0.66, 0.44, 0.92, te * bubble_alpha))
            if self.is_selected():
                col = (0.66, 0.44, 0.92, 0.95 * bubble_alpha)
            else:
                col = (0.30 + 0.025 * te, 0.30 + 0.025 * te, 0.30 + 0.025 * te, (0.94 + 0.02 * te) * bubble_alpha)
        elif self.is_selected():
            col = (0.66, 0.44, 0.92, 0.95 * bubble_alpha)
        else:
            col = (0.18, 0.18, 0.18, 0.9 * bubble_alpha)
        draw_circle(cx, cy, radius, col)
        # Icon/Text
        if self.icon:
            # Versuche das Icon als Bild zu zeichnen (wie _draw_mode_icon in pie_menu.py)
            try:
                from . import pie_menu
                icon_drawn = False
                if hasattr(pie_menu, '_draw_mode_icon'):
                    icon_drawn = pie_menu._draw_mode_icon(self.id, cx, cy, max(1, int(32 * content_scale)), content_alpha)
                if icon_drawn:
                    draw_text_centered(self.label, cx, cy - 20 * content_scale, max(1, int(10 * content_scale)), content_alpha)
                else:
                    draw_text_centered(self.label, cx, cy, max(1, int(12 * content_scale)), content_alpha)
            except Exception:
                draw_text_centered(self.label, cx, cy, max(1, int(12 * content_scale)), content_alpha)
        else:
            draw_text_centered(self.label, cx, cy, max(1, int(12 * content_scale)), content_alpha)
