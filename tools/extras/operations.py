"""The Extras window's operations on one element (UV island / mesh part) or all of them:

* **Fill** -- the element in the primary color (secondary with RMB); with *Fade* the
  color also runs past the element's border into the neighbouring elements (across the
  mesh edges they share, in their own UV space), fading out over ``extras_fill_width``
  texels as the Fill curve says.
* **Edges** -- a band along the model's edges (sharp by angle, all, or marked sharp;
  not the UV borders), the same width on both sides of each edge: primary on the
  edge, running to the secondary color outward, shaped by the Edges falloff curve; with
  *Fade* the band also fades out (RMB swaps the colors).
* **Ambient Occlusion** -- per-texel occlusion of the mesh, through the AO curve
  (``model/value_curve.py``), as a ramp from the secondary (open) to the primary
  (occluded) color; with *Fade* open areas are left alone (RMB swaps the colors).

All of them paint with the brush's blend mode, strength and alpha (the active tool's
values), honor the paint mask and Alphalock and make one undo step. Each returns a short
status text.
"""

import time

import numpy as np

from ...core import history
from ...core.view3d import mesh as v3d_mesh
from ...model import value_curve
from ...paint import edge_ramp, region_paint
from ...utils import blender_utils, pixel_io
from ..mask import data as mask_data
from . import ao


MODES = ('FILL', 'EDGES', 'AO')
LABELS = {'FILL': "Fill", 'EDGES': "Edges", 'AO': "Ambient Occlusion"}


def _wm(ctx, name, default):
    return getattr(ctx.wm, f'pixel_painter_extras_{name}', default)


def _colors(ctx, secondary):
    """``(a, b)``: (primary, secondary) RGB, swapped for the secondary button."""
    a = tuple(ctx.settings.get_brush_rgb(ctx.context))[:3]
    b = tuple(ctx.settings.get_brush_secondary_rgb(ctx.context))[:3]
    return (b, a) if secondary else (a, b)


def _brush(ctx, secondary):
    """``(blend, strength, alpha)`` of the active tool for the button."""
    button = 'RMB' if secondary else 'LMB'
    s, context, mode = ctx.settings, ctx.context, ctx.mode
    strength = s.get_tool_strength(context, mode, force_global=ctx.force_global, button=button)
    alpha = s.get_tool_alpha(context, mode, force_global=ctx.force_global, button=button)
    return blender_utils.get_brush_blend_mode(context), float(strength), float(alpha)


def _paint(ctx, img, idx, rgb, opacity, secondary, message):
    """Blend into ``img`` (mask, Alphalock honored) as one undo step; texels written."""
    idx = np.asarray(idx, dtype=np.int64)
    opacity = np.broadcast_to(np.asarray(opacity, dtype=np.float32), idx.shape)
    rgb = np.asarray(rgb, dtype=np.float32)
    allowed = mask_data.allowed(ctx.context, img)
    if allowed is not None and len(idx):
        keep = allowed[idx]
        idx, opacity = idx[keep], opacity[keep]
        if rgb.ndim > 1:
            rgb = rgb[keep]
    if len(idx) == 0:
        return 0
    blend, strength, alpha = _brush(ctx, secondary)
    protect = bool(getattr(ctx.wm, 'pixel_painter_protect_transparent', False))
    pixel_io.end_stroke()      # never inside a brush stroke's working buffer
    history.begin(img)
    arr = pixel_io.read(img)
    written = region_paint.blend_texels(arr, idx, rgb, opacity * strength, blend, alpha, protect)
    pixel_io.write(img, arr)
    history.commit(img, message)
    return written


def _targets(emap, label):
    return emap.pixels(label)


def fill_fade(ctx, emap, label):
    """Fill's fade-out past the element ``label``: ``(texels, opacity)`` in the
    neighbouring elements, ``extras_fill_width`` texels deep from the shared mesh edges,
    opacity from the Fill curve (1 at the border)."""
    empty = (np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.float32))
    cache = v3d_mesh.mesh_cache(ctx.context)
    if cache is None or label is None:
        return empty
    width = max(1, int(_wm(ctx, 'fill_width', 4)))
    tri, k = edge_ramp.border_sides(cache.tri_verts, emap.tri_label, (int(label),))
    seg, seg_label = _uv_segments(cache, emap, tri, k)
    if len(seg) == 0:
        return empty
    dist = edge_ramp.segment_distance(seg, seg_label, emap.labels, emap.w, emap.h, width + 1.0)
    inside, steps = edge_ramp.band(dist, width, 'BETWEEN')
    idx = np.flatnonzero(inside)
    points = curve_points(ctx.wm, 'fill')
    _t, opacity = edge_ramp.ramp(steps[idx], width, True, curve=lambda x: value_curve.sample(points, x))
    return idx, opacity.astype(np.float32)


def fill(ctx, emap, label, secondary=False):
    img = ctx.image
    idx = _targets(emap, label)
    opacity = np.ones(len(idx), dtype=np.float32)
    faded = 0
    if bool(_wm(ctx, 'fill_fade', False)):
        fade_idx, fade_opacity = fill_fade(ctx, emap, label)
        faded = len(fade_idx)
        idx = np.concatenate((idx, fade_idx))
        opacity = np.concatenate((opacity, fade_opacity))
    color = _colors(ctx, secondary)[0]
    n = _paint(ctx, img, idx, color, opacity, secondary, "Extras: Fill")
    return f"Fill: {n} texels" + (f" ({faded} in the fade)" if faded else "")


