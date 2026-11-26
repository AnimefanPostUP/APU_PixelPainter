"""Painting tools: Square, Circle, Spray, Line, Eraser."""

from ...paint import pixels as draw_functions
from ...paint import native_paths as native_paint
from ..base import SettingDefaults
from ..mask import guard as mask_guard
from ..stroke import REGION_MARGIN, BrushTool
from ...utils import math_utils, native, pixel_io


def _paint(env, pixels, base_buffer=None, weights=None):
    draw_functions.write_pixels_to_image(
        env.img,
        pixels,
        env.color,
        base_buffer=base_buffer,
        blend=env.blend,
        opacity=env.opacity,
        alpha_opacity=env.alpha_opacity,
        pixel_weights=weights,
        protect_transparent=env.protect_transparent,
    )


class SquareBrushTool(BrushTool):
    tool_id = 'SQUARE'
    label = "Square"
    description = "Square brush shape"
    icon = "Tool_Square.png"
    outline_shape = 'SQUARE'
    line_tip_shape = 'SQUARE'

    def on_draw(self, env):
        if native_paint.usable(env) and native_paint.paint_shape(env, 'SQUARE', env.spacing == 'PIXEL'):
            env.mark_painted()
            return
        if env.spacing == 'PIXEL':
            # Remember painted pixels for the whole stroke so interpolation
            # never double-stamps a coordinate.
            painted = env.state['stroke_painted']
            for (sx, sy) in env.interpolation_steps():
                stamp, _ = env.expand(sx, sy, math_utils.get_pixels_in_shape(sx, sy, env.radius, 'SQUARE'))
                step_pixels = set(stamp) - painted
                if step_pixels:
                    _paint(env, step_pixels)
                    painted |= step_pixels
        else:
            all_pixels = set()
            for (sx, sy) in env.interpolation_steps():
                stamp, _ = env.expand(sx, sy, math_utils.get_pixels_in_shape(sx, sy, env.radius, 'SQUARE'))
                all_pixels.update(stamp)
            if all_pixels:
                _paint(env, all_pixels)
        env.mark_painted()


class WeightedBrushTool(BrushTool):
    """Brush whose footprint has per-pixel weights (falloff).

    Subclasses implement :meth:`sample`. Overlapping samples keep the max
    weight; in 'Pixel' spacing the weight map lives for the whole stroke and is
    re-applied onto the pre-stroke snapshot, so revisiting pixels never
    over-darkens them.
    """

    outline_shape = 'CIRCLE'
    line_tip_shape = 'FALLOFF'

    def sample(self, env, x, y, falloff, curve_sampler):
        """Return ``(pixels, weights)`` for one stamp at ``(x, y)``."""
        raise NotImplementedError

    def rewrites_stroke(self, env):
        # 'Pixel' spacing re-applies the whole stroke's weight map every step.
        return env.spacing == 'PIXEL'

    def native_draw(self, env, falloff, curve_sampler):
        """C# version of :meth:`on_draw` (tools/native_paint.py); False = not handled."""
        return native_paint.paint_weighted(env, falloff, curve_sampler)

    def on_draw(self, env):
        falloff, curve_sampler = env.falloff(self.falloff_property)
        if native_paint.usable(env) and self.native_draw(env, falloff, curve_sampler):
            env.mark_painted()
            return
        pixel_spacing = env.spacing == 'PIXEL'
        weights = env.state['stroke_weight_map'] if pixel_spacing else {}
        for (sx, sy) in env.interpolation_steps():
            px_list, pw_list = env.expand(sx, sy, *self.sample(env, sx, sy, falloff, curve_sampler))
            for px, w in zip(px_list, pw_list):
                if w > weights.get(px, 0.0):
                    weights[px] = w
        if weights:
            _paint(
                env,
                list(weights.keys()),
                base_buffer=env.state['stroke_back_buffer'] if pixel_spacing else None,
                weights=list(weights.values()),
            )
        env.mark_painted()


class CircleBrushTool(WeightedBrushTool):
    tool_id = 'CIRCLE'
    label = "Circle"
    description = "Circle brush shape with falloff"
    icon = "Tool_Circle.png"
    falloff_property = 'pixel_painter_circle_falloff'

    def sample(self, env, x, y, falloff, curve_sampler):
        return math_utils.get_pixels_in_circle_weighted(
            x, y, env.radius, falloff, curve_sampler=curve_sampler)


