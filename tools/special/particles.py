"""Particles: bodies thrown at the model that dent the paint where they hit and smear it
where they slide -- wear and tear, chipped edges, runs and streaks.

3D Viewport: every draw step throws Count bodies from in front of the brush (spread over
its size on the surface) along the view direction. They fly under gravity (world down)
and collide with the mesh; a hard hit bounces (Bounces times), after that -- or on a
soft landing -- they slide down along the surface, over bends and off edges, until they
leave the mesh's bounding box scaled x2 or come to rest (``particle_sim.py``). Every
impact paints a dent, the slide a thinner streak. Image Editor (no mesh): the bodies
land inside the brush and hop downward (``paint.special.scatter_2d``).

With the C# backend (:mod:`utils.native`) the bodies fly against a native BVH of the
mesh's triangles (built once per mesh cache) and the contacts are mapped to pixels in
NumPy; otherwise ``particle_sim.fly`` runs with the mesh's ``BVHTree``.

Size: dent radius; Amount: how strongly they paint (times the strength). Left button:
primary color, right: secondary.

Visual display: the bodies' flight / slide paths and impacts are drawn over the canvas,
fading out (``model/particle_trails.py``, drawn by ``overlays/special.draw_particle_trails``).
"""

import math
import time

import numpy as np

from ...model import particle_trails
from ...paint import region_paint, special
from ...utils import math_utils, native
from ..base import SettingDefaults
from .common import SpecialBrush, commit, image_view, wm_value


LIFT = 0.15                 # bodies start this many mesh sizes in front of the surface
RESTITUTION = 0.45          # 2D hops: length kept per bounce
SEAM_SLACK = 1.6            # slide pixels further apart than this x the 3D distance: a UV seam, no line
MAX_LINE = 96               # longest filled slide line between two contacts, pixels
TRAIL_COLOR = (1.00, 0.88, 0.35)
HIT_COLOR = (1.00, 0.55, 0.25)


