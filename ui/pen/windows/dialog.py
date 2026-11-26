"""ConfirmDialog: a modal yes / no panel over the pen menu (deleting / replacing palettes).
"""

from ...kit import Column, Row, TextBlock
from ..style import DangerButton, PenButton, PenPanel


# ---- confirmation ------------------------------------------------------------------------

class ConfirmDialog:
    """``open(lines, action, label)``: shows the dialog; the action runs on confirm."""

    def __init__(self, bar):
        self.bar = bar
        self.lines = []
        self.action = None
        self.label = "Delete"
        message = TextBlock(lambda: self.lines, size=11.0, color=(1, 1, 1, 0.95))
        buttons = Row([
            DangerButton("", layout='row', size=(110.0, 30.0), key='CONFIRM_YES', on_click=self.confirm),
            PenButton("Cancel", layout='row', size=(110.0, 30.0), key='CONFIRM_NO', on_click=self.close),
        ], gap=8.0)
        buttons.children[0].label = lambda: self.label
        self.panel = PenPanel(Column([message, buttons], gap=10.0), title="Please confirm", padding=12.0)
        self.panel.key = 'CONFIRM_DIALOG'
        self.panel.visible = False

    @property
    def is_open(self):
        return self.panel.visible

    def open(self, lines, action, label="Delete"):
        self.lines = [lines] if isinstance(lines, str) else list(lines)
        self.action = action
        self.label = label
        self.panel.visible = True

    def confirm(self):
        action = self.action
        self.close()
        if action is not None:
            action()

    def close(self):
        self.panel.visible = False
        self.action = None
