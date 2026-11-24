# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####
# Created by Kushiro
# Addon Recoded and Drastically Expanded by AnimefanPostUP

import importlib

import bpy


bl_info = {
    "name": "APU Pixel Painter",
    "description": "All in One Tool for Pixelpainting",
    "author": "Kushiro, AnimefanPostUP",
    "version": (1, 1, 0),
    "blender": (4, 2, 0),
    "location": "Image Editor > Toolbar, 3D Viewport (Texture Paint) > Toolbar",
    "category": "Image Editor",
}


# Submodules in dependency order (leaves first). On every register() they are
# reloaded in this order so "Reload Scripts" picks up code changes.
_MODULES = (
    # utilities
    'utils.math_utils',
    'utils.blender_utils',
    'utils.persistence_settings',
    'utils.settings_service',
    # generic UI kit (no addon knowledge)
    'ui.kit.geometry',
    'ui.kit.anim',
    'ui.kit.theme',
    'ui.kit.events',
    'ui.kit.aa',
    'ui.kit.draw',
    'ui.kit.widget',
    'ui.kit.widgets',
    'ui.kit.color_models',
    'ui.kit.color_selector',
    'ui.kit.color_pad',
    'ui.kit.radial',
    'ui.kit.form',
    'ui.kit.curve',
    'ui.kit.ring',
    'ui.kit.overlay',
    'ui.kit.icons',
    'ui.kit.modal',
    'ui.kit',
    # pixel drawing + overlays
    'tools.draw_blending',
    'tools.draw_functions',
    'tools.draw_gridoverlay',
    'tools.draw_tool_smooth',
    'tools.overlays',
    'tools.overlays_selectmode',
    # core framework + shared runtime state (no tool imports)
    'core.framework',
    'core.state',
    'core.view3d',
    'tools.overlays_view3d',
    'core.context',
    'core.history',
    'core.variables',
    # tools
    'tools.falloff',
    'tools.blend_modes',
    'tools.base',
    'tools.registry',
    'tools.subtools.helpers',
    'tools.subtools.color_pick',
    'tools.subtools.strength',
    'tools.subtools.eyedropper',
    'tools.subtools.tool_switch',
    'tools.subtools.pen',
    'tools.pen_pressure',
    'tools.color_history',
    'tools.color_palette',
    'utils.palette_library',
    'utils.palette_image',
    'tools.mask_geometry',
    'tools.mask',
    'tools.view_nav',
    'tools.stroke',
    'tools.brushes',
    'tools.filters',
    'ui.selection_actions',
    'ui.pen_settings',
    'ui.pen_bar',
    'ui.pen_windows',
    'tools.pen_bar',
    'tools.selection_ops',
    'tools.selection',
    'tools.catalog',
    # core operator (builds the tool manager from the catalog)
    'core.core',
    'ui.tool_settings_ui',
    'ui.palette_ops',
    'ui.image_save_ops',
    'ui.mask_ops',
    'ui.settings_menu',
    'properties',
    # addon UI
    'ui.icons',
    'ui.native_menus',
    'ui.pie_menu',
    'ui.user_interface',
    'ui.paint_selected_faces_uv',
)


def _module(name):
    return importlib.import_module(f"{__package__}.{name}")


def _reload_modules():
    for name in _MODULES:
        importlib.reload(_module(name))


def _cleanup_runtime():
    """Remove handlers/timers/state left by a previous load (before reloading code)."""
    try:
        _module('ui.kit.modal').force_cleanup()
    except Exception:
        pass
    try:
        # Reloading creates a new handler function; drop the old one first.
        _module('utils.persistence_settings').unregister_startup_load()
    except Exception:
        pass
    try:
        core = _module('core.core')
        _module('tools.draw_functions').remove_draw_handler(core._state)
        core._undo_clear()
        _module('core.history').unregister()
        core._state['running'] = False
        core._state['current_cx'] = None
        core._state['current_cy'] = None
    except Exception:
        pass


def _classes():
    return (
        *_module('core.core').classes,
        *_module('tools.selection').classes,
        *_module('ui.native_menus').classes,
        *_module('ui.pie_menu').classes,
        *_module('ui.tool_settings_ui').classes,
        *_module('ui.settings_menu').classes,
        *_module('ui.palette_ops').classes,
        *_module('ui.image_save_ops').classes,
        *_module('ui.mask_ops').classes,
    )


def register():
    _cleanup_runtime()
    _reload_modules()
    _module('core.core').new_generation()   # sessions from before this load shut down

    import bmesh
    faces_uv = _module('ui.paint_selected_faces_uv')
    faces_uv.set_bmesh_module(bmesh)
    faces_uv.register()

    _module('properties').register()
    _module('core.history').register()
    _module('ui.icons').register()
    for cls in _classes():
        bpy.utils.register_class(cls)
    for tool in _module('ui.user_interface').TOOLS:
        bpy.utils.register_tool(tool)

    persistence = _module('utils.persistence_settings')
    wm = getattr(bpy.context, 'window_manager', None)
    for step in (persistence.ensure_settings_file_exists, persistence.load_window_manager_settings):
        try:
            step(wm)
        except Exception:
            pass
    try:
        persistence.register_startup_load()
    except Exception:
        pass

    if wm is not None:
        try:
            svc = _module('utils.settings_service').PixelPainterSettingsService()
            svc.set_brush_strength(bpy.context, getattr(wm, 'pixel_painter_global_strength', 1.0))
            _module('core.core').apply_active_tool_settings(bpy.context)
        except Exception:
            pass


def unregister():
    persistence = _module('utils.persistence_settings')
    try:
        persistence.save_window_manager_settings(getattr(bpy.context, 'window_manager', None))
    except Exception:
        pass
    try:
        persistence.unregister_startup_load()
    except Exception:
        pass

    _cleanup_runtime()
    for tool in reversed(_module('ui.user_interface').TOOLS):
        try:
            bpy.utils.unregister_tool(tool)
        except Exception:
            pass
    for cls in reversed(_classes()):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    _module('ui.icons').unregister()
    _module('properties').unregister()
    _module('core.history').unregister()
    _module('ui.paint_selected_faces_uv').unregister()


if __name__ == "__main__":
    register()
