"""Widget base class, draw context and layout containers.

Protocol overview
-----------------
Layout (two passes, like most retained-mode UI kits):

* ``measure(theme) -> (w, h)``  preferred size in screen pixels.
* ``arrange(rect, theme)``      receive final rect, position children.
* ``place(origin, theme)``      used for *root* widgets: position the widget
                                relative to an anchor point (the cursor).

Interaction is driven by :class:`~.overlay.Overlay`, which resolves exactly one
widget under the pointer via :meth:`Widget.pick`:

* ``interactive`` widgets can become *hot* (hovered), be pressed and clicked.
* ``blocks_pointer`` widgets are not clickable but claim the pointer, so
  nothing *behind* them reacts (e.g. a panel blocks radial-sector picking).

Drawing receives a :class:`DrawContext` that carries the theme, the current
interaction state and the overlay's open/close animation progress.
"""

from . import anim
from .geometry import Rect
from .theme import with_alpha


MENU = 'menu'   # ``options=MENU``: the widget opens a dropdown (three filled dots)


def option_dots(options):
    """The dots an ``options`` binding asks for, as filled flags: ``(count, index)``
    -- a toggle that switches between ``count`` options, ``index`` is the active one
    (one filled dot among empty ones) -- or :data:`MENU` (three filled dots)."""
    value = _resolve(options, None)
    if value is None:
        return []
    if value == MENU:
        return [True, True, True]
    try:
        count, index = value
    except (TypeError, ValueError):
        return []
    return [i == index for i in range(max(0, int(count)))]


def draw_dots(dc, flags, x, y, dx, dy, alpha):
    """``flags`` as dots centered on ``x, y``, one step ``(dx, dy)`` apart (screen px):
    filled ones solid, the others as rings."""
    from . import draw
    theme = dc.theme
    r = theme.px(1.8)
    n = len(flags)
    for i, filled in enumerate(flags):
        t = i - (n - 1) * 0.5
        px, py = x + dx * t, y + dy * t
        if filled:
            draw.circle(px, py, r, with_alpha(theme.text, 0.95 * alpha), segments=12)
        else:
            draw.circle_outline(px, py, r, with_alpha(theme.text_muted, 0.85 * alpha), width=max(1.0, theme.px(0.8)),
                                segments=12)


def _resolve(value, default=None):
    """Bindings may be plain values or zero-arg callables evaluated lazily."""
    if callable(value):
        try:
            return value()
        except Exception:
            return default
    return default if value is None else value


class DrawContext:
    """Per-frame information passed down the widget tree while drawing."""

    __slots__ = (
        'theme', 'origin', 'opened', 'closing', 'alpha', 'chosen',
        'pointer', 'pointer_widget', 'hot', 'pressed', 'now', 'dt',
    )

    def __init__(self, theme, origin=(0.0, 0.0), opened=1.0, closing=0.0, alpha=1.0,
                 chosen=None, pointer=(0.0, 0.0), pointer_widget=None, hot=None,
                 pressed=None, now=0.0, dt=0.0):
        self.theme = theme
        self.origin = origin
        self.opened = opened      # eased 0..1 open animation
        self.closing = closing    # eased 0..1 close animation (0 while open)
        self.alpha = alpha        # global fade multiplier
        self.chosen = chosen      # widget being confirmed while closing
        self.pointer = pointer
        self.pointer_widget = pointer_widget
        self.hot = hot
        self.pressed = pressed
        self.now = now
        self.dt = dt

    @property
    def is_closing(self):
        return self.chosen is not None or self.closing > 0.0

    def reveal(self, x, y):
        """Animate a point outward from the overlay origin while opening."""
        ox, oy = self.origin
        return ox + (x - ox) * self.opened, oy + (y - oy) * self.opened

    def reveal_scale(self, start=0.5):
        """Scale factor that grows from ``start`` to 1 while opening."""
        return start + (1.0 - start) * self.opened


