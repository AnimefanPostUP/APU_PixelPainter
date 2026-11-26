"""Falloff actions: the brush's custom falloff curve and the Shape falloff field.
"""

import traceback


from ....utils import blender_utils
from ....model import blend_modes, falloff


class FalloffActions:
    """Part of :class:`.bar.PenBarTool` (a mixin: uses its state)."""

    # ---- custom falloff curve (the brush's falloff CurveMapping) ---------------------------

    def _curve_map(self):
        brush = self._c().context.tool_settings.image_paint.brush
        mapping = getattr(brush, 'curve', None) if brush is not None else None
        if mapping is None or not len(mapping.curves):
            return None, None
        return mapping, mapping.curves[0]

    def custom_curve_points(self):
        try:
            _mapping, curve = self._curve_map()
            return [tuple(p.location) for p in curve.points] if curve is not None else []
        except Exception:
            return []

    def set_custom_curve_points(self, points):
        """Replace the curve's anchors (at least 2, sorted by x): ``(x, y)`` or ``(x, y,
        handle_type)``. An ``(x, y)`` anchor at an existing anchor's spot keeps its handle
        type (e.g. a preset's sharp corners while other anchors are edited); new ones get
        auto handles."""
        points = sorted(tuple(p) for p in points)
        if len(points) < 2:
            return
        try:
            mapping, curve = self._curve_map()
            if curve is None:
                return
            pts = curve.points
            kept = {(round(p.location[0], 4), round(p.location[1], 4)): p.handle_type for p in pts}
            handles = [p[2] if len(p) > 2 else kept.get((round(p[0], 4), round(p[1], 4)), 'AUTO')
                       for p in points]
            while len(pts) > len(points):
                pts.remove(pts[len(pts) - 1])
            while len(pts) < len(points):
                pts.new(0.5, 0.5)
            for point, p, handle in zip(pts, points, handles):
                point.location = (p[0], p[1])
                point.handle_type = handle
            mapping.update()
        except Exception:
            traceback.print_exc()
        self.use_custom_falloff()

    def reset_custom_curve(self):
        self.set_custom_curve_points(falloff.CUSTOM_DEFAULT_POINTS)

    def load_curve_preset(self, preset_id):
        """Load one of ``falloff.CURVE_PRESETS`` into the custom curve (selects Custom)."""
        points = falloff.curve_preset_points(preset_id)
        if points:
            self.set_custom_curve_points(points)

    # ---- Shape falloff (the pen menu's falloff field) ------------------------------------

    def falloff_shape(self):
        """``(hardness, sharpness)`` of the Shape falloff."""
        try:
            return falloff.shape_values(self._c().wm)
        except Exception:
            return falloff.SHAPE_DEFAULT

    def set_cursor_hidden(self, hidden):
        """Hide / show the OS cursor (the falloff field draws its marker instead)."""
        ctx = self._c()
        hidden = bool(hidden)
        if bool(ctx.state.get('cursor_hidden')) == hidden:
            return
        ctx.state['cursor_hidden'] = hidden
        try:
            ctx.context.window.cursor_modal_set('NONE' if hidden else 'CROSSHAIR')
        except Exception:
            pass

    def warp_cursor(self, x, y):
        """Move the OS cursor to region point ``x``/``y``."""
        ctx = self._c()
        region = ctx.region
        if region is None:
            return
        try:
            ctx.context.window.cursor_warp(int(round(x + region.x)), int(round(y + region.y)))
        except Exception:
            pass

    def set_falloff_shape(self, hardness, sharpness):
        """Set the Shape falloff's values and use it for the active tool."""
        _key, hardness, sharpness = falloff.shape_key(hardness, sharpness)
        ctx = self._c()
        if falloff.shape_values(ctx.wm) != (hardness, sharpness):
            setattr(ctx.wm, falloff.SHAPE_HARDNESS_PROPERTY, hardness)
            setattr(ctx.wm, falloff.SHAPE_SHARPNESS_PROPERTY, sharpness)
        if self.active_falloff() != 'SHAPE':
            self.set_falloff('SHAPE')

    def use_custom_falloff(self):
        """Editing the curve selects the Custom falloff (so the edit shows)."""
        if self.active_falloff() != 'CUSTOM':
            self.set_falloff('CUSTOM')

    def custom_curve_sampler(self):
        ctx = self._c()
        try:
            return ctx.settings.get_falloff_curve_sampler(ctx.context)
        except Exception:
            return None

    def _falloff_property(self, ctx):
        return self.registry.get(ctx.mode).falloff_property or falloff.DEFAULT_FALLOFF_PROPERTY

    def active_falloff(self):
        ctx = self._c()
        return getattr(ctx.wm, self._falloff_property(ctx), None)

    def set_falloff(self, preset_id):
        ctx = self._c()
        setattr(ctx.wm, self._falloff_property(ctx), preset_id)

    def blend_favorites(self):
        """Blend ids marked as favorites (settings / the Blend flyout's Edit Favorites);
        may be empty. The defaults only while the property is missing."""
        raw = getattr(self._c().wm, 'pixel_painter_blend_favorites', None)
        if isinstance(raw, (set, list, tuple, frozenset)):
            return set(raw)
        return set(blend_modes.DEFAULT_FAVORITES)

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

    def get_state(self, key):
        """Pen UI layout state (``pen_bar_*`` / ``pen_color_*`` size, position, lock)."""
        return self._c().state.get(key)

    def set_state(self, key, value):
        self._c().state[key] = value
