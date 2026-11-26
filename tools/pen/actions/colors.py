"""Color actions of the pen menu: the tertiary color (a point on the primary -> secondary
gradient) and the color history.
"""



from ....model import color_history, tertiary_color


class ColorActions:
    """Part of :class:`.bar.PenBarTool` (a mixin: uses its state)."""

    # ---- tertiary color (model/tertiary_color.py) ---------------------------------------

    def tertiary_active(self):
        return tertiary_color.active(self._c().state)

    def tertiary_t(self):
        return tertiary_color.position(self._c().state)

    def tertiary_color(self):
        primary, secondary = self.colors()
        return tertiary_color.color(self._c().state, primary, secondary)

    def set_tertiary_t(self, t):
        """The gradient slider: moves the tertiary color along it and selects it."""
        self._c().state[tertiary_color.T_KEY] = tertiary_color.snapped(t)
        self.select_tertiary()

    def select_tertiary(self):
        """The pen tip paints the tertiary color; the color selector keeps editing the
        color it edited (no RMB lock meanwhile: the tip paints with the left button)."""
        ctx = self._c()
        state = ctx.state
        if tertiary_color.active(state):
            return
        state[tertiary_color.TARGET_KEY] = self._target(ctx)
        state[tertiary_color.ACTIVE_KEY] = True
        state['pen_color_pending'] = None
        if state.get('pen_rmb_lock'):
            state['pen_rmb_lock'] = False
            ctx.apply_tool_settings()

    def toggle_tertiary(self):
        """The tertiary bubble: select it, or (selected) back to the color the selector edits."""
        if self.tertiary_active():
            self.select_color(self._target(self._c()))
        else:
            self.select_tertiary()

    def color_target(self):
        """'PRIMARY' / 'SECONDARY': the color the color selector edits."""
        return self._target(self._c())

    def color_role(self, which):
        """How the primary / secondary color is marked: 'ACTIVE' (the pen paints it),
        'TARGET' (the tertiary color is selected; the color selector edits this one) or None."""
        if self.color_target() != which:
            return None
        return 'TARGET' if self.tertiary_active() else 'ACTIVE'

    def select_color(self, which):
        """Tap on the primary / secondary color. With the tertiary color selected the
        first tap only makes it the color the selector edits; a tap on that one (or
        without the tertiary color) paints with it -- the secondary one sets the RMB lock."""
        ctx = self._c()
        state = ctx.state
        if tertiary_color.active(state) and self._target(ctx) != which:
            state[tertiary_color.TARGET_KEY] = which
            state['pen_color_pending'] = None
            return
        state[tertiary_color.ACTIVE_KEY] = False
        state['pen_color_pending'] = None
        self.set_rmb_lock(which == 'SECONDARY')

    def swap_colors(self):
        ctx = self._c()
        primary, secondary = self.colors()
        ctx.settings.set_brush_rgb(ctx.context, *secondary)
        ctx.settings.set_brush_secondary_rgb(ctx.context, *primary)

    def spacing(self):
        return getattr(self._c().wm, 'pixel_painter_spacing', 'FREE')

    def toggle_spacing(self):
        wm = self._c().wm
        wm.pixel_painter_spacing = 'FREE' if self.spacing() == 'PIXEL' else 'PIXEL'

    def alpha_lock(self):
        return bool(getattr(self._c().wm, 'pixel_painter_protect_transparent', False))

    def toggle_alpha_lock(self):
        wm = self._c().wm
        wm.pixel_painter_protect_transparent = not self.alpha_lock()

    def rmb_lock(self):
        return bool(self._c().state.get('pen_rmb_lock'))

    def set_rmb_lock(self, value):
        if bool(value) != self.rmb_lock():
            self.toggle_rmb_lock()

    def toggle_rmb_lock(self):
        state = self._c().state
        state['pen_rmb_lock'] = not state.get('pen_rmb_lock')
        if state['pen_rmb_lock']:
            state[tertiary_color.ACTIVE_KEY] = False   # the pen tip paints the secondary color
        self._c().apply_tool_settings()

    def tools(self):
        return list(self.registry)

    def active_tool(self):
        return self._c().mode

    def uses_value(self, channel):
        """Does the active tool read ``channel`` (its S / A / M slider is grayed out if not)?"""
        try:
            tool = self.registry.get(self.active_tool())
        except Exception:
            return True
        return tool is None or channel in getattr(tool, 'uses_values', (channel,))

    def select_tool(self, tool_id):
        ctx = self._c()
        self.manager.select(ctx, tool_id)
        ctx.apply_tool_settings()

    # ---- color history ------------------------------------------------------------------

    def color_history(self):
        return color_history.colors(self._c().state)

    def use_history_color(self, rgb):
        """Paint with ``rgb`` from the history / palette: it becomes the color the
        selector edits (the secondary one with the RMB lock), which is then selected
        (instead of the tertiary color)."""
        ctx = self._c()
        which = self._target(ctx)
        if which == 'SECONDARY':
            ctx.settings.set_brush_secondary_rgb(ctx.context, *rgb)
        else:
            ctx.settings.set_brush_rgb(ctx.context, *rgb)
        ctx.state['pen_color_pending'] = None
        if tertiary_color.active(ctx.state):
            self.select_color(which)
