"""Pen settings: the Settings window of the pen menu (Windows ring > *Settings*; a
movable window like Mask / View, kept open and in place per project), built from
UI-kit widgets -- usable with a pen, no Blender popup.

Layout: the row of icon tabs at the top, the tab's name, then the tab's page
(groups of related controls on soft neutral plates,
:class:`~.pen_style.PlainGroup`). The look is
the shared pen style (``ui/pen/style.py``): rounded buttons, one accent color. The tabs
and the settings are the ones of the Blender settings popup
(:mod:`.settings_menu`, still used by the N-panel / tool header) and share its
remembered tab (``pixel_painter_settings_tab``).

Values are read and written through the pen menu's actions
(:class:`tools.pen.tool.PenBarTool`: ``wm_get`` / ``wm_set`` / ``wm_toggle_flag``
/ ``wm_range`` for ``pixel_painter_*`` properties).
"""


from ...kit import MENU, Column, Grid, Rect, Row, Slider, TextBlock, Widget
from ...kit import draw
from ...kit.form import text_left
from ...kit.theme import with_alpha
from ...kit.widget import _resolve
from ....model import blend_modes, falloff
from ..icons.menu import paint_color_wheel, paint_curve, paint_eyedropper, paint_save
from ..metrics import TINT_FALLOFF, TINT_MODES, TINT_TOOLS
from ..style import PenButton, PlainGroup
from ..icons.settings import icon_blend, icon_bolt, icon_brush, icon_eye, icon_falloff, icon_grid, icon_keyboard, icon_layout, icon_pen, icon_pressure, icon_reset


PAGE_WIDTH = 300.0       # unscaled width of every group
TAB_SIZE = (38.0, 38.0)
TINT_COLOR = (0.95, 0.45, 0.65)
TINT_PEN = (0.66, 0.44, 0.92)
TINT_DISPLAY = (0.55, 0.70, 0.85)
TINT_KEYS = (0.85, 0.80, 0.45)
TINT_PERFORMANCE = (0.45, 0.85, 0.55)

CHANNELS = (('size', "Size"), ('strength', "Strength"), ('alpha', "Alpha"), ('modifier', "Modifier"))
FAVORITE_GROUPS = (("Common", 'COMMON'), ("Contrast", 'CONTRAST'), ("Math", 'MATH'), ("HSL / HSV", 'HSL'))
SHORTCUTS = (
    ("Painting", (("LMB", "Paint with the primary color"), ("RMB", "Paint with the secondary color"),
                  ("Hold Shift", "Smooth while held"), ("Hold Alt", "Draw a line while held"),
                  ("Hold Ctrl", "Pick a color from the image"))),
    ("Selection", (("Drag LMB", "Create or move the selection"), ("Drag edge", "Resize the selection box"),
                   ("RMB", "Clear the selection box"), ("Ctrl+C / V", "Copy / paste the selection"))),
    ("Tools & Menus", (("Shift+1..9", "Select a tool"), ("E", "Color selector"),
                       ("Shift+E", "Strength / alpha bubble"), ("W", "Brush type menu"),
                       ("Shift+W", "Blend mode pie"), ("Q / Esc", "Exit the tool"))),
    ("History", (("Ctrl+Z", "Undo"), ("Ctrl+Shift+Z", "Redo"))),
)
USAGE = (
    "Size: press and drag up / down",
    "S / A / M: press or drag along the slider",
    "Background: drag to move; triangle: resize",
    "Padlock: lock position and size",
    "Colors: tap to paint with one, arrows swap",
    "History (along the circle): tap to reuse",
    "Pickers (beside each color): arm one, then tap the canvas",
    "Mix (top-left corner): tap to paint with the mix",
    "Blend: press, drag onto an entry, lift",
    "Falloff field (beside Redo): swipe; in = hard, out = soft,",
    "  top = linear, bottom = sharp; a tap jumps",
    "Curve (beside Custom): edit / draw / load presets",
    "RMB: the pen paints the secondary color",
    "Save (top right): saves the image; dot = unsaved",
    "Mask (top right): opens the paint mask window",
    "View (top right): orient / roll / fit the 3D view",
)
SAVE_METHODS = (('AUTO', "Auto"), ('PACK', "Pack"), ('FILE', "File"))
SAVE_HINTS = {
    'AUTO': ("Repacks a packed image, saves an image with a file",
             "to it, packs anything else (e.g. a new image)."),
    'PACK': ("Always packs the image into the .blend.",),
    'FILE': ("Always writes a file; images without one go to:",),
}


