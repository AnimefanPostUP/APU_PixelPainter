"""Paint mask: limit painting to chosen UV islands or mesh parts.

Settings (WindowManager, ``pixel_painter_mask_*``): *enabled*, *source*
(``UV_ISLAND`` / ``MESH_PART``), *invert*, *grow* (pixels added around each
island) and *show* (red stripes over the blocked area). The chosen islands / parts are
stored per project in the scene property ``pixel_painter_mask_selection``
(JSON ``{object name: [face index, ...]}``: one face per chosen element, so a
choice survives mesh edits that keep that face in the element).

* Elements come from the active mesh object and the other selected mesh
  objects (base mesh, the paint UV map), grouped with
  :mod:`tools.mask_geometry` and rasterized into pixel sets of the painted
  image's size. They are rebuilt when the mesh, its UVs, the image size or a
  setting changes -- checked from modal events only (never while drawing).
* Painting: chosen elements are paintable, everything else is protected
  (*invert* swaps that). :func:`allowed` gives the paintable pixels;
  ``StrokeTool.paint`` puts protected pixels back after every draw step
  (:func:`restore_blocked`), so every tool is masked the same way.
* Choosing: while *Pick* is on (state ``mask_picking``; the pen menu's Pick
  button or ``image.pixel_painter_mask_pick``), a press on the canvas toggles
  the element under the cursor; dragging sets every element it passes to the
  same state. Esc / right click end picking.
"""

import json
import time
import zlib

import blf
import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader

from ..core.framework import Shortcut, ToolFrame
from ..utils import native, pixel_io
from . import mask_geometry as geo


SELECTION_PROP = 'pixel_painter_mask_selection'
CHECK_INTERVAL = 1.0           # seconds between mesh change checks while hovering
# Protected area: diagonal stripes of red and lighter red, 15% visible.
STRIPE_DARK = (0.85, 0.08, 0.08, 0.15)
STRIPE_LIGHT = (1.00, 0.50, 0.50, 0.15)
STRIPE_WIDTH = 8.0             # screen px per stripe (times the UI scale)
PICK_HINT = "Mask: tap islands / parts to toggle them  ·  Esc: done"
VIEW_OFFSET = 0.002            # 3D overlay pulled towards the viewer (fraction of view distance)


# ---------------------------------------------------------------------------
# Elements
# ---------------------------------------------------------------------------

class Element:
    __slots__ = ('obj', 'faces', 'pixels')

    def __init__(self, obj, faces, pixels):
        self.obj = obj          # object name
        self.faces = faces      # sorted polygon indices
        self.pixels = pixels    # sorted flat pixel indices


class MaskData:
    def __init__(self, key, size, elements, version):
        self.key = key
        self.size = size
        self.elements = elements
        self.version = version


_data = None
_version = 0
_last_check = 0.0
_allowed_key = None
_allowed = None


def invalidate():
    global _data, _allowed_key, _allowed
    _data = None
    _allowed_key = None
    _allowed = None


def _settings(wm):
    return (getattr(wm, 'pixel_painter_mask_source', 'UV_ISLAND'),
            int(getattr(wm, 'pixel_painter_mask_grow', 0)))


def _objects(context):
    objs = []
    active = getattr(context, 'active_object', None)
    if active is not None and active.type == 'MESH':
        objs.append(active)
    for obj in getattr(context, 'selected_objects', None) or ():
        if obj.type == 'MESH' and obj not in objs:
            objs.append(obj)
    return objs


def _uv_name(context, obj):
    from ..core import view3d
    return view3d._uv_layer_name(context, obj)


