"""Per-event context handed to every tool callback (``ctx`` in tool code)."""

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
    def image(self):
        space = self.space
        return getattr(space, 'image', None) if space else None

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
        from . import core  # late import: core imports the tools
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
        u, v = region.view2d.region_to_view(event.mouse_x - region.x, event.mouse_y - region.y)
        return int(u * w), int(v * h)

    def update_cursor(self, event):
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
