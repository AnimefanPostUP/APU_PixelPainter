"""Pen bar tool: on-screen controls for pen / tablet painting -- the pen menu and the
color selector (see :mod:`ui.pen_bar`).

A global, ``screen_space`` tool: the core offers it every event before its
cursor-over-image gating, so the bar works anywhere in the editor. Shown
while ``pixel_painter_pen_bar`` is enabled. Besides forwarding events to the
widgets it

* runs the armed eyedropper on the next canvas press,
* edits the pen's color for the color pad (keeping hue / saturation through
  grey and black, where RGB has none) -- applied on release (the original
  stays marked until the old / new bubble is tapped), or with Preview on
  (``pixel_painter_pen_color_preview``, set in the settings popup) kept
  pending (the brush keeps its color) until the old / new bubble is tapped, and
* with the RMB lock on, turns pen-tip (left button) presses into right
  button presses, so the pen paints with the secondary color / RMB settings.
* keeps the optional tertiary color (``tools/tertiary_color.py``): selected, the
  pen tip paints with it; the color selector then edits the primary or secondary
  color named by ``pen_color_target`` (tap one of them to switch).
"""

import colorsys

import bpy

from ...core.context import ToolContext
from ...core.framework import ToolFrame
from ...ui.kit import Theme, UIEvent, hsv_for_rgb
from ...ui.pen.bar import PenBar
from ...ui.pen.metrics import LAYOUT_STATE
from ...model import tertiary_color
from .actions.colors import ColorActions
from .actions.falloff import FalloffActions
from .actions.mask import MaskActions
from .actions.palettes import PaletteActions
from .actions.settings import SettingsActions
from .actions.windows import WindowActions
from .layout import LayoutStore
from .eyedropper import PenEyedropperTool



def _side_insets(area, region):
    """Widths of overlapping sidebar regions covering the WINDOW region.

    The toolbar (TOOLS) is ignored: the bar sits at the editor edge, over the
    toolbar's empty lower part (the session sees pen events before the toolbar).
    """
    left = right = 0.0
    for other in area.regions:
        if other.type != 'UI' or other.width <= 1 or other.height <= 1:
            continue
        if other.x + other.width * 0.5 < region.x + region.width * 0.5:
            left = max(left, other.x + other.width - region.x)
        else:
            right = max(right, region.x + region.width - other.x)
    return max(0.0, left), max(0.0, right)


