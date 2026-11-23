"""Pen bar tool: on-screen controls for pen / tablet painting (see :mod:`ui.pen_bar`).

A global, ``screen_space`` tool: the core offers it every event before its
cursor-over-image gating, so the bar works anywhere in the editor. Shown
while ``pixel_painter_pen_bar`` is enabled. Besides forwarding events to the
widgets it

* runs the armed eyedropper on the next canvas press,
* edits the pen's color for the color pad (keeping hue / saturation through
  grey and black, where RGB has none) -- applied on release, or with Preview
  on live while the pen is down (the original stays marked until the old /
  new bubble is tapped), and
* with the RMB lock on, turns pen-tip (left button) presses into right
  button presses, so the pen paints with the secondary color / RMB settings.
"""

import colorsys
import traceback

import bpy

from ..core.context import ToolContext
from ..core.framework import ToolFrame
from ..ui.kit import Theme, UIEvent, hsv_for_rgb
from ..ui.pen_bar import PenBar
from ..utils import blender_utils
from . import blend_modes, falloff
from .subtools.pen import PenEyedropperTool



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


class PenBarTool(ToolFrame):
    label = "Pen Bar"
    is_global = True
    screen_space = True
    priority = 200

    state_defaults = {
        'pen_armed':         None,   # 'EYEDROPPER': runs on the next canvas press
        'pen_rmb_lock':      False,  # the pen tip paints like the right mouse button
        'pen_bar_collapsed': False,
        'pen_color_panel':   True,   # color pad shown in the bar (under the color row)
        'pen_color_preview': False,  # pad applies live while the pen is down (else on release)
        'pen_bar_scale':     1.0,    # resize handle: 0.2 .. 2 x the default size
        'pen_hsv':           None,   # (rgb, hsv) last written by the color pad
        'pen_color_original': None,  # (target, hsv) before the pad edits: bubble + cross compare to it
    }
    persistent_state = ('pen_rmb_lock', 'pen_bar_collapsed', 'pen_color_panel', 'pen_color_preview',
                        'pen_bar_scale')

    def __init__(self, registry):
        super().__init__()
        self.registry = registry
        self.bar = None             # built on first use (needs the icon set)
        self._ctx = None            # ToolContext of the event / draw being handled
        self._remap_release = False

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
            if self.bar is not None and (self.bar.flyout is not None or self.bar.overlay.dragging):
                self.bar.reset()
            return
        self._ctx = ctx
        try:
            self._handle(ctx, event)
        finally:
            self._ctx = None

    def _handle(self, ctx, event):
        bar = self._layout(ctx)
        mouse = ctx.mouse_region(event)
        if bar is not None and mouse is not None:
            ui_event = UIEvent(type=event.type, value=event.value, x=mouse[0], y=mouse[1],
                               shift=event.shift, ctrl=event.ctrl, alt=event.alt)
            if bar.handle(ui_event):
                event.consume()
                return

        armed = ctx.state.get('pen_armed')
        if armed and event.is_press:
            if event.type == 'LEFTMOUSE':
                ctx.state['pen_armed'] = None
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
            self._remap_release = bool(ctx.state.get('pen_rmb_lock'))
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

    def _pen_color(self, ctx):
        if ctx.state.get('pen_rmb_lock'):
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
        return hsv if target == self._button(ctx) else None  # RMB lock switched: other color

    def pen_hsv(self):
        return self._applied_hsv(self._c())

    def set_pen_hsv(self, h, s, v):
        """The color pad's commit (with Preview on: every step while the pen is down)."""
        ctx = self._c()
        if self._original(ctx) is None:
            ctx.state['pen_color_original'] = (self._button(ctx), self._applied_hsv(ctx))
        self._apply_hsv(ctx, h, s, v)

    def original_hsv(self):
        """Marked on the pad (cross + ticks) until the bubble is tapped."""
        return self._original(self._c())

    def has_color_change(self):
        ctx = self._c()
        original = self._original(ctx)
        if original is None:
            return False
        return any(abs(a - b) > 1e-4 for a, b in zip(colorsys.hsv_to_rgb(*original), self._pen_color(ctx)))

    def preview_colors(self):
        """(old, new) RGB for the preview bubble."""
        ctx = self._c()
        new = tuple(self._pen_color(ctx))
        original = self._original(ctx)
        return (colorsys.hsv_to_rgb(*original) if original is not None else new), new

    def accept_color_change(self):
        """The bubble: the current color becomes the reference."""
        self._c().state['pen_color_original'] = None

    def color_preview(self):
        return bool(self._c().state.get('pen_color_preview'))

    def toggle_color_preview(self):
        state = self._c().state
        state['pen_color_preview'] = not state.get('pen_color_preview')

    def _apply_hsv(self, ctx, h, s, v):
        rgb = colorsys.hsv_to_rgb(h, s, v)
        if ctx.state.get('pen_rmb_lock'):
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

    def toggle_rmb_lock(self):
        state = self._c().state
        state['pen_rmb_lock'] = not state.get('pen_rmb_lock')
        self._c().apply_tool_settings()

    def tools(self):
        return list(self.registry)

    def active_tool(self):
        return self._c().mode

    def select_tool(self, tool_id):
        ctx = self._c()
        self.manager.select(ctx, tool_id)
        ctx.apply_tool_settings()

    def _falloff_property(self, ctx):
        return self.registry.get(ctx.mode).falloff_property or falloff.DEFAULT_FALLOFF_PROPERTY

    def active_falloff(self):
        ctx = self._c()
        return getattr(ctx.wm, self._falloff_property(ctx), None)

    def set_falloff(self, preset_id):
        ctx = self._c()
        setattr(ctx.wm, self._falloff_property(ctx), preset_id)

    def blend_favorites(self):
        """Blend ids marked as favorites in the settings (the pie's defaults when none)."""
        raw = getattr(self._c().wm, 'pixel_painter_blend_favorites', None)
        selected = set(raw) if isinstance(raw, (set, list, tuple, frozenset)) else set()
        return selected or set(blend_modes.DEFAULT_FAVORITES)

    def active_blend(self):
        return blender_utils.get_brush_blend_mode(self._c().context)

    def set_blend(self, blend):
        try:
            brush = self._c().context.tool_settings.image_paint.brush
            if brush is not None:
                brush.blend = blend
        except Exception:
            traceback.print_exc()

    def collapsed(self):
        return bool(self._c().state.get('pen_bar_collapsed'))

    def set_collapsed(self, collapsed):
        self._c().state['pen_bar_collapsed'] = bool(collapsed)

    def bar_scale(self):
        return self._c().state.get('pen_bar_scale') or 1.0

    def set_bar_scale(self, scale):
        self._c().state['pen_bar_scale'] = float(scale)

    def undo(self):
        self._run_deferred('undo')

    def redo(self):
        self._run_deferred('redo')

    def _run_deferred(self, op_name):
        """Run ``bpy.ops.ed.<op_name>`` on the next tick, outside the modal event handler."""
        ctx = self._c()
        window, area, region = ctx.context.window, ctx.area, ctx.region

        def _run():
            try:
                with bpy.context.temp_override(window=window, area=area, region=region):
                    getattr(bpy.ops.ed, op_name)()
            except Exception:
                traceback.print_exc()
            return None

        bpy.app.timers.register(_run, first_interval=0.0)
