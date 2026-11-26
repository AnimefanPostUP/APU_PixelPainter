"""Icon sets backed by image files, usable in both Blender layouts and GPU overlays."""

import os

from . import draw

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

    ``generators`` maps keys to procedural icons: objects with ``signature()``
    (cheap, changes when the icon would change) and ``render(size)`` returning
    a flat list of straight-alpha RGBA floats. They re-render on signature change.
    """

    GENERATED_SIZE = 64

    def __init__(self, directory, files, generators=None):
        self.directory = directory
        self.files = dict(files)   # key -> filename
        self.generators = dict(generators or {})
        self._previews = None
        self._preview_signatures = {}
        self._textures = {}
        self._texture_signatures = {}

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
        self._preview_signatures.clear()
        for key in self.generators:
            self._update_generated_preview(key)

    def unregister(self):
        if self._previews is not None:
            try:
                bpy.utils.previews.remove(self._previews)
            except Exception:
                pass
            self._previews = None
        self._preview_signatures.clear()
        self.clear_gpu_cache()

    def clear_gpu_cache(self):
        self._textures.clear()
        self._texture_signatures.clear()

    # ---- generated icons -----------------------------------------------------

    def _signature(self, key):
        try:
            return self.generators[key].signature()
        except Exception:
            return None

    def _render(self, key):
        try:
            return self.generators[key].render(self.GENERATED_SIZE)
        except Exception:
            return None

    def _update_generated_preview(self, key):
        pcoll = self._previews
        if pcoll is None:
            return
        sig = self._signature(key)
        if key in pcoll and self._preview_signatures.get(key) == sig:
            return
        pixels = self._render(key)
        if pixels is None:
            return
        preview = pcoll[key] if key in pcoll else pcoll.new(key)
        size = self.GENERATED_SIZE
        preview.image_size = (size, size)
        preview.image_pixels_float.foreach_set(pixels)
        preview.icon_size = (size, size)
        preview.icon_pixels_float.foreach_set(pixels)
        self._preview_signatures[key] = sig

    def _generated_texture(self, key):
        sig = self._signature(key)
        tex = self._textures.get(key)
        if tex is not None and self._texture_signatures.get(key) == sig:
            return tex
        pixels = self._render(key)
        if pixels is None:
            return tex
        # The overlay blends with ALPHA_PREMULT: premultiply the white disc.
        premul = list(pixels)
        for i in range(0, len(premul), 4):
            a = premul[i + 3]
            premul[i] *= a
            premul[i + 1] *= a
            premul[i + 2] *= a
        size = self.GENERATED_SIZE
        try:
            buf = gpu.types.Buffer('FLOAT', len(premul), premul)
            tex = gpu.types.GPUTexture((size, size), format='RGBA16F', data=buf)
        except Exception:
            return None
        self._textures[key] = tex
        self._texture_signatures[key] = sig
        return tex

    # ---- Blender layout icons ---------------------------------------------

    def icon_id(self, key):
        """``icon_value`` for ``key`` (0 when missing)."""
        if key not in self.files and key not in self.generators:
            return 0
        for _attempt in range(2):
            if self._previews is None:
                try:
                    self.register()
                except Exception:
                    return 0
            if key in self.generators:
                try:
                    self._update_generated_preview(key)
                except Exception:
                    self._previews = None
                    continue
            icon = self._previews.get(key) if self._previews is not None else None
            if icon is not None:
                return icon.icon_id
            self._previews = None  # stale collection: rebuild once
        return 0

    # ---- GPU overlay icons -------------------------------------------------

    def texture(self, key, refresh=False):
        if refresh:
            self._textures.pop(key, None)
        if key in self.generators:
            return self._generated_texture(key)
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

    def draw_quad(self, key, corners, uvs, alpha=1.0):
        """Draw part of an icon: the texture area ``uvs`` (4 points, 0..1) mapped onto the
        screen quad ``corners`` (4 points, same order). Returns False if nothing was drawn."""
        if key is None or alpha <= 0.05:
            return False
        tex = self.texture(key)
        if tex is None:
            return False
        draw.flush()   # the icon goes on top of the shapes issued before it
        try:
            from gpu_extras.batch import batch_for_shader
            try:
                shader, tinted = gpu.shader.from_builtin('IMAGE_COLOR'), True
            except Exception:
                shader, tinted = gpu.shader.from_builtin('IMAGE'), False
            batch = batch_for_shader(shader, 'TRIS', {"pos": list(corners), "texCoord": list(uvs)},
                                     indices=((0, 1, 2), (0, 2, 3)))
            gpu.state.blend_set('ALPHA_PREMULT')
            shader.bind()
            shader.uniform_sampler("image", tex)
            if tinted:
                shader.uniform_float("color", (1.0, 1.0, 1.0, alpha))
            batch.draw(shader)
            return True
        except Exception:
            return False
        finally:
            gpu.state.blend_set('ALPHA')

    def draw(self, key, cx, cy, size, alpha=1.0):
        """Draw icon centered at ``(cx, cy)``. Returns False if nothing was drawn."""
        if key is None or size <= 1.0 or alpha <= 0.05:
            return False
        tex = self.texture(key)
        if tex is None:
            return False
        x = cx - size * 0.5
        y = cy - size * 0.5
        draw.flush()   # the icon goes on top of the shapes issued before it
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
