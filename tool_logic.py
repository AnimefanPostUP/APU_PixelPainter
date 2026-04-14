"""Class-based tool implementation for Pixel Painter brushes."""

from dataclasses import dataclass
from typing import Callable, Dict

import numpy as np

from . import draw_functions
from . import math_utils


@dataclass
class DrawEnvironment:
    """Collect all draw-time inputs needed by a tool `on_draw` method."""

    context: object
    state: Dict[str, object]
    img: object
    mode: str
    color: object
    blend: str
    opacity: float
    radius: int
    spacing: str
    wm: object
    cursor_x: int
    cursor_y: int
    interpolation_steps: Callable[[], object]
    curve_sampler_factory: Callable[[object], object]


class ToolBase:
    """Base class for all tools; subclasses implement `on_draw`."""

    tool_id = 'BASE'

    def on_draw(self, env: DrawEnvironment):
        """Draw one tool step into the active image."""
        raise NotImplementedError()


class BrushTool(ToolBase):
    """Base class for brush-like tools that paint pixels."""


class LineBrushTool(BrushTool):
    """Draw straight lines using the previous non-line shape as the tip."""

    tool_id = 'LINE'

    def on_draw(self, env: DrawEnvironment):
        # Render a line preview from the per-stroke back buffer so dragging
        # does not accumulate intermediate previews.
        if env.state['start_position'] is None or env.state['back_buffer'] is None:
            return
        shape = env.state['last_shape']
        tip_shape = 'CIRCLE' if shape == 'SPRAY' else shape
        x0, y0 = env.state['start_position']

        if tip_shape == 'CIRCLE':
            circle_falloff = env.wm.pixel_painter_circle_falloff
            curve_sampler = None
            if circle_falloff == 'CUSTOM':
                curve_sampler = env.curve_sampler_factory(env.context)
            pixel_weight_map = {}
            for (lx, ly) in math_utils.get_line_pixels(x0, y0, env.cursor_x, env.cursor_y):
                px_list, pw_list = math_utils.get_pixels_in_circle_weighted(
                    lx, ly, env.radius, circle_falloff, curve_sampler=curve_sampler)
                for px, w in zip(px_list, pw_list):
                    if w > pixel_weight_map.get(px, 0.0):
                        pixel_weight_map[px] = w
            if pixel_weight_map:
                draw_functions.write_pixels_to_image(
                    env.img,
                    list(pixel_weight_map.keys()),
                    env.color,
                    base_buffer=env.state['back_buffer'],
                    blend=env.blend,
                    opacity=env.opacity,
                    pixel_weights=list(pixel_weight_map.values()),
                )
            return

        all_pixels = set()
        for (lx, ly) in math_utils.get_line_pixels(x0, y0, env.cursor_x, env.cursor_y):
            all_pixels |= math_utils.get_pixels_in_shape(lx, ly, env.radius, tip_shape)
        draw_functions.write_pixels_to_image(
            env.img,
            all_pixels,
            env.color,
            base_buffer=env.state['back_buffer'],
            blend=env.blend,
            opacity=env.opacity,
        )


