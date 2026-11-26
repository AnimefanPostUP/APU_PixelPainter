"""Color-pick subtool (E): the color selector at the cursor.

Shows the same :class:`~ui.kit.ColorSelector` as the pen bar, with the layout
(Sheet / Square / Triangle / Wheel), model (HSV / HSL) and sliders chosen in
the settings popup (Color Selector tab). It opens with the current color's
spot under the cursor.

* Main area (sheet / square / triangle / disc): follows the mouse -- the color
  under the cursor applies instantly; a click applies it and closes.
  Leaving the main area (e.g. on the way to a bar) restores the color from
  where the mouse last paused.
* Hold Shift: the mouse moves slower (``SLOW_FACTOR``) over the whole selector --
  the cursor itself crawls, for precise picking, bar / slider drags and taps.
* Bars / sliders: click to jump, press and drag to swipe (relative) -- also
  how pens without hover use the whole selector.
* Mouse wheel: over a bar / slider changes that channel; elsewhere the channel
  the main area does not set (Sheet: saturation, Square / Triangle: hue,
  Wheel: value / lightness). Shift: fine steps.
* E: switch between the primary and secondary color.
* Click outside the selector / Enter / Space: done.
* Right-click / Esc: restore the colors from before and close (during a drag:
  only discard that drag).
"""

import colorsys
import time

from ...core.framework import Shortcut, ToolFrame
from ...ui.kit import ColorBubble, ColorSelector, Column, Overlay, Panel, Row, Theme, UIEvent
from ...ui.kit.events import PASS_THROUGH
from . import helpers


_SATURATION_EPS = 0.01
SLOW_FACTOR = 0.2          # Shift: the mouse moves this much slower over the selector
_WHEEL_STEP = 0.05
_WHEEL_STEP_FINE = 0.01
SELECTOR_WIDTH = 300.0     # unscaled px
_GAIN = 0.5


