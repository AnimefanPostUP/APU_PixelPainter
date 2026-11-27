# Pixel Painter — Developer Guide

## Layout

Folders group code by **type**; inside a folder every module holds **one concern**
(usually one class, or a family of similar small classes), so the file a class lives
in follows from what it is. Package `__init__.py` files are side-effect free (a
docstring that lists the package's modules): import the concrete module, e.g.
`from ..tools.mask import data as mask_data`, `from .brushes.circle import CircleBrushTool`.

```
__init__.py            bl_info, register / unregister (purges the add-on's modules first: no reload list)
paths.py               add-on folder, textures/, settings.json, palettes.json, native/runtimes
properties.py          all WindowManager + Scene properties (per-tool ones generated from the registry)
core/                  manages tools, knows nothing about what they do
  framework.py         ToolFrame, Shortcut, InputEvent, HoldTool, FunctionTool, ToolManager (no bpy)
  operator.py          the modal operator: guards, cursor tracking, MANAGER.dispatch; settings sync
  context.py           ToolContext -- the `ctx` every tool callback receives
  state.py             STATE (shared blackboard read by overlays), SETTINGS service
  history.py           pixel undo integrated with Blender's undo
  variables.py         ToolVariableStore
  view3d/              3D Viewport: mesh (cache), raycast (mouse -> pixel), islands (UV island
                       clipping), elements (texel -> island / part map, hover, outlines),
                       stroke_path, frames, surface_path, footprint, patch (Edge mode)
model/                 pure domain data (no bpy): falloff, blend_modes, color_history,
                       color_palette, tertiary_color, value_curve (AO curve + presets)
paint/                 pixel kernels, no tool logic: pixels (write / alpha), blending, smooth, special
                       (the special brushes: rust noise, noise blur, pull warp, heal, particle dents),
                       native_paths (C# fast paths of whole draw steps), region_paint (per-texel
                       colors), edge_ramp (Edges band math)
overlays/              canvas drawing in the draw handlers: handler (add / remove), gpu_prims
                       (shared primitives), brush_outline, cursor, sub_modes (E / Shift+E / Ctrl
                       HUDs), selection, grid, view3d_outline, element_outline (hovered island / part)
tools/                 all tool behaviour
  base.py              ToolBase (a ToolFrame + registry metadata), DrawEnvironment, SettingDefaults
  stroke.py            StrokeTool / BrushTool: press-drag-release painting + standard subtools
  registry.py          ToolRegistry
  catalog.py           TOOLS (order = enum / pie / Shift+number order) and global_tools()
  brushes/             one module per tool: square, circle, spray (weighted: falloff base), line,
                       eraser; common (paint a footprint)
  filters/             smooth, smear; edge (Edge-mode surface filtering), common
  selection/           tool (SelectionTool), operators (Apply / Copy / Cancel / Stencil), geometry
  mask/                data (elements, chosen set, allowed()), geometry (pure numpy), guard
                       (enforcement during strokes), overlay (drawing), tool (MaskTool)
  extras/              the Extras window's tools: tool (ExtrasTool, global), operations (Fill /
                       Edges / Ambient Occlusion), ao (per-texel ray casting)
  special/             the Brushes window's tools (group 'SPECIAL'): particles, rust, noise_blur,
                       pull, repair; common (SpecialBrush base, island clip of pixel arrays)
  pen/                 tool (PenBarTool: lifecycle, events, drawing), actions/ (its actions by
                       concern: colors, settings, palettes, falloff, windows, mask, extras,
                       brushes), layout
                       (per-project window layout), pressure, view_nav, eyedropper
  subtools/            color_pick (E), strength (Shift+E), eyedropper (hold Ctrl),
                       tool_switch (hold Alt -> Line, hold Shift -> Smooth/Eraser, Shift+1..9)
ui/
  kit/                 generic UI kit (no Pixel Painter knowledge) -- see below
  pen/                 the pen UI (built from the kit)
    bar.py             PenBar: construction, handle(), draw(); combines menu/
    metrics.py         the dial's rings, arcs, sizes and tints
    style.py           the shared pen look (PenButton, DangerButton, PlainGroup, ...)
    menu/              PenBar's concerns: dial, flyouts, drag_drop, window_layout, readouts
    widgets/           the dial's widgets: color, blend, falloff_field, grid_corner, window_ring
    windows/           frame (Window: move / lock / resize / help), parts, mask, view, settings,
                       palettes, extras, brushes, dialog (ConfirmDialog), shapes (window backgrounds)
    icons/             icon painters: menu, settings, palettes, windows, extras, brushes
  panels/              tool_settings (header / N-panel), settings_popup (tabbed settings popup)
  menus/               pie_menu (ToolPie / FalloffPie / FalloffPicker), native_menus (blend / mode
                       pies), selection_actions (buttons under the selection box)
  operators/           image_save, palette, mask, paint_selected_faces_uv
  icons/               tool_icons (ICONS), falloff_icons (procedural)
  workspace_tool.py    the WorkSpaceTools (Image Editor, 3D Viewport) and their keymaps
  viewport_frame.py    the "special mode" frame around the editor
utils/                 blender_utils, math_utils, native (C# loader), pixel_io, settings_service,
                       persistence_settings, palette_library, palette_image
native/                the C# backend (see below)
tests/                 pure-Python unit tests (python -m unittest discover -s tests)
```

Where new code goes: a tool -> its own module in the matching `tools/` folder (and an
entry in `tools/catalog.py`); pixel math -> `paint/`; something drawn on the canvas ->
`overlays/`; pure data / rules without Blender -> `model/`; a pen UI widget ->
`ui/pen/widgets/`, an icon -> `ui/pen/icons/`. When a module grows a second concern,
give that concern its own module.

## Tools and input

The core does not know what tools do. `core/operator.py` guards the session,
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

**Secondary tool.** A tool that uses the mouse *instead of* the selected tool
(mask editing, an armed Extras tool, E / Shift+E, the eyedroppers) sets
`secondary = True` (active subtools) or overrides `holds_mouse(ctx)` (global
tools armed by state). `ToolManager.secondary_tool(ctx)` returns it (usually
None). While it is set, the selected tool's brush outline is not drawn (2D, 3D
surface, off-mesh ring) -- the secondary tool draws its own cursor in
`draw_overlay` (the pickers: `overlays.cursor.draw_pick_cursor` plus the element
outline) -- and the selected tool's pen menu button shows a dotted outline
instead of its band (`RingSegment(suspended=...)`). Alt / Shift tool switches
are not secondary tools: the stand-in really paints with its own outline.

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