class PenBarTool(ColorActions, SettingsActions, PaletteActions, FalloffActions, WindowActions, MaskActions,
                 ToolFrame):
    label = "Pen Bar"
    is_global = True
    screen_space = True
    priority = 200

    state_defaults = {
        'pen_armed':         None,   # 'EYEDROPPER_PRIMARY' / '_SECONDARY': runs on the next canvas press
        'pen_pick_target':   None,   # the color the running pen eyedropper sets ('PRIMARY' / 'SECONDARY')
        'pen_rmb_lock':      False,  # the pen tip paints like the right mouse button
        tertiary_color.ACTIVE_KEY: False,               # the pen tip paints the tertiary color
        tertiary_color.T_KEY: tertiary_color.DEFAULT_T,  # its spot on the primary -> secondary gradient
        tertiary_color.TARGET_KEY: 'PRIMARY',           # meanwhile the color selector edits this one
        'pen_bar_collapsed': False,
        'pen_color_panel':   True,   # the color selector is shown
        **LAYOUT_STATE,              # menu / color selector size and position (Reset Pen UI)
        'pen_bar_locked':    False,  # menu: no moving / resizing
        'pen_color_locked':  False,  # color selector: no moving / resizing
        'pen_mask_panel':    False,  # the Mask window is shown
        'pen_mask_locked':   False,
        'pen_view_panel':    False,  # the View window is shown
        'pen_view_locked':   False,
        'pen_view_autofit':  True,   # View window: re-fit the object after orient / orbit / roll
        'pen_view_compact':  False,  # View window: only the Orient dial (the Orbit dial hidden)
        'pen_settings_panel':  False,  # the Settings window is shown
        'pen_settings_locked': False,
        'pen_library_panel':   False,  # the Palettes window is shown
        'pen_library_locked':  False,
        'pen_mask_help':     False,  # the window's '?' help text is shown
        'pen_view_help':     False,
        'pen_palette_view':  False,  # the palette band shows the project's palettes (else the active one's colors)
        'pen_palette_status': None,  # last message of the palette library window (also set by palette_ops)
        'pen_hsv':           None,   # (rgb, hsv) last written by the color pad
        'pen_color_original': None,  # (target, hsv) before the pad edits: bubble + cross compare to it
        'pen_color_pending': None,   # (target, hsv) Preview: pad color not yet applied to the brush
    }
    persistent_state = ('pen_rmb_lock', tertiary_color.ACTIVE_KEY, tertiary_color.T_KEY, tertiary_color.TARGET_KEY,
                        'pen_bar_collapsed', 'pen_color_panel',
                        *LAYOUT_STATE, 'pen_bar_locked', 'pen_color_locked', 'pen_palette_view',
                        'pen_mask_panel', 'pen_mask_locked', 'pen_view_panel', 'pen_view_locked',
                        'pen_view_autofit', 'pen_view_compact', 'pen_mask_help', 'pen_view_help',
                        'pen_settings_panel', 'pen_settings_locked', 'pen_library_panel', 'pen_library_locked')
    # Saved per project (scene property, tools/pen_layout.py): the windows' open / collapsed
    # state, position, scale, lock and help.
    layout_keys = (*LAYOUT_STATE, 'pen_bar_collapsed', 'pen_bar_locked',
                   'pen_color_panel', 'pen_color_locked',
                   'pen_mask_panel', 'pen_mask_locked', 'pen_mask_help',
                   'pen_view_panel', 'pen_view_locked', 'pen_view_help', 'pen_view_autofit',
                   'pen_view_compact', 'pen_settings_panel', 'pen_settings_locked',
                   'pen_library_panel', 'pen_library_locked')

    def __init__(self, registry):
        super().__init__()
        self.registry = registry
        self.bar = None             # built on first use (needs the icon set)
        self._ctx = None            # ToolContext of the event / draw being handled
        self._remap_release = False
        self._library = None        # palette library (palettes.json), loaded on first use
        self._layout_store = LayoutStore({k: self.state_defaults[k] for k in self.layout_keys})

    def on_register(self):
        # No triggers: the bar starts them for the next canvas press.
        self.eyedropper = self.add_subtool(PenEyedropperTool())

    @staticmethod
    def enabled(ctx):
        return bool(getattr(ctx.wm, 'pixel_painter_pen_bar', False))

    # ---- lifecycle -------------------------------------------------------------------

    def on_interrupt(self, ctx):
        if self.bar is not None:
            self.bar.end_drag()

    def on_deactivate(self, ctx):
        if self.bar is not None:
            self.bar.reset()
        self._remap_release = False

    # ---- events ----------------------------------------------------------------------

    def on_event(self, ctx, event):
        if not self.enabled(ctx):
            if self.bar is not None and self.bar.busy():
                self.bar.reset()
            return
        self._ctx = ctx
        try:
            self._handle(ctx, event)
            if self.bar is None or not self.bar.dragging():
                self._layout_store.save_if_changed(ctx.context, ctx.state)
        finally:
            self._ctx = None

    def _handle(self, ctx, event):
        bar = self._layout(ctx)
        mouse = ctx.mouse_region(event)
        if bar is not None and mouse is not None:
            ui_event = UIEvent(type=event.type, value=event.value, x=mouse[0], y=mouse[1],
                               shift=event.shift, ctrl=event.ctrl, alt=event.alt,
                               unicode=getattr(event.raw, 'unicode', '') or '')
            if bar.handle(ui_event):
                event.consume()
                return

        armed = ctx.state.get('pen_armed')
        if armed and event.is_press:
            if event.type == 'LEFTMOUSE':
                ctx.state['pen_armed'] = None
                ctx.state['pen_pick_target'] = 'SECONDARY' if armed == 'EYEDROPPER_SECONDARY' else 'PRIMARY'
                self.eyedropper.activate(ctx, event)
                event.consume()
                return
            if event.type in {'ESC', 'RIGHTMOUSE'}:
                ctx.state['pen_armed'] = None
                event.consume()
                return

        self._remap_rmb(ctx, event)

    def _remap_rmb(self, ctx, event):
        """RMB lock: the pen tip (LMB) acts as the right mouse button for everything after us."""
        if event.type != 'LEFTMOUSE':
            return
        if event.is_press:
            # Not while a sub-mode UI is open (E color selector, Shift+E): the pen operates it;
            # not while picking mask islands (a tap toggles, RMB would end picking).
            self._remap_release = (bool(ctx.state.get('pen_rmb_lock')) and not ctx.state.get('sub_mode')
                                   and not ctx.state.get('mask_picking'))
        if self._remap_release:
            event.type = 'RIGHTMOUSE'
            if event.is_release:
                self._remap_release = False

    # ---- drawing ---------------------------------------------------------------------

    def draw_overlay(self, ctx):
        if not self.enabled(ctx):
            return
        self._ctx = ctx
        try:
            bar = self._layout(ctx)
            if bar is not None:
                bar.draw()
        finally:
            self._ctx = None

    def _layout(self, ctx):
        area, region = ctx.area, ctx.region
        if area is None or region is None:
            return None
        if self.bar is None:
            self.bar = PenBar(self)
        self._layout_store.load_if_needed(ctx.context, ctx.state)
        left, right = _side_insets(area, region)
        side = getattr(ctx.wm, 'pixel_painter_pen_bar_side', 'LEFT')
        self.bar.layout(region.width, region.height, side, left, right, Theme.for_context(ctx.context))
        return self.bar

    # ---- actions used by ui.pen_bar.PenBar -------------------------------------------

    def _c(self):
        return self._ctx if self._ctx is not None else ToolContext(bpy.context, self.manager)

    @staticmethod
    def _button(ctx):
        return 'RMB' if ctx.state.get('pen_rmb_lock') else 'LMB'

    def get_value(self, channel):
        ctx = self._c()
        settings, mode, force_global = ctx.settings, ctx.mode, ctx.force_global
        if channel == 'size':
            return settings.get_tool_size(ctx.context, mode, force_global=force_global)
        getter = getattr(settings, f'get_tool_{channel}')
        return getter(ctx.context, mode, force_global=force_global, button=self._button(ctx))

    def set_value(self, channel, value):
        ctx = self._c()
        settings, mode, force_global = ctx.settings, ctx.mode, ctx.force_global
        if channel == 'size':
            settings.set_tool_size(ctx.context, mode, value, force_global=force_global)
        else:
            setter = getattr(settings, f'set_tool_{channel}')
            setter(ctx.context, mode, value, force_global=force_global, button=self._button(ctx))
        ctx.apply_tool_settings()

    def pen_rgb(self):
        """The color the pen paints (the secondary one with the RMB lock, the tertiary one
        while selected)."""
        if self.tertiary_active():
            return tuple(self.tertiary_color())
        return tuple(self._pen_color(self._c()))

    @staticmethod
    def _target(ctx):
        """The color the color selector edits: 'PRIMARY' / 'SECONDARY' (the RMB lock
        decides; while the tertiary color is selected, the one tapped last)."""
        state = ctx.state
        if tertiary_color.active(state):
            return 'SECONDARY' if state.get(tertiary_color.TARGET_KEY) == 'SECONDARY' else 'PRIMARY'
        return 'SECONDARY' if state.get('pen_rmb_lock') else 'PRIMARY'

    def _pen_color(self, ctx):
        """The color the color selector edits (see :meth:`_target`)."""
        if self._target(ctx) == 'SECONDARY':
            return ctx.settings.get_brush_secondary_rgb(ctx.context)
        return ctx.settings.get_brush_rgb(ctx.context)

    def _applied_hsv(self, ctx):
        """HSV of the color the pen paints. While the color is the one the pad wrote,
        the pad's own HSV is returned (hue / saturation survive grey and black)."""
        rgb = tuple(self._pen_color(ctx))
        hsv = hsv_for_rgb(rgb, ctx.state.get('pen_hsv'))
        ctx.state['pen_hsv'] = (rgb, hsv)
        return hsv

    def _original(self, ctx):
        """HSV from before the pad edits of the color the pen paints now, or None."""
        original = ctx.state.get('pen_color_original')
        if not original:
            return None
        target, hsv = original
        return hsv if target == self._target(ctx) else None  # target switched: other color

    def _pending(self, ctx):
        """Preview: HSV picked on the pad but not yet applied to the pen's color, or None."""
        pending = ctx.state.get('pen_color_pending')
        if not pending or not self._preview_on(ctx):
            return None
        target, hsv = pending
        return hsv if target == self._target(ctx) else None  # target switched: other color

    def pen_hsv(self):
        ctx = self._c()
        pending = self._pending(ctx)
        return pending if pending is not None else self._applied_hsv(ctx)

    def set_pen_hsv(self, h, s, v):
        """The color pad's commit (with Preview on: every step while the pen is down).

        With Preview on the color is only kept pending; the bubble applies it."""
        ctx = self._c()
        if self._preview_on(ctx):
            ctx.state['pen_color_pending'] = (self._target(ctx), (h, s, v))
            return
        if self._original(ctx) is None:
            ctx.state['pen_color_original'] = (self._target(ctx), self._applied_hsv(ctx))
        self._apply_hsv(ctx, h, s, v)

    def original_hsv(self):
        """Marked on the pad (cross + ticks): the applied color while a Preview is
        pending, else the color from before the pad edits until the bubble is tapped."""
        ctx = self._c()
        if self._pending(ctx) is not None:
            return self._applied_hsv(ctx)
        return self._original(ctx)

    def has_color_change(self):
        old, new = self.preview_colors()
        return any(abs(a - b) > 1e-4 for a, b in zip(old, new))

    def preview_colors(self):
        """(old, new) RGB for the preview bubble."""
        ctx = self._c()
        applied = tuple(self._pen_color(ctx))
        pending = self._pending(ctx)
        if pending is not None:
            return applied, colorsys.hsv_to_rgb(*pending)
        original = self._original(ctx)
        return (colorsys.hsv_to_rgb(*original) if original is not None else applied), applied

    def accept_color_change(self):
        """The bubble: applies a pending Preview color; the current color becomes the reference."""
        ctx = self._c()
        pending = self._pending(ctx)
        if pending is not None:
            self._apply_hsv(ctx, *pending)
        ctx.state['pen_color_pending'] = None
        ctx.state['pen_color_original'] = None

    @staticmethod
    def _preview_on(ctx):
        # Toggling the property discards a pending color (its update callback, properties.py).
        return bool(getattr(ctx.wm, 'pixel_painter_pen_color_preview', False))

    def color_preview(self):
        return self._preview_on(self._c())

    def color_layout(self):
        return getattr(self._c().wm, 'pixel_painter_color_selector_layout', 'SHEET')

    def color_model(self):
        return getattr(self._c().wm, 'pixel_painter_color_selector_model', 'HSV')

    def color_sliders(self):
        return set(getattr(self._c().wm, 'pixel_painter_color_selector_sliders', set()))

    def color_sliders_open(self):
        """The color selector's channel sliders are folded out."""
        return bool(getattr(self._c().wm, 'pixel_painter_color_selector_sliders_open', False))

    def _apply_hsv(self, ctx, h, s, v):
        rgb = colorsys.hsv_to_rgb(h, s, v)
        if self._target(ctx) == 'SECONDARY':
            ctx.settings.set_brush_secondary_rgb(ctx.context, *rgb)
        else:
            ctx.settings.set_brush_rgb(ctx.context, *rgb)
            ctx.state['sub_color_h'], ctx.state['sub_color_s'], ctx.state['sub_color_v'] = h, s, v
        # Cache what was actually stored (the color may be clamped / quantized).
        ctx.state['pen_hsv'] = (tuple(self._pen_color(ctx)), (h, s, v))

    def color_panel_open(self):
        return bool(self._c().state.get('pen_color_panel'))

    def toggle_color_panel(self):
        state = self._c().state
        state['pen_color_panel'] = not state.get('pen_color_panel')

    def texel_screen_px(self):
        """Screen pixels per image pixel at the current zoom (None if unknown)."""
        ctx = self._c()
        if ctx.is_3d:
            return ctx.state.get('view3d_texel_px')
        v2d, img = ctx.v2d, ctx.image
        if v2d is None or img is None or img.size[0] == 0:
            return None
        x0, _ = v2d.view_to_region(0.0, 0.0, clip=False)
        x1, _ = v2d.view_to_region(1.0 / img.size[0], 0.0, clip=False)
        return abs(x1 - x0)

    def brush_shape(self):
        return self.registry.get(self._c().mode).outline_shape

    def armed(self):
        return self._c().state.get('pen_armed')

    def toggle_arm(self, kind):
        state = self._c().state
        state['pen_armed'] = None if state.get('pen_armed') == kind else kind

    def colors(self):
        ctx = self._c()
        return ctx.settings.get_brush_rgb(ctx.context), ctx.settings.get_brush_secondary_rgb(ctx.context)

