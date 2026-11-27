# APU Pixel Painter

A Blender 4.2 addon for painting low-resolution, pixel-art textures **directly on 3D models**.

Paint in the 3D Viewport (Texture Paint mode) with pixel-exact brushes: every stroke snaps to the texel grid of the model's texture, without anti-aliasing or blur. The Image Editor is supported as well, with the same tools and settings.

<!-- Screenshot: pixel-art model being painted in the 3D Viewport, pen menu open -->
<img width="1994" height="951" alt="2026-11-27 00-56-41" src="https://github.com/user-attachments/assets/2d39f9cf-42b8-4ea1-9562-470df0ffe442" />


> DISCLAIMER: Coded primarily with Claude, partially by hand. The main goal was a drawing tool and UI that is easier to use, especially for the niche use case of pixel art.

## Pixel Art on 3D Models

- **Paints on the mesh**: the hovered texel comes from a raycast on the active mesh, so you paint where you point, at the texture's real resolution.
- **UV mode**: each stamp is clipped to the UV island under the cursor. Brushes near an island edge do not spill onto neighbouring islands or the padding.
- **Edge mode**: strokes continue across UV seams by unfolding the surface around the brush. Smooth and Smear also read and write across seams.
- **Pixel grid on the mesh**: a texel-border overlay drawn on the model; it fades out when texels get too small to read.
- **View window**: axis views, orbit / roll steps, Fit, Center, Zoom and Persp / Ortho, so you can navigate with a pen alone.
- **Paint Selected Faces**: fills the UV area of the selected faces with the primary color.
- **Save button**: saves or packs the painted image; a dot shows while it has unsaved changes.

## Tools

Circle, Square, Line, Spray, Eraser, Smooth, Smear, Select (copy / paste) and Mask. Per tool falloff, strength, alpha and blend mode. Once, Fixed or Time spacing per tool, and Alpha Lock (protects transparent pixels).

<!-- Screenshot: tools / brush outline on a model -->
<img width="307" height="231" alt="image" src="https://github.com/user-attachments/assets/78204197-4436-4759-b0dc-7952801d390b" />

## Pen Menu

An on-canvas dial for pens and tablets (enable **Pen Bar** in the tool header).

<!-- Screenshot: pen menu -->
<img width="366" height="349" alt="image" src="https://github.com/user-attachments/assets/74e23180-088b-44e3-9cbb-024f5c95b114" />

- **No hover required**: everything works with press, drag and release, because pens often cannot move the pointer without touching.
- **Dial layout**: the Size knob in the center, with pie segments in two rings around it. Categories are separated by a wider gap and a divider line.
- **Radial sliders** (Strength, Alpha, Modifier): pressing sets the value from the distance to the center, and dragging keeps setting it.
- **Color section**: primary and secondary color, each with its own eyedropper, plus Swap. A gradient slider between the two picks an optional third (tertiary) color.
- **Color history**: the last painted colors along the outer ring; tap one to paint with it.
- **Palette band**: 24 slots. **Palettes** switches the band to the project's 24 palettes.
- **Palettes**: stored per project in the .blend. A library window imports and exports them to `palettes.json` or the clipboard. *From image...* builds a palette from an image's colors.
- **Falloff field**: one 2D swipe sets hardness (toward the center) and sharpness (along the field). A tap jumps. *Curve* opens a custom falloff curve editor.
- **Blend modes**: favorite blend modes as buttons; the Blend flyout holds the rest.
- **Undo / Redo** as buttons on the dial.
- **Grid button**: tap turns the pixel grid on or off; drag up / down sets its opacity.
- **Floating**: drag the background to move the menu, drag the corner triangle to resize it (0.2x–2x), and use the padlock to lock it. The X collapses it to a small *Pen* tab. Position, size and the open windows are stored per project.
- **Windows ring**: opens floating windows (Mask, View, Filling; its outer ring: Special, Backup). They are movable, resizable and lockable like the menu.
- **Filling window**: tools that work on a whole UV island or a whole connected mesh part (the arc on top switches between the two). Tap a tool, and the island / part under the cursor gets an outline (in the 3D Viewport on the mesh, in the Image Editor around its pixels). Tap the canvas to run the tool on that island / part, or tap *All* to run it on every one. The left button uses the primary color first, the right button the secondary color. All tools use the brush's blend mode, strength and alpha, and respect the mask and Alpha Lock.
  - **Fill**: fills the island / part with one color.
  - **Edges**: a band along the model's edges (edges sharper than an angle, all edges, or edges marked sharp; not the UV borders). It runs from the primary color on the edge to the secondary color and can fade out. *Symmetric* gives the same width on both sides of every edge; *Pixel line* snaps the edge onto a one-pixel line and spreads the band evenly from it. Settings: edge type, angle, placement, width per side, and a falloff curve with presets (Linear, Constant, Smooth, Sphere, Root, Plateau, Stepped, Ring, Inverted).
  - **Ambient Occlusion**: casts rays from every texel of the mesh. The result is a ramp from the secondary color (open) to the primary color (occluded), shaped by an AO curve with presets (Linear, Smooth, Strong, Contact, Hard, Stepped, Inverted). Settings: samples and distance. With *Fade*, open areas keep their pixels.
  - The settings of the armed tool sit around the window's circle like the pen menu: choices as icon buttons in the rings, the sliders on the outer ring's sides, colored by kind (tools blue as in the pen menu). *Placement* swaps between Symmetric and Pixel line; *Curve* folds the tool's curve editor out under the circle.