1. Subclass a tool base in a new module of the matching `tools/` folder
   (e.g. `tools/brushes/dither.py`):
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
| `widgets.py` | `Label`, `Button`, `BubbleButton`, `RoundButton`, `DragBubble`, `ColorBubble` (old / new), `Panel` |
| `radial.py` | `RadialMenu` (arc or explicit directions, `attach_below`, number keys) |
| `form.py` | `Group` (titled, tinted block of controls), `Slider`, `IconButton` (painted icon + label), `TextBlock`, `Spacer` |
| `curve.py` | `CurveEditor` (anchors of a 0..1 curve: Move / Add / Draw by pen; `stroke_to_curve` fits a freehand stroke) |
| `ring.py` | `Dial` (center widget + rings of pie segments; each `add_arc` is a category with its own `tint`, separated by `group_gap` and a divider line; `gap` between segments; `add_corner` fills the enclosing square's corners with `CornerSegment`s), `RingSegment` (icon / label / painter), `RingSlider` (radial slider: press / drag sets the value from the distance to the center) |
| `color_selector.py` | `ColorSelector` — pen-friendly color selector, every part swiped like a touchpad (pure Python layout / input). Layouts are `ColorShape` variants: `SheetShape`, `SquareShape`, `TriangleShape`, `WheelShape`; model HSV / HSL; optional RGB / HSV / HSL channel sliders underneath |
| `color_models.py` | HSV / HSL / RGB conversions that keep hue / saturation through grey, black and white |
| `color_pad.py` | `ColorPad` (the selector with the Sheet layout), `hsv_for_rgb` |
| `overlay.py` | `Overlay` — interaction controller (pure Python, unit-tested) |
| `modal.py` | `OverlayOperator` mixin — draw handler, timer, modal wiring |
| `draw.py`, `icons.py`, `theme.py` | GPU primitives, image icons, colors/metrics/timings. Every shape becomes `SMOOTH_COLOR` triangle arrays, cached at their position and relative to an integer origin (a moved shape is a cache hit); inside `draw.batched()` (`Overlay.draw`) they are drawn as one batch per run. Text and icons call `draw.flush()` first -- anything else drawing with raw `gpu` / `blf` inside an overlay must too, or it lands under shapes issued before it |
| `anim.py` | easing helpers; `request_frame()`: an animation that has not reached its end asks for another frame. The Pixel Painter session redraws on its timer only while one is requested (no idle redraws), so every time-based animation must call it |
| `aa.py` | geometric anti-aliasing for `draw.py` (no MSAA in overlays): a coverage ramp centered on every fill edge (0.5 px in / out, the solid part shrunk to meet it: sloped edges smooth, grid-aligned ones crisp; rects snap to whole pixels), lines as soft-edged triangle strips (any width, any GPU backend), vertex counts by on-screen size; meshes are memoized. `ring_segment` / `circle` / `sector` / `triangle` take `rim=` (a 1 px line: `theme.edge_for(fill)`, a darker shade of the fill -- never plain black). Draw through `draw.py`, not raw `gpu` lines, to keep it |

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

* **Pressure** (`tools/pen/pressure.py`): the core stores the pressure of the
  last pointer event in `STATE['pen_pressure']` (1.0 for a mouse; releases are
  skipped). `StrokeTool.paint` scales size (by diameter), strength, alpha and
  modifier for the channels enabled in `pixel_painter_pen_pressure_*`.
  Tools that commit on release set `uses_pen_pressure = False` (Line).
  Tools read the modifier from `env.modifier`, not the WindowManager.
* **Pen bar** (`tools/pen/tool.py` + `ui/pen/bar.py`): a global tool with
  `screen_space = True`. The core calls `MANAGER.dispatch_screen()` *before*
  its cursor-over-image gating, so on-screen UI works anywhere in the editor;
  `dispatch()` then skips screen-space tools. Pens may have no hover and no
  wheel, so the bar uses only press / drag / release: `DragBubble` knobs
  (`draggable`), flyout openers (`activate_on_press`) and flyout entries
  (`drag_release`). `ui/pen/bar.PenBar` holds two floating elements, each its
  own non-modal `Overlay` with its own theme scale: the pen menu and the color
  selector. Each is a `Window`: a `MovePanel` (drag the background to move),
  a padlock (no moving / resizing; top left, the pen menu's bottom left:
  `Window(lock_bottom=True)`), an X (top right) and a resize
  triangle (bottom right). Size and position live in tool state
  (`pen_bar_scale` / `pen_bar_pos`, `pen_color_scale` / `pen_color_pos`,
  `ui.pen.metrics.LAYOUT_STATE`; scale limits `SCALE_LIMITS`); both are clipped to
  the editor (`kit.geometry.clamp_box`) and shrunk while it is too small.
  `image.pixel_painter_reset_pen_ui` (settings popup > Pen, N-panel) restores
  the defaults. The menu is the dial (`kit.Dial`): the Size knob in the center,
  S / A / M radial sliders top right, the tools top left (two rings), the
  bottom Undo / Redo (inner ring, `HISTORY_ARC`) with the favorite blend modes
  outside them (outer ring), bottom right
  the falloff controls (the arcs and radii are the `*_ARC` / `*_RING` constants). The
  corners of its enclosing square hold `kit.CornerSegment` buttons
  (`Dial.add_corner`: inner edge on the circle, outer edges on the square, the
  extreme corners cut for the lock / X / resize triangle, except top left): top
  left the color section -- the gradient slider (`GradientSlider`, primary at
  the left end, secondary at the top), the secondary / primary color each with its own picker (arm kinds
  `EYEDROPPER_PRIMARY` / `_SECONDARY`; the press sets state `pen_pick_target`
  for `PenEyedropperTool`), and between them Swap with the tertiary bubble
  (`TertiaryBubble`: the largest circle in its corner slot, `kit.geometry.best_circle`)
  behind it; these buttons have round
  corners (`RingSegment(round=...)`, `kit.geometry.round_strip`, `COLOR_ROUND`);
  top right, outside S / A / M, the color history band (`HISTORY_BAND_ARC`,
  `model/color_history.py`, recorded by `StrokeTool.begin_stroke` for tools with `paints_color`)
  and past it Alphalock as a capsule (`BRUSH_MODE_RING` / `_ARC`;
  `_add_capsule`: a band whose two outer ends are half circles, via
  `RingSegment(round=..., round_ends=...)` and `kit.geometry.round_strip(ends=...)`).
  The optional tertiary color (`model/tertiary_color.py`, pure) is a point `t` on
  the primary -> secondary gradient (state `pen_tertiary_t`); while selected
  (`pen_tertiary`, set by the slider / bubble) `StrokeTool` paints left-button
  strokes with it (no RMB lock meanwhile). The color selector, pickers and history
  still edit primary / secondary: `PenBarTool._target` (state `pen_color_target`
  while the tertiary color is selected, else the RMB lock); that color gets a dotted
  outline (`kit.draw.ring_segment_dashed_outline`, `kit.geometry.dash_runs`);
  bottom right the palette band (24 slots in `PALETTE_ROWS` bands) and, a capsule
  in the gap right of the circle, Palettes (`PALETTE_BUTTON_ARC`);
  bottom left Windows, Save, Grid and Blend as a capsule (`BOTTOM_LEFT_RING` /
  `BOTTOM_LEFT_ARC`; Blend is a `BlendButton`: a `BLEND_GRADIENT` dark-to-light
  gray fill with the mode's name).
  Palettes (`model/color_palette.py`, pure): a project holds 24 palettes of 24
  colors, stored as JSON in the scene property `pixel_painter_palettes` (saved in
  the .blend); the band shows the active palette's colors or, in the palette view
  (`pen_palette_view`), the palettes. The library (`utils/palette_library.py`,
  `palettes.json` in the add-on folder) is not synced with projects: the Library
  flyout (`ui/pen/windows/palettes.py`) copies palettes in / out and to / from the
  clipboard (JSON with hex colors; pasting also takes any `#rrggbb` list).
  *From image* (`image.pixel_painter_palette_from_image`, `ui/operators/palette.py`):
  an image's distinct pixel colors in reading order (more than 24: median cut,
  `utils/palette_image.py`) become a new palette in the first empty project slot
  (all taken: the library); messages go to state `pen_palette_status`.
  Drag & drop (`ColorDrag` mixin, setting `pen_color_drag`): payloads
  `('color' | 'palette', value, origin)`; a short press stays a tap; targets
  define `accepts(payload)` / `accept_drop(payload, source)` (an ancestor may
  take it, e.g. the library list); `PenBar.drop`. Deleting or replacing a
  palette goes through `PenBar.confirm` (`ConfirmDialog`, modal over the menu). The
  falloff controls sit bottom right (`FALLOFF_FIELD_ARC`): the falloff field
  (`FalloffField`; swipes map through `motion_delta`: two fixed straight axes along /
  across the field's middle ray, so a straight swipe changes one value; the marker
  may reach `FIELD_EDGE_MARGIN` of its radius over the edges) in the outer ring,
  reaching in through the inner ring's outer half (`FALLOFF_SPLIT`, no gap), and
  Custom | Curve in the inner ring's inner half. Outside Undo / Redo (`FAVORITES_ARC`,
  outer ring) `BlendFavorites`: the favorite blend modes (one `BlendFavorite`
  per mode) split evenly into `FAVORITE_ROWS` rings (the outer ring takes the odd one);
  re-placed on draw when `pixel_painter_blend_favorites` changes; labels run along
  the circle, kept upright, two-word names on two lines, via `draw.text_along`). `PenBarTool.blend_favorites` may be empty (the defaults only while the
  property is missing). The Blend flyout: Common / Contrast / Math / HSL/HSV,
  favorites check-marked, *Edit Favorites* (`PenBar.blend_fav_edit`) makes taps
  toggle favorites (`wm_toggle_flag`). Bottom left, first of its corner buttons,
  Windows (`activate_on_press`). It opens the Windows ring
  (`WindowRing`, `WINDOW_RING` = the inner ring's radii): Settings / Mask / View /
  Color / Palettes (library) as `drag_release` `RingSegment`s over the full circle
  from `WINDOW_RING_START`. The ring is the dial's last child (drawn on top, picked
  first), paints an opaque backdrop from the inner ring out to `WINDOW_RING_COVER`
  (the outer ring's edge: the tools are hidden too) and blocks the pointer there;
  these are the only buttons for Settings / Mask / View / Color / Library. Its outer ring
  (`WindowRing.add_outer_entries`, `WINDOW_OUTER_RING` / `_START` / `_STEP`) holds further
  windows at fixed angles (the rest is backdrop): Brushes, right outside Extras; it is handled as the open flyout (`toggle_flyout` / `close_flyout`),
  so a tap outside, ESC / RMB or Windows again close it. The field sets the
  *Shape* falloff (`falloff.SHAPE_*`, `math_utils.shape_falloff`): global
  `pixel_painter_falloff_hardness` (radial: inner edge = 1 = constant, outer = 0)
  and `_sharpness` (along the circle: top = 0 = linear fade, bottom = 1 =
  `(1 - u) ** SHAPE_MAX_POWER`); touching it selects Shape for the active tool.
  `DrawEnvironment.falloff` turns Shape into the hashable key
  `('SHAPE', hardness, sharpness)` (rounded to `SHAPE_DECIMALS`), so the C#
  kernel cache keys on the values. It is swiped like the color selector
  (relative, `gain` 0.5; a tap jumps; ESC restores) and shows a readout plus a
  preview disc while dragged. While pressed it hides the OS cursor (state
  `cursor_hidden`, honored by the core's modal cursor) and warps it onto the marker
  after every swipe step (`PenBarTool.warp_cursor`), so motion is measured from the
  marker. Its corners show quarter preview discs (`IconSet.draw_quad`). The curve button
  opens a flyout with a `kit.CurveEditor` on the brush's falloff curve
  (`PenBarTool.set_custom_curve_points`; Reset: `falloff.CUSTOM_DEFAULT_POINTS`)
  and preset buttons (`falloff.CURVE_PRESETS`: the falloffs the field does not
  cover, as anchors with handle types; `PenBarTool.load_curve_preset`). Anchors
  that stay in place keep their handle type while others are edited.
  Settings (Windows ring) opens the settings flyout (`ui/pen/windows/settings.py`): icon tabs
  and the tab's page of `kit.Group`s (one tint per tab), the same settings and
  remembered tab as the Blender settings popup, read / written through
  `PenBarTool.wm_get` / `wm_set` / `wm_toggle_flag` / `wm_range`. *Color* toggles the
  color selector element (a `ColorSelector` with the old / new bubble above it, `COLOR_WIDTH` wide):
  every part moves relative to the swipe (`gain` 0.5), a tap jumps. Layout
  (`pixel_painter_color_selector_layout`: Sheet / Square / Triangle / Wheel), model
  (`..._model`: HSV / HSL) and sliders (`..._sliders`: RGB / HSV / HSL, any combination)
  are set in the settings popup > Color Selector and apply immediately;
  the E-key color pick subtool (`tools/subtools/color_pick.py`) shows the same
  selector at the cursor (a non-modal `Overlay` layer) in hover mode
  (`ColorSelector.follow`): the main area follows the mouse, a click on it applies and
  closes; leaving it restores the color where the mouse last paused; bars / sliders are
  clicked or swiped; the wheel (`ColorSelector.wheel`) changes the bar under the mouse or
  the channel the main area does not set; Shift slows the mouse (the cursor is warped to
  the slowed point, so picking, drags and taps all get precise); RMB / Esc restore,
  E = primary / secondary; it commits once, on release. It edits
  the color the pen paints. With *Preview* on (`pixel_painter_pen_color_preview`,
  settings popup > Color Selector) the pad is `live` (commits every step).
  *Settings* opens the settings popup. *Save* (bottom-right corner, `BOTTOM_RIGHT_ARC`)
  runs `image.pixel_painter_save_image` (`ui/operators/image_save.py`) on the painted
  image; a dot shows while `image.is_dirty`. How it saves comes from settings >
  Pen > Save Image: `pixel_painter_save_image_method` (`AUTO`: repack packed,
  save to its file, else pack / `PACK` / `FILE`: write a file, images without
  one go to `pixel_painter_save_image_folder`/`<name>.png`) and
  `pixel_painter_save_image_blend` (save the .blend afterwards).
  *Grid* (bottom-right corner, first before Save and Windows, `GridCorner`) shows `pixel_painter_grid_opacity` in percent:
  a tap toggles `pixel_painter_grid_show` (a grid at 0 % comes on at
  `GRID_DEFAULT_OPACITY`), a vertical drag sets the opacity (`GRID_DRAG_PX` for
  0 -> 100 %, ESC restores it). In the 3D Viewport `draw_pixel_grid_overlay_3d`
  (`overlays/grid.py`) draws the cached mesh with a texel-border shader
  (lines via `fwidth`, faded out below ~2-5 px per texel, small clip-space depth bias).
  *Mask* and *View* (Windows ring) open floating windows
  (`TOOL_WINDOWS`, content in `ui/pen/windows/`): movable / lockable /
  resizable like the color selector (state `pen_<name>_panel`, `_locked`,
  `_scale`, `_pos`; default spot beside the menu, tops level). Mask: the paint
  mask controls (a dot on the ring entry while the mask is on). View
  (`tools/pen/view_nav.py`, numpy math in `tests/test_view_nav.py`): axis views,
  15 degree orbit / roll, *Level* (world up is up on screen), *Fit* (pivot on the
  object, distance so every vertex is inside `FIT_MARGIN` of the view, from
  `rv3d.window_matrix`), *Center*, zoom, Persp / Ortho; *Auto Fit*
  (`pen_view_autofit`) re-fits after orient / orbit / roll. Works on the
  `RegionView3D` (a camera view switches to a free view); in the Image Editor
  only Fit / Center / zoom / 1:1 apply (image operators, deferred).
  Layout: compact icon buttons (`WindowButton`: 1 px outline, 10 px labels); View has two
  3x3 pads -- Orient (Front in the middle, Top / Bottom / Left / Right around it,
  roll in the top corners, Level and a differently styled Back at the bottom) and
  Orbit (arrows around Fit; zoom, Center, Persp / Ortho in the corners). The
  explanations show only while the window's '?' corner button is on
  (`Window.help`, state `pen_<name>_help`). Kit hooks used: `Button.outline`,
  `Group(title_indent=)`.
  Per project: `PenBarTool.layout_keys` (every window's open / collapsed state,
  position, scale, lock, help, Auto Fit) are stored as JSON in the scene property
  `pixel_painter_pen_layout` (`tools/pen/layout.py`, `tests/test_pen_layout.py`).
  `LayoutStore.load_if_needed` (from `_layout`, also in draw callbacks: it only
  updates the Python state) loads it when the file / scene changes;
  `save_if_changed` (from `on_event`, not while dragging) writes it after a change.
  A project without a stored layout keeps the current one until its first change. The color from before (`pen_color_original`) stays marked and
  shows in the old / new `ColorBubble` until it is tapped;
  `PenBarTool.pen_hsv` remembers the pad's HSV (`kit.hsv_for_rgb`) so hue and
  saturation survive grey / black. *Picker* arms `PenEyedropperTool`
  (`tools/pen/eyedropper.py`) for the next canvas press; the RMB lock rewrites
  pen-tip LMB events to RMB for every tool after the bar.
  Each element renders at `BAR_SCALE` x the UI scale x its own scale.

## Stroke spacing (`model/spacing.py`)

When a stroke stamps, per tool (`pixel_painter_<TOOL>_spacing` + `_spacing_step` /
`_spacing_distance` / `_spacing_interval`; with `pixel_painter_spacing_per_tool` off the
global `pixel_painter_spacing` / ... instead). `SettingsService.get_tool_spacing` /
`set_tool_spacing` / `spacing_props` resolve which properties apply.

* `PIXEL` (Once): once per new pixel, no build-up (the brushes' `env.spacing == 'PIXEL'` paths);
  value = pixels per stamp. `FREE` (Fixed): builds up; value = pixels between stamps. Defaults:
  Fixed, 1 px (the old behaviour). Values above 1: `StrokeTool.paint` thins the step's
  path with `spacing.thin` (Pixel: path pixels walked, Free: true distance; the walked
  rest carries over in state `spacing_carry`); no stamp due: only `mark_painted`.
* `TIME`: `continue_stroke` does not paint; `StrokeTool.on_tick` (the session timer,
  ~60 Hz: the operator's TIMER -> `ToolManager.tick` -> `ToolFrame.tick` /
  `on_tick`, forwarded to stand-ins by `TemporaryToolSwitch`) stamps at the cursor
  whenever `spacing.due` (state `spacing_last_time`), no path between stamps.
* Tools with `respects_pixel_spacing = False` (Line) ignore step / spacing / time.
* Shown as *Once* (`PIXEL`), *Fixed* (`FREE`), *Time* (`TIME`): `spacing.MODE_LABELS`; the
  ids stay (saved settings).
* Pen menu, bottom right outside the palette bands, one capsule along the circle
  (`SPACING_RING` -- as deep as the Alphalock capsule --, `SPACING_ARC`, kept inside the
  square; `SPACING_WEIGHTS`): on the left `ui/pen/widgets/spacing.SpacingModeButton` (the
  mode's name along the arc, a tap steps), right of it `SpacingSlider` (only the value, "4 px" / "100 ms", along the arc;
  range and scale follow the mode, Time two-part via `spacing.slider_value` /
  `slider_fraction`; the readout in `Readouts` gives the full name).

## Paint mask (`tools/mask/`, `tools/mask/geometry.py`)

Limits painting to chosen UV islands or mesh parts (`pixel_painter_mask_enabled`
/ `_source` `UV_ISLAND` | `MESH_PART` / `_invert` / `_grow` / `_show` / `_opacity`).

* `mask_geometry` (pure numpy, `tests/test_mask.py`): faces -> islands (edge
  with equal UVs on both sides) or parts (vertex-connected), rasterized by
  pixel center (`grow` pushes the edges out) into sorted flat pixel indices.
* `mask.data.refresh()` builds the elements from the active + selected mesh
  objects (base mesh, the paint UV map). It syncs edit-mode meshes, so it is
  only called from modal code (stroke start, picking, hover; mesh changes
  checked every `CHECK_INTERVAL`); draw callbacks read the cache only.
* Chosen elements: scene property `pixel_painter_mask_selection` (JSON, one
  face index per element). `mask.data.allowed()` = chosen pixels (inverted with
  *invert*); with no mesh / UVs there is no masking.
* Enforcement (`tools/mask/guard.py`, `tests/test_mask_guard.py`): `StrokeTool.paint`
  wraps every `on_draw` in `mask_guard.GUARD` (`StrokeMaskGuard`), so every tool is
  masked without knowing about it. (Selection paste is not masked.) The guard copies
  the image once per stroke (protected pixels keep that value for the whole stroke)
  and after each step restores protected pixels only inside the step's written
  region: `StrokeTool.step_region` (default: the steps' stamps grown by the radius;
  `LineBrushTool`: start to cursor; `None` = the whole image, e.g. Edge mode). Tools
  whose step rewrites earlier stamps (Circle / Spray in Pixel spacing) return True
  from `rewrites_stroke`, and the region is the union over the stroke. A tool that
  writes outside its stamps must override `step_region`.
* `MaskTool` (global, priority 150): while state `mask_picking` is on, a
  canvas press toggles the element under the cursor, a drag sets the ones it
  passes to the same state; Esc / RMB end it. The pen bar does not remap the
  RMB lock while picking.
* Overlay: `mask.overlay.draw_2d` (red / light red stripes at `pixel_painter_mask_opacity`, default 15%, via `stripe_colors`; Mask window: a short arc slider in the ring beside Show, `ArcSlider(knee=(0.5, 0.1))`: its first half covers 0 .. 10 %; a small GPU shader; Image Editor: blocked pixel runs, drawn by the core
  before tool overlays) and `mask.overlay.draw_3d` (POST_VIEW, triangles whose UV
  center is blocked).

## Filling window ("Extras" in code: `tools/extras/`, `ui/pen/windows/extras.py`)

Tools that act on a whole *element* -- a UV island or a connected mesh part
(`pixel_painter_extras_source`) -- opened from the Windows ring.

* **Element map** (`core/view3d/elements.py`): built from the evaluated mesh cache
  (the active object, modifiers included). Triangles get element labels (UV islands:
  `islands._tri_island_labels`; mesh parts: shared vertices), texels get them through
  the UV rasterizer (`native.raster_labels`, merged where elements share texels),
  then dilated by one texel (the half-covered edge texels). Cached per source and
  mesh cache version. `label_under(ctx, emap)`: in the 3D Viewport the element of the
  hit triangle, in the Image Editor the one of the hovered texel.
* **Hover outline** (`overlays/element_outline.py`): `set_hover(owner, active, emap,
  label, color)` from modal code; the core's draw callbacks draw it (3D: the
  element's border edges -- edges only one of its triangles uses -- faint through
  geometry, full in front; 2D: its texel contour). It disappears once `active(state)`
  is false. Used by `ExtrasTool` (cyan) and `MaskTool` while picking (orange).
* **ExtrasTool** (global, priority 140): while state `extras_mode` is `FILL` /
  `EDGES` / `AO`, a canvas press runs it on the hovered element (LMB: primary color
  first, RMB: secondary), Esc disarms. Arming disarms mask picking and vice versa.
  *All* (the window's center) runs it with `label=None` (every element).
* **Operations** (`tools/extras/operations.py`): per-texel colors and opacities go
  through `paint.region_paint.blend_texels` with the brush's blend mode and the
  active tool's strength / alpha, filtered by `mask.data.allowed` and Alphalock; one
  `history.begin` / `commit` per run. Edges: model edges only (`edge_ramp.model_edges`:
  by angle / all / marked sharp; the mesh cache keeps the real edges, `cache.edges`,
  so triangulation diagonals never count, and `cache.edge_marked`), drawn in the UV
  space of each triangle beside the edge onto that triangle's element. The band is
  the true distance from texel centers to the edge (`segment_distance`), so both
  sides get the same width: `'BETWEEN'` (Symmetric; an edge on a texel border gets
  both columns beside it) or `'ON'` (Pixel Line: the edge snapped to texel centers,
  `snap_segments`, an odd band), then `band` and `ramp` through the Edges falloff
  curve (`pixel_painter_extras_edge_curve`, kind `'edge'` in `model/value_curve.py`:
  x = steps / width, weight f -> color `1 - f`, opacity `f` with Fade). AO (`tools/extras/ao.py`): texels placed on
  their triangle (`texel_surface`, vectorized barycentrics; uncovered edge texels take
  a neighbour's point), cosine-weighted Hammersley rays spun per texel, cast with
  `cache.bvh.ray_cast` (Python calls: texels x samples), occlusion = hit share, shaped
  by the AO curve (`model/value_curve.py`: monotone cubic, presets `AO_PRESETS`,
  stored as JSON in `pixel_painter_extras_ao_curve`).
* Window (`ui/pen/windows/extras.py`): a `TrimmedDial` with two rings -- inner: the
  tools on top, the armed tool's choices below as deep icon + caption segments (like
  Undo / Redo); outer: the source on top, a `ShownArcSlider` on each side
  (`ArcSlider(short=True)`: only the label's first letter, upright; while dragged
  `Readouts._draw_drag_readout` shows `ArcSlider.readout()` -- full name and value -- in
  a pill beside the window, like the pen menu's S / A / M; the left one `reverse=True`,
  so both grow upward), Edges' Placement (one button swapping
  Symmetric / Pixel line) / Fade / Curve below. Tints by category (`TINT_EXTRAS_*` in
  `ui/pen/metrics.py`): tools = the pen menu's tool blue, All red (`TINT_EXTRAS_ALL`), source, edge choices, options,
  sliders. Mode-specific parts are `ShownSegment`s; `TrimmedDial` reserves height only
  for the visible parts. *Curve* (state `pen_extras_curve`) folds out the tool's
  `CurveEditor` with presets.
* Tests: `tests/test_extras.py` (curve, edge math, texel blending, AO placement).

## Special window ("Brushes" in code: `tools/special/`, `ui/pen/windows/brushes.py`)

Special brushes, opened from the Windows ring's outer ring. They are ordinary
`StrokeTool`s in `TOOLS` (per-tool size / strength / alpha / M, falloff, pen pressure,
mask, undo all as usual) with `group = 'SPECIAL'`: the pen menu's tool ring and the tool
pie list only `group == 'MAIN'` (`ToolRegistry.in_group`), they sit past Shift+9.
`SpecialBrush` (`tools/special/common.py`) spaces stamps (`stamp_spacing`) and clips
whole pixel arrays to the UV island (`island_keep`). The pixel math is pure NumPy in
`paint/special.py` (`tests/test_special_brushes.py`).

* **Rust**: fractal value noise anchored to the texture (`rust_texels`: color mix `t`
  plus a patchy `presence`); per stroke a max-weight buffer, repainted from the stroke
  snapshot (no pile-up). LMB primary cores, RMB swapped. `rust_scale`, `rust_coverage`.
* **Particles**: 3D -- bodies launched from in front of the brush along the view ray,
  integrated under world gravity, collisions by `cache.bvh.ray_cast` per time step,
  reflected with `RESTITUTION`, a dent (`chips`) at every impact (UV via
  `raycast.hit_at`); Image Editor -- `scatter_2d`. M = dent size. `step_region` = the
  dents' box. `particle_count`, `particle_bounces`.
* **Noise Blur**: `noise_blur`: each pixel = mean of `noise_samples(grain)` random
  pixels within `noise_scatter`.
* **Pull**: liquify. A (H, W, 2) displacement field per stroke; `pull_mode` DRAG:
  `pull_field_step` (the cursor move), PINCH / PUSH: `pinch_field_step` per spaced stamp
  (radial, `PINCH_RATE` x the distance to the center; RMB the opposite); both compose with
  the earlier field (`_compose`), `warp` resamples the stroke snapshot (nearest;
  `pull_smooth`: bilinear).
* **Repair**: healing. `heal` adds the Shepard-interpolated border difference
  (destination - source) to the source patch; `repair_texture` blends toward the pure
  membrane fill. `repair_mode` AUTO: `best_offset` per stamp (border SSD over
  `candidate_offsets`); SOURCE: RMB sets state `repair_source`, the next stroke fixes
  `repair_offset` (aligned), read from the stroke snapshot; `overlays/special.py` marks
  the source (Image Editor).
* Window: a `Dial` -- center = the shown brush (tap: select / back), inner ring top the
  five brushes (Particles, Rust, Noise Blur, Pull, Repair; `BrushesActions.toggle_special`: tapping the selected one returns to
  state `brushes_return`), bottom the shown brush's two settings (`ShownArcSlider` /
  option buttons). Edge mode: the brushes work in image space (no seam crossing).

## Settings popup (`ui/panels/settings_popup.py`)

The N-panel / tool header keep only the controls used while painting; options
that are set once and rarely touched live in the settings popup, a popover
panel (`IMAGE_PT_pixel_painter_settings`) with a header bar of categories
(`pixel_painter_settings_tab`, remembered). Open it with
`image.pixel_painter_open_settings` (optional `tab=`) or the Settings button in
the N-panel / header; the pen menu has its own version of it (`ui/pen/windows/settings.py`):
a setting added here should be added there too.
To add a category, add an entry to `SETTINGS_TABS` and a drawer to `_TAB_DRAWERS`.

## Native backend (C#)

Pixel-heavy work runs in a C# library when it is available and the setting
**Use C# Backend** (`pixel_painter_use_native`, default on; settings popup and
pen menu > *Performance*) is enabled. Every Python implementation stays in
place as the fallback, so the addon works without the library.