def _uv_segments(cache, emap, tri, k):
    """Triangle sides ``(tri, k)`` drawn in their triangle's UV space: ``(segments
    (S, 2, 2) pixel units, element label per segment)``."""
    if len(tri) == 0:
        return np.zeros((0, 2, 2)), np.zeros(0, dtype=np.int64)
    uv = cache.tri_uv - np.floor(cache.tri_uv.mean(axis=1, keepdims=True))
    seg = np.stack((uv[tri, k], uv[tri, (k + 1) % 3]), axis=1) * np.array((emap.w, emap.h), dtype=np.float64)
    return seg, emap.tri_label[tri].astype(np.int64)


def edge_segments(ctx, emap):
    """The chosen model edges drawn in the UV space of each triangle beside them:
    ``(segments (S, 2, 2) pixel units, element label per segment)``."""
    cache = v3d_mesh.mesh_cache(ctx.context)
    if cache is None:
        return np.zeros((0, 2, 2)), np.zeros(0, dtype=np.int64)
    mode = _wm(ctx, 'edge_source', 'ANGLE')
    tri, k = edge_ramp.model_edges(cache.tri_verts, cache.tri_pos, mode, float(_wm(ctx, 'edge_angle', 30.0)),
                                   real_edges=cache.edges, marked=cache.edge_marked)
    return _uv_segments(cache, emap, tri, k)


def edges(ctx, emap, label, secondary=False):
    """A band along the model's edges (``extras_edge_source``), the same on both sides
    of each edge (``extras_edge_center``: 'BETWEEN' symmetric / 'ON' a pixel line)."""
    img = ctx.image
    width = max(1, int(_wm(ctx, 'edge_width', 3)))
    center = _wm(ctx, 'edge_center', 'BETWEEN')
    seg, seg_label = edge_segments(ctx, emap)
    if label is not None:
        keep = seg_label == int(label)
        seg, seg_label = seg[keep], seg_label[keep]
    if len(seg) == 0:
        return "Edges: no model edges here (try another angle / edge type)"
    if center == 'ON':
        seg = edge_ramp.snap_segments(seg)
    dist = edge_ramp.segment_distance(seg, seg_label, emap.labels, emap.w, emap.h, width + 1.0)
    inside, steps = edge_ramp.band(dist, width, center)
    idx = np.flatnonzero(inside)
    points = curve_points(ctx.wm, 'edge')
    t, opacity = edge_ramp.ramp(steps[idx], width, bool(_wm(ctx, 'edge_fade', True)),
                                curve=lambda x: value_curve.sample(points, x))
    edge_color, inner_color = _colors(ctx, secondary)
    rgb = region_paint.gradient(edge_color, inner_color, t)
    n = _paint(ctx, img, idx, rgb, opacity, secondary, "Extras: Edges")
    return f"Edges: {n} texels"


def curve_points(wm, kind):
    """Anchors of the Extras curve ``kind`` ('ao' / 'edge' / 'fill')."""
    return value_curve.from_text(getattr(wm, f'pixel_painter_extras_{kind}_curve', ""), kind)


def ambient_occlusion(ctx, emap, label, secondary=False):
    img = ctx.image
    cache = v3d_mesh.mesh_cache(ctx.context)
    if cache is None:
        return "AO: no mesh"
    idx = _targets(emap, label)
    allowed = mask_data.allowed(ctx.context, img)
    if allowed is not None:
        idx = idx[allowed[idx]]     # no rays for texels the mask protects
    if len(idx) == 0:
        return "AO: nothing to paint"
    began = time.perf_counter()
    wm = ctx.wm
    pos, nrm, ok = ao.texel_surface(cache, emap.w, emap.h, idx)
    idx, pos, nrm = idx[ok], pos[ok], nrm[ok]
    samples = int(_wm(ctx, 'ao_samples', 32))
    try:
        wm.progress_begin(0, max(1, len(idx)))
        progress = wm.progress_update
    except Exception:
        progress = None
    try:
        occ = ao.occlusion(cache, pos, nrm, samples=samples, distance=float(_wm(ctx, 'ao_distance', 0.25)),
                           progress=progress)
    finally:
        try:
            wm.progress_end()
        except Exception:
            pass
    weight = value_curve.sample(curve_points(wm, 'ao'), occ)
    occluded, open_color = _colors(ctx, secondary)
    rgb = region_paint.gradient(open_color, occluded, weight)
    opacity = weight if bool(_wm(ctx, 'ao_fade', True)) else 1.0
    n = _paint(ctx, img, idx, rgb, opacity, secondary, "Extras: Ambient Occlusion")
    return f"AO: {n} texels, {samples} rays, {time.perf_counter() - began:.1f} s"


RUN = {'FILL': fill, 'EDGES': edges, 'AO': ambient_occlusion}


def run(ctx, mode, emap, label, secondary=False):
    """Run ``mode`` on ``label`` (None: every element); the status text."""
    fn = RUN.get(mode)
    if fn is None or emap is None or ctx.image is None:
        return None
    return fn(ctx, emap, label, secondary)