- **Mask editing** outlines the island / part under the cursor as well. The *Opacity* slider beside *Show* in the Mask window sets how strong the red stripes over protected areas are (its first half covers 0–10 % for fine control).
- **Special window** (Windows ring, outer ring): special brushes. Tap one to paint with it; tap it again to go back to the tool you used before. Size, strength, alpha, M and the falloff are set on the pen menu as for every tool; the window holds each brush's own two settings. All of them respect the mask, Alpha Lock and undo.
  - **Rust**: mottled patches mixing the primary and secondary color (right button: swapped). The pattern is anchored to the texture, so going over a spot again keeps the same rust. *Scale*: patch size; *Coverage*: how patchy.
  - **Particles**: in the 3D Viewport, small bodies are thrown at the model and fall under gravity. A hard hit bounces (*Bounces* times, small hops), then they **slide down the surface** -- over bends, along walls, wrapping around edges and running down the next face (fast ones fly off edges) -- leaving a dent where they land and a streak where they slide: chipped edges, runs, wear and tear. They stop when they come to rest or once they are well outside the model (its bounding box x2). In the Image Editor they land in the brush and hop downward. *Count* per stamp, *Size* the dent radius, *Amount* how strongly they paint. While you paint, their paths and impacts are drawn over the canvas and fade out.
  - **Noise Blur**: a grainy blur -- pixels take random neighbours. *Scatter*: how far; *Grain*: fewer samples, noisier.
  - **Pull**: liquify. *Drag* moves pixels along with the cursor without smearing; *Pinch* sucks them into the brush's center, *Push* pushes them away from it (the right button does the opposite). *Pixel* keeps pixels crisp, *Smooth* blends between them.
  - **Repair**: a healing brush. *Auto* finds a matching patch around each stamp (spot healing). *Source*: right-click sets the source, then strokes copy from it (aligned) while the colors are matched to the surroundings. *Texture* 0 gives only a smooth fill.
