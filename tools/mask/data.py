"""Mask data: the elements (UV islands / mesh parts) of the painted mesh, which of
them are chosen (scene property, JSON) and :func:`allowed` -- the paintable pixels.

Elements are rebuilt from modal code only (:func:`refresh`, never while drawing);
draw callbacks read the cache (``refresh_data=False``).
"""

import json
import time
import zlib

import numpy as np

from . import geometry as geo


SELECTION_PROP = 'pixel_painter_mask_selection'
CHECK_INTERVAL = 1.0           # seconds between mesh change checks while hovering


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
    from ...core import view3d
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

def allowed_key():
    """Changes whenever :func:`allowed` would return different pixels (draw caches key on it)."""
    return _allowed_key


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
