import math
import time
from .pie_operator import PieOperator
from .pie_grid import PieGrid
from .pie_utils import draw_circle, draw_text_centered, draw_rect, draw_rect_outline
from .pie_utils_draw import draw_triangle_arrow, draw_bezier_curve
from .pie_utils_curve import Point

import gpu
from gpu_extras.batch import batch_for_shader

class PieMenuBase:
    def update_hover(self, direction_index):
        """Setzt den aktuell markierten Operator per Richtung (wie Hover) und ruft OnHighlight/OnUnhighlight auf."""
        prev = self.direction_index
        self.direction_index = direction_index
        for idx, op in enumerate(self.operators):
            if idx == direction_index:
                op.on_highlight()
            else:
                op.on_unhighlight()
    def __init__(self, name="Pie Menu"):
        self.name = name
        self.operators = []  # List[PieOperator]
        self.shapes = []
        self.active_element = None  # (index, position)
        self.direction_index = None
        self.anim = []
        self.last_anim_time = time.perf_counter()
        self.curve_initialized = False
        self.curve_end = Point()
        self.curve_from = Point()
        self.curve_to = Point()
        self.curve_progress = 1.0
        self.last_curve_time = time.perf_counter()

    def add_operator(self, label, icon=None, id=None, ref_func=None):
        idx = len(self.operators)
        op_id = id if id is not None else label
        self.operators.append(PieOperator(label, icon, idx, op_id, ref_func=ref_func))

    def add_shape(self, shape_type, position, label=None):
        self.shapes.append({
            "type": shape_type,
            "position": position,
            "label": label,
        })

    def set_active_element(self, index, position):
        self.active_element = {"index": index, "position": position}

    def update_direction(self, direction_index):
        self.direction_index = direction_index

    def update_animations(self):
        now = time.perf_counter()
        dt = max(0.0, min(0.1, now - self.last_anim_time))
        self.last_anim_time = now
        if not self.anim or len(self.anim) != len(self.operators):
            self.anim = [0.0] * len(self.operators)
        status = []
        for idx, op in enumerate(self.operators):
            op.update_anim(idx == self.direction_index, dt)
            # Collect animation status
            if idx == self.direction_index:
                status.append(op.on_highlight())
            else:
                status.append(op.on_unhighlight())
        # Central animation status: if any RUNNING, menu is animating
        if any(s == 'RUNNING' for s in status):
            return 'RUNNING'
        return 'FINISH'

    def select_operator(self, index):
        """Select an operator and call OnSelect/OnDeselect appropriately."""
        for idx, op in enumerate(self.operators):
            if idx == index:
                op.on_select()
            else:
                op.on_deselect()

    def get_curve_anchor(self, index):
        """Get the curve anchor for a given operator index."""
        if 0 <= index < len(self.operators):
            return self.operators[index].curve_anchor
        return None

    def draw_bezier_curve(self, p0, p1, p2, p3, color=(0.66, 0.44, 0.92, 0.70), segments=20):
        return draw_bezier_curve(p0, p1, p2, p3, color, segments)

    def draw_triangle_arrow(self, cx, cy, mx, my, color=(0.66, 0.44, 0.92, 0.92)):
        return draw_triangle_arrow(cx, cy, mx, my, color)

    def update_curve_endpoint(self, now, target_x, target_y, restart_transition=False):
        last = getattr(self, 'last_curve_time', now)
        dt = max(0.0, min(0.1, now - last))
        self.last_curve_time = now
        if not getattr(self, 'curve_initialized', False):
            self.curve_end.set(target_x, target_y)
            self.curve_from.set(target_x, target_y)
            self.curve_to.set(target_x, target_y)
            self.curve_progress = 1.0
            self.curve_initialized = True
            return target_x, target_y, 0.0
        cur_x, cur_y = self.curve_end.x, self.curve_end.y
        to_x, to_y = self.curve_to.x, self.curve_to.y
        if abs(target_x - to_x) > 1e-4 or abs(target_y - to_y) > 1e-4:
            if restart_transition:
                self.curve_from.set(cur_x, cur_y)
                self.curve_to.set(target_x, target_y)
                self.curve_progress = 0.0
            else:
                self.curve_from.set(target_x, target_y)
                self.curve_to.set(target_x, target_y)
                self.curve_progress = 1.0
                self.curve_end.set(target_x, target_y)
                return target_x, target_y, 0.0
        progress = self.curve_progress
        if progress < 1.0:
            progress = min(1.0, progress + (dt / 0.25 if dt > 0.0 else 0.0))
        from_x, from_y = self.curve_from.x, self.curve_from.y
        to_x, to_y = self.curve_to.x, self.curve_to.y
        nx = from_x + (to_x - from_x) * progress
        ny = from_y + (to_y - from_y) * progress
        self.curve_end.set(nx, ny)
        self.curve_progress = progress
        transition = 1.0 - progress
        return nx, ny, transition

    def update_hover_animation(self, now, hover_index, item_count):
        if not hasattr(self, 'hover_anim') or not isinstance(self.hover_anim, list) or len(self.hover_anim) != item_count:
            self.hover_anim = [0.0] * item_count
        last = getattr(self, 'last_anim_time', now)
        dt = max(0.0, min(0.1, now - last))
        self.last_anim_time = now
        speed = dt / (0.4 / 6.0) if dt > 0.0 else 0.0
        for i in range(item_count):
            target = 1.0 if i == hover_index else 0.0
            if self.hover_anim[i] < target:
                self.hover_anim[i] = min(target, self.hover_anim[i] + speed)
            elif self.hover_anim[i] > target:
                self.hover_anim[i] = max(target, self.hover_anim[i] - speed)
        return self.hover_anim

    @staticmethod
    def ease_in_out(t):
        t = max(0.0, min(1.0, t))
        return t * t * (3.0 - 2.0 * t)

    def ease_in(self, t):
        t = max(0.0, min(1.0, t))
        return t * t * t

    def ease_out(self, t):
        t = max(0.0, min(1.0, t))
        inv = 1.0 - t
        return 1.0 - inv * inv * inv

    def draw_mode_icon(self, mode, cx, cy, size, alpha=1.0):
        # Dummy: override in subclass or inject icon logic
        return False

    def draw_bubble_text_only(self, label, cx, cy, scale=1.0, alpha=1.0):
        draw_text_centered(label, cx, cy, max(1, int(12 * scale)), alpha)

    def draw_bubble_icon_text(self, mode, label, cx, cy, item_r, scale=1.0, alpha=1.0):
        if self.draw_mode_icon(mode, cx, cy, int(32 * scale), alpha):
            draw_text_centered(label, cx, cy - 20 * scale, max(1, int(10 * scale)), alpha)
        else:
            draw_text_centered(label, cx, cy, max(1, int(12 * scale)), alpha)

    def draw(self, layout, cx=0, cy=0, ring_r=120, item_r=28, open_ease=1.0, close_alpha=1.0, is_closing=False, closing_index=None, close_ease=0.0, mx=None, my=None):
        n = len(self.operators)
        if n == 0:
            return
        if mx is None:
            mx, my = cx, cy

        # Richtungserkennung wie im Original: immer direction_index bestimmen
        dx = mx - cx
        dy = my - cy
        sel_idx = self.direction_index if self.direction_index is not None else 0
        if n > 0 and (dx != 0 or dy != 0):
            angle = math.atan2(dy, dx)
            if angle < 0:
                angle += 2 * math.pi
            sel_idx = int((angle / (2 * math.pi)) * n + 0.5) % n
            self.update_direction(sel_idx)

        direction = sel_idx
        self.direction_index = direction
        now = time.perf_counter()
        anim = self.update_hover_animation(now, direction if not is_closing else None, n)

        # Kreise wie im Original
        draw_circle(cx, cy, 22, (0.12, 0.12, 0.12, 0.95 * close_alpha))
        draw_circle(cx, cy, 7, (0.66, 0.44, 0.92, 0.95 * close_alpha))

        # Pfeil und Kurve immer anzeigen, wenn Maus nicht im Zentrum
        arrow_data = None
        if dx != 0 or dy != 0:
            d = math.sqrt(dx * dx + dy * dy)
            ux = dx / d
            uy = dy / d
            base_cx = cx + ux * 7.0
            base_cy = cy + uy * 7.0
            arrow_data = self.draw_triangle_arrow(base_cx, base_cy, mx, my, color=(0.66, 0.44, 0.92, 0.92 * close_alpha))

        if arrow_data is not None and sel_idx is not None:
            angle = (sel_idx / n) * 2 * math.pi
            hix = cx + math.cos(angle) * ring_r * open_ease
            hiy = cy + math.sin(angle) * ring_r * open_ease
            ht = anim[sel_idx] if sel_idx < len(anim) else 0.0
            hte = self.ease_in_out(ht)
            target_radius = item_r * (1.0 + 0.18 * hte)
            tx, ty = arrow_data['tip']
            ux, uy = arrow_data['dir']
            cdx = tx - hix
            cdy = ty - hiy
            cd2 = cdx * cdx + cdy * cdy
            if cd2 > 1e-6:
                cdl = math.sqrt(cd2)
                nx = cdx / cdl
                ny = cdy / cdl
                target_ex = hix + nx * target_radius
                target_ey = hiy + ny * target_radius
                prev_hover = getattr(self, 'curve_hover_index', None)
                hover_changed = (prev_hover != sel_idx)
                ex, ey, transition = self.update_curve_endpoint(now, target_ex, target_ey, restart_transition=hover_changed)
                self.curve_hover_index = sel_idx
                center_mix = 0.2 * transition
                ex = ex * (1.0 - center_mix) + cx * center_mix
                ey = ey * (1.0 - center_mix) + cy * center_mix
                edx = ex - hix
                edy = ey - hiy
                el2 = edx * edx + edy * edy
                if el2 > 1e-6:
                    el = math.sqrt(el2)
                    enx = edx / el
                    eny = edy / el
                else:
                    enx, eny = nx, ny
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
                self.draw_bezier_curve(p0, p1, p2, p3, color=(0.66, 0.44, 0.92, 0.70 * close_alpha))

        # Operatoren als Bubbles im Kreis
        for idx, op in enumerate(self.operators):
            angle = (idx / n) * 2 * math.pi
            op_cx = cx + math.cos(angle) * ring_r * open_ease
            op_cy = cy + math.sin(angle) * ring_r * open_ease
            t = anim[idx] if idx < len(anim) else 0.0
            te = self.ease_in_out(t)
            base_scale = 0.5 + 0.5 * open_ease
            radius = item_r * base_scale * (1.0 + 0.18 * te)
            bubble_alpha = close_alpha
            content_scale = base_scale
            content_alpha = close_alpha
            if is_closing:
                if idx == closing_index:
                    selected_target = item_r * 1.6
                    radius = radius + (selected_target - radius) * close_ease
                    content_scale = max(base_scale, radius / max(item_r, 1e-4))
                else:
                    radius = radius * (1.0 - close_ease)
                    content_scale = content_scale * (1.0 - close_ease)
                if radius <= 0.25 or bubble_alpha <= 0.01:
                    continue
            if te > 0.0:
                draw_circle(op_cx, op_cy, radius + 1.9, (0.66, 0.44, 0.92, te * bubble_alpha))
                col = (0.66, 0.44, 0.92, 0.95 * bubble_alpha) if idx == direction else (0.30 + 0.025 * te, 0.30 + 0.025 * te, 0.30 + 0.025 * te, (0.94 + 0.02 * te) * bubble_alpha)
            elif idx == direction:
                col = (0.66, 0.44, 0.92, 0.95 * bubble_alpha)
            else:
                col = (0.18, 0.18, 0.18, 0.9 * bubble_alpha)
            draw_circle(op_cx, op_cy, radius, col)
            self.draw_bubble_icon_text(op.icon, op.label, op_cx, op_cy, item_r, scale=content_scale, alpha=content_alpha)

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
            x, y = self.active_element["position"]
            # Hier könnte draw_line(x0, y0, x1, y1, color) stehen, falls in pie_utils vorhanden
            pass

    def handle_event(self, event):
        pass
