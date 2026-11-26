"""Drag & drop of colors and palettes between the pen menu's widgets, and the
confirm dialog for deleting / replacing palettes.
"""


from ....model import color_palette


class ColorDragDrop:
    """Part of :class:`.bar.PenBar` (a mixin: uses its state)."""

    def confirm(self, lines, action, label="Delete"):
        """Ask before ``action`` (deleting / replacing a palette): dialog over the menu."""
        self.confirm_dialog.open(lines, action, label)
        self.overlay.layout()

    def drop_on_slot(self, index, payload):
        """A payload dropped on palette slot ``index``."""
        a = self.actions
        kind, value, origin = payload
        origin = origin or ('', None)
        if kind == 'color':
            if origin[0] == 'palette_color':
                a.swap_palette_slots(origin[1], index)
            else:
                a.set_palette_slot(index, value)
            return
        if origin[0] == 'project':
            if origin[1] != index:
                a.swap_project_palettes(origin[1], index)
            return
        current = a.project_palette(index)          # from the library: load a copy
        if current is None or color_palette.is_empty(current):
            a.set_project_palette(index, value)
        else:
            self.confirm([f"Replace “{current['name']}”", f"with “{value['name']}”?"],
                         lambda: a.set_project_palette(index, value), "Replace")

    def drop(self, payload, x, y, source):
        """End of a drag at ``(x, y)``: the widget there (or an ancestor) takes it. Off the
        menu: a palette color is removed, a project palette deleted after a confirmation."""
        target = self._drop_target(x, y, source, payload)
        if target is not None:
            target.accept_drop(payload, source)
            return
        if not self._removes(x, y, payload):
            return
        kind, value, (place, index) = payload
        if place == 'palette_color':
            self.actions.set_palette_slot(index, None)
        else:
            self.confirm([f"Delete the palette “{value['name']}”", "from this project?"],
                         lambda: self.actions.set_project_palette(index, None), "Delete")

    def _removes(self, x, y, payload):
        """Released off the menu, the color selector and the windows: removes palette colors /
        project palettes."""
        origin = payload[2] or ('', None)
        return origin[0] in ('palette_color', 'project') and self._pick_any(x, y) is None

    def _pick_any(self, x, y):
        """The top-most widget under ``(x, y)`` in any element (windows, menu, color selector)."""
        for overlay in self._stack():
            if overlay.root.visible:
                hit = overlay.root.pick(x, y)
                if hit is not None:
                    return hit
        return None

    def _drop_target(self, x, y, source, payload):
        """The widget under ``(x, y)`` -- or its nearest ancestor -- that accepts ``payload``
        (in the menu or a window, e.g. the Palettes window's library)."""
        widget = self._pick_any(x, y)
        while widget is not None:
            if widget is not source and hasattr(widget, 'accept_drop') and widget.accepts(payload):
                return widget
            widget = widget.parent
        return None
