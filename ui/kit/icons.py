"""Icon sets backed by image files, usable in both Blender layouts and GPU overlays."""

import os

try:  # pragma: no cover
    import bpy
    import bpy.utils.previews
    import gpu
    from gpu_extras.presets import draw_texture_2d
except ImportError:  # pragma: no cover
    bpy = None
    gpu = None
    draw_texture_2d = None


class IconSet:
    """A named collection of image icons.

    * :meth:`icon_id` returns an ``icon_value`` for ``layout.operator(...)``.
    * :meth:`draw` blits the icon into a POST_PIXEL overlay.

    Both caches rebuild themselves lazily if Blender invalidated them
    (addon reload, file load), so callers never need to care.
    """

    def __init__(self, directory, files):
        self.directory = directory
        self.files = dict(files)   # key -> filename
        self._previews = None
        self._textures = {}

    def path(self, key):
        filename = self.files.get(key)
        if not filename:
            return None
        path = os.path.join(self.directory, filename)
        return path if os.path.exists(path) else None

    # ---- lifecycle ---------------------------------------------------------

    def register(self):
        self.unregister()
        pcoll = bpy.utils.previews.new()
        for key in self.files:
            path = self.path(key)
            if path:
                pcoll.load(key, path, 'IMAGE')
        self._previews = pcoll

    def unregister(self):
        if self._previews is not None:
            try:
                bpy.utils.previews.remove(self._previews)
            except Exception:
                pass
            self._previews = None
        self._textures.clear()

    def clear_gpu_cache(self):
        self._textures.clear()

    # ---- Blender layout icons ---------------------------------------------

    def icon_id(self, key):
        """``icon_value`` for ``key`` (0 when missing)."""
        if key not in self.files:
            return 0
        for _attempt in range(2):
            if self._previews is None:
                try:
                    self.register()
                except Exception:
                    return 0
            icon = self._previews.get(key) if self._previews is not None else None
            if icon is not None:
                return icon.icon_id
            self._previews = None  # stale collection: rebuild once
        return 0

    # ---- GPU overlay icons -------------------------------------------------

    def texture(self, key, refresh=False):
        if refresh:
            self._textures.pop(key, None)
        if key in self._textures:
            return self._textures[key]
        path = self.path(key)
        if path is None:
            return None
        try:
            img = bpy.data.images.load(path, check_existing=True)
            if hasattr(img, 'alpha_mode'):
                img.alpha_mode = 'PREMUL'
            tex = gpu.texture.from_image(img)
        except Exception:
            return None
        self._textures[key] = tex
        return tex

    def draw(self, key, cx, cy, size, alpha=1.0):
        """Draw icon centered at ``(cx, cy)``. Returns False if nothing was drawn."""
        if key is None or size <= 1.0 or alpha <= 0.05:
            return False
        tex = self.texture(key)
        if tex is None:
            return False
        x = cx - size * 0.5
        y = cy - size * 0.5
        for attempt in range(2):
            try:
                gpu.state.blend_set('ALPHA_PREMULT')
                try:
                    draw_texture_2d(tex, (x, y), size, size, color=(1.0, 1.0, 1.0, alpha))
                except TypeError:
                    # Blender versions without the ``color`` argument.
                    draw_texture_2d(tex, (x, y), size, size)
                return True
            except Exception:
                if attempt == 0:
                    tex = self.texture(key, refresh=True)
                    if tex is None:
                        return False
            finally:
                gpu.state.blend_set('ALPHA')
        return False