class SprayBrushTool(BrushTool):
    """Spray random weighted samples inside a radius with optional falloff."""

    tool_id = 'SPRAY'

    def on_draw(self, env: DrawEnvironment):
        # In PIXEL spacing we keep one stroke-wide weight map and redraw from
        # the captured pre-stroke buffer to avoid over-darkening.
        spray_strength = env.wm.pixel_painter_spray_strength
        spray_falloff = env.wm.pixel_painter_spray_falloff
        curve_sampler = None
        if spray_falloff == 'CUSTOM':
            curve_sampler = env.curve_sampler_factory(env.context)

        if env.spacing == 'PIXEL':
            swm = env.state['stroke_weight_map']
            for (sx, sy) in env.interpolation_steps():
                px_list, pw_list = math_utils.get_spray_pixels(
                    sx,
                    sy,
                    env.radius,
                    spray_strength,
                    spray_falloff,
                    curve_sampler=curve_sampler,
                )
                for px, w in zip(px_list, pw_list):
                    if w > swm.get(px, 0.0):
                        swm[px] = w
            if swm:
                draw_functions.write_pixels_to_image(
                    env.img,
                    list(swm.keys()),
                    env.color,
                    base_buffer=env.state['stroke_back_buffer'],
                    blend=env.blend,
                    opacity=env.opacity,
                    pixel_weights=list(swm.values()),
                )
        else:
            pixel_weight_map = {}
            for (sx, sy) in env.interpolation_steps():
                px_list, pw_list = math_utils.get_spray_pixels(
                    sx,
                    sy,
                    env.radius,
                    spray_strength,
                    spray_falloff,
                    curve_sampler=curve_sampler,
                )
                for px, w in zip(px_list, pw_list):
                    if w > pixel_weight_map.get(px, 0.0):
                        pixel_weight_map[px] = w
            if pixel_weight_map:
                draw_functions.write_pixels_to_image(
                    env.img,
                    list(pixel_weight_map.keys()),
                    env.color,
                    blend=env.blend,
                    opacity=env.opacity,
                    pixel_weights=list(pixel_weight_map.values()),
                )
        env.state['last_paint_cx'] = env.cursor_x
        env.state['last_paint_cy'] = env.cursor_y


class CircleBrushTool(BrushTool):
    """Paint weighted circle footprints with optional falloff."""

    tool_id = 'CIRCLE'

    def on_draw(self, env: DrawEnvironment):
        # Same accumulation strategy as spray for deterministic PIXEL spacing.
        circle_falloff = env.wm.pixel_painter_circle_falloff
        curve_sampler = None
        if circle_falloff == 'CUSTOM':
            curve_sampler = env.curve_sampler_factory(env.context)

        if env.spacing == 'PIXEL':
            swm = env.state['stroke_weight_map']
            for (sx, sy) in env.interpolation_steps():
                px_list, pw_list = math_utils.get_pixels_in_circle_weighted(
                    sx,
                    sy,
                    env.radius,
                    circle_falloff,
                    curve_sampler=curve_sampler,
                )
                for px, w in zip(px_list, pw_list):
                    if w > swm.get(px, 0.0):
                        swm[px] = w
            if swm:
                draw_functions.write_pixels_to_image(
                    env.img,
                    list(swm.keys()),
                    env.color,
                    base_buffer=env.state['stroke_back_buffer'],
                    blend=env.blend,
                    opacity=env.opacity,
                    pixel_weights=list(swm.values()),
                )
        else:
            pixel_weight_map = {}
            for (sx, sy) in env.interpolation_steps():
                px_list, pw_list = math_utils.get_pixels_in_circle_weighted(
                    sx,
                    sy,
                    env.radius,
                    circle_falloff,
                    curve_sampler=curve_sampler,
                )
                for px, w in zip(px_list, pw_list):
                    if w > pixel_weight_map.get(px, 0.0):
                        pixel_weight_map[px] = w
            if pixel_weight_map:
                draw_functions.write_pixels_to_image(
                    env.img,
                    list(pixel_weight_map.keys()),
                    env.color,
                    blend=env.blend,
                    opacity=env.opacity,
                    pixel_weights=list(pixel_weight_map.values()),
                )
        env.state['last_paint_cx'] = env.cursor_x
        env.state['last_paint_cy'] = env.cursor_y


class SmoothTool(ToolBase):
    """Smooth neighboring pixels using the modifier as kernel scale."""

    tool_id = 'SMOOTH'

    def on_draw(self, env: DrawEnvironment):
        # Smooth radius grows with modifier for quick coarse/fine control.
        modifier = env.wm.pixel_painter_modifier
        smooth_radius = max(1, int(modifier * max(1, env.radius)))
        all_pixels = set()
        for (sx, sy) in env.interpolation_steps():
            all_pixels |= math_utils.get_pixels_in_shape(sx, sy, env.radius, 'CIRCLE')
        draw_functions.smooth_pixels_in_image(env.img, list(all_pixels), smooth_radius, env.opacity)
        env.state['last_paint_cx'] = env.cursor_x
        env.state['last_paint_cy'] = env.cursor_y


