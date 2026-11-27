"""Pen UI: on-screen controls made for pens / tablets -- the pen menu (a dial) and
the color selector, two floating elements.

Pens often cannot move the pointer without touching (no reliable hover), so
everything here works with press, drag and release only.

* **Floating elements**: the pen menu and the color selector are moved by
  dragging their empty background and resized by dragging the triangle in
  their bottom-right corner (each has its own size: pen menu 0.2x .. 2x,
  color selector 0.5x .. 2x, and never larger than the editor). The padlock
  (pen menu: bottom-left corner; color selector: top left) locks both. They are clipped to the editor
  borders (and an overlapping sidebar). Size and position are remembered;
  *Reset Pen UI* (settings popup, N-panel) restores the defaults: the pen
  menu in the bottom corner at the chosen side, the color selector beside it.
  The *X* in the top-right corner collapses the pen menu to a *Pen* tab /
  closes the color selector.
* **Pen menu** (:class:`~.kit.Dial`): everything around the *Size* knob in
  the center, as pie segments in two rings; categories are separated by a
  wider gap with a divider line:

  - top right: *S* / *A* / *M* (Strength, Alpha, Modifier) radial sliders,
    as deep as both rings: press sets the value from the distance to the
    center, drag keeps setting it; outside them, along the circle, the color
    history (the last painted colors, newest at the top; tap paints with it);
  - top left: the tools (half in each ring; tap selects);
  - bottom: *Undo* / *Redo* arrows (inner ring); outside them (outer ring)
    the favorite blend modes (tap: paint with it) in rows, names written
    across (upright);
  - bottom right: the falloff -- the *falloff field* (the Shape falloff, swiped
    like the color selector: toward the center = hard, outward = soft; the
    upper end = linear fade, the lower end = sharp; a swipe moves along two
    fixed straight axes -- a cross through the field's middle -- not along the
    arc; a tap jumps; while pressed the cursor is hidden and kept on the marker;
    quarter preview discs in its corners, the marker is a cross; the current falloff
    curve is drawn in the field, from the outer line (full strength) toward the inner
    side; plain gray, only the outer band marks it as selected)
    in the outer ring and the inner ring's outer half; *Custom* (in its own
    color) and *Curve* in the inner ring's inner half.

  The corners of the square around the circle are buttons shaped to fit
  between the circle and the square (icons). Top left the color section: the
  *gradient slider* along the circle (primary at the left end, secondary at the
  top; press / drag picks the optional *tertiary color* on it and selects it --
  the pen tip then paints with it), the secondary and primary color (tap a
  color: the pen paints with it -- the secondary one sets the RMB lock; the
  color buttons have round corners), each with its own
  *Picker* on its outer side (eyedropper for that color: arms it for the next canvas
  press; the picker of the color the selector edits is bright, the other grey), and
  between them *Swap* with the *tertiary bubble* behind it toward the corner (shows
  the tertiary color; tap: selects it / back to the color before). With the
  tertiary color selected, the color selector still edits the primary or the
  secondary color: that one has a dotted outline, a tap on the other switches.
  bottom right the palette band (24 slots in two bands along the circle) and,
  in the gap right of the circle (centered on the right), *Palettes* (switches
  the band between the active palette's colors and the project's 24 palettes);
  bottom left, a capsule (an arc band with round ends) along the circle: *Windows* (opens the Windows ring on the press), *Save* (saves /
  packs the painted image as set in settings > Pen > Save Image; a green dot
  while it has unsaved changes) and the pixel *Grid* (opacity %; tap: on / off,
  drag up / down: opacity) and, ending at the bottom, *Blend* (opens the
  flyout; a dark-to-light gray gradient with the mode's name). Top right, past the color history, a
  capsule with *Pixel* / *Free* (spacing) and *Alphalock* (protect transparent pixels).
* **Palettes** are stored per project (in the .blend); the library window
  (``ui/pen/windows/palettes.py``) imports / exports them to ``palettes.json`` and the
  clipboard -- project and library are not synced. *From image...* turns an
  image file's pixel colors into a new project palette.
* **Drag & drop** (setting *Drag Colors*): drag the primary / secondary color,
  the tertiary bubble, a history color, a palette color or the color selector's old / new bubble (a
  short press stays a tap). Drop it on a palette slot to store it (palette onto
  palette: the two swap), on the primary / secondary color to set it; drop a
  palette color off the menu to remove it. In the palette view, palettes are
  dragged the same way: onto another slot (swap), into the library list
  (saved there), from the library onto a slot (loaded; replacing a palette
  asks first); a project palette dropped off the menu is deleted after a
  confirmation. Tap an empty palette slot to store the current color; tap a
  palette color to paint with it.
* **Curve flyout**: the custom falloff curve (the brush's falloff curve; x =
  distance from the center, y = weight). *Move*: drag anchors, drag one out of
  the box to remove it; *Add*: a tap adds an anchor; *Draw*: draw the falloff
  freehand, it becomes anchors on release; *Reset*: a smooth fade. The
  preset buttons load the falloffs the field does not cover (Smooth, Sphere,
  Root, Plateau, Stepped, Ring, Inverted) into the curve.
* **Size knob**: press and drag up / down; the value changes relative to
  where the drag started. A readout -- for Size with a preview of the brush
  footprint -- shows beside the menu while a knob or slider is dragged. Pens
  cannot scroll, so the knob and sliders stand in for the wheel.
* **Color selector** (:class:`~.kit.ColorSelector`): the row at the top holds the
  old / new bubble, the Shape button (a popup: Sheet, Square, Triangle, Wheel) and the
  sliders button, which folds out the RGB / HSV / HSL channel sliders (each
  with an input field), their toggles and a hex field with Copy / Paste. The
  model (HSV / HSL) comes from the settings (Color Selector tab). Every part is swiped
  like a touchpad; a tap jumps. It edits the color the pen paints (secondary
  with the RMB lock; with the tertiary color selected, the dotted one). The change applies when the pen is lifted; the color
  from before editing stays marked with a cross and shows in the old / new
  bubble at the top until the bubble is tapped (accept: the new color becomes
  the reference). With *Preview* on (settings popup, Color Selector tab) the
  selector only previews: the brush keeps its color (marked with the cross)
  and the picked one shows in the bubble until the bubble is tapped, which
  applies it.
* **Windows ring**: the Windows corner button's popup, a full ring over the
  inner ring (around the Size knob; while open a backdrop hides both rings,
  the tools too):
  *Settings* (the settings flyout), *Mask* / *View* (their windows), *Color*
  (the color selector), *Palettes* (the palette library) and *Extras* (Fill /
  Edges / Ambient Occlusion on UV islands or mesh parts). Opened by the
  *press* like a flyout: keep the pen down, drag onto an entry and lift -- or
  lift anywhere and tap an entry. A tap outside or on Windows closes it.
* **Flyout** (Blend): opened by the *press*. Keep the pen down, drag
  onto an entry and lift -- or lift anywhere and tap an entry. A tap outside
  closes the flyout. Columns Common / Contrast / Math / HSL/HSV; a star right of
  each mode marks / unmarks it as a favorite (gold while it is one; the flyout
  stays open).
* **Look**: the windows and flyouts share the pen style (``ui/pen/style.py``):
  neutral grays, one accent color, rounded shapes, titles on plates.

This module builds, lays out and draws the widgets (two non-modal UI-kit
layers). :class:`tools.pen.tool.PenBarTool` forwards events and provides the
``actions`` object the widgets call.
"""


