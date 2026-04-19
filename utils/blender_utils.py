"""Blender-specific helper functions (context, regions, brush settings)."""


def get_space_img(context):
    """Return (space, image) for the active Image Editor, or (None, None)."""
    space = context.space_data
    if not space or space.type != 'IMAGE_EDITOR':
        return None, None
    return space, space.image


def get_window_region_and_v2d(area):
    """Return (region, view2d) for the WINDOW region of an Image Editor area."""
    if not area or area.type != 'IMAGE_EDITOR':
        return None, None
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    return region, (region.view2d if region else None)


def mouse_to_view_uv_or_px(context, event):
    """Convert a mouse event position to view (UV) coordinates."""
    area = context.area
    region, v2d = get_window_region_and_v2d(area)
    if not region or not v2d:
        return None, None
    rx = event.mouse_x - region.x
    ry = event.mouse_y - region.y
    return v2d.region_to_view(rx, ry)


def get_brush_image_radius(context):
    """Map brush screen-pixel size [1-512] linearly to image pixel radius [0-64]."""
    try:
        wm = context.window_manager
        if hasattr(wm, 'pixel_painter_active_size'):
            return max(0, min(64, int(wm.pixel_painter_active_size)))

        ups   = context.tool_settings.unified_paint_settings
        brush = context.tool_settings.image_paint.brush
        size  = ups.size if ups.use_unified_size else (brush.size if brush else 1)
    except Exception:
        size = 1
    size = max(1, min(512, size))
    return round((size - 1) * 64 / 64)


def get_raw_brush_image_radius(context):
    """Map raw brush/unified size [1-512] to image radius [0-64], ignoring routed tool size."""
    try:
        ups = context.tool_settings.unified_paint_settings
        brush = context.tool_settings.image_paint.brush
        size = ups.size if ups.use_unified_size else (brush.size if brush else 1)
    except Exception:
        size = 1
    size = max(1, min(512, size))
    return round((size - 1) * 64 / 64)


def get_brush_blend_mode(context):
    """Return the active brush blend mode identifier string (e.g. 'MIX', 'ADD')."""
    try:
        brush = context.tool_settings.image_paint.brush
        return brush.blend if brush else 'MIX'
    except Exception:
        return 'MIX'


def get_brush_secondary_color(context):
    """Return the secondary brush color, respecting unified color setting."""
    try:
        ups   = context.tool_settings.unified_paint_settings
        brush = context.tool_settings.image_paint.brush
        if ups.use_unified_color:
            return ups.secondary_color
        return brush.secondary_color if brush else (0.0, 0.0, 0.0)
    except Exception:
        return (0.0, 0.0, 0.0)


def get_brush_strength(context):
    """Return the active brush strength [0.0-1.0], respecting unified strength."""
    try:
        ups   = context.tool_settings.unified_paint_settings
        brush = context.tool_settings.image_paint.brush
        if ups.use_unified_strength:
            return ups.strength
        return brush.strength if brush else 1.0
    except Exception:
        return 1.0
