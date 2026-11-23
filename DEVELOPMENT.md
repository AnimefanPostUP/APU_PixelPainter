# Pixel Painter — Developer Guide

## Layout

```
__init__.py            bl_info, ordered module reload list, register/unregister
properties.py          all WindowManager properties (per-tool ones generated from the registry)
core/                  modal paint operator, undo, sub-modes (E / Shift+E bubbles), selection logic
tools/
  base.py              ToolBase interface, DrawEnvironment, SettingDefaults
  registry.py          ToolRegistry
  catalog.py           TOOLS — the registered tools (order = enum / pie / Shift+number order)
  brushes.py           Square, Circle, Spray (WeightedBrushTool), Line, Eraser
  filters.py           Smooth, Smear
  selection.py         Select tool metadata + settings UI
  falloff.py           falloff presets (enum, curve preset, icons)
  blend_modes.py       blend modes (enum, groups, favorites)
  draw_*.py, overlays*.py  pixel writing and canvas overlays
ui/
  kit/                 generic UI kit (no Pixel Painter knowledge) — see below
  pie_menu.py          ToolPie / FalloffPie / FalloffPicker + W-key operator
  selection_actions.py Copy / Apply / Stencil buttons under the selection box
  native_menus.py      Blender-native blend pie and mode pie
  icons.py             ICONS (tool + falloff icons)
  tool_settings_ui.py  header / N-panel settings
tests/                 pure-Python unit tests for the UI kit
```

## Adding a tool

1. Subclass `ToolBase` (or `BrushTool` / `WeightedBrushTool`) in `tools/`:

   ```python
   class DitherTool(BrushTool):
       tool_id = 'DITHER'
       label = "Dither"
       description = "Checkerboard dither"
       icon = "Tool_Dither.png"           # in textures/, optional
       outline_color = (0.2, 0.9, 1.0, 0.9)
       defaults = SettingDefaults(size=True, modifier=False, strength=False, alpha=False)

       def on_draw(self, env):
           ...                             # paint into env.img at env.cursor_x/y
           env.mark_painted()

       def draw_settings(self, context, layout):
           ...                             # optional extra header controls
   ```

2. Add an instance to the list in `tools/catalog.py`.

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
