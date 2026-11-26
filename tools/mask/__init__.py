"""Paint mask: limit painting to chosen UV islands or mesh parts.

Settings (WindowManager, ``pixel_painter_mask_*``): *enabled*, *source*
(``UV_ISLAND`` / ``MESH_PART``), *invert*, *grow* (pixels added around each
island) and *show* (red stripes over the blocked area). The chosen islands / parts are
stored per project in the scene property ``pixel_painter_mask_selection``
(JSON ``{object name: [face index, ...]}``: one face per chosen element, so a
choice survives mesh edits that keep that face in the element).

Modules: :mod:`.data` (elements, chosen set, :func:`~.data.allowed`),
:mod:`.geometry` (pure numpy grouping / rasterizing), :mod:`.guard` (enforcement
during strokes), :mod:`.overlay` (drawing), :mod:`.tool` (``MaskTool``, picking).

* Elements come from the active mesh object and the other selected mesh
  objects (base mesh, the paint UV map), grouped with
  :mod:`tools.mask_geometry` and rasterized into pixel sets of the painted
  image's size. They are rebuilt when the mesh, its UVs, the image size or a
  setting changes -- checked from modal events only (never while drawing).
* Painting: chosen elements are paintable, everything else is protected
  (*invert* swaps that). :func:`allowed` gives the paintable pixels;
  ``StrokeTool.paint`` puts protected pixels back after every draw step
  (:mod:`tools.mask_guard`), so every tool is masked the same way.
* Choosing: while *Edit* is on (state ``mask_picking``; the Mask window's
  center button or ``image.pixel_painter_mask_pick``), a press on the canvas toggles
  the element under the cursor; dragging sets every element it passes to the
  same state. Esc / right click end editing. Meanwhile an orange frame runs
  around the editor (``ui/viewport_frame.py``).
"""
