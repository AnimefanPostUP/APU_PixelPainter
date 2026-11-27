"""Actions of the Brushes window (the special brushes, tools/special/).
"""

SPECIAL_TOOLS = ('PARTICLES', 'RUST', 'NOISE_BLUR', 'PULL', 'REPAIR')   # the window's order, left to right
DEFAULT_SPECIAL = 'RUST'


class BrushesActions:
    """Part of :class:`.bar.PenBarTool` (a mixin: uses its state)."""

    def special_active(self):
        """The selected tool is one of the special brushes."""
        return self.active_tool() in SPECIAL_TOOLS

    def special_tool(self):
        """The brush the window shows: the selected special brush, else the last one (Rust at first)."""
        if self.special_active():
            return self.active_tool()
        last = self._c().state.get('brushes_last')
        return last if last in SPECIAL_TOOLS else DEFAULT_SPECIAL

    def special_selected(self, tool_id):
        return self.active_tool() == tool_id

    def toggle_special(self, tool_id):
        """Select ``tool_id``; tapping the selected one goes back to the tool used before."""
        state = self._c().state
        if self.active_tool() == tool_id:
            back = state.get('brushes_return')
            if back and back not in SPECIAL_TOOLS:
                self.select_tool(back)
            return
        if not self.special_active():
            state['brushes_return'] = self.active_tool()
        state['brushes_last'] = tool_id
        self.select_tool(tool_id)

    # ---- Repair ---------------------------------------------------------------------------

    def repair_mode(self):
        return self.wm_get('repair_mode', 'AUTO')

    def toggle_repair_mode(self):
        self.wm_set('repair_mode', 'AUTO' if self.repair_mode() == 'SOURCE' else 'SOURCE')

    def repair_has_source(self):
        return self._c().state.get('repair_source') is not None

    def clear_repair_source(self):
        state = self._c().state
        state['repair_source'] = None
        state['repair_offset'] = None
        self.wm_set('repair_mode', 'AUTO')
