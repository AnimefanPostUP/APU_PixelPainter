"""Line tool: a straight line from the press to the cursor, tipped with the last brush shape.
"""

from ...core.view3d import footprint as v3d_footprint, surface_path
from ...paint import native_paths as native_paint
from ..base import SettingDefaults
from ..mask import guard as mask_guard
from ..stroke import REGION_MARGIN, BrushTool
from ...utils import math_utils, native, pixel_io
from .common import paint_pixels


class LineBrushTool(BrushTool):
    """Straight line using the last non-line tool as the tip shape."""

    tool_id = 'LINE'
    label = "Line"
    description = "Draw a straight line (hold Alt)"
    icon = "Tool_Line.png"
    defaults = SettingDefaults(size=False, modifier=False, strength=False, alpha=False)
    usable_as_line_tip = False
    respects_pixel_spacing = False
    # The line is committed on release, when a lifting pen reports almost no
    # pressure: pressure would make every line thin.
    uses_pen_pressure = False

    state_defaults = {
        **BrushTool.state_defaults,
        'start_position': None,  # (cx, cy) where the line started
        'back_buffer':    None,  # pixel snapshot for clean line preview
        'line_start_hit': None,  # (tri, local) where an Edge-mode line started
    }

    @staticmethod
    def tip_tool(state):
        from ..catalog import TOOLS  # late import: the catalog imports this module
        return TOOLS.get(state.get('last_shape') or 'SQUARE')

    def on_stroke_begin(self, env):
        # Lines re-render from their own back buffer; no stroke caches needed.
        pass

    def step_region(self, ctx, env, steps):
        # The line from its start to the cursor (the back buffer written around it
        # holds the press-time pixels, so protected ones are unchanged there).
        start = env.state.get('start_position')
        if env.edge_mode or env.expand_stamp is not None or start is None:
            return None
        return mask_guard.bounds_of([start, (env.cursor_x, env.cursor_y)],
                                    max(0, int(env.radius)) + REGION_MARGIN)

    # ---- stroke hooks: press snapshots, drag previews, release commits ------

    def on_press(self, ctx):
        img = ctx.image
        cx, cy = ctx.cursor
        if img is not None and cx is not None:
            ctx.state['back_buffer'] = pixel_io.read(img)
            ctx.state['start_position'] = (cx, cy)
            # 3D: the surface point, for the Edge-mode shortest path
            tri, local = ctx.state.get('view3d_hit_tri'), ctx.state.get('view3d_hit_local')
            ctx.state['line_start_hit'] = (tri, local) if ctx.is_3d and tri is not None else None

    def on_release(self, ctx):
        if ctx.state.get('start_position') is not None:
            self.paint(ctx)
        ctx.state['start_position'] = None
        ctx.state['back_buffer'] = None
        ctx.state['line_start_hit'] = None

    def on_cancel(self, ctx):
        img = ctx.image
        back_buffer = ctx.state.get('back_buffer')
        if img is not None and back_buffer is not None:
            pixel_io.write(img, back_buffer.copy())
        ctx.state['start_position'] = None
        ctx.state['back_buffer'] = None
        ctx.state['line_start_hit'] = None

    @staticmethod
    def surface_endpoints(state):
        """``(start, end)`` surface points ``(tri, local)`` of an Edge-mode line, or None."""
        start = state.get('line_start_hit')
        tri, local = state.get('view3d_hit_tri'), state.get('view3d_hit_local')
        if start is None or tri is None or local is None:
            return None
        return start, (tri, local)

    def tip_segments(self, state, line, radius):
        """Contour of the tip shape stamped at every ``line`` pixel (see ``ToolBase.outline_segments``)."""
        shape = self.tip_tool(state).outline_shape
        return math_utils.mask_outline_segments(*math_utils.stamp_mask(line, radius, shape))

    def outline_segments(self, state, x, y, radius):
        start = state.get('start_position')
        if start is None:
            return math_utils.shape_outline_segments(x, y, radius, self.tip_tool(state).outline_shape)
        return self.tip_segments(state, math_utils.get_line_pixels(start[0], start[1], x, y), radius)

    def outline_pixels(self, state, x, y, radius):
        shape = self.tip_tool(state).outline_shape
        start = state.get('start_position')
        if start is None:
            return math_utils.get_pixels_in_shape(x, y, radius, shape)
        pixels = set()
        for (lx, ly) in math_utils.get_line_pixels(start[0], start[1], x, y):
            pixels |= math_utils.get_pixels_in_shape(lx, ly, radius, shape)
        return pixels

    def on_draw(self, env):
        # Re-render from the press-time snapshot so dragging never accumulates
        # intermediate previews.
        if env.state['start_position'] is None or env.state['back_buffer'] is None:
            return
        line = None
        frame = None
        if env.edge_mode:
            # Shortest path over the surface, across UV seams.
            ends = self.surface_endpoints(env.state)
            result = surface_path.edge_line(env.context, env.img, *ends, env.radius) if ends else None
            if result is not None:
                frame, line = result
        if line is None:
            x0, y0 = env.state['start_position']
            line = math_utils.get_line_pixels(x0, y0, env.cursor_x, env.cursor_y)

        footprint = None
        if frame is None and native.enabled():
            tip = getattr(self.tip_tool(env.state), 'line_tip_shape', 'CIRCLE')
            footprint = native_paint.line_footprint(env, line, tip)
        pixels, weights = footprint if footprint is not None else self._line_footprint(env, line)
        if frame is not None:
            # ``line`` is in the start face's unfolded texture space: map to real pixels.
            w, h = env.img.size
            pixels, weights = v3d_footprint.expand_footprint(
                frame, pixels, weights, w, h, (0, 0), drop_uncovered=True)
        if len(pixels):
            paint_pixels(env, pixels, base_buffer=env.state['back_buffer'], weights=weights)

    def _line_footprint(self, env, line):
        """``(pixels, weights|None)`` of the tip stamped along ``line``."""
        tip = getattr(self.tip_tool(env.state), 'line_tip_shape', 'CIRCLE')
        if tip == 'FALLOFF':
            falloff, curve_sampler = env.falloff('pixel_painter_circle_falloff')
            weights = {}
            for (lx, ly) in line:
                px_list, pw_list = env.clip(lx, ly, *math_utils.get_pixels_in_circle_weighted(
                    lx, ly, env.radius, falloff, curve_sampler=curve_sampler))
                for px, w in zip(px_list, pw_list):
                    if w > weights.get(px, 0.0):
                        weights[px] = w
            return list(weights.keys()), list(weights.values())

        shape = 'SQUARE' if tip == 'SQUARE' else 'CIRCLE'
        all_pixels = set()
        for (lx, ly) in line:
            if env.islands is not None:
                all_pixels.update(env.clip(lx, ly, math_utils.get_pixels_in_shape(lx, ly, env.radius, shape))[0])
            else:
                all_pixels |= math_utils.get_pixels_in_shape(lx, ly, env.radius, shape)
        return list(all_pixels), None
