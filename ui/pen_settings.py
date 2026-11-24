"""Pen settings: the settings flyout of the pen menu (its *Settings* gear), built
from UI-kit widgets like the curve flyout -- usable with a pen, no Blender popup.

Layout: a row of icon tabs and the tab's name, then the tab's page: groups of
related controls (:class:`~.kit.Group`), each page in its own color. The tabs
and the settings are the ones of the Blender settings popup
(:mod:`.settings_menu`, still used by the N-panel / tool header) and share its
remembered tab (``pixel_painter_settings_tab``).

Values are read and written through the pen menu's actions
(:class:`tools.pen_bar.PenBarTool`: ``wm_get`` / ``wm_set`` / ``wm_toggle_flag``
/ ``wm_range`` for ``pixel_painter_*`` properties).
"""

import colorsys
import math

from .kit import Button, Column, Grid, Group, IconButton, Panel, Rect, Row, Slider, TextBlock, Widget
from .kit import draw
from .kit.form import text_left
from .kit.theme import with_alpha
from .kit.widget import _resolve
from ..tools import blend_modes, falloff
from .pen_bar import (TINT_FALLOFF, TINT_MODES, TINT_TOOLS, _paint_color_wheel, _paint_curve,
                      _paint_eyedropper, _paint_save, _thick_line)


PAGE_WIDTH = 300.0       # unscaled width of every group
TAB_SIZE = (38.0, 38.0)
TINT_COLOR = (0.95, 0.45, 0.65)
TINT_PEN = (0.66, 0.44, 0.92)
TINT_DISPLAY = (0.55, 0.70, 0.85)
TINT_KEYS = (0.85, 0.80, 0.45)

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
    "Curve (beside Custom): edit / draw the falloff",
    "RMB: the pen paints the secondary color",
    "Save (top right): saves the image; dot = unsaved",
)
SAVE_METHODS = (('AUTO', "Auto"), ('PACK', "Pack"), ('FILE', "File"))
SAVE_HINTS = {
    'AUTO': ("Repacks a packed image, saves an image with a file",
             "to it, packs anything else (e.g. a new image)."),
    'PACK': ("Always packs the image into the .blend.",),
    'FILE': ("Always writes a file; images without one go to:",),
}


# ---- icons: painter(dc, x, y, size, alpha) ------------------------------------------------

def _ink(dc, alpha, amount=0.92):
    return with_alpha(dc.theme.text, amount * alpha)


def _icon_brush(dc, x, y, size, alpha):
    s = size * 0.6
    color = _ink(dc, alpha)
    _thick_line((x + s * 0.45, y + s * 0.45), (x - s * 0.05, y - s * 0.05), s * 0.13, color)
    draw.circle(x - s * 0.22, y - s * 0.22, s * 0.24, color, segments=16)


def _icon_blend(dc, x, y, size, alpha):
    r = size * 0.24
    draw.circle(x - r * 0.45, y, r, (0.15, 0.15, 0.15, alpha), segments=20)
    draw.circle(x + r * 0.45, y, r, (1.0, 1.0, 1.0, 0.7 * alpha), segments=20)
    draw.circle_outline(x - r * 0.45, y, r, _ink(dc, alpha, 0.6), width=1.0, segments=20)


def _icon_falloff(dc, x, y, size, alpha):
    _paint_curve(dc, x, y, size * 1.2, alpha)


def _icon_pen(dc, x, y, size, alpha):
    s = size * 0.6
    color = _ink(dc, alpha)
    ux = uy = math.sqrt(0.5)
    tip = (x - ux * s * 0.5, y - uy * s * 0.5)
    base = (x - ux * s * 0.2, y - uy * s * 0.2)
    _thick_line(base, (x + ux * s * 0.5, y + uy * s * 0.5), s * 0.22, color)
    draw.triangle(tip, (base[0] - uy * s * 0.11, base[1] + ux * s * 0.11),
                  (base[0] + uy * s * 0.11, base[1] - ux * s * 0.11), color)


def _icon_eye(dc, x, y, size, alpha):
    w, h = size * 0.34, size * 0.2
    color = _ink(dc, alpha)
    top = [(x - w + 2 * w * i / 16, y + h * math.sin(math.pi * i / 16)) for i in range(17)]
    bottom = [(px, y - (py - y)) for px, py in top]
    draw.polyline(top, color, 1.5)
    draw.polyline(bottom, color, 1.5)
    draw.circle(x, y, h * 0.7, color, segments=16)


