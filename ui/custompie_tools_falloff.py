_mode_icon_files = {
    'CONSTANT': "Falloff_Const.png",
    'LINEAR': "Falloff_Linea.png",
    'SMOOTH_FALLOFF': "Falloff_Smooth.png",
    'SPHERE': "Falloff_Sphere.png",
    'SHARPEN': "Falloff_Sharpen.png",
}

_falloff_pie_items = [
    ('CONSTANT', 'Constant'),
    ('SMOOTH', 'Smooth'),
    ('CUSTOM', 'Custom'),
    ('LINEAR', 'Linear'),
    ('SPHERE', 'Sphere'),
    ('SHARPEN', 'Sharpen'),
]

def _falloff_icon_key(item_id):
    if item_id == 'SMOOTH':
        return 'SMOOTH_FALLOFF'
    return item_id

from .pie_grid import PieGrid
from .pie_operator import PieOperator
# from bpy.types import Menu  # Entfernt, da nicht auflösbar außerhalb von Blender

from .pie_menu_base import PieMenuBase

class PixelPainterFalloffPie(PieMenuBase):
    bl_idname = "PIXELPAINTER_MT_falloff_pie"
    bl_label = "Brush Falloff"

    def draw(self, context):
        layout = self.layout
        pie = layout.menu_pie()
        pie.scale_x = 1.0
        pie.scale_y = 1.0
        # Operatoren erzeugen (mit Icon)
        self.operators = [PieOperator(label, _mode_icon_files.get(id), idx, id, ref_func=lambda: context.window_manager.pixel_painter_falloff) for idx, (id, label) in enumerate(_falloff_pie_items)]
        self.update_hover(None)
        self.update_animations()
        self.draw(layout, 0, 0, 120, 28, 1.0, 1.0, False, None, 0.0)
