"""Shared by the brush tools: paint a footprint with the brush color.
"""

from ...paint.pixels import write_pixels_to_image


def paint_pixels(env, pixels, base_buffer=None, weights=None):
    write_pixels_to_image(
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