class ColorPickTool(ToolFrame):
    """Color selector at the cursor. Click outside / Enter confirm, RMB / Esc cancel,
    E toggles primary / secondary."""

    label = "Color Pick"
    mode_name = 'COLOR_PICK'
    exclusive = True
    captures_input = True
    triggers = (Shortcut('E', shift=False, ctrl=False, alt=False),)

    state_defaults = {
        **helpers.SUB_MODE_STATE,
        'sub_orig_color':     None,
        'sub_orig_color_secondary': None,
        'sub_color_target':   'PRIMARY',
        'sub_color_h':        None,   # the edited color (kept as HSV: hue survives grey)
        'sub_color_s':        None,
        'sub_color_v':        None,
        'sub_color_start_h':  None,   # the color from before (marked on the selector)
        'sub_color_start_s':  None,
        'sub_color_start_v':  None,
    }

    clock = staticmethod(time.perf_counter)

    def __init__(self):
        super().__init__()
        self.overlay = None
        self.selector = None
        self.panel = None
        self._pointer = (0.0, 0.0)    # region point the selector sees (slowed while Shift is held)
        self._last_real = (0, 0)      # where the OS cursor is (after our warps)

    def on_register(self):
        self.bind(Shortcut('E'), self._toggle_target)
        self.bind(Shortcut('WHEELUPMOUSE', None), lambda ctx, ev: self._adjust_saturation(ctx, ev, +1))
        self.bind(Shortcut('WHEELDOWNMOUSE', None), lambda ctx, ev: self._adjust_saturation(ctx, ev, -1))
        self.bind(Shortcut(('RET', 'NUMPAD_ENTER', 'SPACE')), self._confirm)

    # ---- lifecycle ---------------------------------------------------------------

    def on_activate(self, ctx, event):
        state, settings = ctx.state, ctx.settings
        rgb = settings.get_brush_rgb(ctx.context)
        sec_rgb = settings.get_brush_secondary_rgb(ctx.context)
        state['sub_mode'] = self.mode_name
        state['sub_color_target'] = 'PRIMARY'
        state['sub_orig_color'] = tuple(rgb)
        state['sub_orig_color_secondary'] = tuple(sec_rgb) if sec_rgb is not None else None
        self._load_color(state, rgb)
        helpers.set_sub_start_to_event(state, event)
        self._build(ctx, event)
        ctx.redraw()

    def on_deactivate(self, ctx):
        if self.overlay is not None and self.overlay.dragging is not None:
            self.overlay.end_drag()
        self.overlay = self.selector = self.panel = None
        if ctx.state.get('sub_mode') == self.mode_name:
            ctx.state['sub_mode'] = None
        ctx.redraw()

    def on_interrupt(self, ctx):
        if self.overlay is not None and self.overlay.dragging is not None:
            self.overlay.end_drag()

    def draw_overlay(self, ctx):
        from ...overlays import sub_modes
        sub_modes.draw_sub_mode_overlay(ctx.context, ctx.state)
        if self.overlay is not None:
            self.overlay.draw()

    # ---- building --------------------------------------------------------------------

    @staticmethod
    def _setting(ctx, name, default):
        try:
            return getattr(ctx.wm, f'pixel_painter_color_selector_{name}', default)
        except Exception:
            return default

    def _build(self, ctx, event):
        state = ctx.state
        self.selector = ColorSelector(
            lambda: (state['sub_color_h'], state['sub_color_s'], state['sub_color_v']),
            lambda h, s, v: self._set_hsv(ctx, h, s, v),
            original=lambda: (state['sub_color_start_h'], state['sub_color_start_s'], state['sub_color_start_v']),
            live=True,
            layout=self._setting(ctx, 'layout', 'SHEET'),
            model=self._setting(ctx, 'model', 'HSV'),
            sliders=set(self._setting(ctx, 'sliders', set()) or ()),
            gain=_GAIN, key='COLOR_SELECTOR')
        bubble = ColorBubble(lambda: self._bubble_colors(ctx), True, lambda: True, radius=13.0)
        bubble.interactive = False
        self.panel = Panel(Column([Row([bubble]), self.selector], gap=6.0),
                           title=self._title(state), padding=8.0)
        theme = Theme.for_context(ctx.context)
        self.selector.fit_width = theme.px(SELECTOR_WIDTH)
        mx, my = event.mouse_region_x, event.mouse_region_y
        self._set_pointer(mx, my)
        self.overlay = Overlay(self.panel, theme=theme, origin=(mx, my), modal=False, animate=False)
        # The current color's spot under the cursor: nothing changes until the mouse moves.
        px, py = self.selector.main_point()
        self.overlay.move_origin(mx - px, my - py)
        region = getattr(ctx, 'region', None)
        if region is not None:
            dx, dy = self.overlay.fit_inside(region.width, region.height)
            if dx or dy:   # pushed inside the editor: the cursor moves along
                self._warp(ctx, event, mx + dx, my + dy)
                self._set_pointer(mx + dx, my + dy)
        self.selector.follow_begin(self.clock())

    @staticmethod
    def _warp(ctx, event, x, y):
        """Move the OS cursor to region point ``x``/``y``."""
        try:
            ox, oy = event.mouse_x - event.mouse_region_x, event.mouse_y - event.mouse_region_y
            ctx.context.window.cursor_warp(int(round(x + ox)), int(round(y + oy)))
        except Exception:
            pass

    @staticmethod
    def _title(state):
        return "Secondary Color" if state.get('sub_color_target') == 'SECONDARY' else "Primary Color"

    def _bubble_colors(self, ctx):
        """(old, new) RGB of the color being edited."""
        state = ctx.state
        if state.get('sub_color_target') == 'SECONDARY':
            old = state.get('sub_orig_color_secondary')
            new = ctx.settings.get_brush_secondary_rgb(ctx.context)
        else:
            old = state.get('sub_orig_color')
            new = ctx.settings.get_brush_rgb(ctx.context)
        return tuple(old or new), tuple(new)

    # ---- color -----------------------------------------------------------------------

    @staticmethod
    def _load_color(state, rgb):
        """Edit ``rgb``; hue survives when it is grey (kept from the last edit)."""
        h, s, v = colorsys.rgb_to_hsv(*rgb)
        if state.get('sub_color_s') is not None and s <= _SATURATION_EPS:
            h = state.get('sub_color_h') or 0.0
        state['sub_color_h'], state['sub_color_s'], state['sub_color_v'] = h, s, v
        state['sub_color_start_h'], state['sub_color_start_s'], state['sub_color_start_v'] = h, s, v

    def _set_hsv(self, ctx, h, s, v):
        state = ctx.state
        state['sub_color_h'], state['sub_color_s'], state['sub_color_v'] = h, s, v
        rgb = colorsys.hsv_to_rgb(h, s, v)
        if state.get('sub_color_target') == 'SECONDARY':
            ctx.settings.set_brush_secondary_rgb(ctx.context, *rgb)
        else:
            ctx.settings.set_brush_rgb(ctx.context, *rgb)

    # ---- slow pointer (Shift) ------------------------------------------------------------

    def _set_pointer(self, x, y):
        """The selector's pointer (region px) and where the OS cursor is now."""
        self._pointer = (float(x), float(y))
        self._last_real = (x, y)

    def _track(self, ctx, event):
        """Region point the selector sees for ``event``.

        While Shift is held the mouse is slowed down: movement is scaled by
        ``SLOW_FACTOR`` and the OS cursor is moved back to the slowed point, so
        the cursor itself crawls -- precise picking on the main area, precise
        bar / slider drags and taps alike. The slowed point keeps sub-pixel
        precision (the cursor can only sit on whole pixels).
        """
        rx, ry = event.mouse_region_x, event.mouse_region_y
        if not event.shift:
            self._set_pointer(rx, ry)
            return self._pointer
        if event.type != 'MOUSEMOVE':
            return self._pointer       # clicks / wheel land on the slowed point
        lx, ly = self._last_real
        px, py = self._pointer
        px += (rx - lx) * SLOW_FACTOR
        py += (ry - ly) * SLOW_FACTOR
        self._pointer = (px, py)
        tx, ty = int(round(px)), int(round(py))
        if (tx, ty) != (rx, ry):
            self._warp(ctx, event, tx, ty)
        self._last_real = (tx, ty)
        return self._pointer

    # ---- events ----------------------------------------------------------------------

    def on_event(self, ctx, event):
        overlay = self.overlay
        if overlay is None:
            return
        x, y = self._track(ctx, event)
        selector = self.selector
        was_dragging = overlay.dragging is not None
        if (not was_dragging and event.type == 'LEFTMOUSE' and event.value == 'PRESS'
                and selector.shape.follows(x, y)):
            event.consume()            # a click on the main area: take that color, done
            selector.follow(x, y, self.clock())
            self._confirm(ctx, event)
            return
        result = overlay.handle(UIEvent(type=event.type, value=event.value, x=x, y=y,
                                        shift=event.shift, ctrl=event.ctrl, alt=event.alt))
        if result != PASS_THROUGH or was_dragging:
            event.consume()
            ctx.redraw()
            return
        if event.type == 'MOUSEMOVE':
            selector.follow(x, y, self.clock())   # the main area follows the mouse
            event.consume()
            ctx.redraw()
            return
        if event.value != 'PRESS':
            return
        if event.type == 'LEFTMOUSE':
            event.consume()
            if overlay.pointer_widget is None:   # outside the panel: done
                self._confirm(ctx, event)
        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            event.consume()
            self._cancel(ctx, event)

    # ---- actions ---------------------------------------------------------------------

    def _confirm(self, ctx, event):
        self.deactivate(ctx)

    def _cancel(self, ctx, event):
        state, settings = ctx.state, ctx.settings
        settings.set_brush_rgb(ctx.context, *state['sub_orig_color'])
        if state['sub_orig_color_secondary'] is not None:
            settings.set_brush_secondary_rgb(ctx.context, *state['sub_orig_color_secondary'])
        self.deactivate(ctx)

    def _adjust_saturation(self, ctx, event, direction):
        if self.selector is None:
            return
        step = _WHEEL_STEP_FINE if event.shift else _WHEEL_STEP
        self.selector.wheel(*self._track(ctx, event), direction * step)
        ctx.redraw()

    def _toggle_target(self, ctx, event):
        if event.shift:
            return  # swallowed: Shift+E must not open STRENGTH on top
        if self.overlay is not None and self.overlay.dragging is not None:
            return
        state, settings, context = ctx.state, ctx.settings, ctx.context
        if state.get('sub_color_target') == 'SECONDARY':
            if state.get('sub_orig_color_secondary') is not None:
                settings.set_brush_secondary_rgb(context, *state['sub_orig_color_secondary'])
            state['sub_color_target'] = 'PRIMARY'
            rgb = settings.get_brush_rgb(context)
        else:
            if state.get('sub_orig_color') is not None:
                settings.set_brush_rgb(context, *state['sub_orig_color'])
            state['sub_color_target'] = 'SECONDARY'
            rgb = settings.get_brush_secondary_rgb(context)
        self._load_color(state, rgb)
        if self.panel is not None:
            self.panel.title = self._title(state)
        if self.selector is not None and self.selector.parts:
            # The other color's spot under the cursor, so moving on starts from it.
            px, py = self.selector.main_point()
            self._warp(ctx, event, px, py)
            self._pointer = (px, py)
            self._last_real = (int(round(px)), int(round(py)))
            self.selector.follow_begin(self.clock())
        ctx.redraw()