def _read_mesh(context, obj):
    """Numpy arrays of the base mesh (edit-mode changes synced first), or None."""
    if obj.mode == 'EDIT':
        obj.update_from_editmode()
    me = obj.data
    uv_name = _uv_name(context, obj)
    uv_layer = me.uv_layers.get(uv_name) if uv_name else None
    if uv_layer is None:
        uv_layer = me.uv_layers.active
    if uv_layer is None or len(me.polygons) == 0:
        return None
    n_polys, n_loops, n_edges = len(me.polygons), len(me.loops), len(me.edges)
    loop_start = np.empty(n_polys, dtype=np.int32)
    me.polygons.foreach_get('loop_start', loop_start)
    loop_total = np.empty(n_polys, dtype=np.int32)
    me.polygons.foreach_get('loop_total', loop_total)
    loop_vert = np.empty(n_loops, dtype=np.int32)
    me.loops.foreach_get('vertex_index', loop_vert)
    uvs = np.empty(n_loops * 2, dtype=np.float32)
    uv_layer.data.foreach_get('uv', uvs)
    edges = np.empty(n_edges * 2, dtype=np.int32)
    me.edges.foreach_get('vertices', edges)
    fingerprint = (obj.name, me.name, uv_layer.name, n_polys, n_loops, n_edges, len(me.vertices),
                   zlib.crc32(uvs.tobytes()), zlib.crc32(loop_vert.tobytes()))
    return dict(mesh=me, loop_start=loop_start, loop_total=loop_total, loop_vert=loop_vert,
                uvs=uvs.reshape(-1, 2), edges=edges, n_verts=len(me.vertices), fingerprint=fingerprint)


def _elements(obj_name, arrays, source, w, h, grow):
    me = arrays['mesh']
    if source == 'MESH_PART':
        labels = geo.mesh_part_labels(arrays['loop_start'], arrays['loop_vert'], arrays['n_verts'], arrays['edges'])
    else:
        labels = geo.uv_island_labels(arrays['loop_start'], arrays['loop_total'], arrays['loop_vert'], arrays['uvs'])
    me.calc_loop_triangles()
    n_tris = len(me.loop_triangles)
    tri_loops = np.empty(n_tris * 3, dtype=np.int32)
    me.loop_triangles.foreach_get('loops', tri_loops)
    tri_poly = np.empty(n_tris, dtype=np.int32)
    me.loop_triangles.foreach_get('polygon_index', tri_poly)
    tri_uv = arrays['uvs'][tri_loops.reshape(-1, 3)]          # (T, 3, 2)
    tri_label = labels[tri_poly]
    count = int(labels.max()) + 1 if len(labels) else 0
    face_order = np.argsort(labels, kind='stable')
    face_bounds = np.searchsorted(labels[face_order], np.arange(count + 1))
    tri_order = np.argsort(tri_label, kind='stable')
    tri_bounds = np.searchsorted(tri_label[tri_order], np.arange(count + 1))
    elements = []
    for label in range(count):
        faces = np.sort(face_order[face_bounds[label]:face_bounds[label + 1]])
        tris = tri_order[tri_bounds[label]:tri_bounds[label + 1]]
        pixels = geo.raster_triangles(tri_uv[tris], w, h, grow)
        elements.append(Element(obj_name, faces, pixels))
    return elements


def refresh(context, image, force=False):
    """Rebuild the elements if something changed. Call from modal events only (it
    syncs edit-mode meshes); a settings or image size change is picked up at once,
    mesh changes at most every ``CHECK_INTERVAL`` seconds unless ``force``."""
    global _data, _version, _last_check
    if image is None or image.size[0] == 0 or image.size[1] == 0:
        return None
    wm = context.window_manager
    source, grow = _settings(wm)
    w, h = image.size
    head = (source, grow, w, h)
    now = time.perf_counter()
    if (not force and _data is not None and _data.key[0] == head
            and now - _last_check < CHECK_INTERVAL):
        return _data
    _last_check = now
    objs = _objects(context)
    meshes = []
    for obj in objs:
        try:
            arrays = _read_mesh(context, obj)
        except Exception:
            import traceback
            traceback.print_exc()
            arrays = None
        if arrays is not None:
            meshes.append((obj.name, arrays))
    key = (head, tuple(a['fingerprint'] for _n, a in meshes))
    if _data is not None and _data.key == key:
        return _data
    elements = []
    for name, arrays in meshes:
        elements.extend(_elements(name, arrays, source, w, h, grow))
    _version += 1
    _data = MaskData(key, (w, h), elements, _version)
    return _data


def data():
    return _data


# ---------------------------------------------------------------------------
# Selection (scene property, JSON)
# ---------------------------------------------------------------------------

_parsed = (None, {})


def selection(context):
    """``{object name: set(face indices)}`` of the chosen elements."""
    global _parsed
    scene = getattr(context, 'scene', None)
    text = getattr(scene, SELECTION_PROP, "") if scene is not None else ""
    if _parsed[0] != text:
        try:
            raw = json.loads(text) if text else {}
            sel = {str(k): set(int(f) for f in v) for k, v in raw.items()}
        except Exception:
            sel = {}
        _parsed = (text, sel)
    return {k: set(v) for k, v in _parsed[1].items()}


