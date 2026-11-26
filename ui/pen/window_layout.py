"""The pen UI's floating windows: building them, lock / help / collapse, moving and
resizing, clamping to the editor, laying everything out.
"""


from ..kit.geometry import clamp_box
from .metrics import (
    BAR_SCALE, COLOR_WIDTH,
    EDGE_GAP, FLYOUT_GAP, WINDOW_MARGIN, HANDLE_SIZE, PANEL_PADDING, clamp_scale,
)
from .window import CornerButton, MovePanel, ResizeHandle, Window


class WindowLayout:
    """Part of :class:`.bar.PenBar` (a mixin: uses its state)."""

    def _window(self, name, content, close, tab=None, lock_bottom=False, help=None, shape=None):
        locked = lambda: self._locked(name)
        panel = MovePanel(content, padding=PANEL_PADDING, key=f"{name.upper()}_PANEL", locked=locked,
                           on_move_begin=lambda: self._begin_move(name), on_move=self._move_to,
                           on_move_end=self._end_move, shape=shape)
        lock = CornerButton('LOCK', key=f"{name.upper()}_LOCK", selected=locked,
                             on_click=lambda: self._toggle_lock(name))
        grip = ResizeHandle(lambda: self._begin_resize(name), self._resize_to, self._end_resize,
                             key=f"{name.upper()}_RESIZE")
        return Window(panel, lock, grip, locked=locked, close=close, tab=tab, lock_bottom=lock_bottom, help=help)

    def _locked(self, name):
        return bool(self._get(f'pen_{name}_locked', False))

    def _toggle_lock(self, name):
        self.actions.set_state(f'pen_{name}_locked', not self._locked(name))
        self._relayout()   # shows / hides the resize triangle

    def _scale(self, name):
        try:
            return clamp_scale(name, float(self._get(f'pen_{name}_scale', 1.0)))
        except (TypeError, ValueError):
            return 1.0

    def _theme(self, name):
        """The element's theme; shrunk (not stored) while the editor is too small for it."""
        base = self._args[-1]
        theme = base.scaled(base.scale * BAR_SCALE * self._scale(name))
        if name == 'color':
            self.color_extras.visible = bool(self.actions.color_sliders_open())
            self.color_pad.fit_width = theme.px(COLOR_WIDTH)
        w, h = self.windows[name][0].measure(theme)
        bx0, by0, bx1, by1 = self.bounds
        fit = min(1.0, (bx1 - bx0) / max(1.0, w), (by1 - by0) / max(1.0, h))
        if fit < 1.0:
            theme = theme.scaled(theme.scale * fit)
            if name == 'color':
                self.color_pad.fit_width = theme.px(COLOR_WIDTH)
        return theme

    def help_shown(self, name):
        """The window's help text is shown (its '?' corner button)."""
        return bool(self._get(f'pen_{name}_help', False))

    def toggle_help(self, name):
        self.actions.set_state(f'pen_{name}_help', not self.help_shown(name))
        self._relayout()

    def toggle_window(self, name):
        """Show / hide a window (Mask, View, Settings, Palettes). Opening the Palettes
        window reloads the library and switches the palette band to its palette view
        (the drag targets)."""
        opening = not self.actions.panel_open(name)
        self.actions.toggle_panel(name)
        if opening and name == 'library':
            self.library_menu.opened()
            self.actions.set_palette_view(True)
        self._relayout()

    def set_collapsed(self, collapsed):
        self.actions.set_collapsed(collapsed)
        self.close_flyout(relayout=False)
        self._relayout()

    def _sync_visibility(self):
        collapsed = bool(self.actions.collapsed())
        self.menu.collapsed = collapsed
        self.color_window.visible = bool(self.actions.color_panel_open()) and not collapsed
        for name, (window, _overlay) in self.tool_windows.items():
            window.visible = bool(self.actions.panel_open(name)) and not collapsed
        if collapsed and self.flyout is not None:
            self.close_flyout(relayout=False)

    # ---- moving / resizing elements ------------------------------------------------------

    def _clamp(self, x0, y1, width, height):
        """Top-left of an element kept inside the editor (see ``bounds``)."""
        x0, y0 = clamp_box(x0, y1 - height, width, height, self.bounds)
        return x0, y0 + height

    def _begin_move(self, name):
        r = self.windows[name][0].rect
        self._move = (name, self._get(f'pen_{name}_pos'), (r.x0, r.y1), (r.width, r.height))

    def _move_to(self, dx, dy):
        if self._move is None:
            return
        name, _stored, (x0, y1), (w, h) = self._move
        self.actions.set_state(f'pen_{name}_pos', self._clamp(x0 + dx, y1 + dy, w, h))
        self._relayout()

    def _end_move(self, cancelled):
        if cancelled and self._move is not None:
            name, stored = self._move[0], self._move[1]
            self.actions.set_state(f'pen_{name}_pos', stored)
        self._move = None
        self._relayout()

    def _begin_resize(self, name):
        r = self.windows[name][0].panel.rect
        self._resize = (name, self._scale(name), r.width, r.height, (r.x0, r.y1), self._get(f'pen_{name}_pos'))

    def _resize_to(self, dx, dy):
        """Scale so the bottom-right corner follows the pen; the top-left corner stays.
        Limited to the element's size range and to the room left in the editor."""
        if self._resize is None:
            return
        name, scale, w, h, (x0, y1), _stored = self._resize
        factor = 1.0 + (dx * w - dy * h) / max(1.0, w * w + h * h)
        bx0, by0, bx1, by1 = self.bounds
        factor = min(factor, (bx1 - x0) / max(1.0, w), (y1 - by0) / max(1.0, h))
        self.actions.set_state(f'pen_{name}_scale', clamp_scale(name, scale * factor))
        self.actions.set_state(f'pen_{name}_pos', (x0, y1))
        self._relayout()

    def _end_resize(self, cancelled):
        if cancelled and self._resize is not None:
            name, scale, _w, _h, _tl, stored = self._resize
            self.actions.set_state(f'pen_{name}_scale', scale)
            self.actions.set_state(f'pen_{name}_pos', stored)
        self._resize = None
        self._relayout()

    # ---- layout / events -----------------------------------------------------------------

    def _relayout(self):
        if self._args is not None:
            self.layout(*self._args)

    def layout(self, region_width, region_height, side, inset_left, inset_right, theme):
        """Place the elements: where they were left (clipped to the editor), else the
        menu in the bottom corner at the ``side`` edge ('LEFT' / 'RIGHT') and the color
        selector beside it. ``inset_left`` / ``inset_right``: width of overlapping
        regions to keep clear of (the sidebar; the toolbar is ignored)."""
        self._args = (region_width, region_height, side, inset_left, inset_right, theme)
        margin = theme.px(WINDOW_MARGIN)
        self.bounds = (inset_left + margin, margin, region_width - inset_right - margin, region_height - margin)
        self._sync_visibility()
        self.root.region = (region_width, region_height)

        menu_theme = self._theme('bar')
        self.overlay.theme = menu_theme
        self.menu.grip_size = theme.px(HANDLE_SIZE)
        w, h = self.menu.measure(menu_theme)
        pos = self._get('pen_bar_pos')
        if pos is None:
            gap = menu_theme.px(max(0.0, EDGE_GAP - PANEL_PADDING))
            x0 = inset_left + gap if side == 'LEFT' else region_width - inset_right - gap - w
            pos = (x0, gap + h)
        self.overlay.origin = self._clamp(pos[0], pos[1], w, h)
        self.overlay.layout()

        menu = self.menu.rect
        gap = theme.px(FLYOUT_GAP)
        toward_right = menu.cx < region_width * 0.5
        outer = [menu]        # placed elements; default spots go beside the outermost one
        if self.color_window.visible:
            color_theme = self._theme('color')
            self.color_overlay.theme = color_theme
            self.color_window.grip_size = theme.px(HANDLE_SIZE)
            cw, ch = self.color_window.measure(color_theme)
            pos = self._get('pen_color_pos')
            if pos is None:   # beside the menu, toward the canvas, bottoms level
                x0 = menu.x1 + gap if toward_right else menu.x0 - gap - cw
                pos = (x0, menu.y0 + ch)
            self.color_overlay.origin = self._clamp(pos[0], pos[1], cw, ch)
            self.color_overlay.layout()
            outer.append(self.color_window.rect)

        for name, (window, overlay) in self.tool_windows.items():
            if not window.visible:
                continue
            win_theme = self._theme(name)
            overlay.theme = win_theme
            window.grip_size = theme.px(HANDLE_SIZE)
            ww, wh = window.measure(win_theme)
            pos = self._get(f'pen_{name}_pos')
            if pos is None:   # beside the menu / the windows placed so far, tops level with the menu
                if toward_right:
                    x0 = max(r.x1 for r in outer) + gap
                else:
                    x0 = min(r.x0 for r in outer) - gap - ww
                pos = (x0, menu.y1)
            overlay.origin = self._clamp(pos[0], pos[1], ww, wh)
            overlay.layout()
            if self._get(f'pen_{name}_pos') is None:
                outer.append(window.rect)

    def _stack(self):
        """Overlays, top-most first: the menu while its flyout is open, else the Mask / View
        windows, the color selector, the menu."""
        windows = [overlay for _window, overlay in self.tool_windows.values()]
        if self.flyout is not None or self.confirm_dialog.is_open:
            return [self.overlay, *windows, self.color_overlay]
        return [*windows, self.color_overlay, self.overlay]
