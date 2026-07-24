"""Persist Pixel Painter WindowManager settings across Blender sessions."""

import json
import os
import shutil

import bpy
from bpy.app.handlers import persistent


_TOOLS = ['SQUARE', 'CIRCLE', 'SPRAY', 'LINE', 'SMOOTH', 'SMEAR', 'ERASER', 'SELECT']
_LOADING = False
_STARTUP_LOAD_ATTEMPTS = 0
_MAX_STARTUP_LOAD_ATTEMPTS = 20
_DEBUG = True


def _dbg(message):
    if _DEBUG:
        print(f"[PixelPainter][Settings] {message}")


def _settings_file_path():
    """Return the JSON file used to persist Pixel Painter settings.

    Stored directly in the add-on folder as requested.
    """
    try:
        addon_root = os.path.dirname(os.path.dirname(__file__))
    except Exception:
        addon_root = None
    if not addon_root:
        _dbg("Addon root path unavailable")
        return None
    path = os.path.join(addon_root, 'settings.json')
    return path


def _legacy_settings_file_path():
    """Return the previous CONFIG-based settings location (migration source)."""
    try:
        config_dir = bpy.utils.user_resource('CONFIG')
    except Exception:
        config_dir = None
    if not config_dir:
        _dbg("CONFIG user resource path unavailable for legacy path")
        return None
    folder = os.path.join(config_dir, 'apu_pixel_painter')
    path = os.path.join(folder, 'settings.json')
    return path


def _persisted_keys():
    """Return all WindowManager property names that should be persisted."""
    keys = [
        'pixel_painter_mode',
        'pixel_painter_radius',
        'pixel_painter_spacing',
        'pixel_painter_modifier',
        'pixel_painter_global_modifier',
        'pixel_painter_global_strength',
        'pixel_painter_global_alpha',
        'pixel_painter_global_strength_rmb',
        'pixel_painter_global_modifier_rmb',
        'pixel_painter_global_alpha_rmb',
        'pixel_painter_circle_falloff',
        'pixel_painter_spray_falloff',
        'pixel_painter_spray_strength',
        'pixel_painter_protect_transparent',
        'pixel_painter_grid_opacity',
        'pixel_painter_blend_favorites',
        'pixel_painter_ui_show_settings',
        'pixel_painter_ui_show_blend_mode',
        'pixel_painter_ui_show_shortcuts',
        'pixel_painter_ui_show_tool_settings',
    ]
    for tool in _TOOLS:
        keys.extend([
            f'pixel_painter_{tool}_size',
            f'pixel_painter_{tool}_use_global_size',
            f'pixel_painter_{tool}_modifier',
            f'pixel_painter_{tool}_use_global_modifier',
            f'pixel_painter_{tool}_strength',
            f'pixel_painter_{tool}_use_global_strength',
            f'pixel_painter_{tool}_alpha',
            f'pixel_painter_{tool}_use_global_alpha',
            f'pixel_painter_{tool}_strength_rmb',
            f'pixel_painter_{tool}_use_global_strength_rmb',
            f'pixel_painter_{tool}_modifier_rmb',
            f'pixel_painter_{tool}_use_global_modifier_rmb',
            f'pixel_painter_{tool}_alpha_rmb',
            f'pixel_painter_{tool}_use_global_alpha_rmb',
        ])
    return keys


def _json_safe(value):
    if isinstance(value, set):
        return sorted(list(value))
    return value


def on_property_update(_self, context):
    """Property update callback to persist setting changes immediately."""
    if _LOADING:
        _dbg("Skipped save during load guard")
        return
    wm = getattr(context, 'window_manager', None)
    save_window_manager_settings(wm)


def save_window_manager_settings(wm=None):
    """Save persisted Pixel Painter settings from WindowManager to disk."""
    if _LOADING:
        _dbg("Skipped save during load guard")
        return
    if wm is None:
        wm = getattr(bpy.context, 'window_manager', None)
    if wm is None:
        _dbg("No WindowManager available for save")
        return

    path = _settings_file_path()
    if not path:
        _dbg("No settings path available for save")
        return

    data = {}
    for key in _persisted_keys():
        if not hasattr(wm, key):
            continue
        try:
            data[key] = _json_safe(getattr(wm, key))
        except Exception:
            continue

    try:
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
        _dbg(f"Saved {len(data)} keys to {path}")
    except Exception as exc:
        print(f"[PixelPainter] Failed to save persisted settings: {exc}")


