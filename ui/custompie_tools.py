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



from .pie_utils import draw_circle, draw_text_centered, draw_rect, draw_rect_outline
from .custompie_tools_falloff import _falloff_pie_items
from .custompie_blending import _blend_labels
from .pie_grid import PieGrid
from .pie_operator import PieOperator

from .pie_menu_base import PieMenuBase

class PixelPainterModePie(PieMenuBase):
    bl_idname = "PIXELPAINTER_MT_mode_pie"
    bl_label = "Drawing Mode"

    def draw(self, context):
        layout = self.layout
        pie = layout.menu_pie()
        pie.scale_x = 1.0
        pie.scale_y = 1.0
        # Operatoren erzeugen (mit Icon)
        self.operators = [PieOperator(label, _mode_icon_files.get(id), idx, id, ref_func=lambda: context.window_manager.pixel_painter_mode) for idx, (id, label) in enumerate(_custom_pie_items)]
        self.update_hover(None)
        self.update_animations()
        self.draw(layout, 0, 0, 120, 28, 1.0, 1.0, False, None, 0.0)