class Widget:
    interactive = False      # can be hot / pressed / clicked
    blocks_pointer = False   # claims the pointer without being clickable
    drag_release = False     # releasing over it confirms even if pressed elsewhere
    draggable = False        # a press starts a drag: drag_begin / drag_update / drag_end
    activate_on_press = False  # activates on press instead of press+release (e.g. opens a
                               # flyout the pointer can then be dragged into)

    def __init__(self, *, key=None, on_click=None, selected=None, enabled=True,
                 visible=True, keep_open=False, options=None):
        self.key = key
        self.options = options       # dots: (count, index) of a multi-option toggle, or MENU
        self.parent = None
        self.children = []
        self.rect = Rect()
        self.on_click = on_click
        self.selected_binding = selected
        self.enabled_binding = enabled
        self.visible = visible
        self.keep_open = keep_open   # activating does not close a modal overlay
        self.hover_t = 0.0           # animated hover amount, 0..1

    # ---- tree --------------------------------------------------------------

    def add(self, child):
        child.parent = self
        self.children.append(child)
        return child

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()

    def find(self, key):
        for widget in self.walk():
            if widget.key == key:
                return widget
        return None

    # ---- bindings ----------------------------------------------------------

    @property
    def is_selected(self):
        return bool(_resolve(self.selected_binding, False))

    @property
    def is_enabled(self):
        return bool(_resolve(self.enabled_binding, True))

    # ---- layout ------------------------------------------------------------

    def measure(self, theme):
        return self.rect.width, self.rect.height

    def arrange(self, rect, theme):
        self.rect = rect

    def place(self, origin, theme):
        w, h = self.measure(theme)
        self.arrange(Rect.from_center(origin[0], origin[1], w, h), theme)

    def bounds(self):
        """Union of this widget's and all visible descendants' rects."""
        result = self.rect
        for child in self.children:
            if child.visible:
                result = result.union(child.bounds())
        return result

    # ---- picking -----------------------------------------------------------

    def contains(self, x, y):
        return self.rect.contains(x, y)

    def pick(self, x, y):
        """Top-most widget under ``(x, y)`` that is interactive or blocks the pointer."""
        if not self.visible:
            return None
        for child in reversed(self.children):
            hit = child.pick(x, y)
            if hit is not None:
                return hit
        if (self.interactive or self.blocks_pointer) and self.contains(x, y):
            return self
        return None

    def anchor_point(self, tx, ty):
        """``((x, y), (center_x, center_y))`` on this widget's outline facing ``(tx, ty)``.

        Used by connectors (e.g. the radial menu's curve) to attach to the
        hovered element. Widgets returning None defer to their parent.
        """
        return None

    def find_anchor(self, tx, ty):
        widget = self
        while widget is not None:
            point = widget.anchor_point(tx, ty)
            if point is not None:
                return point
            widget = widget.parent
        return None

    # ---- interaction -------------------------------------------------------

    def activate(self):
        """Run the click action."""
        if self.on_click is not None:
            self.on_click()

    def drag_begin(self, x, y):
        """``draggable`` widgets: the press that starts a drag."""

    def drag_update(self, x, y):
        """``draggable`` widgets: pointer moved while dragging (anywhere on screen)."""

    def drag_end(self, x, y, cancelled=False):
        """``draggable`` widgets: release (or cancel) ending the drag."""

    def on_key(self, event, ui):
        """Keyboard hook; return True when consumed. Children get it first."""
        for child in self.children:
            if child.visible and child.on_key(event, ui):
                return True
        return False

    # ---- drawing -----------------------------------------------------------

    def update(self, dc):
        target = 1.0 if (dc.hot is self and not dc.is_closing) else 0.0
        if dc.is_closing and dc.chosen is self:
            target = 1.0
        speed = dc.dt / max(dc.theme.hover_duration, 1e-4)
        self.hover_t = anim.approach(self.hover_t, target, speed)
        if self.hover_t != target:
            anim.request_frame()

    def draw(self, dc):
        if not self.visible:
            return
        self.update(dc)
        self.draw_self(dc)
        if self.options is not None:
            flags = option_dots(self.options)
            if flags:
                self.draw_options(dc, flags)
        for child in self.children:
            child.draw(dc)

    def draw_self(self, dc):
        pass

    def draw_options(self, dc, flags):
        """The option dots (see :func:`option_dots`): a column inside the right edge."""
        r = self.rect
        if r.width <= 0.0 or r.height <= 0.0:
            return
        step = dc.theme.px(5.0)
        alpha = dc.alpha * (1.0 if self.is_enabled else dc.theme.disabled_alpha)
        draw_dots(dc, flags, r.x1 - dc.theme.px(6.0), (r.y0 + r.y1) * 0.5, 0.0, -step, alpha)


