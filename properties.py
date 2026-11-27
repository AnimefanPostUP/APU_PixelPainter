"""WindowManager properties for Pixel Painter.

Per-tool properties (``pixel_painter_<TOOL>_<channel>[_rmb]`` and their
``use_global`` toggles) are generated from the tool registry, so a newly
registered tool gets its settings automatically.
"""

import bpy

from .model import blend_modes
from .model import falloff
from .tools.catalog import TOOLS
from .tools.registry import SETTING_CHANNELS
from .utils import persistence_settings
from .utils import settings_service
from .ui.panels import settings_popup as settings_menu
from .ui.kit import color_selector


PREFIX = 'pixel_painter_'

# Defaults of the per-tool value properties.
CHANNEL_VALUE_DEFAULTS = {'size': 1, 'modifier': 0.5, 'strength': 1.0, 'alpha': 1.0}
# Channels that exist per mouse button (size is shared by LMB and RMB).
BUTTON_CHANNELS = ('modifier', 'strength', 'alpha')


# ---------------------------------------------------------------------------
# Update callbacks
# ---------------------------------------------------------------------------

def _persist(self, context):
    persistence_settings.on_property_update(self, context)


def _apply_curve_preset(context, preset_id):
    preset = falloff.get(preset_id)
    if preset is None or preset.curve_preset is None:
        return
    try:
        brush = context.tool_settings.image_paint.brush
        if brush and hasattr(brush, 'curve_preset'):
            brush.curve_preset = preset.curve_preset
    except Exception:
        pass


def _falloff_updater(prop_name):
    def _update(self, context):
        _apply_curve_preset(context, getattr(self, prop_name))
        _persist(self, context)
    return _update


def _update_mode(self, context):
    """Load the effective settings of the newly selected tool."""
    try:
        from .core import operator as core
        core.apply_active_tool_settings(context)
    except Exception:
        pass
    _persist(self, context)


def _update_pen_color_preview(self, context):
    """Switching Preview discards a pad color that was not applied yet."""
    try:
        from .core.state import STATE
        STATE['pen_color_pending'] = None
    except Exception:
        pass
    _persist(self, context)


def _redraw_mask(self, context):
    """Mask / grid settings: redraw the editors (the overlay changes); persist."""
    try:
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type in {'IMAGE_EDITOR', 'VIEW_3D'}:
                    area.tag_redraw()
    except Exception:
        pass
    _persist(self, context)


# ---------------------------------------------------------------------------
# "Active" proxies: read/write whichever value (global or per-tool) is in effect
# ---------------------------------------------------------------------------

def _active_proxy(channel, cast, fallback):
    svc = settings_service.PixelPainterSettingsService()
    getter_fn = getattr(svc, f'get_tool_{channel}')
    setter_fn = getattr(svc, f'set_tool_{channel}')

    def _force_global(wm):
        return bool(wm.pixel_painter_mode == 'SMOOTH' and getattr(wm, 'pixel_painter_temp_smooth_force_global', False))

    def _get(self):
        try:
            return cast(getter_fn(bpy.context, self.pixel_painter_mode, force_global=_force_global(self)))
        except Exception:
            return fallback(self)

    def _set(self, value):
        try:
            setter_fn(bpy.context, self.pixel_painter_mode, value, force_global=_force_global(self))
            from .core import operator as core
            core.apply_active_tool_settings(bpy.context)
        except Exception:
            pass

    return _get, _set


def _selection_state_flag(key):
    def _get(self):
        try:
            from .core import operator as core
            return bool(core._state.get(key))
        except Exception:
            return False
    return _get


# ---------------------------------------------------------------------------
# Definitions
# ---------------------------------------------------------------------------

def _factor(name, default, **kwargs):
    return bpy.props.FloatProperty(name=name, min=0.0, max=1.0, default=default, subtype='FACTOR', **kwargs)