def ensure_settings_file_exists(wm=None):
    """Create settings JSON on first run using current WindowManager values."""
    path = _settings_file_path()
    if not path:
        _dbg("No settings path available while ensuring file")
        return
    if os.path.exists(path):
        _dbg(f"Settings file already exists: {path}")
        return

    legacy_path = _legacy_settings_file_path()
    if legacy_path and os.path.exists(legacy_path):
        try:
            shutil.copyfile(legacy_path, path)
            _dbg(f"Migrated settings file from {legacy_path} to {path}")
            return
        except Exception as exc:
            _dbg(f"Failed to migrate legacy settings file: {exc}")

    _dbg(f"Settings file missing, creating from current values: {path}")
    save_window_manager_settings(wm)


def load_window_manager_settings(wm=None):
    """Load persisted Pixel Painter settings into WindowManager."""
    global _LOADING

    if wm is None:
        wm = getattr(bpy.context, 'window_manager', None)
    if wm is None:
        _dbg("No WindowManager available for load")
        return

    path = _settings_file_path()
    if not path or not os.path.exists(path):
        _dbg(f"Settings file not found for load: {path}")
        return

    try:
        with open(path, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
    except Exception as exc:
        print(f"[PixelPainter] Failed to load persisted settings: {exc}")
        return

    if not isinstance(data, dict):
        _dbg("Settings file did not contain a dict; skipping")
        return

    _LOADING = True
    applied = 0
    try:
        for key, value in data.items():
            if not hasattr(wm, key):
                continue
            if key == 'pixel_painter_blend_favorites' and isinstance(value, list):
                value = set(value)
            try:
                setattr(wm, key, value)
                applied += 1
            except Exception:
                continue
    finally:
        _LOADING = False
    _dbg(f"Loaded {applied} keys from {path}")


def _startup_load_timer():
    """Retry loading settings until Blender has a valid WindowManager."""
    global _STARTUP_LOAD_ATTEMPTS

    wm = getattr(bpy.context, 'window_manager', None)
    if wm is None:
        _STARTUP_LOAD_ATTEMPTS += 1
        _dbg(f"Startup load retry {_STARTUP_LOAD_ATTEMPTS}/{_MAX_STARTUP_LOAD_ATTEMPTS}: no WindowManager yet")
        if _STARTUP_LOAD_ATTEMPTS >= _MAX_STARTUP_LOAD_ATTEMPTS:
            _dbg("Startup load aborted after max retries")
            return None
        return 0.5

    _dbg("Startup load timer running with valid WindowManager")
    ensure_settings_file_exists(wm)
    load_window_manager_settings(wm)
    try:
        from ..core import core as core_module
        core_module.apply_active_tool_settings(bpy.context)
        _dbg("Reapplied active tool settings after load")
    except Exception:
        _dbg("Failed to reapply active tool settings after load")
        pass
    return None


@persistent
def _on_load_post(_dummy):
    """Schedule a delayed restore when Blender loads a startup file/project."""
    _dbg("load_post triggered; scheduling startup load")
    register_startup_load()


def register_startup_load():
    """Schedule a startup settings load once Blender UI context is ready."""
    global _STARTUP_LOAD_ATTEMPTS
    _STARTUP_LOAD_ATTEMPTS = 0
    path = _settings_file_path()
    if path:
        _dbg(f"Register startup load (settings path: {path})")
    try:
        if bpy.app.timers.is_registered(_startup_load_timer):
            bpy.app.timers.unregister(_startup_load_timer)
            _dbg("Unregistered previous startup timer")
    except Exception:
        pass
    try:
        bpy.app.timers.register(_startup_load_timer, first_interval=0.1)
        _dbg("Registered startup timer")
    except Exception:
        _dbg("Failed to register startup timer")
        pass
    try:
        handlers = bpy.app.handlers.load_post
        if _on_load_post not in handlers:
            handlers.append(_on_load_post)
            _dbg("Attached load_post handler")
    except Exception:
        _dbg("Failed to attach load_post handler")
        pass


def unregister_startup_load():
    """Remove pending startup-load timer when the addon unregisters."""
    try:
        if bpy.app.timers.is_registered(_startup_load_timer):
            bpy.app.timers.unregister(_startup_load_timer)
            _dbg("Unregistered startup timer")
    except Exception:
        pass
    try:
        handlers = bpy.app.handlers.load_post
        if _on_load_post in handlers:
            handlers.remove(_on_load_post)
            _dbg("Detached load_post handler")
    except Exception:
        pass