```
native/
  PixelPainterNative/   C# project (NativeAOT -> plain native library, no .NET runtime needed)
    Exports.cs          C ABI entry points (pp_*), ApiVersion
    Blend.cs            blend modes (mirrors paint/blending.py)
    Paint.cs            brush paint, alpha, erase, mask restore
    Filters.cs          smooth (summed-area table), smear
    Stamps.cs           brush footprints: kernel / spray stamps, max-merge, stroke grid
    Regions.cs          selection region blend / blit
    Raster.cs           UV triangle rasterization (mask, Paint Selected Faces)
  build.ps1             build -> native/runtimes/<rid>/PixelPainterNative.{dll,so,dylib}
  runtimes/<rid>/       the built library (committed)
utils/native.py         ctypes loader + NumPy wrappers, enabled(), status()
utils/pixel_io.py       image pixel access shared by both backends
paint/native_paths.py   tool-level fast paths (footprint + paint of a whole draw step)
```

* **Build**: `powershell -ExecutionPolicy Bypass -File native/build.ps1` (.NET 10
  SDK + MSVC Build Tools on Windows). NativeAOT does not cross-compile between
  operating systems: build Linux / macOS libraries there. Blender keeps the
  library loaded: restart Blender after rebuilding.
* **Two layers**: the pixel kernels (`paint.pixels.write_pixels_to_image`,
  `set_pixels_alpha`, `paint.smooth.*`, `mask_guard.restore_all`,
  `selection.geometry.blit_region`, `paint.blending.blend_region_pixels`,
  `mask.geometry.raster_triangles`, Paint Selected Faces) each start with an
  `if native.enabled():` branch. On top of that, the stroke tools' `on_draw`
  build the whole footprint in C# via `paint/native_paths.py` (not in the 3D
  Viewport's Edge mode, where `env.expand` maps stamps over seams in Python).
