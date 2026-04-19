"""Brush and tool-setting access helpers for Pixel Painter."""


class PixelPainterSettingsService:
    """Read/write brush and modal setting values outside core operator logic."""

    @staticmethod
    def _is_shift_smooth_global(context, tool_mode):
        try:
            wm = context.window_manager
            return bool(tool_mode == 'SMOOTH' and getattr(wm, 'pixel_painter_temp_smooth_force_global', False))
        except Exception:
            return False

    def get_brush_strength(self, context):
        """Return active strength respecting unified paint strength."""
        try:
            ups = context.tool_settings.unified_paint_settings
            brush = context.tool_settings.image_paint.brush
            return ups.strength if ups.use_unified_strength else (brush.strength if brush else 1.0)
        except Exception:
            return 1.0

    def set_brush_strength(self, context, value):
        """Set active strength with [0,1] clamping and unified fallback."""
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
            ups = context.tool_settings.unified_paint_settings
            brush = context.tool_settings.image_paint.brush
            if ups.use_unified_color:
                return tuple(ups.color[:3])
            return tuple(brush.color[:3]) if brush else (1.0, 1.0, 1.0)
        except Exception:
            return (1.0, 1.0, 1.0)

    def get_brush_secondary_rgb(self, context):
        """Return brush secondary RGB as a tuple."""
        try:
            ups = context.tool_settings.unified_paint_settings
            brush = context.tool_settings.image_paint.brush
            if ups.use_unified_color:
                return tuple(ups.secondary_color[:3])
            return tuple(brush.secondary_color[:3]) if brush else (0.0, 0.0, 0.0)
        except Exception:
            return (0.0, 0.0, 0.0)

    def get_modifier(self, context):
        """Return the Pixel Painter modifier slider value."""
        try:
            wm = context.window_manager
            return getattr(wm, 'pixel_painter_global_modifier', wm.pixel_painter_modifier)
        except Exception:
            return 0.5

    def set_modifier(self, context, value):
        """Set modifier slider with [0,1] clamping."""
        try:
            v = max(0.0, min(1.0, value))
            wm = context.window_manager
            wm.pixel_painter_modifier = v
            if hasattr(wm, 'pixel_painter_global_modifier'):
                wm.pixel_painter_global_modifier = v
        except Exception:
            pass

    def set_brush_rgb(self, context, r, g, b):
        """Set brush primary RGB color."""
        try:
            ups = context.tool_settings.unified_paint_settings
            brush = context.tool_settings.image_paint.brush
            if ups.use_unified_color:
                ups.color = (r, g, b)
            elif brush:
                brush.color = (r, g, b)
        except Exception:
            pass

    def set_brush_secondary_rgb(self, context, r, g, b):
        """Set brush secondary RGB color."""
        try:
            ups = context.tool_settings.unified_paint_settings
            brush = context.tool_settings.image_paint.brush
            if ups.use_unified_color:
                ups.secondary_color = (r, g, b)
            elif brush:
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

    # ---- Per-tool settings with global/per-tool toggle logic ----

    def get_tool_size(self, context, tool_mode, force_global=False):
        """Get brush size for the tool, respecting global vs per-tool toggle."""
        try:
            wm = context.window_manager
            if force_global or self._is_shift_smooth_global(context, tool_mode):
                return wm.pixel_painter_radius
            use_global = getattr(wm, f'pixel_painter_{tool_mode}_use_global_size', True)
            if use_global:
                return wm.pixel_painter_radius
            return getattr(wm, f'pixel_painter_{tool_mode}_size', 1)
        except Exception:
            return 1

    def set_tool_size(self, context, tool_mode, value, force_global=False):
        """Set brush size for the tool (updates the active per-tool or global value)."""
        value = max(0, min(64, int(value)))
        try:
            wm = context.window_manager
            if force_global or self._is_shift_smooth_global(context, tool_mode):
                wm.pixel_painter_radius = value
                return
            use_global = getattr(wm, f'pixel_painter_{tool_mode}_use_global_size', True)
            if use_global:
                wm.pixel_painter_radius = value
            else:
                setattr(wm, f'pixel_painter_{tool_mode}_size', value)
        except Exception:
            pass

    def get_tool_modifier(self, context, tool_mode, force_global=False, button='LMB'):
        """Get modifier value for the tool, respecting global vs per-tool toggle."""
        suffix = '_rmb' if button == 'RMB' else ''
        try:
            wm = context.window_manager
            global_key = f'pixel_painter_global_modifier{suffix}'
            if not hasattr(wm, global_key):
                base_global = wm.pixel_painter_modifier
            else:
                base_global = getattr(wm, global_key)
            if force_global or self._is_shift_smooth_global(context, tool_mode):
                return base_global
            use_global_key = f'pixel_painter_{tool_mode}_use_global_modifier{suffix}'
            use_global = getattr(wm, use_global_key, True)
            if use_global:
                return base_global
            return getattr(wm, f'pixel_painter_{tool_mode}_modifier{suffix}', 0.5)
        except Exception:
            return 0.5

    def set_tool_modifier(self, context, tool_mode, value, force_global=False, button='LMB'):
        """Set modifier value for the tool (updates the active per-tool or global value)."""
        suffix = '_rmb' if button == 'RMB' else ''
        value = max(0.0, min(1.0, float(value)))
        try:
            wm = context.window_manager
            global_key = f'pixel_painter_global_modifier{suffix}'
            if force_global or self._is_shift_smooth_global(context, tool_mode):
                if hasattr(wm, global_key):
                    setattr(wm, global_key, value)
                if suffix == '':
                    wm.pixel_painter_modifier = value
                return
            use_global_key = f'pixel_painter_{tool_mode}_use_global_modifier{suffix}'
            use_global = getattr(wm, use_global_key, True)
            if use_global:
                if hasattr(wm, global_key):
                    setattr(wm, global_key, value)
                if suffix == '':
                    wm.pixel_painter_modifier = value
            else:
                setattr(wm, f'pixel_painter_{tool_mode}_modifier{suffix}', value)
        except Exception:
            pass

    def get_tool_strength(self, context, tool_mode, force_global=False, button='LMB'):
        """Get strength (brush strength) for the tool, respecting global vs per-tool toggle."""
        suffix = '_rmb' if button == 'RMB' else ''
        try:
            wm = context.window_manager
            base_global = getattr(wm, f'pixel_painter_global_strength{suffix}',
                                   self.get_brush_strength(context))
            if force_global or self._is_shift_smooth_global(context, tool_mode):
                return base_global
            use_global = getattr(wm, f'pixel_painter_{tool_mode}_use_global_strength{suffix}', True)
            if use_global:
                return base_global
            return getattr(wm, f'pixel_painter_{tool_mode}_strength{suffix}', 1.0)
        except Exception:
            return 1.0

    def set_tool_strength(self, context, tool_mode, value, force_global=False, button='LMB'):
        """Set strength (brush strength) for the tool (updates the active per-tool or global value)."""
        suffix = '_rmb' if button == 'RMB' else ''
        value = max(0.0, min(1.0, float(value)))
        try:
            wm = context.window_manager
            global_key = f'pixel_painter_global_strength{suffix}'
            if force_global or self._is_shift_smooth_global(context, tool_mode):
                if hasattr(wm, global_key):
                    setattr(wm, global_key, value)
                if suffix == '':
                    self.set_brush_strength(context, value)
                return
            use_global = getattr(wm, f'pixel_painter_{tool_mode}_use_global_strength{suffix}', True)
            if use_global:
                if hasattr(wm, global_key):
                    setattr(wm, global_key, value)
                if suffix == '':
                    self.set_brush_strength(context, value)
            else:
                setattr(wm, f'pixel_painter_{tool_mode}_strength{suffix}', value)
        except Exception:
            pass

    def get_tool_alpha(self, context, tool_mode, force_global=False, button='LMB'):
        """Get canvas alpha for the tool (global/per-tool aware)."""
        suffix = '_rmb' if button == 'RMB' else ''
        try:
            wm = context.window_manager
            base_global = getattr(wm, f'pixel_painter_global_alpha{suffix}', 1.0)
            if force_global or self._is_shift_smooth_global(context, tool_mode):
                return base_global
            use_global = getattr(wm, f'pixel_painter_{tool_mode}_use_global_alpha{suffix}', True)
            if use_global:
                return base_global
            return getattr(wm, f'pixel_painter_{tool_mode}_alpha{suffix}', 1.0)
        except Exception:
            return 1.0

    def set_tool_alpha(self, context, tool_mode, value, force_global=False, button='LMB'):
        """Set canvas alpha for the tool (global/per-tool aware)."""
        suffix = '_rmb' if button == 'RMB' else ''
        value = max(0.0, min(1.0, float(value)))
        try:
            wm = context.window_manager
            global_key = f'pixel_painter_global_alpha{suffix}'
            if force_global or self._is_shift_smooth_global(context, tool_mode):
                if hasattr(wm, global_key):
                    setattr(wm, global_key, value)
                return
            use_global = getattr(wm, f'pixel_painter_{tool_mode}_use_global_alpha{suffix}', True)
            if use_global:
                if hasattr(wm, global_key):
                    setattr(wm, global_key, value)
            else:
                setattr(wm, f'pixel_painter_{tool_mode}_alpha{suffix}', value)
        except Exception:
            pass

    def apply_tool_runtime_settings(self, context, tool_mode, force_global=False):
        """Load effective tool settings into runtime globals used by drawing paths."""
        try:
            wm = context.window_manager
            wm.pixel_painter_modifier = self.get_tool_modifier(context, tool_mode, force_global=force_global)
            self.set_brush_strength(context, self.get_tool_strength(context, tool_mode, force_global=force_global))
        except Exception:
            pass
