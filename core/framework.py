"""Event-driven tool framework (Blender-independent).

Concepts
--------
* :class:`ToolFrame` -- base class of everything that reacts to input: main
  tools (Square, Select, ...), subtools (color pick, eyedropper, ...) and
  global tools (Shift+number switching). A subtool *is* a tool.
* :class:`InputEvent` -- one input event. Whoever handles it calls
  :meth:`InputEvent.consume` (Unity's ``Event.Use()``); once consumed, nobody
  after that sees it.
* :class:`ToolManager` -- the core. Owns the registered tools, knows the
  selected (base) tool and iterates every tool's :meth:`ToolFrame.dispatch`
  until the event is consumed.

Event routing inside one tool (:meth:`ToolFrame.dispatch`)
---------------------------------------------------------
1. **Active subtools** (most recently activated first). An *exclusive*
   active subtool hides the event from its parent even if it does not consume
   it -- e.g. while the color picker is open, the brush never paints.
2. **Idle subtools**, in registration order: the first one whose shortcut
   matches gets activated (or, for a :class:`FunctionTool`, its function is
   called). Registration order is priority order.
3. :meth:`ToolFrame.on_event` -- catch-all hook.

Subtools are only reachable through their parent, so their shortcuts only
work while the parent is the active tool.

Writing a tool
--------------
::

    class MyTool(ToolFrame):
        tool_id = 'MY_TOOL'

        # shared-state keys this tool owns (declared when it is registered)
        state_defaults = {'my_tool_anchor': None}

        def on_register(self):
            # a plain function binding (a FunctionTool subtool)
            self.bind(Shortcut('C', ctrl=True), self.copy)
            # a hold-modifier subtool backed by two methods of this object
            self.fine = self.add_subtool(HoldTool('SHIFT'))
            # a full subtool class with its own shortcuts / subtools
            self.add_subtool(MyPopup(), Shortcut('E'))

        def on_activate(self, ctx, event): ...
        def on_deactivate(self, ctx): ...
        def copy(self, ctx, event): ...      # return False to NOT consume
"""

from typing import Callable, Dict, Iterable, List, Optional, Sequence


PRESS = 'PRESS'
RELEASE = 'RELEASE'
ANY = None

MODIFIER_KEYS: Dict[str, Sequence[str]] = {
    'SHIFT': ('LEFT_SHIFT', 'RIGHT_SHIFT'),
    'CTRL': ('LEFT_CTRL', 'RIGHT_CTRL'),
    'ALT': ('LEFT_ALT', 'RIGHT_ALT'),
}
MOUSE_BUTTONS = frozenset({'LEFTMOUSE', 'RIGHTMOUSE', 'MIDDLEMOUSE'})


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

class InputEvent:
    """One input event with Unity-style consumption.

    Attribute names match ``bpy.types.Event`` so handler code can treat it
    like a Blender event (``event.type``, ``event.mouse_region_x``, ...).
    """

    __slots__ = (
        'type', 'value', 'shift', 'ctrl', 'alt',
        'mouse_x', 'mouse_y', 'mouse_region_x', 'mouse_region_y',
        'pressure', 'is_tablet',
        'raw', 'consumed',
    )

    def __init__(self, type, value='NOTHING', *, shift=False, ctrl=False, alt=False,
                 mouse_x=0, mouse_y=0, mouse_region_x=0, mouse_region_y=0,
                 pressure=1.0, is_tablet=False, raw=None):
        self.type = type
        self.value = value
        self.shift = bool(shift)
        self.ctrl = bool(ctrl)
        self.alt = bool(alt)
        self.mouse_x = mouse_x
        self.mouse_y = mouse_y
        self.mouse_region_x = mouse_region_x
        self.mouse_region_y = mouse_region_y
        self.pressure = float(pressure)   # tablet pen pressure 0..1 (1.0 for a mouse)
        self.is_tablet = bool(is_tablet)
        self.raw = raw
        self.consumed = False

    @classmethod
    def from_blender(cls, event):
        return cls(
            event.type, event.value,
            shift=event.shift, ctrl=event.ctrl, alt=event.alt,
            mouse_x=event.mouse_x, mouse_y=event.mouse_y,
            mouse_region_x=event.mouse_region_x, mouse_region_y=event.mouse_region_y,
            pressure=getattr(event, 'pressure', 1.0),
            is_tablet=getattr(event, 'is_tablet', False),
            raw=event,
        )

    def consume(self):
        """Mark the event as used; no later tool will receive it."""
        self.consumed = True

    use = consume  # Unity spelling

    @property
    def is_press(self):
        return self.value == PRESS

    @property
    def is_release(self):
        return self.value == RELEASE

    def held(self, modifier: str) -> bool:
        """True while ``'SHIFT'`` / ``'CTRL'`` / ``'ALT'`` is held."""
        return bool(getattr(self, modifier.lower()))

    def is_modifier_key(self, modifier: str) -> bool:
        return self.type in MODIFIER_KEYS[modifier]

    def __repr__(self):
        mods = ''.join(m[0] for m in ('shift', 'ctrl', 'alt') if getattr(self, m))
        return f"<InputEvent {self.type} {self.value}{' +' + mods if mods else ''}{' used' if self.consumed else ''}>"


