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
import sys

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


def _module(name):
    return importlib.import_module(f"{__package__}.{name}")


def _reload_modules():
    """Forget every loaded submodule, so the imports below load fresh code
    ("Reload Scripts", re-enabling). The import order follows the imports themselves:
    no module list to keep in sync. Run after :func:`_cleanup_runtime`, which still
    needs the previous load's modules."""
    prefix = __package__ + "."
    for name in [n for n in sys.modules if n.startswith(prefix)]:
        del sys.modules[name]


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
        core = _module('core.operator')
        _module('paint.pixels').remove_draw_handler(core._state)
        core._undo_clear()
        _module('utils.pixel_io').invalidate()
        _module('core.history').unregister()
        core._state['running'] = False
        core._state['current_cx'] = None
        core._state['current_cy'] = None
    except Exception:
        pass


def _classes():
    return (
        *_module('core.operator').classes,
        *_module('tools.selection').classes,
        *_module('ui.menus.native_menus').classes,
        *_module('ui.menus.pie_menu').classes,
        *_module('ui.panels.tool_settings').classes,
        *_module('ui.panels.settings_popup').classes,
        *_module('ui.operators.palette').classes,
        *_module('ui.operators.image_save').classes,
        *_module('ui.operators.mask').classes,
    )


def register():
    _cleanup_runtime()
    _reload_modules()
    _module('core.operator').new_generation()   # sessions from before this load shut down

    import bmesh
    faces_uv = _module('ui.operators.paint_selected_faces_uv')
    faces_uv.set_bmesh_module(bmesh)
    faces_uv.register()

    _module('properties').register()
    _module('core.history').register()
    _module('ui.icons.tool_icons').register()
    for cls in _classes():
        bpy.utils.register_class(cls)
    for tool in _module('ui.workspace_tool').TOOLS:
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
            _module('core.operator').apply_active_tool_settings(bpy.context)
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
    for tool in reversed(_module('ui.workspace_tool').TOOLS):
        try:
            bpy.utils.unregister_tool(tool)
        except Exception:
            pass
    for cls in reversed(_classes()):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    _module('ui.icons.tool_icons').unregister()
    _module('properties').unregister()
    _module('core.history').unregister()
    _module('ui.operators.paint_selected_faces_uv').unregister()


if __name__ == "__main__":
    register()
