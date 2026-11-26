"""The Grid corner button: tap toggles the pixel grid, a vertical drag sets its opacity.
"""

import math

from ...kit import RingSegment
from ...kit import draw
from ...kit.theme import with_alpha
from ...kit.widget import _resolve
from ..metrics import DRAG_THRESHOLD, GRID_DRAG_PX


class GridCorner(RingSegment):
    """Pixel grid overlay: shows the opacity in percent (dimmed while hidden). A tap
    toggles the grid (``on_click``); dragging up / down sets the opacity
    (``on_value(v)``, 0..1; ESC restores it)."""

    draggable = True

    def __init__(self, label="", *, shown, value, on_value, **kwargs):
        super().__init__(label, selected=shown, **kwargs)
        self.shown = shown
        self.value = value
        self.on_value = on_value
        self.dragging = False
        self._press = None
        self._start = 0.0
        self._moved = False
        self._theme = None

    def drag_begin(self, x, y):
        self._press = (x, y)
        self._start = float(_resolve(self.value, 0.0) or 0.0)
        self._moved = False
        self.dragging = True

    def drag_update(self, x, y):
        if self._press is None or self._theme is None:
            return
        dx, dy = x - self._press[0], y - self._press[1]
        if not self._moved:
            self._moved = math.hypot(dx, dy) >= self._theme.px(DRAG_THRESHOLD)
        if self._moved:
            self.on_value(max(0.0, min(1.0, self._start + dy / self._theme.px(GRID_DRAG_PX))))

    def drag_end(self, x, y, cancelled=False):
        self.dragging = False
        moved, self._press = self._moved, None
        if cancelled:
            if moved:
                self.on_value(self._start)
        elif not moved:
            self.activate()

    def draw_self(self, dc):
        self._theme = dc.theme
        alpha = self.draw_frame(dc, active=1.0 if self.dragging else None)
        size = self.content_size()
        if size <= 2.0:
            return
        theme = dc.theme
        x, y = self.middle()
        on = bool(_resolve(self.shown, False))
        value = float(_resolve(self.value, 0.0) or 0.0)
        color = theme.text if on else theme.text_muted
        draw.text_centered(f"{int(round(value * 100.0))}%", x, y, min(theme.px(10.0), size * 0.42),
                           with_alpha(color, (1.0 if on else 0.7) * alpha), theme.font_id)