def _store(context, sel):
    scene = getattr(context, 'scene', None)
    if scene is None or not hasattr(scene, SELECTION_PROP):
        return
    clean = {k: sorted(v) for k, v in sel.items() if v}
    setattr(scene, SELECTION_PROP, json.dumps(clean, sort_keys=True) if clean else "")


def _selection_text(context):
    scene = getattr(context, 'scene', None)
    return getattr(scene, SELECTION_PROP, "") if scene is not None else ""


def is_chosen(element, sel):
    faces = sel.get(element.obj)
    if not faces:
        return False
    return bool(np.isin(element.faces, np.fromiter(faces, dtype=np.int64)).any())


def clear(context):
    _store(context, {})


def element_at(mask_data, x, y):
    """The element covering pixel ``(x, y)`` (the smallest one where they overlap), or None."""
    if mask_data is None or x is None or y is None:
        return None
    w, h = mask_data.size
    if not (0 <= x < w and 0 <= y < h):
        return None
    pixel = y * w + x
    hits = [e for e in mask_data.elements if geo.contains(e.pixels, pixel)]
    return min(hits, key=lambda e: len(e.pixels)) if hits else None


def set_chosen(context, element, chosen):
    sel = selection(context)
    faces = sel.setdefault(element.obj, set())
    if chosen:
        faces.add(int(element.faces[0]))
    else:
        faces.difference_update(int(f) for f in element.faces)
    _store(context, sel)


# ---------------------------------------------------------------------------
# Painting
# ---------------------------------------------------------------------------

def active(wm):
    return bool(getattr(wm, 'pixel_painter_mask_enabled', False))


def allowed(context, image, refresh_data=True):
    """Flat bool array (one per pixel) of paintable pixels, or None (no masking).

    ``refresh_data``: check for mesh changes first (modal code only)."""
    global _allowed_key, _allowed
    wm = context.window_manager
    if not active(wm) or image is None:
        return None
    mask_data = refresh(context, image) if refresh_data else _data
    if mask_data is None or not mask_data.elements or tuple(mask_data.size) != tuple(image.size):
        return None   # no mesh / UVs to mask with: paint normally
    invert = bool(getattr(wm, 'pixel_painter_mask_invert', False))
    key = (mask_data.version, _selection_text(context), invert)
    if key != _allowed_key:
        w, h = mask_data.size
        chosen = np.zeros(w * h, dtype=bool)
        sel = selection(context)
        for element in mask_data.elements:
            if is_chosen(element, sel):
                chosen[element.pixels] = True
        _allowed = ~chosen if invert else chosen
        _allowed_key = key
    return _allowed


def snapshot(image):
    return pixel_io.read(image)


def restore_blocked(image, before, allowed_pixels):
    """Put back the protected pixels a draw step changed."""
    if before is None or allowed_pixels is None or len(before) != len(allowed_pixels) * 4:
        return
    if native.enabled():
        after = pixel_io.buffer(image)
        restored = native.restore_blocked(after, before, allowed_pixels)
        if restored is not None:
            if restored:
                pixel_io.write(image, after)
            return
    after = snapshot(image)
    a4, b4 = after.reshape(-1, 4), before.reshape(-1, 4)
    changed = ~allowed_pixels & np.any(a4 != b4, axis=1)
    if changed.any():
        a4[changed] = b4[changed]
        pixel_io.write(image, after)


# ---------------------------------------------------------------------------
# Overlays (draw callbacks: read the cached data only)
# ---------------------------------------------------------------------------

_batch2d = (None, None)
_local3d = (None, None)
_stripe_shader = None
_stripe_failed = False


