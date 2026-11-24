# Pixel Painter — Developer Guide

## Layout

```
__init__.py            bl_info, ordered module reload list, register/unregister
properties.py          all WindowManager properties (per-tool ones generated from the registry)
core/
  framework.py         ToolFrame, Shortcut, InputEvent, HoldTool, FunctionTool, ToolManager (no bpy)
  core.py              modal operator: guards, cursor tracking, MANAGER.dispatch; settings sync
  context.py           ToolContext -- the `ctx` every tool callback receives
  state.py             STATE (shared blackboard read by overlays), SETTINGS service
  history.py           pixel undo integrated with Blender's undo
tools/
  base.py              ToolBase (a ToolFrame + registry metadata), DrawEnvironment, SettingDefaults
  stroke.py            StrokeTool / BrushTool: press-drag-release painting + standard subtools
  registry.py          ToolRegistry
  catalog.py           TOOLS (order = enum / pie / Shift+number order) and global_tools()
  brushes.py           Square, Circle, Spray (WeightedBrushTool), Line, Eraser
  filters.py           Smooth, Smear
  selection.py         Select tool (box drag / move / resize, copy / paste, stencil) + its operators
  selection_ops.py     selection box geometry and pixel-region operations
  subtools/            color_pick (E), strength (Shift+E), eyedropper (hold Ctrl),
                       tool_switch (hold Alt -> Line, hold Shift -> Smooth/Eraser, Shift+1..9)
  falloff.py           falloff presets (enum, curve preset, icon keys)
  blend_modes.py       blend modes (enum, groups, favorites)
  draw_*.py, overlays*.py  pixel writing and canvas overlays
ui/
  kit/                 generic UI kit (no Pixel Painter knowledge) -- see below
  pie_menu.py          ToolPie / FalloffPie / FalloffPicker + W-key operator
  selection_actions.py Copy / Apply / Stencil buttons under the selection box
  native_menus.py      Blender-native blend pie and mode pie
  icons.py             ICONS (tool icons + generated falloff icons)
  falloff_icons.py     procedural falloff icons (white disc, alpha = falloff)
  tool_settings_ui.py  header / N-panel quick controls
  settings_menu.py     settings popup (tabbed: Color Selector, Tools, Blending, Falloff, Pen, ...)
tests/                 pure-Python unit tests (UI kit, tool framework)
```

## Tools and input