- **Backup window** (Windows ring, outer ring, beside Settings): an optional texture backup. *Run backup program* starts a small program next to Blender (Blender's own Python, no extra install). It keeps every texture with unsaved changes in RAM -- nothing is written while you work -- and only when Blender closes or crashes does it write them to disk, then it quits itself. Textures you saved are dropped from it, so closing with everything saved leaves no backup.
  - **Backups**: the last 1-5 backups (*Keep backups*), each with date, *crashed* / *closed*, the .blend and its textures. *Images* lists a backup's textures, *Restore* restores one or all of them: an image with the same name and size gets its pixels back (undoable), otherwise a new image is created (*Restore as copy*: always a new image).
  - **Options**: *Delete after* N days (0 = never), *Sync every* N seconds, *Clear cache*, *Open folder*. The cache lives in Blender's config folder (`config/apu_pixel_painter/backup`), documented by `index.json`. The same controls are in the settings popup's *Backup* tab.

### Color Selector

<!-- Screenshot: color selector -->
<img width="221" height="187" alt="image" src="https://github.com/user-attachments/assets/c260a375-53ed-4f8a-bdca-96132b7f6276" />

- **Relative swipes**: press anywhere on a part and drag. The selection moves by the drag distance instead of jumping under the pen; a tap jumps.
- **Shift** slows the movement for fine adjustments. RMB / Esc restores the previous color.
- **Hue and saturation survive** dragging through grey or black.
- **Old / new bubble**: compares the new color with the previous one. With *Preview* on, the brush keeps its color until you tap the bubble.

### Color Dragging

<!-- Screenshot / GIF: dragging a color onto a palette slot -->
<img width="205" height="116" alt="image" src="https://github.com/user-attachments/assets/3b5f104e-93e4-4efd-ba81-1765be8e001d" />

Colors can be dragged between the pen menu's widgets (setting: *Drag Colors*). A short press still counts as a tap.

- **Drag sources**: primary / secondary color, the tertiary bubble, history colors, palette colors, and the color selector's old / new bubble.
- **Drop on a palette slot**: stores the color there; palette onto palette swaps the two.
- **Drop on primary / secondary**: sets that color.
- **Drop a palette color off the menu**: removes it from the palette.
- **Whole palettes**: in the palette view, palettes are dragged the same way: slot to slot (swap), into the library (save), or from the library onto a slot (load). Dropping a palette off the menu deletes it after a confirmation.
- **Empty slots**: tap an empty slot to store the current color.

## Shortcuts

| Key | Action |
| --- | --- |
| Ctrl | Color picker |
| Alt | Line drawer |
| Shift | Smoothing (LMB) / Eraser (RMB) |
| W | Tool menu |
| Shift + W | Blend modes |
| E | Color select |
| Shift + E | Strength, Modifier, Alpha menu |
| Shift + 1–7 | Quick tool selection |

In Selection mode:

| Key | Action |
| --- | --- |
| Ctrl + C / Ctrl + V | Copy / paste |
| Shift | Mirrored scaling of the selection rectangle |

## Settings

The N-panel and the settings popup contain:

- **Spacing** (bottom right, per tool; *Spacing per tool* off in the settings: one for all): the button on the left steps *Once* → *Fixed* → *Time*, the slider right of it shows its value. *Once* paints every pixel once per stroke, no build-up (value: pixels per stamp); *Fixed* builds up with a stamp every N pixels (1 = every pixel); *Time* stamps every N ms while held, also standing still (airbrush; the first 60 % of the slider cover up to 100 ms).
- **Shared settings**: whether tools share global Size, Strength, Alpha and Modifier, or keep their own.
- **Pen UI**: menu side, Reset Pen UI, color preview, Drag Colors, pressure mapping.
- **Saving**: Auto / Pack / File, optionally saving the .blend afterwards.
- **Performance**: an optional C# backend (Windows, `native/`) for pixel-heavy operations. The NumPy fallback produces the same results.
- **Backup**: the texture backup program (see the Backup window above).

## Requirements

Blender 4.2.

<details>
<summary>Older screenshots</summary>

<img width="646" height="661" alt="2026-04-19 19-19-18" src="https://github.com/user-attachments/assets/2ec504ea-4fdd-437b-adf3-cc16e735dbda" />
<img width="397" height="356" alt="2026-04-19 19-19-08" src="https://github.com/user-attachments/assets/36a1daf2-6d37-47a4-b109-8bd883d385bb" />
<img width="558" height="409" alt="2026-04-19 19-18-48" src="https://github.com/user-attachments/assets/16031655-11cc-4d79-864a-54554d6e9ff6" />
<img width="606" height="352" alt="2026-04-19 19-18-36" src="https://github.com/user-attachments/assets/e91eead1-4363-46be-8cab-adadd8a89a83" />
<img width="724" height="439" alt="2026-04-19 19-18-25" src="https://github.com/user-attachments/assets/e02ee9d2-d529-49b4-a94d-4b91e4528ee2" />
<img width="582" height="578" alt="2026-04-19 19-18-11" src="https://github.com/user-attachments/assets/74f07c28-0011-4827-b3fd-963e0021a2a4" />
<img width="437" height="1052" alt="2026-04-19 19-19-32" src="https://github.com/user-attachments/assets/9ee75fb7-4359-492e-bfe1-8387523bf534" />
<img width="708" height="712" alt="image" src="https://github.com/user-attachments/assets/179a7d98-a869-4b81-853a-3e6933fc55f7" />

</details>