* **3D Viewport, UV mode**: every stamp is clipped to the UV island under its
  center (`core.view3d.islands.island_map` / `IslandClip`, set as `env.islands` by
  `StrokeTool.paint`), so a brush near an island's edge never spills onto
  neighbouring islands or the padding. Python footprints go through
  `env.expand` / `env.clip`; the C# stamps take `env.island_labels(centers)`.
  Edge mode drops texels its unfold does not cover (`expand_footprint`).
* **3D Viewport, Edge mode filters**: Smooth and Smear read neighbouring
  pixels, so mapping the stamp alone is not enough. `env.edge_patch`
  (`core.view3d.patch.edge_patch` -> `EdgePatch`) unfolds the surface around each
  stamp (padded by the blur radius / smear reach), gathers it from the image,
  filters it with a `valid` mask (only on-surface texels are read: `pp_smooth`
  / `pp_smear` and the `paint.smooth.*_buffer` fallbacks take it) and
  scatters the result back over the seams (`tools/filters/edge.edge_smooth` /
  `edge_smear`). Smear measures its drag direction on the unfolded surface.
* **Same results**: the C# code mirrors the Python math (float32 where NumPy
  uses float32, colorsys in double, Python rounding). `tests/test_native.py`
  runs both paths on the same images; keep it passing when changing either side.
