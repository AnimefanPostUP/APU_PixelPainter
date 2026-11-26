"""TextField: a single-line input box (numbers, color codes).

A tap starts editing with the whole text selected (typing replaces it). While
editing the field has the keyboard focus of its :class:`~.overlay.Overlay`:

* typing inserts (only ``allowed`` characters, when given); Backspace / Delete,
  Left / Right / Home / End move and delete; Ctrl+A selects all, Ctrl+C / X / V
  copy, cut and paste (the system clipboard, :mod:`.clipboard`).
* Enter, Tab (also moves on to the next field) or a press elsewhere commit:
  ``on_commit(text)``; Esc or a right click cancel.

Not editing, the field shows ``text`` (a str or a callable, re-read every frame).
"""

from . import clipboard, draw
from .geometry import Rect
from .theme import mix, with_alpha
from .widget import Widget, _resolve


NUMBER_CHARS = "0123456789.,+-°%"
HEX_CHARS = "#0123456789abcdefABCDEFxX ,;()rgbRGB."


class TextField(Widget):
    """``text``: shown value (str or callable); ``on_commit(text)``: the edited text.
    ``size``: unscaled (w, h); ``font_size`` unscaled; ``scale`` an extra factor
    (hosts that scale their content, e.g. the color selector's fit-to-width)."""

    interactive = True
    takes_focus = True

    def __init__(self, text, on_commit, *, size=(60.0, 18.0), font_size=9.0, allowed=None,
                 max_length=40, **kwargs):
        kwargs.setdefault('keep_open', True)
        super().__init__(**kwargs)
        self.text_binding = text
        self.on_commit = on_commit
        self.size = size
        self.font_size = font_size
        self.allowed = allowed
        self.max_length = max_length
        self.scale = 1.0
        self.editing = False
        self.text = ""
        self.caret = 0
        self.select_all = False

    # ---- layout ------------------------------------------------------------------

    def measure(self, theme):
        return theme.px(self.size[0]) * self.scale, theme.px(self.size[1]) * self.scale

    # ---- editing -----------------------------------------------------------------

    def shown_text(self):
        return self.text if self.editing else str(_resolve(self.text_binding, "") or "")

    def activate(self):
        if not self.editing:
            self.begin_edit()

    def begin_edit(self):
        self.text = str(_resolve(self.text_binding, "") or "")
        self.caret = len(self.text)
        self.select_all = True
        self.editing = True

    def end_edit(self, commit=True):
        if not self.editing:
            return
        self.editing = False
        self.select_all = False
        if commit and self.on_commit is not None:
            self.on_commit(self.text)

    def _insert(self, chars):
        if self.allowed is not None:
            chars = "".join(c for c in chars if c in self.allowed)
        chars = chars.replace("\n", " ").replace("\r", "")
        if not chars:
            return
        if self.select_all:
            self.text, self.caret, self.select_all = "", 0, False
        room = max(0, self.max_length - len(self.text))
        chars = chars[:room]
        self.text = self.text[:self.caret] + chars + self.text[self.caret:]
        self.caret += len(chars)

    def key_input(self, event):
        """A keyboard event while editing (presses act; releases are only swallowed)."""
        if event.value != 'PRESS':
            return
        t = event.type
        if t in {'RET', 'NUMPAD_ENTER'}:
            self.end_edit(commit=True)
        elif t == 'ESC':
            self.end_edit(commit=False)
        elif t == 'BACK_SPACE':
            if self.select_all:
                self.text, self.caret, self.select_all = "", 0, False
            elif event.ctrl:
                self.text, self.caret = self.text[self.caret:], 0
            elif self.caret > 0:
                self.text = self.text[:self.caret - 1] + self.text[self.caret:]
                self.caret -= 1
        elif t == 'DEL':
            if self.select_all:
                self.text, self.caret, self.select_all = "", 0, False
            else:
                self.text = self.text[:self.caret] + self.text[self.caret + 1:]
        elif t in {'LEFT_ARROW', 'RIGHT_ARROW', 'HOME', 'END'}:
            if self.select_all:
                self.caret = 0 if t in {'LEFT_ARROW', 'HOME'} else len(self.text)
                self.select_all = False
            elif t == 'LEFT_ARROW':
                self.caret = max(0, self.caret - 1)
            elif t == 'RIGHT_ARROW':
                self.caret = min(len(self.text), self.caret + 1)
            else:
                self.caret = 0 if t == 'HOME' else len(self.text)
        elif event.ctrl and t == 'A':
            self.select_all = True
            self.caret = len(self.text)
        elif event.ctrl and t in {'C', 'X'}:
            clipboard.set_text(self.text)
            if t == 'X':
                self.text, self.caret, self.select_all = "", 0, False
        elif event.ctrl and t == 'V':
            self._insert(clipboard.get_text().strip())
        elif event.unicode and not event.ctrl and not event.alt and event.unicode.isprintable():
            self._insert(event.unicode)

    # ---- drawing -----------------------------------------------------------------

    def draw_self(self, dc):
        theme = dc.theme
        r = self.rect
        if r.width <= 1.0 or r.height <= 1.0:
            return
        alpha = dc.alpha * (1.0 if self.is_enabled else theme.disabled_alpha)
        radius = min(theme.px(5.0) * self.scale, r.height * 0.5)
        if self.editing:
            fill = theme.surface_dark
        else:
            fill = mix(theme.surface_dark, theme.surface_hover, self.hover_t * 0.8)
        draw.rounded_rect(r, radius, with_alpha(fill, alpha), rim=theme.edge_for(fill, alpha))
        if self.editing or self.hover_t > 0.01:
            amount = 1.0 if self.editing else self.hover_t
            draw.rounded_rect_outline(r, radius, with_alpha(theme.accent, amount * alpha),
                                      width=theme.px(1.2))

        size = theme.px(self.font_size) * self.scale
        text = self.shown_text()
        tw = draw.text_size(text, size, theme.font_id)[0] if text else 0.0
        x0 = r.cx - tw * 0.5
        if self.editing and self.select_all and text:
            pad = theme.px(1.5)
            draw.rect(Rect(x0 - pad, r.cy - size * 0.65, x0 + tw + pad, r.cy + size * 0.65),
                      with_alpha(theme.accent, 0.55 * alpha))
        if text:
            draw.text_centered(text, r.cx, r.cy, size, with_alpha(theme.text, 0.95 * alpha), theme.font_id)
        if self.editing and not self.select_all:   # steady caret: the host redraws on events only
            before = draw.text_size(text[:self.caret], size, theme.font_id)[0] if self.caret else 0.0
            cx = x0 + before + theme.px(0.5)
            draw.polyline([(cx, r.cy - size * 0.6), (cx, r.cy + size * 0.6)],
                          with_alpha(theme.text, alpha), max(1.0, theme.px(1.0)))