TABS = (
    ('COLOR', "Color Selector", TINT_COLOR, paint_color_wheel(None)),
    ('TOOLS', "Tools", TINT_TOOLS, icon_brush),
    ('BLENDING', "Blending", TINT_MODES, icon_blend),
    ('FALLOFF', "Falloff", TINT_FALLOFF, icon_falloff),
    ('PEN', "Pen", TINT_PEN, icon_pen),
    ('DISPLAY', "Display", TINT_DISPLAY, icon_eye),
    ('PERFORMANCE', "Performance", TINT_PERFORMANCE, icon_bolt),
    ('SHORTCUTS', "Shortcuts", TINT_KEYS, icon_keyboard),
)


# ---- widgets ---------------------------------------------------------------------------

class _Pages(Widget):
    """Shows the page ``current()`` names (the first one when unknown)."""

    def __init__(self, pages, current):
        super().__init__()
        self.pages = {key: self.add(page) for key, page in pages}
        self.current = current

    def _active(self):
        first = next(iter(self.pages.values()))
        active = self.pages.get(_resolve(self.current, None), first)
        for page in self.pages.values():
            page.visible = page is active
        return active

    def measure(self, theme):
        return self._active().measure(theme)

    def arrange(self, rect, theme):
        self.rect = rect
        self._active().arrange(rect, theme)


class _KeyRow(Widget):
    """A shortcut: keycap on the left, what it does on the right. ``all_keys``: every
    key text of the page, so the descriptions line up after the widest keycap."""

    def __init__(self, keys, action, width, all_keys):
        super().__init__()
        self.keys = keys
        self.action = action
        self.width = width
        self.all_keys = all_keys

    def measure(self, theme):
        return theme.px(self.width), theme.px(20.0)

    def draw_self(self, dc):
        theme = dc.theme
        r = self.rect
        size = theme.px(9.0)
        pad = theme.px(5.0)
        tw, _th = draw.text_size(self.keys, size, theme.font_id)
        cap = Rect(r.x0, r.y0 + theme.px(2.0), r.x0 + tw + pad * 2.0, r.y1 - theme.px(2.0))
        draw.rounded_rect(cap, theme.px(5.0), with_alpha(theme.surface_pressed, dc.alpha),
                          rim=theme.edge_for(theme.surface_pressed, dc.alpha))
        draw.text_centered(self.keys, cap.cx, cap.cy, size, with_alpha(theme.text, dc.alpha), theme.font_id)
        column = max(draw.text_size(k, size, theme.font_id)[0] for k in self.all_keys) + pad * 2.0 + theme.px(10.0)
        text_left(self.action, r.x0 + column, r.cy, size,
                  with_alpha(theme.text_muted, dc.alpha), theme.font_id)


# ---- the flyout -------------------------------------------------------------------------

