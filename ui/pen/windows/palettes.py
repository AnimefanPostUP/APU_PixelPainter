"""Pen menu palettes: the palette library window and the confirmation dialog.

* :class:`PaletteLibrary` -- the Palettes window (Windows ring > *Palettes*; movable,
  kept open and in place per project) for the
  palettes in ``palettes.json`` (shared by all projects, see
  ``utils/palette_library.py``). Project palettes and library palettes are not
  synced: palettes are copied between them by drag & drop (a project palette
  dropped on the library list is saved there; a library palette dropped on a
  palette slot is loaded into the project), or by the buttons. Each entry can be
  copied to the clipboard and deleted (after a confirmation); a palette in the
  clipboard (JSON or ``#rrggbb`` codes) can be pasted into the library or into
  the active palette.
* :class:`ConfirmDialog` -- a small dialog over the pen menu: message, action
  button, *Cancel*. A tap outside it, ESC or right click cancel.

Drag payloads are ``('palette', palette, origin)`` with origin ``('project', i)``
or ``('library', i)`` (see ``ui.pen.bar.ColorDrag``).
"""

from ...kit import Column, Rect, Row, TextBlock, Widget
from ...kit import draw
from ...kit.theme import with_alpha
from ...kit.widget import _resolve
from ....model import color_palette
from ..widgets.color import ColorDrag
from ..style import PenButton, PlainGroup
from ..icons.palettes import library_arrow, paint_copy, paint_image, paint_library, paint_palettes, paint_paste, paint_save, paint_trash

PAGE_WIDTH = 300.0
ROWS_PER_PAGE = 8
TINT_PALETTE = (0.95, 0.55, 0.30)
TINT_LIBRARY = (0.45, 0.75, 0.95)


def draw_palette_cells(rect, palette, alpha, theme, rows=2):
    """The palette's colors as a grid of cells filling ``rect`` (empty slots dark)."""
    colors = (palette or {}).get("colors") or [None] * color_palette.PALETTE_SIZE
    cols = (len(colors) + rows - 1) // rows
    w, h = rect.width / cols, rect.height / rows
    draw.rect(rect, with_alpha(theme.surface_dark, alpha))
    for i, c in enumerate(colors):
        if c is None:
            continue
        col, row = i % cols, i // cols
        draw.rect(Rect(rect.x0 + col * w, rect.y1 - (row + 1) * h, rect.x0 + (col + 1) * w, rect.y1 - row * h),
                  (c[0], c[1], c[2], alpha))


# ---- widgets ---------------------------------------------------------------------------

class PalettePreview(ColorDrag, Widget):
    """A palette as a strip of color cells. Drag source (``origin()``: the payload's
    origin); ``palette()`` None shows an empty strip."""

    interactive = True

    def __init__(self, bar, palette, origin, *, size=(150.0, 22.0), **kwargs):
        super().__init__(**kwargs)
        self.bar = bar
        self.palette = palette
        self.origin = origin
        self.size = size

    def measure(self, theme):
        return theme.px(self.size[0]), theme.px(self.size[1])

    def drag_payload(self):
        pal = _resolve(self.palette, None)
        return None if pal is None else ('palette', pal, _resolve(self.origin, None))

    def draw_self(self, dc):
        theme = dc.theme
        pal = _resolve(self.palette, None)
        if pal is None:
            return
        draw_palette_cells(self.rect, pal, dc.alpha, theme)
        border = theme.accent if self.hover_t > 0.5 else theme.edge_for(theme.surface)
        draw.rounded_rect_outline(self.rect, theme.px(3.0), with_alpha(border, dc.alpha), width=1.0)


class _DropGroup(PlainGroup):
    """A group that takes dropped palettes: ``accept(payload) -> bool`` / ``on_drop(payload)``."""

    def __init__(self, title, content, *, accept, on_drop, **kwargs):
        super().__init__(title, content, **kwargs)
        self.accept = accept
        self.on_drop = on_drop

    def accepts(self, payload):
        return bool(self.accept(payload))

    def accept_drop(self, payload, source):
        self.on_drop(payload)




