"""Palettes: per project (scene property, saved in the .blend) and the library
(palettes.json): slots, views, drag & drop, import / export.
"""

import traceback

import bpy

from ....utils import palette_library
from ....model import color_palette


class PaletteActions:
    """Part of :class:`.bar.PenBarTool` (a mixin: uses its state)."""

    # ---- palettes: per project (the scene, saved in the .blend), library (palettes.json) ----

    def color_drag_enabled(self):
        return bool(self.wm_get('pen_color_drag', True))

    def project(self):
        scene = self._c().context.scene
        return color_palette.decode_project(getattr(scene, 'pixel_painter_palettes', "") if scene else "")

    def _store_project(self, project):
        scene = self._c().context.scene
        if scene is not None and hasattr(scene, 'pixel_painter_palettes'):
            scene.pixel_painter_palettes = color_palette.encode_project(project)

    # The active palette's colors (the palette band's color view).

    def palette(self):
        active = color_palette.active_palette(self.project())
        return list(active["colors"]) if active else [None] * color_palette.PALETTE_SIZE

    def set_palette_slot(self, index, rgb):
        self._store_project(color_palette.edit_active(
            self.project(), lambda pal: color_palette.with_color(pal, index, rgb)))

    def swap_palette_slots(self, i, j):
        self._store_project(color_palette.edit_active(
            self.project(), lambda pal: color_palette.with_swapped_colors(pal, i, j)))

    def clear_palette(self):
        """Empty the active palette's colors (it keeps its name and slot)."""
        self._store_project(color_palette.edit_active(
            self.project(), lambda pal: dict(pal, colors=[None] * color_palette.PALETTE_SIZE)))

    # The project's palettes (the palette band's palette view).

    def palette_view(self):
        return bool(self._c().state.get('pen_palette_view'))

    def set_palette_view(self, on):
        self._c().state['pen_palette_view'] = bool(on)

    def active_palette_index(self):
        return self.project()["active"]

    def active_palette(self):
        return color_palette.active_palette(self.project())

    def project_palette(self, index):
        return self.project()["palettes"][index]

    def select_palette(self, index):
        """Make slot ``index`` the active palette (an empty slot gets a new, empty palette)."""
        project = self.project()
        if project["palettes"][index] is None:
            project = color_palette.with_palette(project, index,
                                                 color_palette.empty_palette(color_palette.next_name(project)))
        self._store_project(color_palette.with_active(project, index))

    def set_project_palette(self, index, palette):
        """Slot ``index`` set to a copy of ``palette`` (None deletes the palette)."""
        self._store_project(color_palette.with_palette(self.project(), index, palette))

    def swap_project_palettes(self, i, j):
        self._store_project(color_palette.with_swapped_palettes(self.project(), i, j))

    def set_active_palette(self, palette):
        """Replace the active palette's colors (paste)."""
        self._store_project(color_palette.edit_active(
            self.project(), lambda pal: dict(pal, colors=list(palette["colors"]))))

    # Library: not synced with the project; palettes are copied in and out.

    def library(self, reload=False):
        if self._library is None or reload:
            self._library = palette_library.load()
        return self._library

    def library_add(self, palette):
        self._library = self.library() + [dict(palette, colors=list(palette["colors"]))]
        palette_library.save(self._library)

    def library_delete(self, index):
        lib = list(self.library())
        if 0 <= index < len(lib):
            del lib[index]
            self._library = lib
            palette_library.save(lib)

    def palette_from_image(self):
        """Pick an image file; its pixel colors become a new palette (ui/operators/palette.py)."""
        self._run_deferred(lambda: bpy.ops.image.pixel_painter_palette_from_image('INVOKE_DEFAULT'))

    # Clipboard.

    def copy_palette(self, palette):
        """Put ``palette`` on the system clipboard (JSON with hex colors)."""
        try:
            self._c().wm.clipboard = color_palette.to_text(palette)
            return True
        except Exception:
            traceback.print_exc()
            return False

    def clipboard_palette(self):
        """The palette in the clipboard text (our JSON or any #rrggbb codes), or None."""
        try:
            return color_palette.from_text(self._c().wm.clipboard)
        except Exception:
            return None

    def set_color(self, which, rgb):
        """Set the primary ('PRIMARY') or secondary ('SECONDARY') color."""
        ctx = self._c()
        if which == 'SECONDARY':
            ctx.settings.set_brush_secondary_rgb(ctx.context, *rgb)
        else:
            ctx.settings.set_brush_rgb(ctx.context, *rgb)
        ctx.state['pen_color_pending'] = None