class SmearTool(ToolBase):
    """Smear pixels opposite the cursor motion vector."""

    tool_id = 'SMEAR'

    def on_draw(self, env: DrawEnvironment):
        # Each interpolation step computes motion delta to move source sampling
        # upstream and blend it into the current footprint.
        modifier = env.wm.pixel_painter_modifier
        steps = list(env.interpolation_steps())
        prev_x = env.state['last_paint_cx']
        prev_y = env.state['last_paint_cy']
        for i, (sx, sy) in enumerate(steps):
            ox = (prev_x if prev_x is not None else sx) if i == 0 else steps[i - 1][0]
            oy = (prev_y if prev_y is not None else sy) if i == 0 else steps[i - 1][1]
            ddx = sx - ox
            ddy = sy - oy
            smear_reach = modifier * max(1, env.radius)
            draw_functions.smear_pixels_in_image(
                env.img,
                list(math_utils.get_pixels_in_shape(sx, sy, env.radius, 'CIRCLE')),
                ddx,
                ddy,
                smear_reach,
                env.opacity,
            )
        env.state['last_paint_cx'] = env.cursor_x
        env.state['last_paint_cy'] = env.cursor_y


class SquareBrushTool(BrushTool):
    """Default square brush with PIXEL and FREE spacing behaviors."""

    tool_id = 'SQUARE'

    def on_draw(self, env: DrawEnvironment):
        # PIXEL spacing stores already-painted pixels for the stroke so repeated
        # interpolation calls cannot double-stamp the same coordinate.
        if env.spacing == 'PIXEL':
            painted = env.state['stroke_painted']
            for (sx, sy) in env.interpolation_steps():
                step_pixels = math_utils.get_pixels_in_shape(sx, sy, env.radius, env.mode) - painted
                if step_pixels:
                    draw_functions.write_pixels_to_image(
                        env.img,
                        step_pixels,
                        env.color,
                        blend=env.blend,
                        opacity=env.opacity,
                    )
                    painted |= step_pixels
        else:
            all_pixels = set()
            for (sx, sy) in env.interpolation_steps():
                all_pixels |= math_utils.get_pixels_in_shape(sx, sy, env.radius, env.mode)
            if all_pixels:
                draw_functions.write_pixels_to_image(
                    env.img,
                    all_pixels,
                    env.color,
                    blend=env.blend,
                    opacity=env.opacity,
                )
        env.state['last_paint_cx'] = env.cursor_x
        env.state['last_paint_cy'] = env.cursor_y


class ToolRegistry:
    """Registry that maps tool IDs to class-based draw handlers."""

    def __init__(self):
        self._tools: Dict[str, ToolBase] = {
            'LINE': LineBrushTool(),
            'SPRAY': SprayBrushTool(),
            'CIRCLE': CircleBrushTool(),
            'SMOOTH': SmoothTool(),
            'SMEAR': SmearTool(),
            'SQUARE': SquareBrushTool(),
        }

    def draw_active_tool(self, env: DrawEnvironment):
        """Dispatch draw work to the active tool class."""
        tool = self._tools.get(env.mode, self._tools['SQUARE'])
        tool.on_draw(env)

    def ensure_stroke_state(self, env: DrawEnvironment):
        """Initialize per-stroke state buffers on first draw call of a stroke."""
        if env.state['last_paint_cx'] is None:
            env.state['stroke_painted'] = set()
            env.state['stroke_weight_map'] = {}
            env.state['stroke_back_buffer'] = np.array(env.img.pixels, dtype=np.float32)
