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
* ``activate_on_press`` widgets activate on the press itself (a flyout
  opener: keep the pen down, drag onto the flyout entry, release).
* ``draggable`` widgets capture the pointer from press to release and get
  ``drag_begin`` / ``drag_update`` / ``drag_end`` (value knobs); ESC /
  right-click during a drag cancel it.
* Enter / Numpad-Enter / Space confirm the hot widget.
* Holding the key that opened the overlay, moving, and releasing it
  confirms the hot widget (after ``theme.hold_release_delay``).
* ESC / right-click cancel a modal overlay.
* A widget with ``takes_focus`` (a :class:`~.textfield.TextField`) that starts
  editing when activated gets the keyboard focus: every key event goes to its
  ``key_input(event)`` until it stops editing. Tab moves on to the next such widget
  (Shift+Tab: back); a press elsewhere commits it, a right click cancels it.
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
# Not keyboard input: these keep their usual meaning while a field has the focus.
_POINTER_EVENTS = {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE',
                   'WHEELINMOUSE', 'WHEELOUTMOUSE', 'TRACKPADPAN', 'TRACKPADZOOM', 'MOUSEROTATE',
                   'MOUSESMARTZOOM', 'PEN', 'ERASER', 'WINDOW_DEACTIVATE', 'NONE'}


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
        self.dragging = None         # draggable widget capturing the pointer
        self.focus = None            # editing widget receiving the keyboard (TextField)
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

        if self.dragging is not None:
            return self._handle_drag(event)

        if self._live_focus() is not None and self._handle_focus(event):
            return RUNNING

        if event.type == 'MOUSEMOVE':
            return self._unhandled()

        if self.modal and event.type in _CANCEL_KEYS and event.value == PRESS:
            return self.cancel()

        if event.type == 'LEFTMOUSE':
            if event.value == PRESS:
                hot = self.hot
                if hot is not None and hot.draggable:
                    self.dragging = self.pressed = hot
                    hot.drag_begin(event.x, event.y)
                    return RUNNING
                if self.modal or hot is not None:
                    self._press_seen = True
                if hot is not None and hot.activate_on_press:
                    self.pressed = None
                    return self.choose(hot)
                self.pressed = hot
                return RUNNING if (self.modal or hot is not None) else PASS_THROUGH
            if event.value == RELEASE:
                pressed, self.pressed = self.pressed, None
                press_seen = self._press_seen
                if not self.modal:
                    self._press_seen = False  # a layer only owns presses that landed on it
                hot = self.hot
                if hot is not None and (hot is pressed or (getattr(hot, 'drag_release', False) and press_seen)):
                    return self.choose(hot)
                return RUNNING if (self.modal or pressed is not None or press_seen) else PASS_THROUGH

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

    def _handle_drag(self, event):
        """Every event belongs to the dragged widget until release / cancel."""
        if event.type == 'MOUSEMOVE':
            self.dragging.drag_update(event.x, event.y)
        elif event.type == 'LEFTMOUSE' and event.value == RELEASE:
            self.end_drag(event.x, event.y)
        elif event.type in _CANCEL_KEYS and event.value == PRESS:
            self.end_drag(cancelled=True)
        return RUNNING

    # ---- keyboard focus ------------------------------------------------------

    def _in_tree(self, widget):
        """``widget`` is shown in this overlay's tree (not hidden, not replaced)."""
        while widget is not None:
            if not widget.visible:
                return False
            if widget is self.root:
                return True
            parent = widget.parent
            if parent is None or widget not in parent.children:
                return False
            widget = parent
        return False

    def _live_focus(self):
        focus = self.focus
        if focus is not None and (not focus.editing or not self._in_tree(focus)):
            self.focus = None
            if focus.editing:
                focus.end_edit(commit=False)
        return self.focus

    def set_focus(self, widget):
        """Give ``widget`` (editing) the keyboard; the previous focus commits."""
        if self.focus is not None and self.focus is not widget:
            self.focus.end_edit(commit=True)
        self.focus = widget

    def blur(self, commit=True):
        """End the focused widget's editing (``commit`` its text or discard it)."""
        focus, self.focus = self.focus, None
        if focus is not None:
            focus.end_edit(commit=commit)

    def blur_unless_over(self, x, y):
        """Commit the focused field unless ``x``/``y`` is on it (a press anywhere else)."""
        if self.focus is not None and self.root.pick(x, y) is not self.focus:
            self.blur(commit=True)

    def _focus_order(self):
        return [w for w in self.root.walk() if getattr(w, 'takes_focus', False) and self._in_tree(w)]

    def _handle_focus(self, event):
        """True when the focused widget used ``event``."""
        focus = self.focus
        kind = event.type
        if kind in _POINTER_EVENTS or kind.startswith(('TIMER', 'NDOF', 'EVT_')):
            return False
        if kind == 'LEFTMOUSE':
            if self.root.pick(event.x, event.y) is focus:
                return True                      # on the field: keep editing
            if event.value == PRESS:
                self.blur(commit=True)           # elsewhere: commit, then the press acts
            return False
        if kind == 'RIGHTMOUSE':
            if event.value == PRESS:
                self.blur(commit=False)
            return True
        if kind == 'TAB':
            if event.value == PRESS:
                order = self._focus_order()
                self.blur(commit=True)
                if focus in order and len(order) > 1:
                    step = -1 if event.shift else 1
                    nxt = order[(order.index(focus) + step) % len(order)]
                    nxt.begin_edit()
                    self.focus = nxt
            return True
        focus.key_input(event)
        if not focus.editing:
            self.focus = None
        return True

    def end_drag(self, x=None, y=None, cancelled=False):
        """Finish the running drag (e.g. the host lost the pointer: ``cancelled=True``)."""
        widget, self.dragging = self.dragging, None
        self.pressed = None
        if widget is not None:
            px, py = self.pointer if x is None else (x, y)
            widget.drag_end(px, py, cancelled)

    def choose(self, widget):
        """Confirm ``widget``: activate now, or after the close animation."""
        if widget is None or not widget.is_enabled:
            return self._unhandled()
        if not self.modal or widget.keep_open:
            widget.activate()
            if getattr(widget, 'takes_focus', False) and getattr(widget, 'editing', False):
                self.set_focus(widget)
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
        dt = anim.frame_dt(now, self._last_frame, idle=anim.IDLE_FRAME)
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
        with draw.blend_mode('ALPHA'), draw.batched():
            self.root.draw(dc)
