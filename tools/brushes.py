"""Painting tools: Square, Circle, Spray, Line, Eraser."""

import numpy as np

from . import draw_functions
from .base import SettingDefaults
from .stroke import BrushTool
from ..utils import math_utils


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
        if env.spacing == 'PIXEL':
            # Remember painted pixels for the whole stroke so interpolation
            # never double-stamps a coordinate.
            painted = env.state['stroke_painted']
            for (sx, sy) in env.interpolation_steps():
                step_pixels = math_utils.get_pixels_in_shape(sx, sy, env.radius, 'SQUARE') - painted
                if step_pixels:
                    _paint(env, step_pixels)
                    painted |= step_pixels
        else:
            all_pixels = set()
            for (sx, sy) in env.interpolation_steps():
                all_pixels |= math_utils.get_pixels_in_shape(sx, sy, env.radius, 'SQUARE')
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

    def on_draw(self, env):
        falloff, curve_sampler = env.falloff(self.falloff_property)
        pixel_spacing = env.spacing == 'PIXEL'
        weights = env.state['stroke_weight_map'] if pixel_spacing else {}
        for (sx, sy) in env.interpolation_steps():
            px_list, pw_list = self.sample(env, sx, sy, falloff, curve_sampler)
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


class SprayBrushTool(WeightedBrushTool):
    tool_id = 'SPRAY'
    label = "Spray"
    description = "Randomised spray within a circle"
    icon = "Tool_Spray.png"
    outline_color = (1.0, 0.55, 0.0, 0.9)
    defaults = SettingDefaults(size=False, modifier=False, strength=False, alpha=False)
    falloff_property = 'pixel_painter_spray_falloff'

    def sample(self, env, x, y, falloff, curve_sampler):
        return math_utils.get_spray_pixels(
            x, y, env.radius, env.wm.pixel_painter_spray_strength, falloff,
            curve_sampler=curve_sampler)

    def draw_settings(self, context, layout):
        layout.prop(context.window_manager, "pixel_painter_spray_strength", text="Density", slider=True)


class LineBrushTool(BrushTool):
    """Straight line using the last non-line tool as the tip shape."""

    tool_id = 'LINE'
    label = "Line"
    description = "Draw a straight line (hold Alt)"
    icon = "Tool_Line.png"
    defaults = SettingDefaults(size=False, modifier=False, strength=False, alpha=False)
    usable_as_line_tip = False
    respects_pixel_spacing = False

    @staticmethod
    def tip_tool(state):
        from .catalog import TOOLS  # late import: the catalog imports this module
        return TOOLS.get(state.get('last_shape') or 'SQUARE')

    def on_stroke_begin(self, env):
        # Lines re-render from their own back buffer; no stroke caches needed.
        pass

    # ---- stroke hooks: press snapshots, drag previews, release commits ------

    def on_press(self, ctx):
        img = ctx.image
        cx, cy = ctx.cursor
        if img is not None and cx is not None:
            ctx.state['back_buffer'] = np.array(img.pixels, dtype=np.float32)
            ctx.state['start_position'] = (cx, cy)

    def on_release(self, ctx):
        if ctx.state.get('start_position') is not None:
            self.paint(ctx)
        ctx.state['start_position'] = None
        ctx.state['back_buffer'] = None

    def on_cancel(self, ctx):
        img = ctx.image
        back_buffer = ctx.state.get('back_buffer')
        if img is not None and back_buffer is not None:
            img.pixels.foreach_set(back_buffer)
            img.update()
        ctx.state['start_position'] = None
        ctx.state['back_buffer'] = None

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
        x0, y0 = env.state['start_position']
        line = math_utils.get_line_pixels(x0, y0, env.cursor_x, env.cursor_y)
        tip = getattr(self.tip_tool(env.state), 'line_tip_shape', 'CIRCLE')

        if tip == 'FALLOFF':
            falloff, curve_sampler = env.falloff('pixel_painter_circle_falloff')
            weights = {}
            for (lx, ly) in line:
                px_list, pw_list = math_utils.get_pixels_in_circle_weighted(
                    lx, ly, env.radius, falloff, curve_sampler=curve_sampler)
                for px, w in zip(px_list, pw_list):
                    if w > weights.get(px, 0.0):
                        weights[px] = w
            if weights:
                _paint(env, list(weights.keys()), base_buffer=env.state['back_buffer'],
                       weights=list(weights.values()))
            return

        shape = 'SQUARE' if tip == 'SQUARE' else 'CIRCLE'
        all_pixels = set()
        for (lx, ly) in line:
            all_pixels |= math_utils.get_pixels_in_shape(lx, ly, env.radius, shape)
        _paint(env, all_pixels, base_buffer=env.state['back_buffer'])


class EraserTool(BrushTool):
    """Reduce alpha by the tool strength."""

    tool_id = 'ERASER'
    label = "Eraser"
    description = "Erase alpha by strength"
    icon = "Tool_Eraser.png"
    outline_color = (1.0, 0.1, 0.1, 0.9)
    defaults = SettingDefaults(size=True, modifier=False, strength=False, alpha=False)
    line_tip_shape = 'CIRCLE'

    def on_draw(self, env):
        all_pixels = set()
        for (sx, sy) in env.interpolation_steps():
            all_pixels |= math_utils.get_pixels_in_shape(sx, sy, env.radius, 'CIRCLE')
        if not all_pixels:
            return
        w, h = env.img.size
        arr = np.array(env.img.pixels, dtype=np.float32)
        for (px, py) in all_pixels:
            if 0 <= px < w and 0 <= py < h:
                idx = (py * w + px) * 4
                arr[idx + 3] = max(0.0, arr[idx + 3] - env.opacity)
        env.img.pixels.foreach_set(arr)
        env.img.update()
        env.mark_painted()