from ..kit import ColorSelector, Column, Overlay, RoundButton, Spacer
from ..kit import draw
from ..kit.events import PRESS, RUNNING
from .widgets.color import BubbleDrag
from .icons.menu import paint_color_wheel, paint_gear
from .metrics import SHAPE_PAD, TOOL_WINDOWS, POINTER_TYPES
from .windows.frame import CornerButton, MenuLayer
from .menu.dial import DialControls
from .menu.flyouts import Flyouts
from .menu.drag_drop import ColorDragDrop
from .menu.window_layout import WindowLayout
from .windows.dialog import ConfirmDialog
from .windows.extras import build_extras_window
from .windows.mask import build_mask_window
from .icons.palettes import paint_library
from .windows.palettes import PaletteLibrary
from .windows.settings import SettingsMenu
from .windows.shapes import dial_star
from .windows.parts import body_shapes, build_body_window, window_shapes
from .windows.view import build_view_window
from .menu.readouts import Readouts


def _is_inside(widget, ancestor):
    while widget is not None:
        if widget is ancestor:
            return True
        widget = widget.parent
    return False



class PenBar(DialControls, Flyouts, ColorDragDrop, WindowLayout, Readouts):
    """Widget layers of the pen menu and the color selector.
    ``actions`` is the :class:`tools.pen.tool.PenBarTool`."""

    def __init__(self, actions):
        from ..icons.tool_icons import ICONS  # late import: ui.icons imports the tool catalog
        self.actions = actions
        self.icons = ICONS
        self.flyout = None          # open flyout panel
        self.flyout_opener = None
        self._drag = None           # (channel, value at drag start) while a knob / slider is dragged
        self._move = None           # (element, stored pos, top-left, size) while an element is moved
        self._resize = None         # (element, scale, width, height, top-left, stored pos) while resized
        self._args = None           # the last layout() arguments
        self.drag_preview = None    # (rgb, x, y, source) while a color is dragged
        self.bounds = (0.0, 0.0, 0.0, 0.0)
        self.knobs = {}
        self.arm_buttons = {}

        # Pen menu.
        self.blend_flyout = self._build_blend_flyout()
        self.blend_flyout.visible = False
        self.curve_mode = 'MOVE'
        self.curve_flyout = self._build_curve_flyout()
        self.curve_flyout.visible = False
        self.shape_flyout = self._build_shape_flyout()
        self.shape_flyout.visible = False
        self.settings_menu = SettingsMenu(self)
        self.library_menu = PaletteLibrary(self)
        self.confirm_dialog = ConfirmDialog(self)
        tab = RoundButton("Pen", radius=17.0, key='PEN_TAB', on_click=lambda: self.set_collapsed(False))
        self.menu = self._window('bar', self._build_dial(),
                                 CornerButton('CLOSE', key='HIDE', on_click=lambda: self.set_collapsed(True)),
                                 tab=tab, lock_bottom=True,   # top left: the tertiary bubble
                                 shape=lambda panel, theme: [dial_star(panel.content, theme.px(SHAPE_PAD))])
        self.root = MenuLayer(self.menu, [self.blend_flyout, self.curve_flyout, self.shape_flyout],
                               self.confirm_dialog.panel)
        self.overlay = Overlay(self.root, modal=False, animate=False)

        # Color selector.
        a = actions
        self.color_pad = ColorSelector(a.pen_hsv, a.set_pen_hsv, original=a.original_hsv,
                                       live=a.color_preview, layout=a.color_layout, model=a.color_model,
                                       sliders=lambda: a.color_sliders() if a.color_sliders_open() else (),
                                       fields=True, key='COLOR_PAD')
        self.color_bubble = BubbleDrag(self, a.preview_colors, True, a.has_color_change, radius=12.0,
                                        on_click=a.accept_color_change, key='COLOR_BUBBLE')
        self.color_extras = self._build_color_extras()
        content = Column([self._build_color_header(), self.color_pad, self.color_extras,
                          Spacer(0.0, 2.0)], gap=6.0)
        self.color_window = self._window('color', build_body_window("Color", content, paint_color_wheel(None)),
                                         CornerButton('CLOSE', key='COLOR_CLOSE', on_click=a.toggle_color_panel),
                                         shape=body_shapes)
        self.color_overlay = Overlay(self.color_window, modal=False, animate=False)

        # Mask / View / Settings / Palettes / Extras windows (opened from the Windows ring).
        builders = {
            'mask': (build_mask_window, window_shapes, True),
            'view': (build_view_window, window_shapes, True),
            'settings': (lambda bar: build_body_window("Settings", self.settings_menu.content, paint_gear),
                         body_shapes, False),
            'library': (lambda bar: build_body_window("Palettes", self.library_menu.content, paint_library),
                        body_shapes, False),
            'extras': (build_extras_window, window_shapes, True),
        }
        self.tool_windows = {}
        for name in TOOL_WINDOWS:
            build, shape, has_help = builders[name]
            close = CornerButton('CLOSE', key=f'{name.upper()}_CLOSE', on_click=lambda n=name: self.toggle_window(n))
            help_button = None
            if has_help:
                help_button = CornerButton('HELP', key=f'{name.upper()}_HELP',
                                            selected=lambda n=name: self.help_shown(n),
                                            on_click=lambda n=name: self.toggle_help(n))
            window = self._window(name, build(self), close, help=help_button, shape=shape)
            window.visible = False
            self.tool_windows[name] = (window, Overlay(window, modal=False, animate=False))
        self.windows = {'bar': (self.menu, self.overlay), 'color': (self.color_window, self.color_overlay),
                        **self.tool_windows}

    # ---- state -----------------------------------------------------------------------

    def _value(self, channel):
        try:
            return self.actions.get_value(channel)
        except Exception:
            return 0

    def _get(self, key, default=None):
        try:
            value = self.actions.get_state(key)
        except Exception:
            return default
        return default if value is None else value

    def busy(self):
        """A flyout or the confirmation is open, or something is dragged."""
        return (self.flyout is not None or self.confirm_dialog.is_open
                or any(ov.dragging is not None for _w, ov in self.windows.values()))

    def reset(self):
        """End drags, close flyouts, forget hover (session end / bar hidden)."""
        self.end_drag()
        self.confirm_dialog.close()
        self.close_flyout()
        for _window, overlay in self.windows.values():
            overlay.hot = None
            overlay.pressed = None
            overlay.pointer_widget = None

    def handle(self, event):
        """Forward a :class:`~.kit.UIEvent` (region coords); True when an element used it."""
        stack = [ov for ov in self._stack() if ov.root.visible]
        for overlay in stack:
            if overlay.dragging is not None:
                return overlay.handle(event) == RUNNING
        if event.type == 'LEFTMOUSE' and event.value == PRESS:
            for overlay in stack:   # a press off an input field commits it
                overlay.blur_unless_over(event.x, event.y)
        elif event.type not in POINTER_TYPES:
            for overlay in stack:   # typing goes to the input field being edited
                if overlay.focus is not None:
                    if overlay.handle(event) == RUNNING:
                        return True
                    break
        if self.confirm_dialog.is_open:
            # Modal: only the dialog reacts; a press elsewhere, ESC or right click cancel.
            if event.value == PRESS and event.type in {'ESC', 'RIGHTMOUSE'}:
                self.confirm_dialog.close()
                self.overlay.layout()
                return True
            if event.value == PRESS and event.type == 'LEFTMOUSE':
                hit = self.root.pick(event.x, event.y)
                if not _is_inside(hit, self.confirm_dialog.panel):
                    self.confirm_dialog.close()
                    self.overlay.layout()
                    return True
            self.overlay.handle(event)
            return event.type in {'LEFTMOUSE', 'RIGHTMOUSE', 'ESC', 'MOUSEMOVE'}
        if self.flyout is not None and event.value == PRESS:
            if event.type in {'ESC', 'RIGHTMOUSE'}:
                self.close_flyout()
                return True
            if event.type == 'LEFTMOUSE':
                hit = self.root.pick(event.x, event.y)
                if hit is None:
                    self.close_flyout()
                    return True  # a tap outside only closes the flyout
                if not _is_inside(hit, self.flyout) and hit is not self.flyout_opener:
                    self.close_flyout()
        for overlay in stack:
            if overlay.handle(event) == RUNNING:
                return True
        return False

    # ---- drawing -----------------------------------------------------------------------

    def draw(self):
        for overlay in reversed(self._stack()):
            if overlay.root.visible:
                overlay.draw()
        with draw.blend_mode('ALPHA'):
            self._draw_drag_readout()
            self._draw_arm_hint()
            self._draw_color_drag()

