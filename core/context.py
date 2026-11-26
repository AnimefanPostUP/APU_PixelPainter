"""Per-event context handed to every tool callback (``ctx`` in tool code)."""

from ..utils.blender_utils import get_paint_image
from .view3d import raycast
from .state import SETTINGS, STATE


def is_shift_smooth_global(context):
    """True while Shift temporarily drives SMOOTH with the global settings."""
    try:
        wm = context.window_manager
        return bool(wm.pixel_painter_mode == 'SMOOTH' and getattr(wm, 'pixel_painter_temp_smooth_force_global', False))
    except Exception:
        return False


class ToolContext:
    """Thin wrapper around a ``bpy.types.Context`` plus the shared services."""

    __slots__ = ('context', 'manager', 'state', 'settings')

    def __init__(self, context, manager=None):
        self.context = context
        self.manager = manager
        self.state = STATE
        self.settings = SETTINGS

    # ---- blender accessors -----------------------------------------------------

    @property
    def wm(self):
        return self.context.window_manager

    @property
    def area(self):
        return getattr(self.context, 'area', None)

    @property
    def region(self):
        area = self.area
        if not area:
            return None
        return next((r for r in area.regions if r.type == 'WINDOW'), None)

    @property
    def v2d(self):
        region = self.region
        return region.view2d if region else None

    @property
    def space(self):
        return getattr(self.context, 'space_data', None)

    @property
    def is_3d(self):
        """True when running in the 3D Viewport (Texture Paint mode)."""
        space = self.space
        return space is not None and space.type == 'VIEW_3D'

    @property
    def image(self):
        """The image being painted (Image Editor image or 3D paint canvas)."""
        return get_paint_image(self.context)

    @property
    def edge_mode(self):
        """3D Viewport with brushes continuing over mesh edges (across UV seams)."""
        return self.is_3d and getattr(self.wm, 'pixel_painter_view3d_mode', 'UV') == 'EDGE'

    @property
    def can_paint(self):
        """The editor can map the cursor to image pixels."""
        return self.is_3d or self.v2d is not None

    # ---- tool mode ---------------------------------------------------------------

    @property
    def mode(self):
        return self.wm.pixel_painter_mode

    def set_mode(self, tool_id):
        self.wm.pixel_painter_mode = tool_id

    @property
    def force_global(self):
        return is_shift_smooth_global(self.context)

    def apply_tool_settings(self):
        from . import operator as core  # late import: core imports the tools
        core.apply_active_tool_settings(self.context)

    # ---- cursor ------------------------------------------------------------------

    @property
    def cursor(self):
        return self.state.get('current_cx'), self.state.get('current_cy')

    def hovered_pixel(self, event):
        """Image pixel ``(x, y)`` under ``event``, or ``None``."""
        region = self.region
        image = self.image
        if region is None or image is None:
            return None
        w, h = image.size
        if w == 0 or h == 0:
            return None
        rx, ry = event.mouse_x - region.x, event.mouse_y - region.y
        if self.is_3d:
            hit = raycast.ray_hit(self.context, rx, ry)
            if hit is None:
                return None
            self.state['view3d_uv_tile'] = raycast.hit_tile(hit)
            self.state['view3d_hit_tri'] = hit.tri
            self.state['view3d_hit_local'] = tuple(hit.local)
            texel_px = raycast.texel_screen_size(self.context, hit, image)
            if texel_px is not None:
                self.state['view3d_texel_px'] = texel_px
            return raycast.hit_to_pixel(hit, w, h)
        u, v = region.view2d.region_to_view(rx, ry)
        return int(u * w), int(v * h)

    def mouse_region(self, event):
        """``(x, y)`` of ``event`` relative to the WINDOW region, or None."""
        region = self.region
        if region is None:
            return None
        return event.mouse_x - region.x, event.mouse_y - region.y

    _PEN_EVENTS = frozenset({'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'LEFTMOUSE', 'RIGHTMOUSE', 'MIDDLEMOUSE'})

    def update_pen(self, event):
        """Track the pen pressure (``pen_pressure``; 1.0 for a mouse).

        Releases are skipped: a lifted pen reports 0, and tools that paint on
        release (Line) should see the pressure the stroke ended with.
        """
        if event.type not in self._PEN_EVENTS or event.value == 'RELEASE':
            return
        if event.is_tablet:
            self.state['pen_pressure'] = max(0.0, min(1.0, event.pressure))
            self.state['pen_is_tablet'] = True
        else:
            self.state['pen_pressure'] = 1.0
            self.state['pen_is_tablet'] = False

    def update_cursor(self, event):
        self.state['mouse_region'] = self.mouse_region(event)
        pixel = self.hovered_pixel(event)
        if pixel is None:
            self.state['current_cx'] = self.state['current_cy'] = None
        else:
            self.state['current_cx'], self.state['current_cy'] = pixel
        return pixel

    def image_color(self, x, y):
        if x is None or y is None:
            return None
        return self.settings.get_image_pixel_color(self.context, x, y)

    def redraw(self):
        area = self.area
        if area:
            area.tag_redraw()
