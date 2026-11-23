"""Interaction controller for a widget tree.

:class:`Overlay` owns *one* root widget and turns a stream of
:class:`~.events.UIEvent` into hover / press / click / keyboard behaviour,
plus the open and close animations. It does not import ``bpy`` so the whole
interaction model can be unit-tested; :mod:`.modal` wires it into Blender.

Interaction rules
-----------------
* Exactly one widget is under the pointer at a time (:meth:`Widget.pick`):
  overlapping widgets never react together.
* A click is *press then release on the same widget*. Widgets with
  ``drag_release = True`` (radial items) also accept a release after the
  pointer travelled to them, as Blender's own pie menus do.
* Enter / Numpad-Enter / Space confirm the hot widget.
* Holding the key that opened the overlay, moving, and releasing it
  confirms the hot widget (after ``theme.hold_release_delay``).
* ESC / right-click cancel a modal overlay.
* While the close animation runs, input is swallowed; the chosen widget's
  action runs once the animation has finished.

Non-modal overlays (``modal=False``) are "widget layers" embedded in another
modal operator: they pass every event they do not consume through, never
close, and activate widgets immediately.
"""

import time

from . import anim
from . import draw
from .events import CANCELLED, FINISHED, PASS_THROUGH, PRESS, RELEASE, RUNNING
from .geometry import fit_offset
from .theme import Theme
from .widget import DrawContext


_CONFIRM_KEYS = {'RET', 'NUMPAD_ENTER', 'SPACE'}
_CANCEL_KEYS = {'ESC', 'RIGHTMOUSE'}


class Overlay:
    def __init__(self, root, *, theme=None, origin=(0.0, 0.0), modal=True, animate=True,
                 trigger_key=None, clock=time.perf_counter):
        self.root = root
        self.theme = theme or Theme()
        self.origin = origin
        self.modal = modal
        self.animate = animate
        self.trigger_key = trigger_key
        self.clock = clock

        self.opened_at = clock()
        self.closing_since = None
        self.chosen = None
        self.result = None

        self.pointer = origin
        self.pointer_widget = None   # whatever pick() returned (may be a blocker)
        self.hot = None              # interactive widget under the pointer
        self.pressed = None          # widget that received the current LMB press
        self._press_seen = False
        self._last_frame = None
        self.layout()

    # ---- layout ------------------------------------------------------------

    def layout(self):
        self.root.place(self.origin, self.theme)

    def set_origin(self, x, y):
        """Re-anchor the overlay (e.g. a widget layer following on-canvas content)."""
        if (x, y) != self.origin:
            self.origin = (x, y)
            self.layout()

    def move_origin(self, dx, dy):
        self.origin = (self.origin[0] + dx, self.origin[1] + dy)
        self.pointer = (self.pointer[0] + dx, self.pointer[1] + dy)
        self.layout()

    def fit_inside(self, width, height):
        """Shift the overlay so it lies inside a ``width x height`` region.

        Returns the applied ``(dx, dy)`` so the caller can move the OS cursor
        along (a radial menu must stay centered under the cursor).
        """
        dx, dy = fit_offset(self.root.bounds(), width, height, self.theme.px(self.theme.region_margin))
        if dx or dy:
            self.move_origin(dx, dy)
        return dx, dy

    # ---- state -------------------------------------------------------------

    @property
    def is_closing(self):
        return self.chosen is not None and self.result is None

    @property
    def is_done(self):
        return self.result is not None

    def update_pointer(self, x, y):
        self.pointer = (x, y)
        if self.is_closing:
            return
        widget = self.root.pick(x, y)
        self.pointer_widget = widget
        self.hot = widget if (widget is not None and widget.interactive and widget.is_enabled) else None

    # ---- events ------------------------------------------------------------

    def _consumed(self):
        return RUNNING if (self.modal or self.result is None) else self.result

    def _unhandled(self):
        return RUNNING if self.modal else PASS_THROUGH

    def handle(self, event):
        """Process one event and return RUNNING / FINISHED / CANCELLED / PASS_THROUGH."""
        if self.result is not None:
            return self.result
        if event.type == 'TIMER':
            return self.tick() if self.modal else PASS_THROUGH
        if self.is_closing:
            return RUNNING

        self.update_pointer(event.x, event.y)

        if event.type == 'MOUSEMOVE':
            return self._unhandled()

        if self.modal and event.type in _CANCEL_KEYS and event.value == PRESS:
            return self.cancel()

        if event.type == 'LEFTMOUSE':
            if event.value == PRESS:
                self.pressed = self.hot
                self._press_seen = True
                return RUNNING if (self.modal or self.hot is not None) else PASS_THROUGH
            if event.value == RELEASE:
                pressed, self.pressed = self.pressed, None
                hot = self.hot
                if hot is not None and (hot is pressed or (getattr(hot, 'drag_release', False) and self._press_seen)):
                    return self.choose(hot)
                return RUNNING if (self.modal or pressed is not None) else PASS_THROUGH

        if event.type in _CONFIRM_KEYS and event.value == PRESS and self.hot is not None:
            return self.choose(self.hot)

        if (self.modal and self.trigger_key and event.type == self.trigger_key
                and event.value == RELEASE):
            held = self.clock() - self.opened_at
            if held >= self.theme.hold_release_delay and self.hot is not None:
                return self.choose(self.hot)
            return RUNNING

        if self.root.on_key(event, self):
            return self._consumed()

        return self._unhandled()

    def choose(self, widget):
        """Confirm ``widget``: activate now, or after the close animation."""
        if widget is None or not widget.is_enabled:
            return self._unhandled()
        if not self.modal or widget.keep_open:
            widget.activate()
            return RUNNING
        self.chosen = widget
        self.pointer_widget = widget
        self.hot = widget
        self.closing_since = self.clock()
        if not self.animate:
            return self._finish_chosen()
        return RUNNING

    def cancel(self):
        self.result = CANCELLED
        return CANCELLED

    def tick(self):
        """Advance time-based state; call on every timer event."""
        if self.is_closing and self.close_progress() >= 1.0:
            return self._finish_chosen()
        return RUNNING if self.result is None else self.result

    def _finish_chosen(self):
        self.result = FINISHED
        self.chosen.activate()
        return FINISHED

    # ---- animation ---------------------------------------------------------

    def open_progress(self, now=None):
        if not self.animate:
            return 1.0
        now = self.clock() if now is None else now
        return anim.progress(now, self.opened_at, self.theme.open_duration)

    def close_progress(self, now=None):
        if self.closing_since is None:
            return 0.0
        if not self.animate:
            return 1.0
        now = self.clock() if now is None else now
        return anim.progress(now, self.closing_since, self.theme.close_duration)

    def draw_context(self):
        now = self.clock()
        dt = anim.frame_dt(now, self._last_frame)
        self._last_frame = now
        close_t = self.close_progress(now)
        return DrawContext(
            self.theme,
            origin=self.origin,
            opened=anim.ease_out(self.open_progress(now)),
            closing=anim.ease_out(close_t),
            alpha=1.0 - close_t,
            chosen=self.chosen,
            pointer=self.pointer,
            pointer_widget=self.pointer_widget,
            hot=self.hot,
            pressed=self.pressed,
            now=now,
            dt=dt,
        )

    def draw(self):
        """Draw the widget tree (call from a POST_PIXEL draw handler)."""
        dc = self.draw_context()
        with draw.blend_mode('ALPHA'):
            self.root.draw(dc)