def _stripes():
    """Shader filling triangles with diagonal stripes (screen space), or None if unsupported."""
    global _stripe_shader, _stripe_failed
    if _stripe_shader is None and not _stripe_failed:
        try:
            info = gpu.types.GPUShaderCreateInfo()
            info.push_constant('MAT4', 'mvp')
            info.push_constant('VEC4', 'color_a')
            info.push_constant('VEC4', 'color_b')
            info.push_constant('FLOAT', 'stripe')
            info.vertex_in(0, 'VEC3', 'pos')
            info.fragment_out(0, 'VEC4', 'FragColor')
            info.vertex_source("void main() { gl_Position = mvp * vec4(pos, 1.0); }")
            info.fragment_source(
                "void main() {"
                "  float t = mod((gl_FragCoord.x + gl_FragCoord.y) / stripe, 2.0);"
                "  FragColor = t < 1.0 ? color_a : color_b;"
                "}")
            _stripe_shader = gpu.shader.create_from_info(info)
        except Exception:
            import traceback
            traceback.print_exc()
            _stripe_failed = True
    return _stripe_shader


def _draw_striped(coords3, context):
    """Draw (N, 3) triangle vertices with the stripe pattern (fallback: plain red, 15%)."""
    shader = _stripes()
    if shader is not None:
        batch = batch_for_shader(shader, 'TRIS', {"pos": coords3})
        scale = getattr(context.preferences.system, 'ui_scale', 1.0)
        shader.bind()
        shader.uniform_float("mvp", gpu.matrix.get_projection_matrix() @ gpu.matrix.get_model_view_matrix())
        shader.uniform_float("color_a", STRIPE_DARK)
        shader.uniform_float("color_b", STRIPE_LIGHT)
        shader.uniform_float("stripe", STRIPE_WIDTH * scale)
        batch.draw(shader)
        return
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'TRIS', {"pos": coords3})
    shader.bind()
    shader.uniform_float("color", STRIPE_DARK)
    batch.draw(shader)


def _blocked_for_draw(context, image):
    """Cached paintable pixels for drawing (no mesh access), or None."""
    wm = context.window_manager
    if not active(wm) or not getattr(wm, 'pixel_painter_mask_show', True):
        return None
    return allowed(context, image, refresh_data=False)


def draw_2d(context, v2d, image):
    """Image Editor: red stripes over the protected pixels (POST_PIXEL)."""
    global _batch2d
    if v2d is None or image is None:
        return
    allowed_pixels = _blocked_for_draw(context, image)
    if allowed_pixels is None:
        return
    w, h = image.size
    if _batch2d[0] != _allowed_key:
        rows, starts, ends = geo.blocked_runs(~allowed_pixels.reshape(h, w))
        verts = geo.run_triangles(rows, starts, ends)
        verts3 = np.zeros((len(verts), 3), dtype=np.float32)
        verts3[:, :2] = verts
        _batch2d = (_allowed_key, verts3 if len(verts3) else None)
    verts3 = _batch2d[1]
    if verts3 is None:
        return
    x0, y0 = v2d.view_to_region(0.0, 0.0, clip=False)
    x1, y1 = v2d.view_to_region(1.0, 1.0, clip=False)
    gpu.state.blend_set('ALPHA')
    with gpu.matrix.push_pop():
        gpu.matrix.translate((x0, y0))
        gpu.matrix.scale(((x1 - x0) / w, (y1 - y0) / h))
        _draw_striped(verts3, context)
    gpu.state.blend_set('NONE')


def draw_3d(context, image):
    """3D Viewport: red stripes over mesh triangles whose UV center is protected (POST_VIEW)."""
    global _local3d
    from ..core import view3d
    allowed_pixels = _blocked_for_draw(context, image)
    if allowed_pixels is None:
        return
    cache = view3d.cached_mesh()
    rv3d = getattr(context, 'region_data', None)
    if cache is None or rv3d is None:
        return
    obj = bpy.data.objects.get(cache.key[0])
    if obj is None:
        return
    w, h = image.size
    key = (cache.version, _allowed_key)
    if _local3d[0] != key:
        center = cache.tri_uv.mean(axis=1)
        px = np.floor(center[:, 0] * w).astype(np.int64)
        py = np.floor(center[:, 1] * h).astype(np.int64)
        inside = (px >= 0) & (px < w) & (py >= 0) & (py < h)
        blocked = np.zeros(len(center), dtype=bool)
        blocked[inside] = ~allowed_pixels[py[inside] * w + px[inside]]
        _local3d = (key, cache.tri_pos[blocked])
    local = _local3d[1]
    if local is None or len(local) == 0:
        return
    from .overlays_view3d import _to_world_towards_view
    coords = _to_world_towards_view(local, obj, rv3d)
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_mask_set(False)
    gpu.state.depth_test_set('LESS_EQUAL')
    try:
        _draw_striped(coords, context)
    finally:
        gpu.state.depth_test_set('NONE')
        gpu.state.blend_set('NONE')


