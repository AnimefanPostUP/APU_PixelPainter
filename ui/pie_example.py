"""
Pie Example PieMenu Variante
===========================

Beispiel für eine weitere PieMenu-Variante.
Hier können andere Operatoren, Formen oder Layouts definiert werden.
"""

from .pie_menu import PieMenu

class PieExampleMenu(PieMenu):
    def __init__(self):
        super().__init__(name="Example Pie")
        self.add_operator("object.delete", label="Delete")
        self.add_shape("triangle", position=(0, 1), label="Triangle")
        self.set_active_element(0, (0, 1))

    def draw(self, context):
        super().draw(context)
        # Zusätzliche Zeichnungen oder Logik für das Example Pie

pie_example_menu = PieExampleMenu()
