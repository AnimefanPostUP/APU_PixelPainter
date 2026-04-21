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

class PixelPainterBlendPie(PieMenuBase):
    bl_idname = "PIXELPAINTER_MT_blend_pie"
    bl_label = "Blend Mode"

    def draw(self, context):
        layout = self.layout
        pie = layout.menu_pie()
        pie.scale_x = 1.0
        pie.scale_y = 1.0
        self.operators = [PieOperator(_blend_labels[blend], None, idx, blend, ref_func=lambda: context.window_manager.pixel_painter_blend) for idx, blend in enumerate(_blend_order)]
        self.update_hover(None)
        self.update_animations()
        self.draw(layout, 0, 0, 120, 28, 1.0, 1.0, False, None, 0.0)


