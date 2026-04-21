
import time

class PieGrid:
    def __init__(self, items=None):
        self.items = items or []
        self.hover_index = None
        self.last_anim_time = time.perf_counter()

    def add_item(self, item):
        self.items.append(item)

    def update_hover(self, hover_index):
        self.hover_index = hover_index

    def update_animations(self):
        now = time.perf_counter()
        dt = max(0.0, min(0.1, now - self.last_anim_time))
        self.last_anim_time = now
        for idx, op in enumerate(self.items):
            op.update_anim(idx == self.hover_index, dt)

    def draw(self, layout, cx, cy, ring_r, item_r, open_ease, close_alpha, is_closing, closing_index, close_ease):
        # Layout: verteile Operatoren im Kreis
        n = len(self.items)
        for idx, op in enumerate(self.items):
            angle = (idx / n) * 2 * math.pi
            op_cx = cx + math.cos(angle) * ring_r * open_ease
            op_cy = cy + math.sin(angle) * ring_r * open_ease
            op.draw(layout, op_cx, op_cy, ring_r, item_r, open_ease, close_alpha, idx == self.hover_index, is_closing, closing_index, close_ease)