def _draw_hint(context):
    region = getattr(context, 'region', None)
    if region is None:
        return
    font = 0
    size = int(13 * context.preferences.system.ui_scale)
    blf.size(font, size)
    tw, th = blf.dimensions(font, PICK_HINT)
    x, y = (region.width - tw) * 0.5, 40.0 * context.preferences.system.ui_scale
    pad = 6.0
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    box = [(x - pad, y - pad), (x + tw + pad, y - pad), (x + tw + pad, y + th + pad), (x - pad, y + th + pad)]
    gpu.state.blend_set('ALPHA')
    batch = batch_for_shader(shader, 'TRI_FAN', {"pos": box})
    shader.bind()
    shader.uniform_float("color", (0.1, 0.1, 0.1, 0.85))
    batch.draw(shader)
    blf.position(font, x, y, 0)
    blf.color(font, 1.0, 1.0, 1.0, 1.0)
    blf.draw(font, PICK_HINT)
    gpu.state.blend_set('NONE')


# ---------------------------------------------------------------------------
# Picking tool
# ---------------------------------------------------------------------------

def _redraw_editors(context):
    try:
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type in {'IMAGE_EDITOR', 'VIEW_3D'}:
                    area.tag_redraw()
    except Exception:
        pass


def set_picking(state, context, on):
    """Start / stop choosing elements on the canvas (starting also turns the mask on)."""
    state['mask_picking'] = bool(on)
    state['mask_pick_value'] = None
    if on:
        wm = context.window_manager
        if not active(wm):
            wm.pixel_painter_mask_enabled = True
    _redraw_editors(context)


class MaskTool(ToolFrame):
    """Global tool: element picking on the canvas, keeps the mask data fresh, draws the overlay."""

    label = "Mask"
    is_global = True
    priority = 150              # after the pen bar (its buttons win), before tool shortcuts

    state_defaults = {
        'mask_picking': False,     # canvas presses toggle islands / parts
        'mask_pick_value': None,   # True / False while a pick drag sets elements to it
    }

    def on_register(self):
        self.bind(Shortcut('LEFTMOUSE'), self._press)
        self.bind(Shortcut('LEFTMOUSE', 'RELEASE'), self._release)
        self.bind(Shortcut(('ESC', 'RIGHTMOUSE')), self._stop)

    def on_interrupt(self, ctx):
        ctx.state['mask_pick_value'] = None

    def on_session_end(self, ctx):
        ctx.state['mask_picking'] = False
        ctx.state['mask_pick_value'] = None

    def _apply(self, ctx, value=None):
        """Toggle (``value`` None) or set the element under the cursor; returns its new state."""
        img = ctx.image
        mask_data = refresh(ctx.context, img, force=value is None)
        element = element_at(mask_data, *ctx.cursor)
        if element is None:
            return None
        chosen = is_chosen(element, selection(ctx.context))
        target = (not chosen) if value is None else value
        if target != chosen:
            set_chosen(ctx.context, element, target)
            _redraw_editors(ctx.context)
        return target

    def _press(self, ctx, event):
        if not ctx.state.get('mask_picking'):
            return False
        ctx.state['mask_pick_value'] = self._apply(ctx)
        return True

    def _release(self, ctx, event):
        if not ctx.state.get('mask_picking'):
            return False
        ctx.state['mask_pick_value'] = None
        return True

    def _stop(self, ctx, event):
        if not ctx.state.get('mask_picking') or not event.is_press:
            return False
        set_picking(ctx.state, ctx.context, False)
        return True

    def on_event(self, ctx, event):
        if event.type != 'MOUSEMOVE':
            return
        value = ctx.state.get('mask_pick_value')
        if ctx.state.get('mask_picking') and value is not None:
            self._apply(ctx, value)
            event.consume()
        elif active(ctx.wm):
            refresh(ctx.context, ctx.image)

    def draw_overlay(self, ctx):
        # The shading itself is drawn by the core under all tool overlays (draw_2d / draw_3d).
        if ctx.state.get('mask_picking') and not getattr(ctx.wm, 'pixel_painter_pen_bar', False):
            _draw_hint(ctx.context)
