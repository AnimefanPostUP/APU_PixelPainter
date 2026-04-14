"""Base class for event-driven Pixel Painter sub-modes."""


class SubModeHandler:
    """Unified event API for modal sub-modes."""

    mode_name = "BASE"

    def on_enter(self, context, event):
        return None

    def on_cancel(self, context):
        return None

    def on_confirm(self, context):
        return None

    def on_mouse_move(self, context, event):
        return None

    def on_mouse_left_press(self, context, event):
        return None

    def on_mouse_right_press(self, context, event):
        return None

    def on_wheel_up(self, context, event):
        return None

    def on_wheel_down(self, context, event):
        return None

    def on_shift_press(self, context, event):
        return None

    def on_shift_release(self, context, event):
        return None

    def on_key_e_press(self, context, event):
        return None

    def handle_event(self, context, event):
        """Dispatch Blender events to unified sub-mode callbacks.

        Returns True when consumed.
        """
        if event.type == 'MOUSEMOVE':
            self.on_mouse_move(context, event)
            return True

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            self.on_mouse_left_press(context, event)
            return True

        if event.type == 'RIGHTMOUSE' and event.value == 'PRESS':
            self.on_mouse_right_press(context, event)
            return True

        if event.type == 'WHEELUPMOUSE':
            self.on_wheel_up(context, event)
            return True

        if event.type == 'WHEELDOWNMOUSE':
            self.on_wheel_down(context, event)
            return True

        if event.type in {'LEFT_SHIFT', 'RIGHT_SHIFT'} and event.value == 'PRESS':
            self.on_shift_press(context, event)
            return True

        if event.type in {'LEFT_SHIFT', 'RIGHT_SHIFT'} and event.value == 'RELEASE':
            self.on_shift_release(context, event)
            return True

        if event.type == 'E' and event.value == 'PRESS':
            self.on_key_e_press(context, event)
            return True

        return False