class Shortcut:
    """Matches events by key, value and modifier state.

    ``type`` may be a key name, a modifier name (``'SHIFT'`` matches both
    shift keys) or a sequence of those. ``value=None`` matches any value
    (use it for ``MOUSEMOVE``). Modifier arguments: ``True`` = must be held,
    ``False`` = must not be held, ``None`` = don't care.
    """

    __slots__ = ('types', 'value', 'shift', 'ctrl', 'alt')

    def __init__(self, type, value=PRESS, *, shift=None, ctrl=None, alt=None):
        names = (type,) if isinstance(type, str) else tuple(type)
        expanded = []
        for name in names:
            expanded.extend(MODIFIER_KEYS.get(name, (name,)))
        self.types = frozenset(expanded)
        self.value = value
        self.shift = shift
        self.ctrl = ctrl
        self.alt = alt

    def matches(self, event) -> bool:
        if event.type not in self.types:
            return False
        if self.value is not None and event.value != self.value:
            return False
        for name in ('shift', 'ctrl', 'alt'):
            want = getattr(self, name)
            if want is not None and bool(getattr(event, name)) != want:
                return False
        return True

    def __repr__(self):
        mods = [f"{m}={getattr(self, m)}" for m in ('shift', 'ctrl', 'alt') if getattr(self, m) is not None]
        return f"Shortcut({sorted(self.types)}, {self.value}{', ' if mods else ''}{', '.join(mods)})"


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