def _icon_keyboard(dc, x, y, size, alpha):
    w, h = size * 0.36, size * 0.22
    color = _ink(dc, alpha)
    draw.rect_outline(Rect(x - w, y - h, x + w, y + h), color, width=1.5)
    k = w * 0.22
    for row, keys in ((0.35, 5), (-0.15, 5)):
        for i in range(keys):
            kx = x - w + w * 2.0 * (i + 0.5) / keys
            draw.rect(Rect.from_center(kx, y + h * row, k, k * 0.8), color)
    draw.rect(Rect.from_center(x, y - h * 0.6, w * 1.1, k * 0.7), color)


def _icon_reset(dc, x, y, size, alpha):
    r = size * 0.28
    color = _ink(dc, alpha)
    draw.arc(x, y, r, math.radians(60), math.radians(360), color, width=max(1.0, size * 0.07), segments=24)
    hx, hy = x + math.cos(math.radians(60)) * r, y + math.sin(math.radians(60)) * r
    head = r * 0.5
    draw.triangle((hx + head * 0.9, hy + head * 0.1), (hx - head * 0.3, hy + head * 0.7),
                  (hx - head * 0.1, hy - head * 0.6), color)


def _icon_pressure(dc, x, y, size, alpha):
    color = _ink(dc, alpha)
    w = size * 0.1
    for i, h in enumerate((0.25, 0.45, 0.65)):
        bx = x + (i - 1) * w * 1.7
        draw.rect(Rect(bx - w * 0.5, y - size * 0.3, bx + w * 0.5, y - size * 0.3 + size * h), color)


def _icon_grid(dc, x, y, size, alpha):
    w = size * 0.3
    color = _ink(dc, alpha, 0.8)
    for i in range(4):
        t = -w + 2.0 * w * i / 3.0
        draw.polyline([(x + t, y - w), (x + t, y + w)], color, 1.0)
        draw.polyline([(x - w, y + t), (x + w, y + t)], color, 1.0)


def _icon_layout(kind):
    """Color selector layout glyphs: Sheet, Square, Triangle, Wheel."""
    def paint(dc, x, y, size, alpha):
        s = size * 0.36
        if kind == 'SHEET':
            steps = 12
            for i in range(steps):
                c = colorsys.hsv_to_rgb(i / steps, 1.0, 1.0)
                cell = Rect(x - s + 2 * s * i / steps, y - s * 0.7, x - s + 2 * s * (i + 1) / steps, y + s * 0.7)
                draw.gradient_quad(cell, (0, 0, 0, alpha), (0, 0, 0, alpha), (*c, alpha), (*c, alpha))
        elif kind == 'SQUARE':
            r = Rect(x - s * 0.8, y - s * 0.8, x + s * 0.8, y + s * 0.8)
            draw.gradient_quad(r, (0, 0, 0, alpha), (0, 0, 0, alpha), (1, 0.1, 0.1, alpha), (1, 1, 1, alpha))
        elif kind == 'TRIANGLE':
            for i in range(24):
                c = colorsys.hsv_to_rgb(i / 24, 1.0, 1.0)
                draw.sector(x, y, s, math.tau * i / 24, math.tau * (i + 1) / 24, (*c, alpha), segments=2)
            draw.circle(x, y, s * 0.75, with_alpha(dc.theme.surface_dark, alpha), segments=24)
            p = [(x + math.cos(a) * s * 0.7, y + math.sin(a) * s * 0.7)
                 for a in (math.radians(90), math.radians(210), math.radians(330))]
            draw.shaded_tris(p, [(1, 0.1, 0.1, alpha), (0, 0, 0, alpha), (1, 1, 1, alpha)])
        else:
            for i in range(24):
                c = colorsys.hsv_to_rgb(i / 24, 1.0, 1.0)
                draw.sector(x, y, s, math.tau * i / 24, math.tau * (i + 1) / 24, (*c, alpha), segments=2)
            draw.circle(x, y, s * 0.35, (1, 1, 1, 0.8 * alpha), segments=16)
    return paint