def _static_properties():
    size_get, size_set = _active_proxy('size', int, lambda wm: int(getattr(wm, 'pixel_painter_radius', 1)))
    strength_get, strength_set = _active_proxy('strength', float, lambda wm: 1.0)
    modifier_get, modifier_set = _active_proxy('modifier', float, lambda wm: 0.5)
    alpha_get, alpha_set = _active_proxy('alpha', float, lambda wm: 1.0)

    return {
        'radius': bpy.props.IntProperty(
            name="Radius", description="Brush radius in pixels", min=0, max=64, default=1, update=_persist),
        'mode': bpy.props.EnumProperty(
            name="Mode", items=TOOLS.enum_items(), default=TOOLS.default_id, update=_update_mode),
        'circle_falloff': bpy.props.EnumProperty(
            name="Circle Falloff", items=falloff.enum_items(), default='CONSTANT',
            update=_falloff_updater('pixel_painter_circle_falloff')),
        'smooth_falloff': bpy.props.EnumProperty(
            name="Smooth Falloff", items=falloff.enum_items(), default='CONSTANT',
            update=_falloff_updater('pixel_painter_smooth_falloff')),
        'smear_falloff': bpy.props.EnumProperty(
            name="Smear Falloff", items=falloff.enum_items(), default='CONSTANT',
            update=_falloff_updater('pixel_painter_smear_falloff')),
        'spray_falloff': bpy.props.EnumProperty(
            name="Spray Falloff", items=falloff.enum_items(), default='LINEAR',
            update=_falloff_updater('pixel_painter_spray_falloff')),
        'falloff_hardness': _factor(
            "Falloff Hardness", falloff.SHAPE_DEFAULT[0],
            description="Shape falloff: full strength out to this part of the radius (1 = hard edge)",
            update=_persist),
        'falloff_sharpness': _factor(
            "Falloff Sharpness", falloff.SHAPE_DEFAULT[1],
            description="Shape falloff: how sharply the fade drops (0 = linear, 1 = sharp)",
            update=_persist),
        'spray_strength': bpy.props.FloatProperty(
            name="Spray Density",
            description="Fraction of the circle area painted per frame (0 = sparse, 1 = full fill)",
            min=0.01, max=1.0, default=0.1, subtype='FACTOR', update=_persist),
        'spacing': bpy.props.EnumProperty(
            name="Spacing",
            description="When to paint: continuously (Free) or once per unique pixel position (Pixel)",
            items=[
                ('FREE', "Free", "Paint continuously as the mouse moves, with stroke interpolation"),
                ('PIXEL', "Pixel", "Paint only when the cursor moves to a new pixel — no repeated stamps"),
            ],
            default='FREE', update=_persist),
        'modifier': _factor("Modifier", 0.5, description="Generic modifier value (currently used as Spread)",
                            update=_persist),
        'global_modifier': _factor("Global Modifier", 0.5, options={'HIDDEN'}, update=_persist),
        'global_strength': _factor("Global Strength", 1.0, options={'HIDDEN'}, update=_persist),
        'global_alpha': _factor("Global Alpha", 1.0, options={'HIDDEN'}, update=_persist),
        'global_strength_rmb': _factor("Global Strength RMB", 1.0, options={'HIDDEN'}, update=_persist),
        'global_modifier_rmb': _factor("Global Modifier RMB", 0.5, options={'HIDDEN'}, update=_persist),
        'global_alpha_rmb': _factor("Global Alpha RMB", 1.0, options={'HIDDEN'}, update=_persist),
        'temp_smooth_force_global': bpy.props.BoolProperty(
            name="Temp Smooth Force Global", default=False, options={'HIDDEN'}),
        'active_size': bpy.props.IntProperty(
            name="Size", description="Active size setter routing to global or local value for current tool",
            min=0, max=64, get=size_get, set=size_set),
        'active_strength': _factor(
            "Strength", 1.0, description="Active strength setter routing to global or local value for current tool",
            get=strength_get, set=strength_set),
        'active_modifier': _factor(
            "Modifier", 0.5, description="Active modifier setter routing to global or local value for current tool",
            get=modifier_get, set=modifier_set),
        'active_alpha': _factor(
            "Alpha", 1.0, description="Active alpha setter routing to global or local value for current tool",
            get=alpha_get, set=alpha_set),
        'view3d_mode': bpy.props.EnumProperty(
            name="3D Mode", description="How brushes map onto the mesh in the 3D Viewport",
            items=[
                ('UV', "UV", "Brushes stay inside the UV island (stop at UV seams)"),
                ('EDGE', "Edge", "Brushes continue over mesh edges onto the connected face, even across UV seams"),
            ],
            default='UV', update=_persist),
        'use_native': bpy.props.BoolProperty(
            name="Use C# Backend",
            description="Run pixel-heavy work (painting, smooth / smear, masks, selections) in the compiled "
                        "C# library (native/). Off, or when the library is missing: the Python / NumPy "
                        "implementation",
            default=True, update=_persist),
        'protect_transparent': bpy.props.BoolProperty(
            name="Protect Transparent", description="Prevent painting on fully transparent pixels (alpha = 0)",
            default=False, update=_persist),
        'selection_has_pending': bpy.props.BoolProperty(
            name="Selection Has Pending Preview", options={'HIDDEN'},
            get=_selection_state_flag('selection_pending_action')),
        'selection_stencil_mode': bpy.props.BoolProperty(
            name="Selection Stencil Mode", options={'HIDDEN'},
            get=_selection_state_flag('selection_stencil_mode')),
        'blend_favorites': bpy.props.EnumProperty(
            name="Blend Favorites", description="Select blend modes shown in the Favorites block",
            items=blend_modes.enum_items(), options={'ENUM_FLAG'}, default=set(blend_modes.DEFAULT_FAVORITES),
            update=_persist),
        'settings_tab': bpy.props.EnumProperty(
            name="Settings Category", description="Category shown in the settings popup",
            items=settings_menu.tab_enum_items(), default=settings_menu.SETTINGS_TABS[0][0], update=_persist),
        'grid_opacity': _factor(
            "Grid Opacity", 0.0, description="Opacity of the pixel grid overlay (0 = hidden, 1 = fully opaque)",
            update=_redraw_mask),
        'grid_show': bpy.props.BoolProperty(
            name="Show Grid", description="Show the pixel grid overlay (at Grid Opacity)", default=True,
            update=_redraw_mask),
        # ---- pen / tablet ----
        'pen_pressure_size': bpy.props.BoolProperty(
            name="Pressure Size", description="Pen pressure scales the brush size", default=False,
            update=_persist),
        'pen_pressure_strength': bpy.props.BoolProperty(
            name="Pressure Strength", description="Pen pressure scales the strength", default=False,
            update=_persist),
        'pen_pressure_alpha': bpy.props.BoolProperty(
            name="Pressure Alpha", description="Pen pressure scales the alpha (opacity) written to the canvas",
            default=False, update=_persist),
        'pen_pressure_modifier': bpy.props.BoolProperty(
            name="Pressure Modifier", description="Pen pressure scales the modifier (smooth / smear spread)",
            default=False, update=_persist),
        'pen_pressure_min': _factor(
            "Minimum Pressure", 0.0,
            description="Multiplier at the lightest touch (0 = pressure is the multiplier, "
                        "higher = light strokes stay stronger)",
            update=_persist),
        'pen_bar': bpy.props.BoolProperty(
            name="Pen Bar",
            description="On-canvas controls for pens: drag knobs, tap buttons, press-drag-release menus",
            default=False, update=_persist),
        'pen_bar_side': bpy.props.EnumProperty(
            name="Pen Bar Side", description="Bottom corner of the editor the pen bar sits in",
            items=[('LEFT', "Left", "Left edge of the editor"), ('RIGHT', "Right", "Right edge of the editor")],
            default='LEFT', update=_persist),
        'pen_color_preview': bpy.props.BoolProperty(
            name="Color Pad Preview",
            description="Pen bar color pad only previews: the brush keeps its color until the "
                        "old / new bubble is tapped (off: the pad color applies when the pen is lifted)",
            default=False, update=_update_pen_color_preview),
        'pen_color_drag': bpy.props.BoolProperty(
            name="Drag Colors",
            description="Pen menu: drag colors (primary / secondary, history, palette, the old / new bubble) "
                        "onto palette slots or the primary / secondary color",
            default=True, update=_persist),
        # ---- saving the painted image (pen menu Save button, ui/operators/image_save.py) ----
        'save_image_method': bpy.props.EnumProperty(
            name="Save Method", description="How the pen menu's Save button stores the painted image",
            items=[
                ('AUTO', "Auto", "Repack a packed image, save an image with a file to it, pack anything else"),
                ('PACK', "Pack", "Always pack the image into the .blend file"),
                ('FILE', "File", "Always write the image to a file (images without one go to the folder below)"),
            ],
            default='AUTO', update=_persist),
        'save_image_folder': bpy.props.StringProperty(
            name="Save Folder",
            description="Folder for images that have no file yet (File method); // = next to the .blend",
            default="//textures/", subtype='DIR_PATH', update=_persist),
        'save_image_blend': bpy.props.BoolProperty(
            name="Also Save .blend",
            description="Save the .blend file after the image (packed pixels only reach the disk with the .blend)",
            default=False, update=_persist),
        # ---- paint mask (tools/mask/) ----
        'mask_enabled': bpy.props.BoolProperty(
            name="Mask", description="Only paint on the chosen UV islands / mesh parts",
            default=False, update=_redraw_mask),
        'mask_source': bpy.props.EnumProperty(
            name="Mask Source", description="What the mask chooses",
            items=[
                ('UV_ISLAND', "UV Islands", "Choose UV islands (faces connected in the UV map)"),
                ('MESH_PART', "Mesh Parts", "Choose connected mesh parts (loose parts are separate)"),
                ('SHARP', "Sharp Areas", "Choose areas between sharp edges (faces meeting at more than "
                                         "the Sharp Angle)"),
            ],
            default='UV_ISLAND', update=_redraw_mask),
        'sharp_angle': bpy.props.FloatProperty(
            name="Sharp Angle", description="Sharp Areas (mask and Extras): faces meeting at more than this "
                                            "angle are split into separate areas (degrees)",
            min=1.0, max=180.0, soft_min=5.0, soft_max=90.0, default=30.0, update=_redraw_mask),
        'mask_invert': bpy.props.BoolProperty(
            name="Invert Mask", description="Protect the chosen islands / parts instead of painting only on them",
            default=False, update=_redraw_mask),
        'mask_grow': bpy.props.IntProperty(
            name="Mask Grow", description="Pixels added around every island / part (covers partly covered edge pixels)",
            min=0, max=8, default=0, update=_redraw_mask),
        'mask_show': bpy.props.BoolProperty(
            name="Show Mask", description="Show red stripes over the protected area", default=True, update=_redraw_mask),
        # ---- Extras window (tools/extras/) ----
        'extras_source': bpy.props.EnumProperty(
            name="Extras Source", description="What the Extras tools act on",
            items=[
                ('UV_ISLAND', "UV Islands", "One UV island (faces connected in the UV map)"),
                ('MESH_PART', "Mesh Parts", "All faces connected in the mesh (loose parts are separate)"),
                ('SHARP', "Sharp Areas", "Faces between sharp edges (meeting at more than the Sharp Angle)"),
            ],
            default='UV_ISLAND', update=_redraw_mask),
        'extras_fill_fade': bpy.props.BoolProperty(
            name="Fade Fill", description="Fill also runs past the island / part into its neighbours, fading out",
            default=False, update=_persist),
        'extras_fill_width': bpy.props.IntProperty(
            name="Fill Fade Width", description="How far Fill fades out past the island / part, in texels",
            min=1, max=64, soft_max=32, default=4, update=_persist),
        'extras_fill_curve': bpy.props.StringProperty(
            name="Fill Fade Curve", description="Fill fade-out curve anchors (JSON, model/value_curve.py)",
            default="", options={'HIDDEN'}, update=_persist),
        'extras_edge_width': bpy.props.IntProperty(
            name="Edge Width", description="Width of the Edges band in texels (per side)",
            min=1, max=32, soft_max=16, default=3, update=_persist),
        'extras_edge_source': bpy.props.EnumProperty(
            name="Edges", description="Which model edges the Edges tool paints along",
            items=[
                ('ANGLE', "Angle", "Edges whose faces meet at more than the angle"),
                ('ALL', "All", "Every model edge (open borders included)"),
                ('MARKED', "Marked", "Edges marked sharp"),
            ],
            default='ANGLE', update=_persist),
        'extras_edge_center': bpy.props.EnumProperty(
            name="Edge Placement", description="How the band sits on the edge",
            items=[
                ('BETWEEN', "Symmetric", "The band hugs the edge: the same number of texels on both sides"),
                ('ON', "Pixel Line", "A one-texel line on the edge (snapped to texel centers), "
                                     "the band spreads evenly from it"),
            ],
            default='BETWEEN', update=_persist),
        'extras_edge_angle': bpy.props.FloatProperty(
            name="Sharp Angle", description="Faces meeting at more than this angle make a sharp edge (degrees)",
            min=1.0, max=180.0, soft_min=5.0, soft_max=90.0, default=30.0, update=_persist),
        'extras_edge_curve': bpy.props.StringProperty(
            name="Edges Falloff", description="Edges falloff curve anchors (JSON, model/value_curve.py)",
            default="", options={'HIDDEN'}, update=_persist),
        'extras_edge_fade': bpy.props.BoolProperty(
            name="Fade Edges", description="The Edges band fades out toward its inner side",
            default=True, update=_persist),
        'extras_ao_samples': bpy.props.IntProperty(
            name="AO Samples", description="Rays per texel (more: smoother, slower)",
            min=4, max=512, soft_min=8, soft_max=128, default=32, update=_persist),
        'extras_ao_distance': bpy.props.FloatProperty(
            name="AO Distance", description="How far occluders count, as a share of the mesh's size",
            min=0.01, max=2.0, soft_min=0.02, soft_max=1.0, default=0.25, update=_persist),
        'extras_ao_fade': bpy.props.BoolProperty(
            name="Fade AO", description="Open areas keep their pixels (opacity follows the AO curve)",
            default=True, update=_persist),
        'extras_ao_curve': bpy.props.StringProperty(
            name="AO Curve", description="Ambient occlusion curve anchors (JSON, model/value_curve.py)",
            default="", options={'HIDDEN'}, update=_persist),
        # ---- color selector (pen bar color pad) ----
        'color_selector_layout': bpy.props.EnumProperty(
            name="Color Selector Layout", description="Shape of the pen bar color selector",
            items=[(i, label, desc) for i, label, desc in color_selector.LAYOUTS],
            default='SHEET', update=_persist),
        'color_selector_model': bpy.props.EnumProperty(
            name="Color Selector Model", description="Color model the color selector works in",
            items=[(i, label, desc) for i, label, desc in color_selector.SELECTOR_MODELS],
            default='HSV', update=_persist),
        'color_selector_sliders': bpy.props.EnumProperty(
            name="Color Selector Sliders", description="Channel sliders shown under the color selector",
            items=[(i, label, desc) for i, label, desc in color_selector.SLIDER_SPACES],
            options={'ENUM_FLAG'}, default=set(), update=_persist),
        'color_selector_sliders_open': bpy.props.BoolProperty(
            name="Show Color Sliders",
            description="Fold out the channel sliders, their input fields and the hex code under the pen color selector",
            default=False, update=_persist),
    }


