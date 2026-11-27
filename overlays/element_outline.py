"""Hover outline of an element (UV island / mesh part, :mod:`core.view3d.elements`):
its border edges on the mesh (3D Viewport, POST_VIEW) and its texel contour (Image
Editor, POST_PIXEL). Shown while the Extras window has a tool armed and while editing
the paint mask.

Tools set the hovered element from modal code (:func:`set_hover`); the draw callbacks
only read it. ``owner`` names who set it -- the outline is dropped as soon as that owner
is no longer active (``active(state)`` is checked while drawing).
"""

import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader

from ..core.view3d import mesh as v3d_mesh


SHADOW = (0.0, 0.0, 0.0, 0.75)
WIDTH = 2.0              # line width, screen px (times the UI scale)
SHADOW_WIDTH = 4.0
HIDDEN_ALPHA = 0.25      # the part of a 3D outline behind geometry

_hover = None            # (owner, active(state) -> bool, ElementMap, label, rgba)
_batch2d = (None, None)  # ((map key, label), GPUBatch)


def set_hover(owner, active, emap, label, color):
    """Outline ``label`` of ``emap`` (None: nothing) for ``owner`` while ``active(state)``.
    Returns True when the outline changed (the caller redraws)."""
    global _hover
    new = None if emap is None or label is None else (owner, active, emap, int(label), tuple(color))
    old = _hover
    _hover = new
    if old is None or new is None:
        return old is not new
    return old[0] != new[0] or old[2] is not new[2] or old[3] != new[3]


def clear(owner=None):
    """Drop the outline (only ``owner``'s when given). True when there was one."""
    global _hover
    if _hover is None or (owner is not None and _hover[0] != owner):
        return False
    _hover = None
    return True


def _current(state):
    hover = _hover
    if hover is None:
        return None
    try:
        if not hover[1](state):
            return None
    except Exception:
        return None
    return hover


def _scale(context):
    try:
        return float(context.preferences.system.ui_scale)
    except Exception:
        return 1.0


def _lines(batch, shader, color, width, viewport):
    shader.bind()
    shader.uniform_float("viewportSize", viewport)
    shader.uniform_float("lineWidth", width)
    shader.uniform_float("color", color)
    batch.draw(shader)


def draw_2d(context, v2d, image, state):
    """Image Editor: the hovered element's texel contour (POST_PIXEL)."""
    global _batch2d
    hover = _current(state)
    region = getattr(context, 'region', None)
    if hover is None or v2d is None or image is None or region is None:
        return
    _owner, _active, emap, label, color = hover
    w, h = image.size
    if (w, h) != (emap.w, emap.h):
        return
    shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    key = (emap.key, emap.source, label)
    if _batch2d[0] != key:
        seg = emap.outline_2d(label)
        batch = None
        if len(seg):
            pos = np.zeros((len(seg) * 2, 3), dtype=np.float32)
            pos[:, :2] = seg.reshape(-1, 2)
            batch = batch_for_shader(shader, 'LINES', {"pos": pos})
        _batch2d = (key, batch)
    batch = _batch2d[1]
    if batch is None:
        return
    x0, y0 = v2d.view_to_region(0.0, 0.0, clip=False)
    x1, y1 = v2d.view_to_region(1.0, 1.0, clip=False)
    viewport = (float(region.width), float(region.height))
    s = _scale(context)
    gpu.state.blend_set('ALPHA')
    try:
        with gpu.matrix.push_pop():
            gpu.matrix.translate((x0, y0))
            gpu.matrix.scale(((x1 - x0) / w, (y1 - y0) / h))
            _lines(batch, shader, SHADOW, SHADOW_WIDTH * s, viewport)
            _lines(batch, shader, color, WIDTH * s, viewport)
    finally:
        gpu.state.blend_set('NONE')


def draw_3d(context, state):
    """3D Viewport: the hovered element's border edges on the mesh (POST_VIEW)."""
    from .view3d_outline import _to_world_towards_view
    hover = _current(state)
    if hover is None:
        return
    _owner, _active, emap, label, color = hover
    cache = v3d_mesh.cached_mesh()
    rv3d = getattr(context, 'region_data', None)
    region = getattr(context, 'region', None)
    if cache is None or rv3d is None or region is None or emap.key[0] != cache.version:
        return
    obj = bpy.data.objects.get(cache.key[0])
    if obj is None:
        return
    local = emap.outline_3d(cache, label)
    if len(local) == 0:
        return
    coords = _to_world_towards_view(local, obj, rv3d)
    shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'LINES', {"pos": coords})
    viewport = (float(region.width), float(region.height))
    s = _scale(context)
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_mask_set(False)
    try:
        # Behind geometry: faint, so the whole element reads; in front: full.
        gpu.state.depth_test_set('NONE')
        _lines(batch, shader, (*color[:3], HIDDEN_ALPHA), WIDTH * s, viewport)
        gpu.state.depth_test_set('LESS_EQUAL')
        _lines(batch, shader, SHADOW, SHADOW_WIDTH * s, viewport)
        _lines(batch, shader, color, WIDTH * s, viewport)
    finally:
        gpu.state.depth_test_set('NONE')
        gpu.state.blend_set('NONE')
