import bpy
import time
import math
import sys
from bpy.types import Operator
from ..ui.pie_menu_base import PieMenuBase
from ..ui.pie_operator import PieOperator
from ..ui.pie_grid import PieGrid
from ..ui.pie_utils import draw_circle, draw_text_centered, draw_rect, draw_rect_outline

print = lambda *args, **kwargs: __import__('builtins').print(*args, file=sys.stderr, **kwargs)

class AnimatedPieMenu(PieMenuBase):
    def draw_bezier_curve(self, p0, p1, p2, p3, color=(0.66, 0.44, 0.92, 0.70), segments=20):
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

        import gpu
        from gpu_extras.batch import batch_for_shader
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        batch = batch_for_shader(shader, 'LINE_STRIP', {'pos': verts})
        gpu.state.line_width_set(3.0)
        shader.bind()
        shader.uniform_float('color', color)
        batch.draw(shader)
        gpu.state.line_width_set(1.0)
            
    def __init__(self, items, icons=None, ref_func=None, name="Animated Pie Menu"):
        super().__init__(name=name)
        self.operators = [
            PieOperator(label, (icons or {}).get(id), idx, id, ref_func=ref_func)
            for idx, (id, label) in enumerate(items)
        ]
        self.update_hover(None)
        self.update_animations()

    def draw(self, layout, cx, cy, ring_r, item_r, open_ease=1.0, close_alpha=1.0, is_closing=False, closing_index=None, close_ease=0.0, mx=None, my=None):
        n = len(self.operators)
        if n == 0:
            return
        if mx is None:
            mx, my = cx, cy

        # Richtungserkennung (immer richtungsbasiert, kein Hover)
        sel_idx = self.direction_index if self.direction_index is not None else 0  # Fallback: 0, damit Kurve immer gezeichnet wird
        dx = mx - cx
        dy = my - cy
        if n > 0 and (dx != 0 or dy != 0):
            angle = math.atan2(dy, dx)
            if angle < 0:
                angle += 2 * math.pi
            sel_idx = int((angle / (2 * math.pi)) * n + 0.5) % n
            self.update_direction(sel_idx)

        # Synchronisiere direction_index explizit mit sel_idx für konsistente Animationen
        direction = sel_idx
        self.direction_index = direction
        now = time.perf_counter()
        anim = self.update_hover_animation(now, direction if not is_closing else None, n)

        # Kreise wie im alten PieMenu: außen dunkel, innen lila
        draw_circle(cx, cy, 22, (0.12, 0.12, 0.12, 0.95 * close_alpha))
        draw_circle(cx, cy, 7, (0.66, 0.44, 0.92, 0.95 * close_alpha))

        
        # --- Pfeil und Kurve wie im klassischen _draw_custom_pie_overlay ---
        arrow_data = None
        if dx != 0 or dy != 0:
            d = math.sqrt(dx * dx + dy * dy)
            ux = dx / d
            uy = dy / d
            base_cx = cx + ux * 7.0
            base_cy = cy + uy * 7.0
            arrow_data = self.draw_triangle_arrow(base_cx, base_cy, mx, my, color=(0.66, 0.44, 0.92, 0.92 * close_alpha))

        print(f"[DEBUG] dx={dx} dy={dy} mx={mx} my={my} arrow_data={arrow_data}")
        #if dx != 0 or dy != 0:
        #print(f"[DEBUG] base_cx={base_cx} base_cy={base_cy} d={d} ux={ux} uy={uy}")
        #else:
        #print(f"[DEBUG] base_cx/base_cy nicht gesetzt, da dx=0 und dy=0")
        #print(f"[DEBUG] arrow_data={arrow_data}")
        if arrow_data is not None and sel_idx is not None:
            print(f"[DEBUG] sel_idx={sel_idx} direction={direction} anim={anim} open_ease={open_ease} close_alpha={close_alpha} is_closing={is_closing} closing_index={closing_index} close_ease={close_ease}")
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
                print(f"[DEBUG] curve: p0={p0} p1={p1} p2={p2} p3={p3}")
                self.draw_bezier_curve(p0, p1, p2, p3, color=(0.66, 0.44, 0.92, 0.70 * close_alpha))
        # --- Ende Übernahme ---

        # 4. Operatoren als Bubbles im Kreis
        for idx, op in enumerate(self.operators):
            angle = (idx / n) * 2 * math.pi
            op_cx = cx + math.cos(angle) * ring_r * open_ease
            op_cy = cy + math.sin(angle) * ring_r * open_ease
            op.draw(layout, op_cx, op_cy, ring_r, item_r, open_ease, close_alpha, idx == self.direction_index, is_closing, closing_index, close_ease)

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
        print(f"[DEBUG] invoke aufgerufen")
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
        print(f"[DEBUG] modal aufgerufen: event.type={event.type}")
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            mx, my = event.mouse_region_x, event.mouse_region_y
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
            self.menu.mx = mx
            self.menu.my = my
            context.area.tag_redraw()
            print(f"[DEBUG] modal: event.type={event.type} mx={mx} my={my}")
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
        if not self.handler:
            return
        try:
            now = time.perf_counter()
            open_t = min(1.0, max(0.0, (now - self.open_started_at) / 0.165))
            open_ease = PieMenuBase.ease_in_out(open_t)
            close_alpha = 1.0 - self.close_ease if self.is_closing else 1.0
            self.menu.draw(None, self.cx, self.cy, self.ring_r, self.item_r, open_ease, close_alpha, self.is_closing, self.closing_index, self.close_ease)
        except ReferenceError:
            pass

# Registrierung für Blender
classes = [AnimatedPieMenuOperator]
def register():
    for cls in classes:
        bpy.utils.register_class(cls)
def unregister():
    for cls in classes:
        bpy.utils.unregister_class(cls)