TABS = (
    ('COLOR', "Color Selector", TINT_COLOR, _paint_color_wheel(None)),
    ('TOOLS', "Tools", TINT_TOOLS, _icon_brush),
    ('BLENDING', "Blending", TINT_MODES, _icon_blend),
    ('FALLOFF', "Falloff", TINT_FALLOFF, _icon_falloff),
    ('PEN', "Pen", TINT_PEN, _icon_pen),
    ('DISPLAY', "Display", TINT_DISPLAY, _icon_eye),
    ('SHORTCUTS', "Shortcuts", TINT_KEYS, _icon_keyboard),
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
        draw.rect(cap, with_alpha(theme.surface_pressed, dc.alpha))
        draw.rect_outline(cap, with_alpha(theme.border, dc.alpha), width=1.0)
        draw.text_centered(self.keys, cap.cx, cap.cy, size, with_alpha(theme.text, dc.alpha), theme.font_id)
        column = max(draw.text_size(k, size, theme.font_id)[0] for k in self.all_keys) + pad * 2.0 + theme.px(10.0)
        text_left(self.action, r.x0 + column, r.cy, size,
                  with_alpha(theme.text_muted, dc.alpha), theme.font_id)


# ---- the flyout -------------------------------------------------------------------------

class SettingsMenu:
    """Builds the settings flyout panel (``self.panel``) for a :class:`ui.pen_bar.PenBar`."""

    def __init__(self, bar):
        self.bar = bar
        self.a = bar.actions
        tabs = [IconButton(label, painter=painter, layout='icon', size=TAB_SIZE, key=f"SETTINGS_TAB_{tab_id}",
                           selected=lambda t=tab_id: self.current() == t,
                           on_click=lambda t=tab_id: self.select(t))
                for tab_id, label, _tint, painter in TABS]
        title = TextBlock(lambda: [self._tab(self.current())[1]], size=13.0, color=(1.0, 1.0, 1.0, 1.0),
                          width=PAGE_WIDTH)
        pages = _Pages([(tab_id, self._page(tab_id, tint)) for tab_id, _label, tint, _p in TABS], self.current)
        self.panel = Panel(Column([Row(tabs, gap=4.0), title, pages], gap=8.0), padding=8.0)
        self.panel.key = 'SETTINGS_FLYOUT'

    # ---- tabs ------------------------------------------------------------------------

    def current(self):
        return self.a.wm_get('settings_tab', TABS[0][0])

    def select(self, tab_id):
        self.a.wm_set('settings_tab', tab_id)
        self.bar.overlay.layout()

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
        return Group(title, content, tint=tint, painter=painter, width=PAGE_WIDTH)

    def _choice(self, prop, value, label, size=(64.0, 26.0), painter=None, layout='row'):
        """Button selecting ``value`` of the enum ``prop``."""
        a = self.a
        return IconButton(label, painter=painter, layout=layout, size=size,
                          key=f"SET_{prop}_{value}".upper(),
                          selected=lambda: a.wm_get(prop) == value, on_click=lambda: a.wm_set(prop, value))

    def _toggle(self, prop, label, size=(64.0, 26.0), painter=None):
        a = self.a
        return IconButton(label, painter=painter, layout='row', size=size, key=f"SET_{prop}".upper(),
                          selected=lambda: bool(a.wm_get(prop)), on_click=lambda: a.wm_set(prop, not a.wm_get(prop)))

    def _flag(self, prop, item, label, size=(64.0, 26.0)):
        a = self.a
        return IconButton(label, layout='row', size=size, key=f"SET_{prop}_{item}".upper(),
                          selected=lambda: a.wm_flag(prop, item), on_click=lambda: a.wm_toggle_flag(prop, item))

    def _slider(self, prop, label, size=(PAGE_WIDTH - 20.0, 24.0), **kwargs):
        """Slider for the number property ``prop`` (a callable for per-tool names)."""
        a = self.a
        name = prop if callable(prop) else (lambda: prop)
        is_int = lambda: a.wm_range(name())[2]

        def set_value(v):
            a.wm_set(name(), int(round(v)) if is_int() else v)

        return Slider(label, lambda: a.wm_get(name(), 0.0) or 0.0, set_value,
                      value_range=lambda: a.wm_range(name())[:2], size=size, **kwargs)

    @staticmethod
    def _hint(lines):
        return TextBlock(list(lines), size=9.0, width=PAGE_WIDTH - 20.0)

    # ---- pages -------------------------------------------------------------------------

    def _page_color(self, tint):
        a = self.a
        layouts = Row([self._choice('color_selector_layout', kind, label, size=(64.0, 58.0),
                                    painter=_icon_layout(kind), layout='column')
                       for kind, label in (('SHEET', "Sheet"), ('SQUARE', "Square"),
                                           ('TRIANGLE', "Triangle"), ('WHEEL', "Wheel"))], gap=6.0)
        model = Row([self._choice('color_selector_model', m, m, size=(130.0, 26.0)) for m in ('HSV', 'HSL')], gap=6.0)
        none = IconButton("None", layout='row', size=(62.0, 26.0), key='SET_SLIDERS_NONE',
                          selected=lambda: not a.wm_get('color_selector_sliders'),
                          on_click=lambda: a.wm_set('color_selector_sliders', set()))
        sliders = Row([none] + [self._flag('color_selector_sliders', s, s, size=(62.0, 26.0))
                                for s in ('RGB', 'HSV', 'HSL')], gap=6.0)
        preview = Column([self._toggle('pen_color_preview', "Preview only", size=(150.0, 28.0), painter=_icon_eye),
                          self._hint(("On: the selector only previews; tap the old / new",
                                      "bubble to apply. Off: applies when the pen lifts."))], gap=6.0)
        def clear_active():
            pal = a.active_palette()
            if pal is None or not any(pal["colors"]):
                return
            self.bar.confirm([f"Remove all colors of “{pal['name']}”?"], a.clear_palette, "Clear")

        palette = Column([
            Row([self._toggle('pen_color_drag', "Drag & drop colors", size=(170.0, 28.0)),
                 IconButton("Clear palette", painter=_icon_reset, layout='row', size=(110.0, 28.0),
                            key='SET_CLEAR_PALETTE', on_click=clear_active)], gap=6.0),
            self._hint(("Palettes are saved in the .blend (per project); the",
                        "Library button imports / exports them (palettes.json).",
                        "Drag colors onto palette slots or the primary / secondary",
                        "color; in the palette view, drag whole palettes.",
                        "Tap an empty slot: store the current color.")),
        ], gap=6.0)
        return [
            self._group("Layout", layouts, tint, _paint_color_wheel(None)),
            self._group("Color Model", model, tint),
            self._group("Channel Sliders", sliders, tint),
            self._group("Pen Color Selector", preview, tint, _icon_eye),
            self._group("Palette (bottom-left corner)", palette, tint),
        ]

    def _page_tools(self, tint):
        a = self.a
        tools = Grid([Button(tool.label, key=f"SET_TOOL_{tool.tool_id}", icon=tool.tool_id if tool.icon else None,
                             icons=self.bar.icons, size=(44.0, 44.0), icon_only=True,
                             selected=lambda t=tool.tool_id: a.active_tool() == t,
                             on_click=lambda t=tool.tool_id: a.select_tool(t))
                      for tool in a.tools()], columns=4, gap=6.0)
        rows = []
        for channel, label in CHANNELS:
            use_global = lambda c=channel: f"{a.active_tool()}_use_global_{c}"
            value = lambda c=channel: f"{a.active_tool()}_{c}"
            toggle = IconButton("Global", layout='row', size=(62.0, 24.0), key=f"SET_GLOBAL_{channel}".upper(),
                                selected=lambda g=use_global: bool(a.wm_get(g())),
                                on_click=lambda g=use_global: a.wm_set(g(), not a.wm_get(g())))
            slider = self._slider(value, label, size=(PAGE_WIDTH - 90.0, 24.0), fill_color=(*TINT_TOOLS, 1.0),
                                  enabled=lambda g=use_global: not a.wm_get(g(), True),
                                  step=1 if channel == 'size' else None, key=f"SET_VALUE_{channel}".upper())
            rows.append(Row([toggle, slider], gap=6.0))
        rows.append(self._hint(("Global: the tool uses the shared value.",)))
        per_tool = Column(rows, gap=5.0)
        reset = IconButton("Reset Tool Settings", painter=_icon_reset, layout='row', size=(200.0, 28.0),
                           key='SET_RESET_TOOLS', on_click=a.reset_tool_settings)
        title = lambda: f"Per-Tool Settings: {self._tool_label(a.active_tool())}"
        return [
            self._group("Tool", tools, tint, _icon_brush),
            self._group(title, per_tool, tint),
            self._group("Reset", reset, tint, _icon_reset),
        ]

    def _tool_label(self, tool_id):
        return next((t.label for t in self.a.tools() if t.tool_id == tool_id), str(tool_id))

    def _page_blending(self, tint):
        a = self.a
        active = Column([TextBlock(lambda: [blend_modes.label(a.active_blend())], size=12.0,
                                   color=(1.0, 1.0, 1.0, 1.0), width=PAGE_WIDTH - 20.0),
                         self._hint(("Change it with Blend in the pen menu.",))], gap=4.0)
        groups = [self._group("Active Blend Mode", active, tint, _icon_blend)]
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
            head = Button(tool.label, key=f"SET_FALLOFF_TOOL_{tool.tool_id}", icon=tool.tool_id if tool.icon else None,
                          icons=icons, size=(30.0, 30.0), icon_only=True,
                          selected=lambda t=tool.tool_id: a.active_tool() == t,
                          on_click=lambda t=tool.tool_id: a.select_tool(t))
            cells = [Button(p.label, key=f"SET_FALLOFF_{tool.tool_id}_{p.id}", icon=p.icon_key, icons=icons,
                            size=(30.0, 30.0), icon_only=True,
                            selected=lambda pr=prop, pid=p.id: a.wm_get(pr) == pid,
                            on_click=lambda pr=prop, pid=p.id: a.wm_set(pr, pid))
                     for p in presets]
            rows.append(Row([head, Grid(cells, columns=6, gap=3.0)], gap=12.0))
        per_tool = Column(rows + [self._hint(("Left: the tool (tap selects it); right: its falloff.",))], gap=5.0)
        edit = IconButton("Edit Custom Curve", painter=_paint_curve, layout='row', size=(200.0, 30.0),
                          key='SET_EDIT_CURVE')
        edit.on_click = lambda: self.bar._open_curve(edit)
        return [
            self._group("Falloff per Tool", per_tool, tint, _icon_falloff),
            self._group("Custom Falloff", edit, tint),
        ]

    def _page_pen(self, tint):
        a = self.a
        side = Row([TextBlock(["Default side"], size=9.5, color=(1.0, 1.0, 1.0, 0.9)),
                    self._choice('pen_bar_side', 'LEFT', "Left", size=(70.0, 26.0)),
                    self._choice('pen_bar_side', 'RIGHT', "Right", size=(70.0, 26.0))], gap=8.0)
        reset = IconButton("Reset Pen UI", painter=_icon_reset, layout='row', size=(200.0, 28.0),
                           key='SET_RESET_PEN_UI', on_click=a.reset_layout)
        menu = Column([side, reset, self._hint(("Reset: default size and position of the",
                                                 "pen menu and the color selector."))], gap=6.0)
        pressure = Column([
            Row([self._toggle(f"pen_pressure_{c}", label, size=(66.0, 26.0)) for c, label in CHANNELS], gap=4.0),
            self._slider('pen_pressure_min', "Minimum pressure", fill_color=(*TINT_PEN, 1.0)),
        ], gap=6.0)
        return [
            self._group("Pen Menu", menu, tint, _icon_pen),
            self._group("Pen Pressure Affects", pressure, tint, _icon_pressure),
            self._group("Save Image (top right)", self._save_settings(), tint, _paint_save(None)),
            self._group("How to Use", self._hint(USAGE), tint, _paint_eyedropper),
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
        grid = self._slider('grid_opacity', "Grid opacity", fill_color=(*TINT_DISPLAY, 1.0))
        return [self._group("Pixel Grid", Column([grid, self._hint(("0: hidden, 100%: fully opaque.",))], gap=6.0),
                            tint, _icon_grid)]

    def _page_shortcuts(self, tint):
        groups = []
        all_keys = [k for _title, rows in SHORTCUTS for k, _d in rows]
        for title, rows in SHORTCUTS:
            groups.append(self._group(title, Column([_KeyRow(k, d, PAGE_WIDTH - 20.0, all_keys) for k, d in rows],
                                                    gap=2.0),
                                      tint))
        return groups