# ---------------------------------------------------------------------------
# Layout containers
# ---------------------------------------------------------------------------

class _Container(Widget):
    def __init__(self, children=(), *, gap=8.0, **kwargs):
        super().__init__(**kwargs)
        self.gap = gap
        for child in children:
            self.add(child)

    def _visible_children(self):
        return [c for c in self.children if c.visible]


class Row(_Container):
    """Lays children out left-to-right, vertically centered (``align='top'``: top-aligned)."""

    def __init__(self, children=(), *, gap=8.0, align='center', **kwargs):
        super().__init__(children, gap=gap, **kwargs)
        self.align = align

    def measure(self, theme):
        sizes = [c.measure(theme) for c in self._visible_children()]
        if not sizes:
            return 0.0, 0.0
        gap = theme.px(self.gap)
        return sum(w for w, _ in sizes) + gap * (len(sizes) - 1), max(h for _, h in sizes)

    def arrange(self, rect, theme):
        self.rect = rect
        gap = theme.px(self.gap)
        children = self._visible_children()
        sizes = [c.measure(theme) for c in children]
        total = sum(w for w, _ in sizes) + gap * max(0, len(sizes) - 1)
        x = rect.cx - total * 0.5
        for child, (w, h) in zip(children, sizes):
            y0 = rect.y1 - h if self.align == 'top' else rect.cy - h * 0.5
            child.arrange(Rect.from_size(x, y0, w, h), theme)
            x += w + gap


class Column(_Container):
    """Lays children out top-to-bottom, horizontally centered."""

    def measure(self, theme):
        sizes = [c.measure(theme) for c in self._visible_children()]
        if not sizes:
            return 0.0, 0.0
        gap = theme.px(self.gap)
        return max(w for w, _ in sizes), sum(h for _, h in sizes) + gap * (len(sizes) - 1)

    def arrange(self, rect, theme):
        self.rect = rect
        gap = theme.px(self.gap)
        y = rect.y1
        for child in self._visible_children():
            w, h = child.measure(theme)
            child.arrange(Rect.from_size(rect.cx - w * 0.5, y - h, w, h), theme)
            y -= h + gap


class Grid(_Container):
    """Row-major grid with uniform cells sized to the largest child."""

    def __init__(self, children=(), *, columns=3, gap=8.0, **kwargs):
        super().__init__(children, gap=gap, **kwargs)
        self.columns = max(1, int(columns))

    def _cell(self, theme):
        sizes = [c.measure(theme) for c in self._visible_children()]
        if not sizes:
            return 0.0, 0.0
        return max(w for w, _ in sizes), max(h for _, h in sizes)

    def measure(self, theme):
        count = len(self._visible_children())
        if not count:
            return 0.0, 0.0
        cw, ch = self._cell(theme)
        gap = theme.px(self.gap)
        cols = min(self.columns, count)
        rows = (count + self.columns - 1) // self.columns
        return cols * cw + gap * (cols - 1), rows * ch + gap * (rows - 1)

    def arrange(self, rect, theme):
        self.rect = rect
        cw, ch = self._cell(theme)
        gap = theme.px(self.gap)
        w, _ = self.measure(theme)
        x_start = rect.cx - w * 0.5
        for index, child in enumerate(self._visible_children()):
            col = index % self.columns
            row = index // self.columns
            cx = x_start + col * (cw + gap) + cw * 0.5
            cy = rect.y1 - row * (ch + gap) - ch * 0.5
            cwi, chi = child.measure(theme)
            child.arrange(Rect.from_center(cx, cy, cwi, chi), theme)
