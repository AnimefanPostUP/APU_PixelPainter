"""
Pie Tools PieMenu Variante
=========================

Beispiel für eine PieMenu-Variante, die auf der PieMenu-Basisklasse basiert.
Hier werden spezifische Operatoren und Formen für das Tool-Menü hinzugefügt.
"""

from .pie_menu import PieMenu

class PieToolsMenu(PieMenu):
    def __init__(self):
        super().__init__(name="Tools Pie")
        self.add_operator("mesh.primitive_cube_add", label="Cube")
        self.add_operator("mesh.primitive_uv_sphere_add", label="Sphere")
        self.add_shape("circle", position=(1, 0), label="Circle")
        self.add_shape("square", position=(-1, 0), label="Square")
        self.set_active_element(0, (1, 0))

    def draw(self, context):
        super().draw(context)
        # Zusätzliche Zeichnungen oder Logik für das Tools Pie

# Instanz für Registrierung oder direkten Zugriff
pie_tools_menu = PieToolsMenu()
