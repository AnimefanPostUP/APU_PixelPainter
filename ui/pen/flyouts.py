"""The pen menu's flyouts: color selector header / shape / extras, the curve editor,
the Blend modes; opening and closing them.
"""


from ..kit import (
    Column, CurveEditor, Grid, Label, Row, Spacer, TextField,
)
from ..kit import clipboard
from ..kit.color_models import parse_color, to_hex
from .style import PenButton, PenFlyoutButton, PenPanel
from ...model import blend_modes, falloff
from .blend_widgets import StarButton
from .icons import (
    paint_sliders,
)
from .metrics import (
    BLEND_ENTRY_SIZE, BLEND_GROUPS, BLEND_STAR_GAP, BLEND_STAR_SIZE,
    COLOR_SHAPES, CURVE_EDITOR_SIZE, CURVE_HINTS, CURVE_MODES, CURVE_PRESET_COLUMNS,
    CURVE_PRESET_SIZE, TINT_CUSTOM,
)
from .window import HintLabel


class Flyouts:
    """Part of :class:`.bar.PenBar` (a mixin: uses its state)."""

    # ---- building ------------------------------------------------------------------

    def _build_color_header(self):
        """The color selector's top row: the old / new bubble, the Shape button (opens the
        shape popup; shows the current shape) and the button that folds the channel
        sliders out."""
        from .settings import _icon_layout   # late import: it imports this module
        a = self.actions
        labels = dict(COLOR_SHAPES)
        shape = PenButton(lambda: labels.get(a.color_layout(), "Shape"), layout='row', size=(92.0, 26.0),
                          painter=lambda dc, x, y, size, alpha: _icon_layout(a.color_layout())(dc, x, y, size, alpha),
                          key='COLOR_SHAPE', selected=lambda: self.flyout is self.shape_flyout,
                          on_click=lambda: self.toggle_flyout(self.shape_flyout, shape))
        fold = PenButton("Sliders", painter=paint_sliders, layout='icon', size=(26.0, 26.0),
                         key='COLOR_SLIDERS', selected=a.color_sliders_open, on_click=self._toggle_color_sliders)
        return Row([self.color_bubble, Spacer(6.0), shape, fold], gap=4.0)

    def _build_shape_flyout(self):
        """The color selector's shape popup (under its Shape button): Sheet, Square,
        Triangle, Wheel."""
        from .settings import _icon_layout   # late import: it imports this module
        a = self.actions

        def choose(kind):
            a.wm_set('color_selector_layout', kind)
            self.close_flyout()
            self._relayout()

        entries = [PenFlyoutButton(label, painter=_icon_layout(kind), layout='column', size=(58.0, 54.0),
                                   key=f'COLOR_SHAPE_{kind}', selected=lambda k=kind: a.color_layout() == k,
                                   on_click=lambda k=kind: choose(k))
                   for kind, label in COLOR_SHAPES]
        panel = PenPanel(Row(entries, gap=4.0), title="Shape", padding=8.0)
        panel.below_opener = True
        return panel

    def _build_color_extras(self):
        """Under the folded-out sliders: which sliders show, and the hex code (typed or
        pasted; Copy / Paste use the system clipboard)."""
        a = self.actions
        spaces = Row([PenButton(space, layout='row', size=(46.0, 18.0), font_size=8.0,
                                key=f'COLOR_SPACE_{space}',
                                selected=lambda sp=space: a.wm_flag('color_selector_sliders', sp),
                                on_click=lambda sp=space: self._toggle_color_space(sp))
                      for space in ('RGB', 'HSV', 'HSL')], gap=3.0)
        self.color_hex = TextField(lambda: to_hex(self.color_pad.rgb()), self._apply_color_text,
                                   size=(80.0, 20.0), font_size=9.0, max_length=32, key='COLOR_HEX')
        copy = PenButton("Copy", layout='row', size=(44.0, 20.0), font_size=8.0, key='COLOR_COPY',
                         on_click=lambda: clipboard.set_text(to_hex(self.color_pad.rgb())))
        paste = PenButton("Paste", layout='row', size=(44.0, 20.0), font_size=8.0, key='COLOR_PASTE',
                          on_click=lambda: self._apply_color_text(clipboard.get_text()))
        extras = Column([spaces, Row([self.color_hex, copy, paste], gap=3.0)], gap=4.0)
        extras.visible = False
        return extras

    def _set_color_option(self, name, value):
        self.actions.wm_set(name, value)
        self._relayout()

    def _toggle_color_space(self, space):
        self.actions.wm_toggle_flag('color_selector_sliders', space)
        self._relayout()

    def _toggle_color_sliders(self):
        a = self.actions
        opened = not a.color_sliders_open()
        a.wm_set('color_selector_sliders_open', opened)
        if opened and not a.color_sliders():
            a.wm_set('color_selector_sliders', {'HSV'})
        self._relayout()

    def _apply_color_text(self, text):
        """A hex code / RGB triple (typed or pasted) becomes the edited color."""
        rgb = parse_color(text)
        if rgb is not None:
            self.color_pad.set_rgb(rgb)

    def _open_curve(self, opener):
        if self.flyout is not self.curve_flyout:
            self.actions.use_custom_falloff()
        self.toggle_flyout(self.curve_flyout, opener)

    def _build_curve_flyout(self):
        """Custom falloff curve: the editor, Move / Add / Draw modes and Reset."""
        a = self.actions
        self.curve_editor = CurveEditor(a.custom_curve_points, a.set_custom_curve_points,
                                        sample=a.custom_curve_sampler, mode=lambda: self.curve_mode,
                                        size=CURVE_EDITOR_SIZE, curve_color=(*TINT_CUSTOM, 1.0),
                                        key='CURVE_EDITOR')

        def mode_button(mode, label):
            return PenButton(label, key=f"CURVE_{mode}", size=(52.0, 26.0),
                             selected=lambda: self.curve_mode == mode,
                             on_click=lambda: setattr(self, 'curve_mode', mode))

        buttons = [mode_button(mode, label) for mode, label in CURVE_MODES]
        buttons.append(PenButton("Reset", key='CURVE_RESET', size=(52.0, 26.0), on_click=a.reset_custom_curve))
        hint = HintLabel(lambda: CURVE_HINTS.get(self.curve_mode, ""), size=9.0)
        # Presets: the falloffs the Shape field does not cover, loaded into the curve.
        presets = [PenButton(label, key=f"CURVE_PRESET_{pid}", icon=falloff.get(pid).icon_key, icons=self.icons,
                             layout='column', size=CURVE_PRESET_SIZE, on_click=lambda p=pid: a.load_curve_preset(p))
                   for pid, label, _points in falloff.CURVE_PRESETS]
        return PenPanel(Column([self.curve_editor, Row(buttons, gap=4.0), hint,
                                Label("Load a preset", size=9.0),
                                Grid(presets, columns=CURVE_PRESET_COLUMNS, gap=4.0)], gap=6.0),
                        title="Custom Falloff", padding=8.0)

    def _flyout_action(self, fn):
        def _run():
            fn()
            self.close_flyout()
        return _run

    def _build_blend_flyout(self):
        """Same groups as the Shift+W blend pie, as four columns: Common, Contrast, Math,
        HSL/HSV. Each mode has a star on its right: tap it to make the mode a favorite
        (shown beside Redo in the dial) or not; a tap on the mode chooses it."""
        a = self.actions

        def choose(blend_id):
            a.set_blend(blend_id)
            self.close_flyout()

        def entry(blend_id):
            mode = PenFlyoutButton(
                blend_modes.label(blend_id), key=f"BLEND_{blend_id}", size=BLEND_ENTRY_SIZE,
                selected=lambda b=blend_id: a.active_blend() == b,
                on_click=lambda b=blend_id: choose(b))
            star = StarButton(key=f"BLEND_STAR_{blend_id}", size=BLEND_STAR_SIZE,
                               marked=lambda b=blend_id: b in a.blend_favorites(),
                               on_click=lambda b=blend_id: a.wm_toggle_flag('blend_favorites', b))
            return Row([mode, star], gap=BLEND_STAR_GAP)

        columns = []
        for title, group in (("Common", 'COMMON'),) + BLEND_GROUPS:
            columns.append(Column([Label(title, size=10.0)] + [entry(b) for b in blend_modes.ids(group)], gap=3.0))
        hint = HintLabel(lambda: "Star: favorite (shown beside Redo in the pen menu)", size=9.0)
        return PenPanel(Column([Row(columns, gap=10.0, align='top'), hint], gap=6.0),
                        title="Blend Mode", padding=8.0)

    def toggle_flyout(self, flyout, opener):
        if self.flyout is flyout:
            self.close_flyout()
            return
        self.close_flyout(relayout=False)
        flyout.visible = True
        self.flyout = flyout
        self.flyout_opener = opener
        self.root.openers[flyout] = opener
        self.overlay.layout()

    def close_flyout(self, relayout=True):
        for flyout in self.root.flyouts:
            flyout.visible = False
        self.window_ring.visible = False
        self.flyout = None
        self.flyout_opener = None
        if relayout:
            self.overlay.layout()
