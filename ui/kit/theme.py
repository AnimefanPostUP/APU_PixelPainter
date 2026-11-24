"""Visual theme for UI kit widgets.

A ``Theme`` holds colors, font sizes and animation timings. Widget sizes are
given in *unscaled* pixels and converted with :meth:`Theme.px`, so the whole
UI follows Blender's resolution scale / DPI.
"""

from dataclasses import dataclass, replace


Color = tuple  # (r, g, b, a)


def with_alpha(color, alpha):
    """Return ``color`` with its alpha multiplied by ``alpha``."""
    return (color[0], color[1], color[2], color[3] * alpha)


def mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(4))


@dataclass(frozen=True)
class Theme:
    # ---- colors ------------------------------------------------------------
    accent: Color = (0.66, 0.44, 0.92, 1.0)
    accent_light: Color = (0.90, 0.80, 1.00, 1.0)
    surface: Color = (0.18, 0.18, 0.18, 0.92)
    surface_hover: Color = (0.24, 0.24, 0.24, 0.96)
    surface_pressed: Color = (0.30, 0.30, 0.30, 0.96)
    surface_dark: Color = (0.12, 0.12, 0.12, 0.95)
    panel_background: Color = (0.10, 0.10, 0.10, 0.55)
    border: Color = (0.30, 0.30, 0.30, 0.92)
    text: Color = (1.0, 1.0, 1.0, 1.0)
    text_muted: Color = (1.0, 1.0, 1.0, 0.72)
    edge_darken: float = 0.6    # rim around filled shapes: the fill's own color times this ...
    edge_alpha: float = 0.6     # ... at this opacity (see Theme.edge_for)
    disabled_alpha: float = 0.35

    # ---- typography (unscaled px) ------------------------------------------
    font_id: int = 0
    font_size: float = 12.0
    font_size_small: float = 10.0

    # ---- interaction / motion ----------------------------------------------
    open_duration: float = 0.165
    close_duration: float = 0.1
    hover_duration: float = 0.4 / 6.0
    connector_duration: float = 0.25
    hold_release_delay: float = 0.25   # hold the trigger key this long, release = confirm
    region_margin: float = 8.0         # keep overlays this far from region edges

    # ---- scale -------------------------------------------------------------
    scale: float = 1.0

    def edge_for(self, fill, alpha=1.0):
        """Rim color for a shape filled with ``fill``: a darker, semi-transparent
        shade of the same color (not black), so every edge matches its shape."""
        k = self.edge_darken
        return (fill[0] * k, fill[1] * k, fill[2] * k, self.edge_alpha * alpha)

    def px(self, value):
        """Convert an unscaled pixel value to screen pixels."""
        return value * self.scale

    def scaled(self, scale):
        return replace(self, scale=scale)

    @classmethod
    def for_context(cls, context=None, **overrides):
        """Theme scaled to Blender's effective UI scale (resolution scale x DPI)."""
        scale = 1.0
        try:
            if context is None:
                import bpy
                context = bpy.context
            prefs = context.preferences
            scale = float(getattr(prefs.system, 'ui_scale', 0.0) or prefs.view.ui_scale or 1.0)
        except Exception:
            scale = 1.0
        return cls(scale=scale, **overrides)
