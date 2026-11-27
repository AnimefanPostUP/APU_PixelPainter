"""Texture backup: an optional helper process that keeps the project's unsaved textures
in RAM and writes them to disk only when Blender closes or crashes.

Modules:

* ``protocol`` -- message framing over the helper's stdin (stdlib only).
* ``store``    -- the on-disk cache: ``index.json`` + one folder per save (stdlib only).
* ``helper``   -- the helper process itself (run with Blender's Python, stdlib only).
* ``service``  -- Blender side: starts / stops the helper, sends changed textures.
* ``restore``  -- Blender side: writes a saved texture back into an image.
"""