class ParticlesTool(SpecialBrush):
    tool_id = 'PARTICLES'
    label = "Particles"
    description = ("Throw particles that bounce off the model, slide down it and dent / streak the paint "
                   "(Special window: Count, Bounces, Size, Amount)")
    outline_color = (0.95, 0.85, 0.30, 0.9)
    defaults = SettingDefaults(size=False, modifier=False, strength=False, alpha=False)
    paints_color = True
    uses_values = frozenset({'strength', 'alpha'})

    def __init__(self):
        super().__init__()
        self._rng = np.random.default_rng()
        self._region = None
        self.trails = particle_trails.Trails()
        self._tree = None            # native TriangleBVH of the mesh cache below
        self._tree_version = None

    def stamp_spacing(self, env):
        return max(1.0, env.radius * 0.5)

    def on_draw(self, env):
        self._region = None
        w, h = env.img.size
        if not self.spaced_steps(env):
            env.mark_painted()
            return
        count = int(wm_value(env, 'particle_count', 6))
        bounces = int(wm_value(env, 'particle_bounces', 2))
        impacts = None
        if _is_view3d(env.context):
            impacts = self._simulate_3d(env, count, bounces, w, h)
        if impacts is None:
            impacts = special.scatter_2d(self._rng, env.cursor_x, env.cursor_y, env.radius, count, bounces,
                                         restitution=RESTITUTION)
            self._record_2d(impacts, bounces)
        dent = float(wm_value(env, 'particle_size', 2))
        amount = float(np.clip(wm_value(env, 'particle_amount', 1.0), 0.0, 1.0))
        xs, ys, wts = special.chips(impacts, dent, self._rng, w, h)
        if len(xs) and amount > 0.0:
            flat, _view = image_view(env)
            region_paint.blend_texels(flat, ys * w + xs, env.color, wts * env.opacity * amount, blend=env.blend,
                                      alpha_target=env.alpha_opacity, protect_transparent=env.protect_transparent)
            commit(env, flat)
            self._region = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
        env.mark_painted()

    def step_region(self, ctx, env, steps):
        return self._region if self._region is not None else super().step_region(ctx, env, steps)

    # ---- 3D: bodies colliding with and sliding on the mesh -----------------------------------

    def _simulate_3d(self, env, count, bounces, w, h):
        """Paint points ``[(x, y, weight), ...]``, or None (no mesh / not over it)."""
        from mathutils import Vector
        from ...core.view3d import mesh, raycast
        from . import particle_sim
        context = env.context
        mouse = env.state.get('mouse_region')
        cache = mesh.mesh_cache(context)
        _region, rv3d = raycast.view_frame(context)
        if mouse is None or cache is None or rv3d is None:
            return None
        hit = raycast.ray_hit(context, *mouse)
        if hit is None:
            return None
        obj = context.active_object
        world = obj.matrix_world
        inv3 = world.inverted_safe().to_3x3()
        box = particle_sim.bounds(np.asarray(cache.verts))
        size = box[2]
        if rv3d.is_perspective:
            eye = world.inverted_safe() @ rv3d.view_matrix.inverted().translation
            forward = (hit.local - eye).normalized()
        else:
            forward = (inv3 @ (rv3d.view_rotation @ Vector((0.0, 0.0, -1.0)))).normalized()
        down = inv3 @ Vector((0.0, 0.0, -1.0))
        down = down.normalized() if down.length > 1e-12 else Vector((0.0, 0.0, -1.0))
        gravity = particle_sim.gravity_for(size, down)
        # Spread over the brush on the surface: texels -> object units through the hit face's density.
        texel = self._texel(cache, hit.tri, w, h, size)
        spread = max(1, env.radius) * texel
        side = forward.orthogonal().normalized()
        up = forward.cross(side).normalized()
        rng = self._rng
        now = time.perf_counter()
        out = []
        tree = self._native_tree(cache)
        for _ in range(max(0, count)):
            a = rng.uniform(0.0, math.tau)
            d = spread * math.sqrt(rng.uniform(0.0, 1.0))
            target = hit.local + side * (math.cos(a) * d) + up * (math.sin(a) * d)
            start = target - forward * (LIFT * size)
            vel = particle_sim.spread_direction(forward, rng) * particle_sim.launch_speed(size)
            if tree is not None:
                flight = particle_sim.fly_native(tree, start, vel, gravity, bounces, box, rng)
                if flight is not None:
                    out.extend(self._flight_points(cache, flight, w, h, size))
                    self.trails.add(now, '3D', _to_world(world, flight.path), _to_world(world, flight.hits))
                    continue
                tree = self._drop_tree()      # native failure: Python from here on
            body = particle_sim.fly(cache.bvh, start, vel, gravity, bounces, box, rng)
            out.extend(self._paint_points(cache, raycast, body, w, h, size))
            self.trails.add(now, '3D', [tuple(world @ q) for q in body.path], [tuple(world @ q) for q in body.hits])
        return out

    @staticmethod
    def _texel(cache, tri, w, h, size):
        """Object units per texel on triangle ``tri``."""
        density = float(cache.density[tri]) if 0 <= tri < len(cache.density) else 0.0
        return (1.0 / math.sqrt(w * h)) / density if density > 0.0 else size * 0.01

    def _paint_points(self, cache, raycast, body, w, h, size):
        """A body's contacts as image points ``(x, y, weight)``; consecutive slide contacts are
        joined by a pixel line (a continuous streak) unless a UV seam lies between them."""
        out = []
        prev = None          # (pixel, loc, tri, weight)
        for loc, tri, weight in body.contacts:
            px = raycast.hit_to_pixel(raycast.hit_at(cache, loc, tri), w, h)
            if prev is not None and weight == prev[3] and px != prev[0]:
                gap = max(abs(px[0] - prev[0][0]), abs(px[1] - prev[0][1]))
                expected = (loc - prev[1]).length / self._texel(cache, tri, w, h, size)
                if gap <= min(MAX_LINE, expected * SEAM_SLACK + 2.0):
                    for x, y in math_utils.get_line_pixels(prev[0][0], prev[0][1], px[0], px[1])[1:-1]:
                        out.append((x, y, weight))
            out.append((px[0], px[1], weight))
            prev = (px, loc, tri, weight)
        return out

    def _native_tree(self, cache):
        """The C# BVH of ``cache``'s triangles (rebuilt when the mesh cache changes), or None."""
        if not native.enabled():
            return self._drop_tree()
        if self._tree is not None and self._tree_version == cache.version:
            return self._tree
        self._drop_tree()
        try:
            self._tree = native.TriangleBVH(cache.tri_pos)
            self._tree_version = cache.version
        except Exception:
            self._tree = None
        return self._tree

    def _drop_tree(self):
        if self._tree is not None:
            self._tree.close()
        self._tree = None
        self._tree_version = None
        return None

    def _flight_points(self, cache, flight, w, h, size):
        """:meth:`_paint_points` for a native ``particle_sim.Flight``: the contacts' UVs in
        one NumPy pass, then the same streak joining."""
        if len(flight.tris) == 0:
            return []
        px = contact_pixels(cache.tri_pos, cache.tri_uv, flight.locs, flight.tris, w, h)
        density = np.asarray(cache.density, dtype=np.float64)[flight.tris]
        safe = np.where(density > 0.0, density, 1.0)
        texel = np.where(density > 0.0, (1.0 / math.sqrt(w * h)) / safe, size * 0.01)
        step = np.zeros(len(flight.tris))
        step[1:] = np.linalg.norm(flight.locs[1:] - flight.locs[:-1], axis=1)
        return join_streaks(px.tolist(), flight.weights.tolist(), (step / texel).tolist())

    # ---- visual display ------------------------------------------------------------------

    def _record_2d(self, impacts, bounces):
        """Image Editor: each body's hops (``scatter_2d`` lists them per body, in order)."""
        now = time.perf_counter()
        per = max(1, int(bounces) + 1)
        for i in range(0, len(impacts), per):
            pts = [(x + 0.5, y + 0.5) for x, y, _e in impacts[i:i + per]]
            self.trails.add(now, '2D', pts, pts)

    def draw_overlay(self, ctx):
        """The last bodies' paths (fading lines) and impacts (dots) over the canvas."""
        live = self.trails.live(time.perf_counter())
        if not live:
            return
        try:
            from ...overlays.special import draw_particle_trails
            draw_particle_trails(ctx.context, self.trails.space, live, TRAIL_COLOR, HIT_COLOR)
        except Exception:
            pass
        from ...ui.kit import anim
        anim.request_frame()     # still fading: the session timer redraws


