"""Subtools that switch tools: temporary (hold a modifier) and global (Shift+number)."""

from ...core.framework import HoldTool, Shortcut, ToolFrame


NUMBER_KEYS = ('ONE', 'TWO', 'THREE', 'FOUR', 'FIVE', 'SIX', 'SEVEN', 'EIGHT', 'NINE')


class TemporaryToolSwitch(HoldTool):
    """While ``modifier`` is held, another tool stands in for the parent tool.

    Events are forwarded to the stand-in tool (it runs with its own
    subtools); the parent gets nothing until the modifier is released, then
    the previous tool comes back. When the target is the parent itself the
    switch is a no-op pass-through.
    """

    def __init__(self, target_id, modifier, **kwargs):
        super().__init__(modifier, **kwargs)
        self.target_id = target_id
        self.stand_in = None
        self._restore_id = None
        self._current_id = None

    @property
    def exclusive(self):
        return self.stand_in is not None

    def on_activate(self, ctx, event):
        if self.parent is not None:
            self.parent.on_interrupt(ctx)  # abort the parent's stroke before switching
        self._restore_id = ctx.mode
        self.retarget(ctx, self.target_for(event))
        if self.stand_in is not None and event is not None and not event.is_modifier_key(self.modifier):
            self.stand_in.dispatch(ctx, event)  # e.g. the Alt+LMB press starts the line
        ctx.redraw()

    def target_for(self, event):
        return self.target_id

    def retarget(self, ctx, tool_id):
        if tool_id == self._current_id:
            return
        if self.stand_in is not None:
            self.stand_in.deactivate(ctx)
        target = self.manager.tool(tool_id)
        self.stand_in = None if target is self.parent else target
        self._current_id = tool_id
        self.manager.set_effective_mode(ctx, tool_id)
        if self.stand_in is not None:
            self.stand_in.activate(ctx, None, host=self)
        ctx.apply_tool_settings()

    def on_event(self, ctx, event):
        if self.stand_in is not None:
            self.stand_in.dispatch(ctx, event)

    def on_interrupt(self, ctx):
        if self.stand_in is not None:
            self.stand_in.interrupt(ctx)

    def on_tick(self, ctx):
        if self.stand_in is not None:
            self.stand_in.tick(ctx)

    def on_deactivate(self, ctx):
        if self.stand_in is not None:
            self.stand_in.deactivate(ctx)
        self.stand_in = None
        # Only restore when nobody else changed the tool in the meantime.
        if ctx.mode == self._current_id and self._restore_id is not None:
            self.manager.set_effective_mode(ctx, self._restore_id)
            ctx.apply_tool_settings()
        self._current_id = None
        self._restore_id = None
        ctx.redraw()

    def active_children(self):
        children = super().active_children()
        return children + (self.stand_in,) if self.stand_in is not None else children

    def draw_chain(self, ctx):
        super().draw_chain(ctx)
        if self.stand_in is not None:
            self.stand_in.draw_chain(ctx)


class ShiftToolSwitch(TemporaryToolSwitch):
    """Hold Shift: LMB uses ``lmb_tool`` (Smooth), RMB uses ``rmb_tool`` (Eraser).

    The Smooth stand-in runs with the global settings
    (``pixel_painter_temp_smooth_force_global``). Pressing E or W ends the
    override so Shift+E / Shift+W reach the parent tool / Blender keymap.
    """

    def __init__(self, lmb_tool='SMOOTH', rmb_tool='ERASER'):
        super().__init__(lmb_tool, 'SHIFT')
        self.lmb_tool = lmb_tool
        self.rmb_tool = rmb_tool

    def wants_activation(self, ctx, event):
        if event.ctrl or event.alt:
            return False
        return super().wants_activation(ctx, event)

    def on_register(self):
        self.bind(Shortcut('LEFTMOUSE'), lambda ctx, ev: self.retarget(ctx, self.lmb_tool), consume=False)
        self.bind(Shortcut('RIGHTMOUSE'), lambda ctx, ev: self.retarget(ctx, self.rmb_tool), consume=False)
        self.bind(Shortcut(('E', 'W')), self._end_for_shortcut, consume=False)

    def target_for(self, event):
        if event is not None and event.type == 'RIGHTMOUSE':
            return self.rmb_tool
        return self.lmb_tool

    def on_activate(self, ctx, event):
        ctx.wm.pixel_painter_temp_smooth_force_global = True
        super().on_activate(ctx, event)

    def on_deactivate(self, ctx):
        ctx.wm.pixel_painter_temp_smooth_force_global = False
        super().on_deactivate(ctx)

    def _end_for_shortcut(self, ctx, event):
        self.deactivate(ctx)
        return False  # let the parent / Blender handle E / W


class ToolSwitchShortcuts(ToolFrame):
    """Global tool: Shift+1..9 selects the n-th registered tool."""

    label = "Tool Shortcuts"
    is_global = True
    priority = 100

    def __init__(self, registry):
        super().__init__()
        self.registry = registry

    def on_register(self):
        self.bind(Shortcut(NUMBER_KEYS, shift=True, ctrl=False, alt=False), self._select)

    def _select(self, ctx, event):
        if self.manager.is_capturing():
            return False
        tool = self.registry.by_shortcut_index(NUMBER_KEYS.index(event.type))
        if tool is None:
            return False
        self.manager.select(ctx, tool.tool_id)
        ctx.apply_tool_settings()
        ctx.redraw()
