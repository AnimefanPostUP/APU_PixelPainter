"""On-canvas Copy / Apply / Stencil buttons under the selection box.

A non-modal UI-kit widget layer embedded in the paint operator: the operator
forwards events (the layer consumes clicks on its buttons and passes
everything else through) and the paint draw handler draws it.
"""

import traceback

import bpy

from .kit import Overlay, Row, RoundButton, Theme
from .kit.events import RUNNING, UIEvent


_STYLE = dict(
    fill=(0.16, 0.16, 0.16, 0.9),
    border=(0.75, 0.75, 0.75, 0.95),
    active_fill=(0.22, 0.35, 0.22, 0.95),
    active_border=(0.4, 1.0, 0.5, 0.95),
)
GAP_BELOW_BOX = 26.0


def _run_operator(name):
    def _run():
        try:
            getattr(bpy.ops.image, name)()
        except RuntimeError:
            pass  # operator reported its own warning (e.g. nothing to stencil)
        except Exception:
            traceback.print_exc()
    return _run


class SelectionActions:
    def __init__(self, state):
        row = Row([
            RoundButton("Copy", key='COPY', on_click=_run_operator('pixel_painter_selection_copy'), **_STYLE),
            RoundButton("Apply", key='APPLY', on_click=_run_operator('pixel_painter_selection_apply'),
                        selected=lambda: state.get('selection_pending_action') is not None, **_STYLE),
            RoundButton("Stencil", key='STENCIL', on_click=_run_operator('pixel_painter_selection_stencil_toggle'),
                        selected=lambda: bool(state.get('selection_stencil_mode')), **_STYLE),
        ], gap=10.0)
        row.visible = False
        self.overlay = Overlay(row, modal=False, animate=False)

    @property
    def visible(self):
        return self.overlay.root.visible

    def hide(self):
        self.overlay.root.visible = False
        self.overlay.hot = None
        self.overlay.pressed = None

    def show_below(self, box_rect):
        """Place the buttons centered under the selection's screen rect ``(l, b, r, t)``."""
        left, bottom, right, _top = box_rect
        theme = Theme.for_context()
        self.overlay.theme = theme
        _w, h = self.overlay.root.measure(theme)
        self.overlay.root.visible = True
        self.overlay.set_origin((left + right) * 0.5, bottom - theme.px(GAP_BELOW_BOX) - h * 0.5)
        self.overlay.layout()

    def handle(self, event):
        """Forward a Blender event; True when the buttons consumed it."""
        if not self.visible:
            return False
        return self.overlay.handle(UIEvent.from_blender(event)) == RUNNING

    def draw(self):
        if self.visible:
            self.overlay.draw()