* **Adding a function**: export it in `Exports.cs` (catch everything, return a
  negative value on failure), add the signature to `_SIGNATURES` and a wrapper
  in `utils/native.py`, call it behind `native.enabled()` with the Python code as
  fallback, add a parity test. Bump `ApiVersion` / `API_VERSION` when a
  signature changes.

### Pixel access (`utils/pixel_io.py`)

Never read `img.pixels` with `np.array(img.pixels)` / `img.pixels[i]` (both copy
the whole image, the first element by element in Python) or write it directly
in painting code. Use `pixel_io`:

```python
arr = pixel_io.read(img)      # private copy (safe to keep, e.g. a back buffer)
buf = pixel_io.buffer(img)    # buffer to edit in place ...
pixel_io.write(img, buf)      # ... then always write it back
```

A stroke (`StrokeTool.begin_stroke` .. `end_stroke`) keeps the image in a
working buffer, read once; `StrokeTool.paint` wraps each draw step in
`pixel_io.deferred(img)`, so the step uploads once after the paint mask.
Code that writes `img.pixels` some other way must call `pixel_io.invalidate()`.

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
`UNDO` flag call `commit(img, push=False)` instead. A step stores only the
bounding box of the changed pixels (before and after); `begin` / `commit` read
through `utils/pixel_io`, so call them while a stroke's working buffer is
active (`pixel_io.begin_stroke` before `begin`, `commit` before `end_stroke`).

Per-event code must not write add-on properties unconditionally: every write
sends a window-wide redraw notifier, even for an unchanged value. Use
`utils.settings_service.set_if_changed`.

## Tests

```
python -m unittest discover -s tests -v
```