class ToolFrame:
    """Base class for main tools, subtools and global tools."""

    tool_id: Optional[str] = None   # main tools: the mode id; subtools: optional
    label: str = ''

    # ---- behaviour flags (class defaults, override per class) ---------------
    priority: int = 0               # manager iteration order for root tools (higher first)
    is_global: bool = False         # active for the whole session, not only when selected
    screen_space: bool = False      # global on-screen UI: gets events before the core's
                                    # cursor-over-image gating (ToolManager.dispatch_screen)
    exclusive: bool = False        # while active as subtool, the parent gets no events
    captures_input: bool = False    # while active, the core skips its cursor/bounds gating
    consume_trigger: bool = True    # consume the event that activated this subtool
    triggers: Sequence[Shortcut] = ()  # shortcuts that activate this tool as a subtool

    # ---- shared state owned by this tool (declared when registered) -----------
    state_defaults: Dict[str, object] = {}     # key -> default in the shared state
    persistent_state: Sequence[str] = ()       # keys that survive the end of a session

    def __init__(self):
        self.parent: Optional['ToolFrame'] = None
        self.host: Optional['ToolFrame'] = None  # tool that drives this one as a stand-in
        self.manager: Optional['ToolManager'] = None
        self.subtools: List['ToolFrame'] = []
        self.is_active = False
        self._active_subtools: List['ToolFrame'] = []
        self._registered = False

    # ---- registration --------------------------------------------------------

    def on_register(self) -> None:
        """Register shortcuts and subtools here (called once)."""

    def setup(self, manager: 'ToolManager', parent: Optional['ToolFrame'] = None) -> None:
        self.manager = manager
        self.parent = parent
        if not self._registered:
            self._registered = True
            manager.declare_state(self.state_defaults, self.persistent_state)
            self.on_register()
        for sub in self.subtools:
            sub.setup(manager, self)

    def add_subtool(self, tool: 'ToolFrame', *triggers: Shortcut) -> 'ToolFrame':
        """Attach ``tool`` as a subtool; ``triggers`` override its class triggers."""
        if triggers:
            tool.triggers = tuple(triggers)
        self.subtools.append(tool)
        if self.manager is not None:
            tool.setup(self.manager, self)
        else:
            tool.parent = self
        return tool

    def bind(self, shortcut, fn: Callable, *, consume: bool = True) -> 'FunctionTool':
        """Call ``fn(ctx, event)`` when ``shortcut`` matches (a FunctionTool subtool).

        ``shortcut`` may be one :class:`Shortcut` or a sequence of them. The
        event is consumed unless ``fn`` returns ``False`` (or ``consume=False``).
        """
        shortcuts = (shortcut,) if isinstance(shortcut, Shortcut) else tuple(shortcut)
        return self.add_subtool(FunctionTool(fn, consume=consume), *shortcuts)

    # ---- hooks ---------------------------------------------------------------

    def on_activate(self, ctx, event) -> None:
        """Tool became active. ``event`` is the triggering event or ``None``."""

    def on_deactivate(self, ctx) -> None:
        """Tool became inactive (its active subtools are already deactivated)."""

    def on_interrupt(self, ctx) -> None:
        """Abort in-progress work (e.g. a stroke) but stay active."""

    def on_event(self, ctx, event) -> None:
        """Catch-all, called when no subtool consumed ``event``."""

    def draw_overlay(self, ctx) -> None:
        """Draw this tool's canvas overlay (POST_PIXEL)."""

    def on_session_end(self, ctx) -> None:
        """The core stopped running (every registered root tool is told)."""

    # ---- state ---------------------------------------------------------------

    @property
    def active_subtools(self):
        return tuple(self._active_subtools)

    def is_capturing(self) -> bool:
        return any(sub.captures_input or sub.is_capturing() for sub in self._active_subtools)

    def wants_activation(self, ctx, event) -> bool:
        return any(sc.matches(event) for sc in self.triggers)

    # ---- activation ------------------------------------------------------------

    def activate(self, ctx, event=None, host: Optional['ToolFrame'] = None) -> None:
        if self.is_active:
            return
        if self.parent is not None and self.exclusive:
            self.parent.on_interrupt(ctx)  # a blocking subtool takes over: abort parent's work
        self.is_active = True
        self.host = host
        if self.parent is not None and host is None:
            self.parent._active_subtools.append(self)
        self.on_activate(ctx, event)

    def deactivate(self, ctx) -> None:
        if not self.is_active:
            return
        for sub in reversed(self._active_subtools):
            sub.deactivate(ctx)
        self.is_active = False
        if self.parent is not None and self in self.parent._active_subtools:
            self.parent._active_subtools.remove(self)
        self.host = None
        self.on_deactivate(ctx)

    def interrupt(self, ctx) -> None:
        for sub in list(self._active_subtools):
            sub.interrupt(ctx)
        self.on_interrupt(ctx)

    def try_trigger(self, ctx, event) -> bool:
        """Activate when a trigger matches; True when this subtool reacted."""
        if not self.wants_activation(ctx, event):
            return False
        self.activate(ctx, event)
        if self.consume_trigger:
            event.consume()
        return True

    # ---- event routing ---------------------------------------------------------

    def dispatch(self, ctx, event) -> None:
        for sub in reversed(list(self._active_subtools)):
            if not sub.is_active:
                continue
            sub.dispatch(ctx, event)
            if event.consumed or (sub.is_active and sub.exclusive):
                return
        for sub in list(self.subtools):
            if sub.is_active:
                continue
            if sub.try_trigger(ctx, event):
                if event.consumed or (sub.is_active and sub.exclusive):
                    return
        self.on_event(ctx, event)

    def draw_chain(self, ctx) -> None:
        self.draw_overlay(ctx)
        for sub in self._active_subtools:
            sub.draw_chain(ctx)

    def __repr__(self):
        return f"<{type(self).__name__} {self.tool_id or ''}{' active' if self.is_active else ''}>"


