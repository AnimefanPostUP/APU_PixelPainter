"""Stroke tools: press-drag-release painting plus the standard modifier subtools."""

from ..core import history, view3d
from ..core.framework import Shortcut
from ..utils import blender_utils, math_utils
from .base import DrawEnvironment, ToolBase
from .subtools.color_pick import ColorPickTool
from .subtools.eyedropper import EyedropperTool
from .subtools.strength import StrengthTool
from .subtools.tool_switch import ShiftToolSwitch, TemporaryToolSwitch


class StrokeTool(ToolBase):
    """A tool that paints while LMB (primary color) or RMB (secondary) is held.

    Subclasses implement :meth:`ToolBase.on_draw`; override
    :meth:`on_press` / :meth:`on_release` / :meth:`on_cancel` for tools
    that need special stroke handling (see ``LineBrushTool``).
    """

    def __init__(self):
        super().__init__()
        self._buttons = set()

    @property
    def is_stroking(self):
        return bool(self._buttons)

    # ---- registration ------------------------------------------------------------

    def on_register(self):
        self.register_modifier_subtools()
        self.register_stroke_bindings()

    def register_modifier_subtools(self):
        """Subtools available while this tool is active. Order = priority."""
        self.add_subtool(EyedropperTool())                          # hold Ctrl
        if self.tool_id != 'LINE':
            self.add_subtool(TemporaryToolSwitch('LINE', 'ALT'))    # hold Alt
        self.add_subtool(ShiftToolSwitch(lmb_tool='SMOOTH', rmb_tool='ERASER'))  # hold Shift
        self.add_subtool(ColorPickTool())                           # E
        self.add_subtool(StrengthTool())                            # Shift+E

    def register_stroke_bindings(self):
        self.bind(Shortcut('LEFTMOUSE'), lambda ctx, ev: self.begin_stroke(ctx, ev, 'LMB'))
        self.bind(Shortcut('RIGHTMOUSE'), lambda ctx, ev: self.begin_stroke(ctx, ev, 'RMB'))
        self.bind(Shortcut('MOUSEMOVE', None), self.continue_stroke)
        self.bind(Shortcut('LEFTMOUSE', 'RELEASE'), lambda ctx, ev: self.end_stroke(ctx, 'LMB'))
        self.bind(Shortcut('RIGHTMOUSE', 'RELEASE'), lambda ctx, ev: self.end_stroke(ctx, 'RMB'))

    # ---- lifecycle ---------------------------------------------------------------

    def on_activate(self, ctx, event):
        if self.parent is None and self.host is None and self.usable_as_line_tip:
            ctx.state['last_shape'] = self.tool_id  # selected (not stand-in): Line tip shape

    def on_deactivate(self, ctx):
        self.on_interrupt(ctx)

    def on_interrupt(self, ctx):
        """Cancel the running stroke; whatever was painted stays undoable."""
        if self.is_stroking:
            self.on_cancel(ctx)
        self._buttons.clear()
        self._reset_stroke_state(ctx)
        history.commit_all()

    # ---- stroke ------------------------------------------------------------------

    def begin_stroke(self, ctx, event, button):
        self._buttons.add(button)
        state = ctx.state
        state['use_secondary'] = button == 'RMB'
        state['last_paint_cx'] = None
        state['last_paint_cy'] = None
        state['last_paint_mouse'] = None
        state['outline_immediate'] = True
        img = ctx.image
        if img is not None:
            history.begin(img)
        self.on_press(ctx)
        ctx.redraw()

    def continue_stroke(self, ctx, event):
        if not self.is_stroking:
            return False
        if ctx.can_paint:
            self.paint(ctx)
        ctx.redraw()

    def end_stroke(self, ctx, button):
        if button not in self._buttons:
            return False
        self.on_release(ctx)
        history.commit_all()  # one Blender undo step per stroke
        self._buttons.discard(button)
        self._reset_stroke_state(ctx)
        ctx.redraw()

    def _reset_stroke_state(self, ctx):
        state = ctx.state
        state['last_paint_cx'] = None
        state['last_paint_cy'] = None
        state['last_paint_mouse'] = None
        state['use_secondary'] = 'RMB' in self._buttons
        state['outline_immediate'] = self.is_stroking

    # ---- stroke hooks --------------------------------------------------------------

    def on_press(self, ctx):
        """Button pressed: paint the first stamp."""
        if ctx.can_paint:
            self.paint(ctx)

    def on_release(self, ctx):
        """Button released (before the undo step is committed)."""

    def on_cancel(self, ctx):
        """Stroke aborted (cursor left the image, tool switched, ...)."""

    # ---- painting --------------------------------------------------------------------

    @staticmethod
    def _brush_color(ctx):
        try:
            brush = ctx.context.tool_settings.image_paint.brush
            if not brush:
                return (1.0, 1.0, 1.0)
            return brush.secondary_color if ctx.state['use_secondary'] else brush.color
        except Exception:
            return (1.0, 1.0, 1.0)

    @staticmethod
    def _interpolation_steps(state, cx, cy):
        """Bresenham walk from the last painted pixel to (cx, cy).

        The start pixel is excluded because it was already painted on the
        previous call -- including it would double-stamp every position.
        """
        px = state['last_paint_cx']
        py = state['last_paint_cy']
        if px is None or py is None or (px == cx and py == cy):
            return [(cx, cy)]
        return math_utils.get_line_pixels(px, py, cx, cy)[1:]

    @staticmethod
    def _interpolation_steps_3d(ctx, img, cx, cy):
        """3D Viewport: follow the mouse on screen so strokes never cross UV seams."""
        state = ctx.state
        start = state.get('last_paint_mouse')
        end = state.get('mouse_region')
        if state['last_paint_cx'] is None or start is None or end is None:
            return [(cx, cy)]
        return view3d.pixel_path(ctx.context, start, end, img) or [(cx, cy)]

    def paint(self, ctx):
        """Build the :class:`DrawEnvironment` and run one :meth:`on_draw` step."""
        state = ctx.state
        cx, cy = ctx.cursor
        if cx is None:
            return
        img = ctx.image
        if img is None:
            return
        w, h = img.size
        if w == 0 or h == 0:
            return

        context, settings, wm = ctx.context, ctx.settings, ctx.wm
        mode = self.tool_id
        force_global = ctx.force_global
        button = 'RMB' if state.get('use_secondary') else 'LMB'
        strength = settings.get_tool_strength(context, mode, force_global=force_global, button=button)
        modifier = settings.get_tool_modifier(context, mode, force_global=force_global, button=button)
        alpha_opacity = settings.get_tool_alpha(context, mode, force_global=force_global, button=button)
        radius = settings.get_tool_size(context, mode, force_global=force_global)
        spacing = wm.pixel_painter_spacing
        # Apply the button-specific modifier so tools reading wm.pixel_painter_modifier see it.
        wm.pixel_painter_modifier = modifier
        env = DrawEnvironment(
            context=context,
            state=state,
            img=img,
            mode=mode,
            color=self._brush_color(ctx),
            blend=blender_utils.get_brush_blend_mode(context),
            opacity=strength,
            alpha_opacity=alpha_opacity,
            protect_transparent=getattr(wm, 'pixel_painter_protect_transparent', False),
            radius=radius,
            spacing=spacing,
            wm=wm,
            cursor_x=cx,
            cursor_y=cy,
            interpolation_steps=(
                (lambda: self._interpolation_steps_3d(ctx, img, cx, cy)) if ctx.is_3d
                else (lambda: self._interpolation_steps(state, cx, cy))),
            curve_sampler_factory=settings.get_falloff_curve_sampler,
        )
        if ctx.edge_mode:
            env.edge_mode = True
            tile = state.get('view3d_uv_tile') or (0, 0)
            hit_tri = state.get('view3d_hit_tri')
            env.expand_stamp = lambda x, y, pixels, weights: view3d.edge_expand(
                context, img, x, y, pixels, weights, tile,
                prefer_tri=hit_tri if (x, y) == (cx, cy) else None)

        # First draw call of a stroke: let the tool prepare its caches.
        if state['last_paint_cx'] is None:
            self.on_stroke_begin(env)

        # Pixel spacing: skip if the cursor hasn't moved to a new pixel.
        if (spacing == 'PIXEL'
                and self.respects_pixel_spacing
                and cx == state['last_paint_cx']
                and cy == state['last_paint_cy']):
            return

        self.on_draw(env)


class BrushTool(StrokeTool):
    """Base class for tools that paint pixels with the brush color."""