def tool_property_names(tool_id):
    """All per-tool property names of ``tool_id`` (``pixel_painter_`` prefixed)."""
    names = []
    for channel in SETTING_CHANNELS:
        suffixes = ('', '_rmb') if channel in BUTTON_CHANNELS else ('',)
        for suffix in suffixes:
            names.append(f'{PREFIX}{tool_id}_{channel}{suffix}')
            names.append(f'{PREFIX}{tool_id}_use_global_{channel}{suffix}')
    return names


def tool_property_defaults(tool_id):
    """``{property_name: default}`` for every per-tool property of ``tool_id``."""
    defaults = {}
    for channel in SETTING_CHANNELS:
        suffixes = ('', '_rmb') if channel in BUTTON_CHANNELS else ('',)
        use_global = TOOLS.uses_global_default(tool_id, channel)
        for suffix in suffixes:
            defaults[f'{PREFIX}{tool_id}_{channel}{suffix}'] = CHANNEL_VALUE_DEFAULTS[channel]
            defaults[f'{PREFIX}{tool_id}_use_global_{channel}{suffix}'] = use_global
    return defaults


def _tool_properties(tool):
    props = {}
    for name, default in tool_property_defaults(tool.tool_id).items():
        short = name[len(PREFIX):]
        nice = short.replace('_', ' ').title().replace('Rmb', 'RMB')
        if '_use_global_' in name:
            props[short] = bpy.props.BoolProperty(name=nice, default=default, update=_persist)
        elif name.endswith('_size'):
            props[short] = bpy.props.IntProperty(name=nice, min=0, max=64, default=default, update=_persist)
        else:
            props[short] = _factor(nice, default, update=_persist)
    return props