class FunctionTool(ToolFrame):
    """A subtool that just calls a function when its shortcut matches."""

    def __init__(self, fn: Callable, *triggers: Shortcut, consume: bool = True):
        super().__init__()
        self.fn = fn
        self.consume = consume
        if triggers:
            self.triggers = tuple(triggers)

    def try_trigger(self, ctx, event) -> bool:
        if not self.wants_activation(ctx, event):
            return False
        result = self.fn(ctx, event)
        if self.consume and result is not False:
            event.consume()
        return True

    def __repr__(self):
        return f"<FunctionTool {getattr(self.fn, '__name__', self.fn)} {list(self.triggers)}>"


class HoldTool(ToolFrame):
    """Subtool that is active while a modifier key is held.

    Activates on the modifier's key press, on a mouse-button press with the
    modifier held, or -- with ``activate_on_any_event`` -- on any event while
    held. Deactivates as soon as an event arrives without the modifier
    (this also recovers from missed key-release events).

    Pass ``on_hold`` / ``on_release`` to back it with plain functions
    ``fn(ctx)`` -- e.g. methods of the parent tool.
    """

    modifier: str = 'SHIFT'
    activate_on_mouse_press: bool = True
    activate_on_any_event: bool = False
    consume_trigger = False

    def __init__(self, modifier: Optional[str] = None, *, on_hold: Optional[Callable] = None,
                 on_release: Optional[Callable] = None, activate_on_any_event: Optional[bool] = None):
        super().__init__()
        if modifier is not None:
            self.modifier = modifier
        if activate_on_any_event is not None:
            self.activate_on_any_event = activate_on_any_event
        self._on_hold = on_hold
        self._on_release = on_release

    def wants_activation(self, ctx, event) -> bool:
        if event.is_modifier_key(self.modifier):
            return event.is_press
        if not event.held(self.modifier):
            return False
        if self.activate_on_any_event:
            return True
        return self.activate_on_mouse_press and event.is_press and event.type in MOUSE_BUTTONS

    def try_trigger(self, ctx, event) -> bool:
        if not super().try_trigger(ctx, event):
            return False
        if event.is_modifier_key(self.modifier):
            event.consume()  # the modifier key itself is fully handled here
        return True

    def dispatch(self, ctx, event) -> None:
        if not event.held(self.modifier):
            self.deactivate(ctx)
            if event.is_modifier_key(self.modifier):
                event.consume()
            return
        super().dispatch(ctx, event)

    def on_activate(self, ctx, event) -> None:
        if self._on_hold is not None:
            self._on_hold(ctx)

    def on_deactivate(self, ctx) -> None:
        if self._on_release is not None:
            self._on_release(ctx)


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

