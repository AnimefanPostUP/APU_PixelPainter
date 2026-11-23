"""WindowManager properties for Pixel Painter.

Per-tool properties (``pixel_painter_<TOOL>_<channel>[_rmb]`` and their
``use_global`` toggles) are generated from the tool registry, so a newly
registered tool gets its settings automatically.
"""

import bpy

from .tools import blend_modes
from .tools import falloff
from .tools.catalog import TOOLS
from .tools.registry import SETTING_CHANNELS
from .utils import persistence_settings
from .utils import settings_service


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
        from .core import core
        core.apply_active_tool_settings(context)
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
            from .core import core
            core.apply_active_tool_settings(bpy.context)
        except Exception:
            pass

    return _get, _set


def _selection_state_flag(key):
    def _get(self):
        try:
            from .core import core
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
        'spray_falloff': bpy.props.EnumProperty(
            name="Spray Falloff", items=falloff.enum_items(), default='LINEAR',
            update=_falloff_updater('pixel_painter_spray_falloff')),
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
        'ui_show_settings': bpy.props.BoolProperty(name="Show Settings", default=True, update=_persist),
        'ui_show_blend_mode': bpy.props.BoolProperty(name="Show Blend Mode", default=False, update=_persist),
        'ui_show_shortcuts': bpy.props.BoolProperty(name="Show Shortcuts", default=True, update=_persist),
        'ui_show_tool_settings': bpy.props.BoolProperty(name="Show Tool Settings", default=False, update=_persist),
        'grid_opacity': _factor(
            "Grid Opacity", 0.0, description="Opacity of the pixel grid overlay (0 = hidden, 1 = fully opaque)",
            update=_persist),
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
}


def persisted_property_names():
    return [PREFIX + name for name in all_properties() if name not in NON_PERSISTED]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_registered = []


def register():
    unregister()
    for name, prop in all_properties().items():
        setattr(bpy.types.WindowManager, PREFIX + name, prop)
        _registered.append(PREFIX + name)


def unregister():
    names = list(_registered) or [PREFIX + n for n in all_properties()]
    for full in names:
        if hasattr(bpy.types.WindowManager, full):
            try:
                delattr(bpy.types.WindowManager, full)
            except Exception:
                pass
    _registered.clear()


def reset_tool_settings(wm):
    """Reset every tool setting to its registry default (used by the reset operator)."""
    wm.pixel_painter_radius = 1
    wm.pixel_painter_mode = TOOLS.default_id
    wm.pixel_painter_circle_falloff = 'CONSTANT'
    wm.pixel_painter_spray_falloff = 'LINEAR'
    wm.pixel_painter_smooth_falloff = 'CONSTANT'
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
    wm.pixel_painter_grid_opacity = 0.0
    for tool in TOOLS:
        for name, default in tool_property_defaults(tool.tool_id).items():
            setattr(wm, name, default)