def all_properties():
    props = _static_properties()
    for tool in TOOLS:
        props.update(_tool_properties(tool))
    return props


# Names of properties that hold settings (not runtime proxies/flags) - persisted to disk.
NON_PERSISTED = {
    'temp_smooth_force_global', 'active_size', 'active_strength', 'active_modifier',
    'active_alpha', 'selection_has_pending', 'selection_stencil_mode',
    'mask_enabled',   # starts off: a forgotten mask must not block painting after a restart
}


def persisted_property_names():
    return [PREFIX + name for name in all_properties() if name not in NON_PERSISTED]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_registered = []


# Saved in the .blend file (per project), not in settings.json.
SCENE_PROPERTIES = {
    'palettes': lambda: bpy.props.StringProperty(
        name="Pixel Painter Palettes", description="The project's color palettes (JSON, see tools/color_palette.py)",
        default="", options={'HIDDEN'}),
    'mask_selection': lambda: bpy.props.StringProperty(
        name="Pixel Painter Mask", description="Chosen mask islands / parts (JSON, see tools/mask.py)",
        default="", options={'HIDDEN'}),
    'pen_layout': lambda: bpy.props.StringProperty(
        name="Pixel Painter Pen Layout",
        description="Pen menu windows: open, position, scale, lock (JSON, see tools/pen_layout.py)",
        default="", options={'HIDDEN'}),
}