class ToolManager:
    """Owns the tools, tracks the selected tool and routes events.

    ``ctx`` objects passed in must provide ``ctx.mode`` (the selected tool id
    as stored by the host, e.g. a WindowManager enum) and
    ``ctx.set_mode(tool_id)``.
    """

    def __init__(self, declare_state: Optional[Callable] = None):
        # ``declare_state(defaults, persistent)`` registers each tool's
        # ``state_defaults`` with the host's shared state (see core.state).
        self._declare_state = declare_state
        self._tools: List[ToolFrame] = []
        self._by_id: Dict[str, ToolFrame] = {}
        self.base_tool: Optional[ToolFrame] = None
        self.effective_mode: Optional[str] = None
        self.running = False

    # ---- registration --------------------------------------------------------

    def declare_state(self, defaults, persistent=()) -> None:
        if self._declare_state is not None and (defaults or persistent):
            self._declare_state(defaults, persistent)

    def register(self, tool: ToolFrame) -> ToolFrame:
        tool.setup(self)
        self._tools.append(tool)
        self._tools.sort(key=lambda t: -t.priority)  # stable: keeps registration order
        if tool.tool_id and not tool.is_global:
            if tool.tool_id in self._by_id:
                raise ValueError(f"Tool id {tool.tool_id!r} registered twice")
            self._by_id[tool.tool_id] = tool
        return tool

    def register_all(self, tools: Iterable[ToolFrame]) -> None:
        for tool in tools:
            self.register(tool)

    def tool(self, tool_id) -> Optional[ToolFrame]:
        return self._by_id.get(tool_id)

    @property
    def tools(self):
        return tuple(self._tools)

    def root_tools(self):
        """Tools the core iterates: active, and not driven by another tool."""
        return [t for t in self._tools if t.is_active and t.parent is None and t.host is None]

    @property
    def effective_tool(self) -> Optional[ToolFrame]:
        return self.tool(self.effective_mode)

    # ---- session -------------------------------------------------------------

    def begin(self, ctx) -> None:
        self.running = True
        for tool in self._tools:
            if tool.is_global:
                tool.activate(ctx)
        self.sync(ctx)

    def end(self, ctx) -> None:
        for tool in self.root_tools():
            tool.deactivate(ctx)
        for tool in self._tools:
            tool.on_session_end(ctx)
        self.base_tool = None
        self.effective_mode = None
        self.running = False

    # ---- selection -------------------------------------------------------------

    def sync(self, ctx) -> None:
        """Follow mode changes made outside the manager (pies, UI, operators)."""
        mode = ctx.mode
        if self.base_tool is not None and mode == self.effective_mode:
            return
        self._switch_base(ctx, mode)

    def select(self, ctx, tool_id) -> None:
        """Make ``tool_id`` the selected tool (ends temporary overrides)."""
        ctx.set_mode(tool_id)
        self._switch_base(ctx, tool_id)

    def set_effective_mode(self, ctx, tool_id) -> None:
        """Temporarily show/use ``tool_id`` without changing the selected tool."""
        self.effective_mode = tool_id
        if ctx.mode != tool_id:
            ctx.set_mode(tool_id)

    def _switch_base(self, ctx, tool_id) -> None:
        old = self.base_tool
        new = self.tool(tool_id)
        if old is not new:
            if old is not None:
                old.deactivate(ctx)   # also ends its temporary overrides
            if new is not None and new.is_active:
                new.deactivate(ctx)   # was driven as a stand-in: detach first
            self.base_tool = new
            if new is not None:
                new.activate(ctx)
        # Deactivated overrides may have restored an older mode; the selection wins.
        if ctx.mode != tool_id:
            ctx.set_mode(tool_id)
        self.effective_mode = tool_id

    # ---- routing ---------------------------------------------------------------

    def dispatch_screen(self, ctx, event) -> bool:
        """Offer ``event`` to the active ``screen_space`` root tools (on-screen UI).

        The host calls this before deciding whether the cursor is over the
        image, so on-screen UI also works over parts of the editor outside
        it. :meth:`dispatch` skips these tools: each sees an event once.
        """
        self.sync(ctx)
        for tool in self.root_tools():
            if tool.screen_space:
                tool.dispatch(ctx, event)
                if event.consumed:
                    break
        return event.consumed

    def dispatch(self, ctx, event) -> bool:
        """Offer ``event`` to every active root tool until one consumes it."""
        self.sync(ctx)
        for tool in self.root_tools():
            if tool.screen_space:
                continue  # offered in dispatch_screen()
            tool.dispatch(ctx, event)
            if event.consumed:
                break
        return event.consumed

    def interrupt(self, ctx) -> None:
        for tool in self.root_tools():
            tool.interrupt(ctx)

    def is_capturing(self) -> bool:
        return any(t.is_capturing() for t in self.root_tools())

    def draw(self, ctx) -> None:
        for tool in self.root_tools():
            tool.draw_chain(ctx)
