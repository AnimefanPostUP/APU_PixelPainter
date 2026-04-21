"""
PieMenu Utility-Funktionen für das Zeichnen und Geometrie
========================================================

Diese Datei enthält Hilfsfunktionen für das Zeichnen von Formen, Linien, Text usw.
Sie werden von PieMenu und Varianten genutzt.
"""

import math
import gpu
from gpu_extras.batch import batch_for_shader
import blf


def draw_circle(cx, cy, radius, color, segments=36):
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    verts = [
        (cx + math.cos((i / segments) * math.tau) * radius,
         cy + math.sin((i / segments) * math.tau) * radius)
        for i in range(segments)
    ]
    batch = batch_for_shader(shader, 'TRI_FAN', {'pos': verts})
    shader.bind()
    shader.uniform_float('color', color)
    batch.draw(shader)


def draw_text_centered(text, x, y, size=14, alpha=1.0):
    font_id = 0
    blf.size(font_id, size)
    w, h = blf.dimensions(font_id, text)
    blf.position(font_id, x - w * 0.5, y - h * 0.5, 0)
    blf.color(font_id, 1.0, 1.0, 1.0, alpha)
    blf.draw(font_id, text)


def draw_rect(x0, y0, x1, y1, color):
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    verts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    batch = batch_for_shader(shader, 'TRI_FAN', {'pos': verts})
    shader.bind()
    shader.uniform_float('color', color)
    batch.draw(shader)


def draw_rect_outline(x0, y0, x1, y1, color, width=1.5):
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    verts = [
        (x0, y0), (x1, y0),
        (x1, y0), (x1, y1),
        (x1, y1), (x0, y1),
        (x0, y1), (x0, y0),
    ]
    batch = batch_for_shader(shader, 'LINES', {'pos': verts})
    gpu.state.line_width_set(width)
    shader.bind()
    shader.uniform_float('color', color)
    batch.draw(shader)
    gpu.state.line_width_set(1.0)

# Weitere Utility-Funktionen nach Bedarf...