def _is_view3d(context):
    space = getattr(context, 'space_data', None)
    return space is not None and space.type == 'VIEW_3D'


def _to_world(world, points):
    """Object-space (N, 3) points as world-space tuples."""
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    m = np.array(world, dtype=np.float64)
    return [tuple(p) for p in (pts @ m[:3, :3].T + m[:3, 3])]


def contact_pixels(tri_pos, tri_uv, locs, tris, w, h):
    """Image pixels (N, 2) of object-space points ``locs`` on triangles ``tris``: their UV
    (barycentric on the triangle) wrapped into 0..1, like ``raycast.hit_to_pixel``."""
    p = np.asarray(tri_pos, dtype=np.float64)[tris]          # (N, 3, 3)
    t = np.asarray(tri_uv, dtype=np.float64)[tris]           # (N, 3, 2)
    v0, v1 = p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]
    v2 = np.asarray(locs, dtype=np.float64) - p[:, 0]
    d00 = np.einsum('ij,ij->i', v0, v0)
    d01 = np.einsum('ij,ij->i', v0, v1)
    d11 = np.einsum('ij,ij->i', v1, v1)
    d20 = np.einsum('ij,ij->i', v2, v0)
    d21 = np.einsum('ij,ij->i', v2, v1)
    denom = d00 * d11 - d01 * d01
    ok = np.abs(denom) > 1e-30
    denom = np.where(ok, denom, 1.0)
    b1 = np.where(ok, (d11 * d20 - d01 * d21) / denom, 0.0)
    b2 = np.where(ok, (d00 * d21 - d01 * d20) / denom, 0.0)
    uv = t[:, 0] + (t[:, 1] - t[:, 0]) * b1[:, None] + (t[:, 2] - t[:, 0]) * b2[:, None]
    uv = np.mod(uv, 1.0)
    x = np.minimum(w - 1, (uv[:, 0] * w).astype(np.int64))
    y = np.minimum(h - 1, (uv[:, 1] * h).astype(np.int64))
    return np.stack((x, y), axis=1)


def join_streaks(pixels, weights, expected):
    """The streak joining of ``ParticlesTool._paint_points``: ``[(x, y, weight), ...]`` of
    the contacts ``pixels``; consecutive slide contacts (same weight) are joined by a pixel
    line unless they lie further apart than ``expected`` (the 3D step in texels) allows."""
    out = []
    prev = None          # (pixel, weight)
    for px, weight, exp in zip(pixels, weights, expected):
        px = (int(px[0]), int(px[1]))
        if prev is not None and weight == prev[1] and px != prev[0]:
            gap = max(abs(px[0] - prev[0][0]), abs(px[1] - prev[0][1]))
            if gap <= min(MAX_LINE, exp * SEAM_SLACK + 2.0):
                for x, y in math_utils.get_line_pixels(prev[0][0], prev[0][1], px[0], px[1])[1:-1]:
                    out.append((x, y, weight))
        out.append((px[0], px[1], weight))
        prev = (px, weight)
    return out