The core does not know what tools do. `core/core.py` guards the session,
tracks the hovered pixel and hands every event to `MANAGER`
(`core.framework.ToolManager`). The manager offers it to every active root
tool -- the global tools, then the selected tool -- until one **consumes** it
(`event.consume()`, Unity's `Event.Use()`). Unconsumed events pass through to
Blender.

Every tool, subtool and key binding is a `ToolFrame`. Inside a tool, an event
goes to:

1. its **active subtools** (latest first). An `exclusive` active subtool
   hides the event from its parent even if it doesn't consume it;
2. its **idle subtools** in registration order -- the first whose shortcut
   matches is activated (`bind()` bindings just call their function);
3. `on_event()`.

Subtools are reached only through their parent, so their shortcuts only work
while the parent tool is in use.

| Hook | When |
|---|---|
| `on_register()` | once: `bind()` shortcuts, `add_subtool()` subtools |
| `on_activate(ctx, event)` | tool selected / subtool triggered (`event` = trigger or `None`) |
| `on_deactivate(ctx)` | tool switched away / subtool ended (`self.deactivate(ctx)`) |
| `on_interrupt(ctx)` | abort running work (cursor left the image, a blocking subtool took over) |
| `on_event(ctx, event)` | catch-all after subtools |
| `draw_overlay(ctx)` | POST_PIXEL drawing while active |
| `on_session_end(ctx)` | the modal operator stopped |

Flags: `exclusive` (block the parent while active), `captures_input` (core
skips its cursor-over-image gating, e.g. the color picker), `is_global` +
`priority` (root tools active for the whole session).

Building blocks:

```python
self.bind(Shortcut('C', ctrl=True), self.copy)          # function; return False = don't consume
self.add_subtool(ColorPickTool(), Shortcut('E'))         # full subtool, trigger override
self.fine = self.add_subtool(HoldTool('SHIFT',           # active while Shift is held
                                      on_hold=self.sync, on_release=self.sync))
self.add_subtool(TemporaryToolSwitch('LINE', 'ALT'))     # another tool stands in while Alt is held
```

`Shortcut('SHIFT')` matches both shift keys; modifier arguments are
`True` (held) / `False` (not held) / `None` (don't care); `value=None`
matches any value (use it for `MOUSEMOVE`).

## Adding a tool

1. Subclass a tool base in `tools/`:
   * `BrushTool` / `StrokeTool` (`tools/stroke.py`) for painting: LMB/RMB
     strokes plus the standard subtools (Ctrl eyedropper, Alt line, Shift
     smooth/eraser, E color pick, Shift+E strength) come for free.
     Override `register_modifier_subtools()` to change that set, and
     `on_press` / `on_release` / `on_cancel` for special strokes (see `LineBrushTool`).
   * `ToolBase` for tools with their own interaction (see `SelectionTool`).

   ```python
   class DitherTool(BrushTool):
       tool_id = 'DITHER'
       label = "Dither"
       description = "Checkerboard dither"
       icon = "Tool_Dither.png"           # in textures/, optional
       outline_color = (0.2, 0.9, 1.0, 0.9)
       defaults = SettingDefaults(size=True, modifier=False, strength=False, alpha=False)

       def on_register(self):
           super().on_register()          # standard subtools + stroke bindings
           self.bind(Shortcut('D'), self.flip_phase)   # only while Dither is in use

       def flip_phase(self, ctx, event):
           ...

       def on_draw(self, env):
           ...                             # paint into env.img at env.cursor_x/y
           env.mark_painted()

       def draw_settings(self, context, layout):
           ...                             # optional extra header controls
   ```

2. Add an instance to the list in `tools/catalog.py` (or to `global_tools()`
   for a tool that is always active).

That's it: the mode enum, per-tool size/strength/modifier/alpha properties and
their defaults, persistence, the reset operator, the tool pie, Shift+number
shortcuts, the settings panel buttons and the cursor outline all come from the
registry. Set `falloff_property` to get the falloff section and picker binding.

## UI kit (`ui/kit`)

Retained-mode widgets for POST_PIXEL overlays. Compose widgets, the kit handles
layout, hit-testing, hover/press/click, keyboard, animation, DPI scaling and drawing.

| Module | Contents |
|---|---|
| `widget.py` | `Widget` base, `Row`, `Column`, `Grid`, `DrawContext` |
| `widgets.py` | `Label`, `Button`, `BubbleButton`, `RoundButton`, `Panel` |
| `radial.py` | `RadialMenu` (arc or explicit directions, `attach_below`, number keys) |
| `color_pad.py` | `ColorPad` — compact HSV selector, every part swiped like a touchpad (pure Python layout / input) |
| `overlay.py` | `Overlay` — interaction controller (pure Python, unit-tested) |
| `modal.py` | `OverlayOperator` mixin — draw handler, timer, modal wiring |
| `draw.py`, `icons.py`, `theme.py` | GPU primitives, image icons, colors/metrics/timings |

A modal pie is a subclass plus an operator:

```python
class MyPie(RadialMenu):
    def __init__(self):
        super().__init__()
        self.add_item(BubbleButton("A", on_click=do_a, selected=lambda: is_a()))
        self.attach_below(Panel(Grid([Button("x", on_click=do_x)], columns=3), title="Extras"))

class MY_OT_pie(OverlayOperator, bpy.types.Operator):
    bl_idname = "image.my_pie"
    bl_label = "My Pie"
    def build_overlay(self, context, event):
        return MyPie()
```

A widget layer inside another modal operator (like the selection buttons) uses
`Overlay(root, modal=False, animate=False)`: forward events with `handle()`;
it returns `RUNNING_MODAL` only for events it consumed.

Interaction rules (see `overlay.py`): one widget under the pointer at a time;
click = press + release on the same widget; radial items also accept
drag-release; Enter/Space confirm; holding the opening key and releasing it
confirms; ESC/RMB cancel; actions run after the close animation.

## Pen / tablet

* **Pressure** (`tools/pen_pressure.py`): the core stores the pressure of the
  last pointer event in `STATE['pen_pressure']` (1.0 for a mouse; releases are
  skipped). `StrokeTool.paint` scales size (by diameter), strength, alpha and
  modifier for the channels enabled in `pixel_painter_pen_pressure_*`.
  Tools that commit on release set `uses_pen_pressure = False` (Line).
  Tools read the modifier from `env.modifier`, not the WindowManager.
* **Pen bar** (`tools/pen_bar.py` + `ui/pen_bar.py`): a global tool with
  `screen_space = True`. The core calls `MANAGER.dispatch_screen()` *before*
  its cursor-over-image gating, so on-screen UI works anywhere in the editor;
  `dispatch()` then skips screen-space tools. Pens may have no hover and no
  wheel, so the bar uses only press / drag / release: `DragBubble` knobs
  (`draggable`), flyout openers (`activate_on_press`) and flyout entries
  (`drag_release`). The bar sits in the bottom corner. *Color* toggles the
  `ColorPad` (inside the bar under the color row, stretched to its width): the
  hue/value sheet and the hue, value and saturation bars all move relative to
  the swipe (`gain` 0.5), a tap jumps; it commits once, on release. It edits
  the color the pen paints. With *Preview* on (`pixel_painter_pen_color_preview`,
  settings popup > Color Selector) the pad is `live` (commits every step).
  *Settings* opens the settings popup. The color from before (`pen_color_original`) stays marked and
  shows in the always-visible old / new `ColorBubble` until it is tapped;
  `PenBarTool.pen_hsv` remembers the pad's HSV (`kit.hsv_for_rgb`) so hue and
  saturation survive grey / black. *Picker* arms `PenEyedropperTool`
  (`tools/subtools/pen.py`) for the next canvas press; the RMB lock rewrites
  pen-tip LMB events to RMB for every tool after the bar.
  The whole bar renders at `BAR_SCALE` x the UI scale x `pen_bar_scale`
  (persistent, 0.2..2), set by dragging the triangle in its top corner.

## Settings popup (`ui/settings_menu.py`)

The N-panel / tool header keep only the controls used while painting; options
that are set once and rarely touched live in the settings popup, a popover
panel (`IMAGE_PT_pixel_painter_settings`) with a header bar of categories
(`pixel_painter_settings_tab`, remembered). Open it with
`image.pixel_painter_open_settings` (optional `tab=`), the pen bar's
*Settings* button or the Settings button in the N-panel / header.
To add a category, add an entry to `SETTINGS_TABS` and a drawer to `_TAB_DRAWERS`.

## Undo

Pixel changes go through Blender's own undo (`core/history.py`), so Ctrl+Z
works with any tool active. Anything that writes pixels must bracket the
change:

```python
from ..core import history
history.begin(img)         # before modifying img.pixels
...                        # modify
history.commit(img, "My Edit")   # records + pushes one Blender undo step
```

`commit` stamps the image with an ID property and pushes a global undo step;
undo/redo handlers restore the matching pixels. Operators with their own
`UNDO` flag call `commit(img, push=False)` instead.

## Tests

```
python -m unittest discover -s tests -v
```