# ---- library window ---------------------------------------------------------------------

class PaletteLibrary:
    """Builds the library flyout (``self.panel``) for a :class:`ui.pen.bar.PenBar`."""

    def __init__(self, bar):
        self.bar = bar
        self.a = bar.actions
        self.page = 0
        a = self.a

        active = lambda: a.active_palette()
        active_preview = PalettePreview(bar, active, lambda: ('project', a.active_palette_index()),
                                        size=(PAGE_WIDTH - 20.0, 26.0), key='LIB_ACTIVE_PREVIEW')
        active_buttons = Row([
            PenButton("Copy", painter=paint_copy, layout='row', size=(66.0, 26.0), key='LIB_ACTIVE_COPY',
                       on_click=self.copy_active),
            PenButton("Paste", painter=paint_paste, layout='row', size=(66.0, 26.0), key='LIB_ACTIVE_PASTE',
                       on_click=self.paste_active),
            PenButton("Save to library", painter=paint_save, layout='row', size=(140.0, 26.0),
                       key='LIB_ACTIVE_SAVE', on_click=self.save_active),
        ], gap=4.0)
        active_group = _DropGroup(lambda: f"Active palette: {(active() or {}).get('name', '(empty slot)')}",
                                  Column([active_preview, active_buttons], gap=6.0), tint=TINT_PALETTE,
                                  painter=paint_palettes, width=PAGE_WIDTH,
                                  accept=lambda p: p[0] == 'palette' and (p[2] or ('',))[0] == 'library',
                                  on_drop=lambda p: self.load_into_active(p[1]))

        rows = [self._row(k) for k in range(ROWS_PER_PAGE)]
        pager = Row([
            PenButton("", painter=library_arrow(-1), layout='icon', size=(28.0, 24.0), key='LIB_PREV',
                       on_click=lambda: self.turn(-1)),
            TextBlock(lambda: [f"{self.page + 1} / {self.pages()}"], size=9.5, color=(1, 1, 1, 0.9)),
            PenButton("", painter=library_arrow(1), layout='icon', size=(28.0, 24.0), key='LIB_NEXT',
                       on_click=lambda: self.turn(1)),
        ], gap=8.0)
        imports = Row([
            PenButton("Paste as new", painter=paint_paste, layout='row', size=(130.0, 26.0),
                       key='LIB_PASTE_NEW', on_click=self.paste_new),
            PenButton("From image...", painter=paint_image, layout='row', size=(130.0, 26.0),
                       key='LIB_FROM_IMAGE', on_click=self.from_image),
        ], gap=6.0)
        library_group = _DropGroup(lambda: f"Library ({len(a.library())} palettes, palettes.json)",
                                   Column(rows + [pager, imports], gap=4.0), tint=TINT_LIBRARY,
                                   painter=paint_library,
                                   width=PAGE_WIDTH,
                                   accept=lambda p: p[0] == 'palette' and (p[2] or ('',))[0] == 'project',
                                   on_drop=lambda p: self.save(p[1]))
        status = TextBlock(lambda: [self.status], size=9.0, width=PAGE_WIDTH)
        hints = TextBlock(["Drag a palette here (palette view, active palette) to save it.",
                           "Drag a library palette onto a palette slot to load it.",
                           "From image: its pixel colors become a new project palette."],
                          size=8.5, width=PAGE_WIDTH)
        # The window's body (``PenBar`` puts it in the movable Palettes window).
        self.content = Column([active_group, library_group, status, hints], gap=8.0)

    # ---- status: shared state, so operators (palette from image) can report here too ------

    DEFAULT_STATUS = "Drag palettes between the palette view and this list."

    @property
    def status(self):
        try:
            return self.a.get_state('pen_palette_status') or self.DEFAULT_STATUS
        except Exception:
            return self.DEFAULT_STATUS

    @status.setter
    def status(self, text):
        self.a.set_state('pen_palette_status', text)

    # ---- rows ------------------------------------------------------------------------

    def _entry(self, k):
        index = self.page * ROWS_PER_PAGE + k
        lib = self.a.library()
        return (index, lib[index]) if index < len(lib) else (index, None)

    def _row(self, k):
        preview = PalettePreview(self.bar, lambda: self._entry(k)[1], lambda: ('library', self._entry(k)[0]),
                                 key=f"LIB_ROW_{k}")
        name = TextBlock(lambda: [(self._entry(k)[1] or {}).get("name", "")[:18]], size=9.0, width=78.0,
                         color=(1, 1, 1, 0.9))
        filled = lambda: self._entry(k)[1] is not None
        copy = PenButton("", painter=paint_copy, layout='icon', size=(26.0, 22.0), key=f"LIB_COPY_{k}",
                          enabled=filled, on_click=lambda: self.copy_entry(k))
        delete = PenButton("", painter=paint_trash, layout='icon', size=(26.0, 22.0), key=f"LIB_DELETE_{k}",
                            enabled=filled, on_click=lambda: self.delete_entry(k))
        return Row([preview, name, copy, delete], gap=4.0)

    def pages(self):
        return max(1, (len(self.a.library()) + ROWS_PER_PAGE - 1) // ROWS_PER_PAGE)

    def turn(self, step):
        self.page = max(0, min(self.pages() - 1, self.page + step))

    def opened(self):
        self.a.library(reload=True)       # palettes.json may have changed (another Blender)
        self.page = min(self.page, self.pages() - 1)

    # ---- actions -----------------------------------------------------------------------

    def save(self, palette):
        if palette is None or color_palette.is_empty(palette):
            self.status = "Nothing to save: the palette has no colors."
            return
        self.a.library_add(palette)
        self.page = self.pages() - 1
        self.status = f"Saved “{palette['name']}” to the library."

    def save_active(self):
        self.save(self.a.active_palette())

    def copy_entry(self, k):
        index, pal = self._entry(k)
        if pal is not None and self.a.copy_palette(pal):
            self.status = f"Copied “{pal['name']}” to the clipboard."

    def copy_active(self):
        pal = self.a.active_palette()
        if pal is None or color_palette.is_empty(pal):
            self.status = "The active palette has no colors to copy."
        elif self.a.copy_palette(pal):
            self.status = f"Copied “{pal['name']}” to the clipboard."

    def delete_entry(self, k):
        index, pal = self._entry(k)
        if pal is None:
            return

        def delete():
            self.a.library_delete(index)
            self.page = min(self.page, self.pages() - 1)
            self.status = f"Deleted “{pal['name']}” from the library."

        self.bar.confirm([f"Delete “{pal['name']}”", "from the palette library?"], delete, "Delete")

    def from_image(self):
        """File browser; the image's pixel colors become a new project palette (ui/operators/palette.py)."""
        self.status = "Choose an image in the file browser..."
        self.a.palette_from_image()

    def paste_new(self):
        pal = self.a.clipboard_palette()
        if pal is None:
            self.status = "The clipboard holds no palette (JSON or #rrggbb colors)."
            return
        self.save(pal)

    def paste_active(self):
        pal = self.a.clipboard_palette()
        if pal is None:
            self.status = "The clipboard holds no palette (JSON or #rrggbb colors)."
            return
        self.load_into_active(pal, "Pasted")

    def load_into_active(self, palette, verb="Loaded"):
        """Replace the active palette's colors (after a confirmation when it has colors)."""
        def load():
            self.a.set_active_palette(palette)
            self.status = f"{verb} {len(color_palette.filled(palette))} colors into the active palette."

        current = self.a.active_palette()
        if current is None or color_palette.is_empty(current):
            load()
        else:
            self.bar.confirm([f"Replace the colors of “{current['name']}”", f"with “{palette['name']}”?"],
                             load, "Replace")