class SettingsMenu:
    """Builds the settings flyout panel (``self.panel``) for a :class:`ui.pen.bar.PenBar`."""

    def __init__(self, bar):
        self.bar = bar
        self.a = bar.actions
        tabs = [PenButton(label, painter=painter, layout='icon', size=TAB_SIZE, key=f"SETTINGS_TAB_{tab_id}",
                           selected=lambda t=tab_id: self.current() == t,
                           on_click=lambda t=tab_id: self.select(t))
                for tab_id, label, _tint, painter in TABS]
        title = TextBlock(lambda: [self._tab(self.current())[1]], size=13.0, color=(1.0, 1.0, 1.0, 1.0),
                          width=PAGE_WIDTH)
        pages = _Pages([(tab_id, self._page(tab_id, tint)) for tab_id, _label, tint, _p in TABS], self.current)
        # The window's body (``PenBar`` puts it in the movable Settings window): the
        # tabs at the top (the window is placed by its top-left corner, so they
        # don't move when the page height changes), the tab's name, its page.
        self.content = Column([Row(tabs, gap=4.0), title, pages], gap=8.0)

    # ---- tabs ------------------------------------------------------------------------

    def current(self):
        return self.a.wm_get('settings_tab', TABS[0][0])

    def select(self, tab_id):
        self.a.wm_set('settings_tab', tab_id)
        self.bar._relayout()

    @staticmethod
    def _tab(tab_id):
        return next((t for t in TABS if t[0] == tab_id), TABS[0])

    def _page(self, tab_id, tint):
        builder = getattr(self, f"_page_{tab_id.lower()}")
        groups = builder(tint)
        return Column(groups, gap=8.0)

    # ---- helpers -----------------------------------------------------------------------

    @staticmethod
    def _group(title, content, tint, painter=None):
        return PlainGroup(title, content, painter=painter, width=PAGE_WIDTH)

    def _choice(self, prop, value, label, size=(64.0, 26.0), painter=None, layout='row'):
        """Button selecting ``value`` of the enum ``prop``."""
        a = self.a
        return PenButton(label, painter=painter, layout=layout, size=size,
                          key=f"SET_{prop}_{value}".upper(),
                          selected=lambda: a.wm_get(prop) == value, on_click=lambda: a.wm_set(prop, value))

    def _toggle(self, prop, label, size=(64.0, 26.0), painter=None):
        a = self.a
        return PenButton(label, painter=painter, layout='row', size=size, key=f"SET_{prop}".upper(),
                          selected=lambda: bool(a.wm_get(prop)), on_click=lambda: a.wm_set(prop, not a.wm_get(prop)))

    def _flag(self, prop, item, label, size=(64.0, 26.0)):
        a = self.a
        return PenButton(label, layout='row', size=size, key=f"SET_{prop}_{item}".upper(),
                          selected=lambda: a.wm_flag(prop, item), on_click=lambda: a.wm_toggle_flag(prop, item))

    def _slider(self, prop, label, size=(PAGE_WIDTH - 20.0, 24.0), **kwargs):
        """Slider for the number property ``prop`` (a callable for per-tool names)."""
        a = self.a
        name = prop if callable(prop) else (lambda: prop)
        is_int = lambda: a.wm_range(name())[2]

        def set_value(v):
            a.wm_set(name(), int(round(v)) if is_int() else v)

        kwargs.pop('fill_color', None)     # one accent color for all sliders
        return Slider(label, lambda: a.wm_get(name(), 0.0) or 0.0, set_value,
                      value_range=lambda: a.wm_range(name())[:2], size=size, corner=size[1] * 0.5, **kwargs)

    @staticmethod
    def _hint(lines):
        return TextBlock(list(lines), size=9.0, width=PAGE_WIDTH - 20.0)

    # ---- pages -------------------------------------------------------------------------

    def _page_color(self, tint):
        a = self.a
        layouts = Row([self._choice('color_selector_layout', kind, label, size=(64.0, 58.0),
                                    painter=icon_layout(kind), layout='column')
                       for kind, label in (('SHEET', "Sheet"), ('SQUARE', "Square"),
                                           ('TRIANGLE', "Triangle"), ('WHEEL', "Wheel"))], gap=6.0)
        model = Row([self._choice('color_selector_model', m, m, size=(130.0, 26.0)) for m in ('HSV', 'HSL')], gap=6.0)
        none = PenButton("None", layout='row', size=(62.0, 26.0), key='SET_SLIDERS_NONE',
                          selected=lambda: not a.wm_get('color_selector_sliders'),
                          on_click=lambda: a.wm_set('color_selector_sliders', set()))
        sliders = Row([none] + [self._flag('color_selector_sliders', s, s, size=(62.0, 26.0))
                                for s in ('RGB', 'HSV', 'HSL')], gap=6.0)
        preview = Column([self._toggle('pen_color_preview', "Preview only", size=(150.0, 28.0), painter=icon_eye),
                          self._hint(("On: the selector only previews; tap the old / new",
                                      "bubble to apply. Off: applies when the pen lifts."))], gap=6.0)
        def clear_active():
            pal = a.active_palette()
            if pal is None or not any(pal["colors"]):
                return
            self.bar.confirm([f"Remove all colors of “{pal['name']}”?"], a.clear_palette, "Clear")

        palette = Column([
            Row([self._toggle('pen_color_drag', "Drag & drop colors", size=(170.0, 28.0)),
                 PenButton("Clear palette", painter=icon_reset, layout='row', size=(110.0, 28.0),
                            key='SET_CLEAR_PALETTE', on_click=clear_active)], gap=6.0),
            self._hint(("Palettes are saved in the .blend (per project); the",
                        "Library button imports / exports them (palettes.json).",
                        "Drag colors onto palette slots or the primary / secondary",
                        "color; in the palette view, drag whole palettes.",
                        "Tap an empty slot: store the current color.")),
        ], gap=6.0)
        return [
            self._group("Layout", layouts, tint, paint_color_wheel(None)),
            self._group("Color Model", model, tint),
            self._group("Channel Sliders", sliders, tint),
            self._group("Pen Color Selector", preview, tint, icon_eye),
            self._group("Palette (bottom-left corner)", palette, tint),
        ]

    def _page_tools(self, tint):
        a = self.a
        tools = Grid([PenButton(tool.label, key=f"SET_TOOL_{tool.tool_id}", icon=tool.tool_id if tool.icon else None,
                             icons=self.bar.icons, size=(44.0, 44.0), icon_only=True,
                             selected=lambda t=tool.tool_id: a.active_tool() == t,
                             on_click=lambda t=tool.tool_id: a.select_tool(t))
                      for tool in a.tools()], columns=4, gap=6.0)
        rows = []
        for channel, label in CHANNELS:
            use_global = lambda c=channel: f"{a.active_tool()}_use_global_{c}"
            value = lambda c=channel: f"{a.active_tool()}_{c}"
            toggle = PenButton("Global", layout='row', size=(62.0, 24.0), key=f"SET_GLOBAL_{channel}".upper(),
                                selected=lambda g=use_global: bool(a.wm_get(g())),
                                on_click=lambda g=use_global: a.wm_set(g(), not a.wm_get(g())))
            slider = self._slider(value, label, size=(PAGE_WIDTH - 90.0, 24.0), fill_color=(*TINT_TOOLS, 1.0),
                                  enabled=lambda g=use_global: not a.wm_get(g(), True),
                                  step=1 if channel == 'size' else None, key=f"SET_VALUE_{channel}".upper())
            rows.append(Row([toggle, slider], gap=6.0))
        rows.append(self._hint(("Global: the tool uses the shared value.",)))
        rows.append(self._toggle('spacing_per_tool', "Spacing per tool", size=(140.0, 26.0)))
        rows.append(self._hint(("Spacing (Once / Fixed / Time and its value): the menu's",
                                "bottom right; per tool, or shared when off.")))
        per_tool = Column(rows, gap=5.0)
        reset = PenButton("Reset Tool Settings", painter=icon_reset, layout='row', size=(200.0, 28.0),
                           key='SET_RESET_TOOLS', on_click=a.reset_tool_settings)
        title = lambda: f"Per-Tool Settings: {self._tool_label(a.active_tool())}"
        return [
            self._group("Tool", tools, tint, icon_brush),
            self._group(title, per_tool, tint),
            self._group("Reset", reset, tint, icon_reset),
        ]

    def _tool_label(self, tool_id):
        return next((t.label for t in self.a.tools() if t.tool_id == tool_id), str(tool_id))

    def _page_blending(self, tint):
        a = self.a
        active = Column([TextBlock(lambda: [blend_modes.label(a.active_blend())], size=12.0,
                                   color=(1.0, 1.0, 1.0, 1.0), width=PAGE_WIDTH - 20.0),
                         self._hint(("Change it with Blend in the pen menu.",))], gap=4.0)
        groups = [self._group("Active Blend Mode", active, tint, icon_blend)]
        for title, group in FAVORITE_GROUPS:
            buttons = [self._flag('blend_favorites', b, blend_modes.label(b), size=(88.0, 24.0))
                       for b in blend_modes.ids(group)]
            groups.append(self._group(f"Favorites: {title}", Grid(buttons, columns=3, gap=4.0), tint))
        return groups

    def _page_falloff(self, tint):
        a = self.a
        icons = self.bar.icons
        presets = [falloff.get(i) for i in falloff.PICKER_ORDER]
        rows = []
        for tool in a.tools():
            if not tool.falloff_property:
                continue
            prop = tool.falloff_property[len('pixel_painter_'):]
            head = PenButton(tool.label, key=f"SET_FALLOFF_TOOL_{tool.tool_id}", icon=tool.tool_id if tool.icon else None,
                          icons=icons, size=(30.0, 30.0), icon_only=True,
                          selected=lambda t=tool.tool_id: a.active_tool() == t,
                          on_click=lambda t=tool.tool_id: a.select_tool(t))
            cells = [PenButton(p.label, key=f"SET_FALLOFF_{tool.tool_id}_{p.id}", icon=p.icon_key, icons=icons,
                            size=(30.0, 30.0), icon_only=True,
                            selected=lambda pr=prop, pid=p.id: a.wm_get(pr) == pid,
                            on_click=lambda pr=prop, pid=p.id: a.wm_set(pr, pid))
                     for p in presets]
            rows.append(Row([head, Grid(cells, columns=7, gap=3.0)], gap=12.0))
        per_tool = Column(rows + [self._hint(("Left: the tool (tap selects it); right: its falloff.",))], gap=5.0)
        edit = PenButton("Edit Custom Curve", painter=paint_curve, layout='row', size=(200.0, 30.0),
                          key='SET_EDIT_CURVE', options=MENU)
        edit.on_click = lambda: self.bar._open_curve(edit)
        return [
            self._group("Falloff per Tool", per_tool, tint, icon_falloff),
            self._group("Custom Falloff", edit, tint),
        ]

    def _page_pen(self, tint):
        a = self.a
        side = Row([TextBlock(["Default side"], size=9.5, color=(1.0, 1.0, 1.0, 0.9)),
                    self._choice('pen_bar_side', 'LEFT', "Left", size=(70.0, 26.0)),
                    self._choice('pen_bar_side', 'RIGHT', "Right", size=(70.0, 26.0))], gap=8.0)
        reset = PenButton("Reset Pen UI", painter=icon_reset, layout='row', size=(200.0, 28.0),
                           key='SET_RESET_PEN_UI', on_click=a.reset_layout)
        menu = Column([side, reset, self._hint(("Reset: default size and position of the",
                                                 "pen menu and the color selector."))], gap=6.0)
        pressure = Column([
            Row([self._toggle(f"pen_pressure_{c}", label, size=(66.0, 26.0)) for c, label in CHANNELS], gap=4.0),
            self._slider('pen_pressure_min', "Minimum pressure", fill_color=(*TINT_PEN, 1.0)),
        ], gap=6.0)
        return [
            self._group("Pen Menu", menu, tint, icon_pen),
            self._group("Pen Pressure Affects", pressure, tint, icon_pressure),
            self._group("Save Image (top right)", self._save_settings(), tint, paint_save(None)),
            self._group("How to Use", self._hint(USAGE), tint, paint_eyedropper),
        ]

    def _save_settings(self):
        """Save method, the .blend toggle and a hint for the chosen method (the folder is
        set in the Blender settings popup: the pen menu has no text input)."""
        a = self.a
        methods = Row([self._choice('save_image_method', m, label, size=(86.0, 26.0))
                       for m, label in SAVE_METHODS], gap=6.0)
        blend = self._toggle('save_image_blend', "Also save the .blend", size=(170.0, 28.0))

        def hint():
            method = a.wm_get('save_image_method', 'AUTO')
            lines = list(SAVE_HINTS.get(method, ()))
            if method == 'FILE':
                lines += [f"  {a.wm_get('save_image_folder', '') or '//'}<name>.png",
                          "(folder: settings popup; // = next to the .blend)"]
            return lines + ["Packed pixels reach the disk with the .blend."]

        return Column([methods, blend, TextBlock(hint, size=9.0, width=PAGE_WIDTH - 20.0)], gap=6.0)

    def _page_display(self, tint):
        show = self._toggle('grid_show', "Show")
        grid = self._slider('grid_opacity', "Grid opacity", size=(PAGE_WIDTH - 90.0, 24.0),
                            fill_color=(*TINT_DISPLAY, 1.0))
        hint = self._hint(("Pen menu (top right): tap the % to toggle, drag up / down to adjust.",))
        return [self._group("Pixel Grid", Column([Row([show, grid], gap=6.0), hint], gap=6.0),
                            tint, icon_grid)]

    def _page_performance(self, tint):
        from ....utils import native
        a = self.a
        toggle = self._toggle('use_native', "Use C# Backend", size=(200.0, 28.0), painter=icon_bolt)

        def status():
            if not native.available():
                return [native.status(), "Using the Python implementation."]
            if a.wm_get('use_native', True):
                return [native.status() + ": painting, filters, masks", "and selections run in C#."]
            return [native.status() + ", but disabled:", "using the Python implementation."]

        hint = self._hint(("Both backends give the same result; C# is much",
                           "faster on large textures and large brushes."))
        content = Column([toggle, TextBlock(status, size=9.0, width=PAGE_WIDTH - 20.0), hint], gap=6.0)
        return [self._group("Backend", content, tint, icon_bolt)]

    def _page_shortcuts(self, tint):
        groups = []
        all_keys = [k for _title, rows in SHORTCUTS for k, _d in rows]
        for title, rows in SHORTCUTS:
            groups.append(self._group(title, Column([_KeyRow(k, d, PAGE_WIDTH - 20.0, all_keys) for k, d in rows],
                                                    gap=2.0),
                                      tint))
        return groups
