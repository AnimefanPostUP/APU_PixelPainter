import math
import gpu
from gpu_extras.batch import batch_for_shader

class RingSegmentPieOperator:
    def __init__(self, cx, cy, inner_radius, outer_radius, segments, active_index=None):
        self.cx = cx
        self.cy = cy
        self.inner_radius = inner_radius
        self.outer_radius = outer_radius
        self.segments = segments  # List of dicts: {label, color, ...}
        self.active_index = active_index

    def draw(self):
        n = len(self.segments)
        angle_step = 2 * math.pi / n
        for i, seg in enumerate(self.segments):
            angle_start = i * angle_step
            angle_end = (i + 1) * angle_step
            color = seg.get('color', (0.5, 0.5, 0.5, 1.0))
            highlight = (i == self.active_index)
            self.draw_ring_segment(angle_start, angle_end, color, highlight)
            # Optional: Draw label in the middle of the segment
            if 'label' in seg:
                self.draw_label_in_segment(angle_start, angle_end, seg['label'])

    def draw_ring_segment(self, angle_start, angle_end, color, highlight=False, steps=32):
        cx, cy = self.cx, self.cy
        inner_r = self.inner_radius
        outer_r = self.outer_radius
        # Points on inner arc
        inner_points = [
            (cx + math.cos(a) * inner_r, cy + math.sin(a) * inner_r)
            for a in self.linspace(angle_start, angle_end, steps)
        ]
        # Points on outer arc (reverse order)
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
        # Draw border lines
        self.draw_segment_borders(angle_start, angle_end, inner_r, outer_r)

    def draw_segment_borders(self, angle_start, angle_end, inner_r, outer_r):
        cx, cy = self.cx, self.cy
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        # Border color
        border_col = (0.1, 0.1, 0.1, 1.0)
        # Two radial lines
        for angle in (angle_start, angle_end):
            p1 = (cx + math.cos(angle) * inner_r, cy + math.sin(angle) * inner_r)
            p2 = (cx + math.cos(angle) * outer_r, cy + math.sin(angle) * outer_r)
            batch = batch_for_shader(shader, 'LINES', {'pos': [p1, p2]})
            shader.bind()
            shader.uniform_float('color', border_col)
            batch.draw(shader)
        # Two arcs (inner and outer)
        for r in (inner_r, outer_r):
            arc_points = [
                (cx + math.cos(a) * r, cy + math.sin(a) * r)
                for a in self.linspace(angle_start, angle_end, 32)
            ]
            batch = batch_for_shader(shader, 'LINE_STRIP', {'pos': arc_points})
            shader.bind()
            shader.uniform_float('color', border_col)
            batch.draw(shader)

    def draw_label_in_segment(self, angle_start, angle_end, label):
        # Place label at the center angle and average radius
        mid_angle = (angle_start + angle_end) / 2
        r = (self.inner_radius + self.outer_radius) / 2
        x = self.cx + math.cos(mid_angle) * r
        y = self.cy + math.sin(mid_angle) * r
        # Use your existing draw_text_centered utility if available
        try:
            from .pie_utils import draw_text_centered
            draw_text_centered(label, x, y, size=14, alpha=1.0)
        except ImportError:
            pass

    @staticmethod
    def linspace(start, stop, num):
        if num == 1:
            return [start]
        step = (stop - start) / (num - 1)
        return [start + i * step for i in range(num)]