def register():
    unregister()
    for name, prop in all_properties().items():
        setattr(bpy.types.WindowManager, PREFIX + name, prop)
        _registered.append(PREFIX + name)
    for name, make in SCENE_PROPERTIES.items():
        setattr(bpy.types.Scene, PREFIX + name, make())


def unregister():
    names = list(_registered) or [PREFIX + n for n in all_properties()]
    for full in names:
        if hasattr(bpy.types.WindowManager, full):
            try:
                delattr(bpy.types.WindowManager, full)
            except Exception:
                pass
    _registered.clear()
    for name in SCENE_PROPERTIES:
        if hasattr(bpy.types.Scene, PREFIX + name):
            try:
                delattr(bpy.types.Scene, PREFIX + name)
            except Exception:
                pass


def reset_tool_settings(wm):
    """Reset every tool setting to its registry default (used by the reset operator)."""
    wm.pixel_painter_radius = 1
    wm.pixel_painter_mode = TOOLS.default_id
    wm.pixel_painter_circle_falloff = 'CONSTANT'
    wm.pixel_painter_spray_falloff = 'LINEAR'
    wm.pixel_painter_smooth_falloff = 'CONSTANT'
    wm.pixel_painter_smear_falloff = 'CONSTANT'
    wm.pixel_painter_falloff_hardness, wm.pixel_painter_falloff_sharpness = falloff.SHAPE_DEFAULT
    wm.pixel_painter_spray_strength = 0.1
    wm.pixel_painter_spacing = 'FREE'
    wm.pixel_painter_modifier = 0.5
    wm.pixel_painter_global_modifier = 0.5
    wm.pixel_painter_global_strength = 1.0
    wm.pixel_painter_global_alpha = 1.0
    wm.pixel_painter_global_strength_rmb = 1.0
    wm.pixel_painter_global_modifier_rmb = 0.5
    wm.pixel_painter_global_alpha_rmb = 1.0
    wm.pixel_painter_temp_smooth_force_global = False
    wm.pixel_painter_protect_transparent = False
    wm.pixel_painter_view3d_mode = 'UV'
    wm.pixel_painter_grid_opacity = 0.0
    wm.pixel_painter_grid_show = True
    for channel in ('size', 'strength', 'alpha', 'modifier'):
        setattr(wm, f'pixel_painter_pen_pressure_{channel}', False)
    wm.pixel_painter_pen_pressure_min = 0.0
    for tool in TOOLS:
        for name, default in tool_property_defaults(tool.tool_id).items():
            setattr(wm, name, default)