SPRAY_KNEE = (0.8, 0.08)   # M up to 80 % = density up to 8 % (the spray reacts strongly)


def spray_density(modifier):
    """Spray density (share of the circle per step) for the modifier ``modifier`` (0..1).

    A hard curve: linear up to the knee (M 0..80 % -> 0..8 %), then a quadratic rise
    to the full circle at M = 100 %, starting with the same slope (no kink)."""
    m = min(1.0, max(0.0, float(modifier)))
    km, kd = SPRAY_KNEE
    slope = kd / km
    if m <= km:
        return m * slope
    t = (m - km) / (1.0 - km)
    linear = slope * (1.0 - km)          # the linear part's share of the rest
    return min(1.0, kd + linear * t + (1.0 - kd - linear) * t * t)


class SprayBrushTool(WeightedBrushTool):
    tool_id = 'SPRAY'
    label = "Spray"
    description = "Randomised spray within a circle"
    icon = "Tool_Spray.png"
    outline_color = (1.0, 0.55, 0.0, 0.9)
    defaults = SettingDefaults(size=False, modifier=False, strength=False, alpha=False)
    falloff_property = 'pixel_painter_spray_falloff'
    uses_values = frozenset({'strength', 'alpha', 'modifier'})   # modifier = how many sprinkles

    @staticmethod
    def density(env):
        """Share of the circle sprinkled per step, from the tool modifier (M; pen pressure
        applied): higher M = more sprinkles. See :func:`spray_density`."""
        return spray_density(env.modifier)

    def native_draw(self, env, falloff, curve_sampler):
        return native_paint.paint_weighted(env, falloff, curve_sampler, spray_density=self.density(env))

    def sample(self, env, x, y, falloff, curve_sampler):
        return math_utils.get_spray_pixels(
            x, y, env.radius, self.density(env), falloff, curve_sampler=curve_sampler)


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

    def tip_pixels(self, state, line, radius):
        """Union of the tip shape stamped at every ``line`` pixel (outline)."""
        shape = self.tip_tool(state).outline_shape
        pixels = set()
        for (lx, ly) in line:
            pixels |= math_utils.get_pixels_in_shape(lx, ly, radius, shape)
        return pixels

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
            from ...core import view3d
            ends = self.surface_endpoints(env.state)
            result = view3d.edge_line(env.context, env.img, *ends, env.radius) if ends else None
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
            from ...core import view3d
            w, h = env.img.size
            pixels, weights = view3d.expand_footprint(
                frame, pixels, weights, w, h, (0, 0), drop_uncovered=True)
        if len(pixels):
            _paint(env, pixels, base_buffer=env.state['back_buffer'], weights=weights)

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


class EraserTool(BrushTool):
    """Reduce alpha by the tool strength."""

    tool_id = 'ERASER'
    paints_color = False
    label = "Eraser"
    description = "Erase alpha by strength"
    icon = "Tool_Eraser.png"
    outline_color = (1.0, 0.1, 0.1, 0.9)
    defaults = SettingDefaults(size=True, modifier=False, strength=False, alpha=False)
    uses_values = frozenset({'strength'})     # strength = how much alpha is erased
    line_tip_shape = 'CIRCLE'

    def on_draw(self, env):
        if native_paint.usable(env) and native_paint.erase(env):
            env.mark_painted()
            return
        all_pixels = set()
        for (sx, sy) in env.interpolation_steps():
            stamp, _ = env.expand(sx, sy, math_utils.get_pixels_in_shape(sx, sy, env.radius, 'CIRCLE'))
            all_pixels.update(stamp)
        if not all_pixels:
            return
        w, h = env.img.size
        if native.enabled():
            arr = pixel_io.buffer(env.img)
            if native.erase(arr, w, h, all_pixels, env.opacity) is not None:
                pixel_io.write(env.img, arr)
                env.mark_painted()
                return
        arr = pixel_io.read(env.img)
        for (px, py) in all_pixels:
            if 0 <= px < w and 0 <= py < h:
                idx = (py * w + px) * 4
                arr[idx + 3] = max(0.0, arr[idx + 3] - env.opacity)
        pixel_io.write(env.img, arr)
        env.mark_painted()
