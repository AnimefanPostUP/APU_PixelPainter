"""Brush and tool-setting access helpers for Pixel Painter."""


class PixelPainterSettingsService:
    """Read/write brush and modal setting values outside core operator logic."""

    def get_brush_opacity(self, context):
        """Return active opacity respecting unified paint strength."""
        try:
            ups = context.tool_settings.unified_paint_settings
            brush = context.tool_settings.image_paint.brush
            return ups.strength if ups.use_unified_strength else (brush.strength if brush else 1.0)
        except Exception:
            return 1.0

    def set_brush_opacity(self, context, value):
        """Set active opacity with [0,1] clamping and unified fallback."""
        value = max(0.0, min(1.0, value))
        try:
            ups = context.tool_settings.unified_paint_settings
            brush = context.tool_settings.image_paint.brush
            if ups.use_unified_strength:
                ups.strength = value
            elif brush:
                brush.strength = value
        except Exception:
            pass

    def get_brush_rgb(self, context):
        """Return brush primary RGB as a tuple."""
        try:
            brush = context.tool_settings.image_paint.brush
            return tuple(brush.color[:3]) if brush else (1.0, 1.0, 1.0)
        except Exception:
            return (1.0, 1.0, 1.0)

    def get_brush_secondary_rgb(self, context):
        """Return brush secondary RGB as a tuple."""
        try:
            brush = context.tool_settings.image_paint.brush
            return tuple(brush.secondary_color[:3]) if brush else (0.0, 0.0, 0.0)
        except Exception:
            return (0.0, 0.0, 0.0)

    def get_modifier(self, context):
        """Return the Pixel Painter modifier slider value."""
        try:
            return context.window_manager.pixel_painter_modifier
        except Exception:
            return 0.5

    def set_modifier(self, context, value):
        """Set modifier slider with [0,1] clamping."""
        try:
            context.window_manager.pixel_painter_modifier = max(0.0, min(1.0, value))
        except Exception:
            pass

    def set_brush_rgb(self, context, r, g, b):
        """Set brush primary RGB color."""
        try:
            brush = context.tool_settings.image_paint.brush
            if brush:
                brush.color = (r, g, b)
        except Exception:
            pass

    def set_brush_secondary_rgb(self, context, r, g, b):
        """Set brush secondary RGB color."""
        try:
            brush = context.tool_settings.image_paint.brush
            if brush:
                brush.secondary_color = (r, g, b)
        except Exception:
            pass

    def get_falloff_curve_sampler(self, context):
        """Return callable `t -> weight` sampled from the active brush curve."""
        try:
            brush = context.tool_settings.image_paint.brush
            curve = getattr(brush, 'curve', None) if brush else None
            if curve is None:
                return None

            try:
                curve.initialize()
            except Exception:
                pass

            def _sample(t):
                t = max(0.0, min(1.0, float(t)))
                try:
                    curves = getattr(curve, 'curves', None)
                    if curves and len(curves) > 0:
                        try:
                            return max(0.0, min(1.0, float(curves[0].evaluate(t))))
                        except Exception:
                            pass
                        try:
                            return max(0.0, min(1.0, float(curve.evaluate(curves[0], t))))
                        except Exception:
                            pass
                    try:
                        return max(0.0, min(1.0, float(curve.evaluate(0, t))))
                    except Exception:
                        return max(0.0, min(1.0, float(curve.evaluate(t))))
                except Exception:
                    return 1.0

            return _sample
        except Exception:
            return None

    def get_image_pixel_color(self, context, cx, cy):
        """Read RGB from image pixel coordinates and return `(r,g,b)` or None."""
        try:
            space = context.space_data
            if not space or not space.image:
                return None
            img = space.image
            w, h = img.size
            if not (0 <= cx < w and 0 <= cy < h):
                return None
            idx = (cy * w + cx) * 4
            return (img.pixels[idx], img.pixels[idx + 1], img.pixels[idx + 2])
        except Exception:
            return None
