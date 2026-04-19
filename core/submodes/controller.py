"""Controller for Pixel Painter event-driven sub-modes."""

from . import helpers
from .color_pick import ColorPickSubMode
from .opacity import StrengthSubMode


class SubModeController:
    """Owns sub-mode handlers and routes modal events to active handler."""

    def __init__(self, state, core_runtime, settings):
        self.state = state
        self.core_runtime = core_runtime
        self.settings = settings
        self.handlers = {
            'STRENGTH': StrengthSubMode(state, settings, helpers, self._exit_mode),
            'COLOR_PICK': ColorPickSubMode(state, settings, helpers, self._exit_mode),
        }

    def has_active_mode(self):
        return self.state.get('sub_mode') in self.handlers

    def active_mode_name(self):
        return self.state.get('sub_mode')

    def handle_active_event(self, context, event):
        mode_name = self.active_mode_name()
        handler = self.handlers.get(mode_name)
        if handler is None:
            return False
        return handler.handle_event(context, event)

    def enter_strength_mode(self, context, event):
        if self.has_active_mode():
            return False
        self.handlers['STRENGTH'].on_enter(context, event)
        self._register_process('STRENGTH')
        return True

    def enter_color_pick_mode(self, context, event):
        if self.active_mode_name() == 'COLOR_PICK':
            return False
        if self.active_mode_name() == 'STRENGTH':
            return False
        self.handlers['COLOR_PICK'].on_enter(context, event)
        self._register_process('COLOR_PICK')
        return True

    def cancel_active_mode(self, context):
        mode_name = self.active_mode_name()
        handler = self.handlers.get(mode_name)
        if handler is None:
            return False
        handler.on_cancel(context)
        self._exit_mode(context, mode_name)
        return True

    def clear_processes(self):
        self.core_runtime.clear_process('SUB_MODE:STRENGTH')
        self.core_runtime.clear_process('SUB_MODE:COLOR_PICK')

    def _register_process(self, mode_name):
        owner = self.state.get('current_tool_id') or 'UNKNOWN'
        self.core_runtime.register_process(f'SUB_MODE:{mode_name}', owner, {'ESC'})

    def _exit_mode(self, context, mode_name):
        if self.state.get('sub_mode') != mode_name:
            return
        self.state['sub_mode'] = None
        self.core_runtime.clear_process(f'SUB_MODE:{mode_name}')
        if mode_name != 'COLOR_PICK':
            helpers.warp_cursor_to_sub_start(self.state, context)
