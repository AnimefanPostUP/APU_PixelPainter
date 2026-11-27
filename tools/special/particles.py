"""Particles: bodies thrown at the model that dent the paint where they hit -- wear and
tear, chipped edges, splatter.

3D Viewport: every draw step throws Count particles from in front of the brush (spread
over its size on the surface) along the view direction. They fly under gravity (world
down), collide with the mesh (BVH ray casts along each time step, ``core.view3d.mesh``),
bounce off with lost energy (Bounces times) and paint a small irregular dent at every
impact -- so they also land on edges and faces the brush never touched. Image Editor
(no mesh): the particles land inside the brush and hop downward
(``paint.special.scatter_2d``). Modifier (M): dent size. Left button: primary color,
right: secondary.
"""

import math

import numpy as np

from ...paint import region_paint, special
from ..base import SettingDefaults
from .common import SpecialBrush, commit, image_view, wm_value


DT = 1.0 / 90.0             # simulation time step, s
MAX_STEPS = 150             # per particle
SPEED = 1.6                 # launch speed, mesh sizes per second
GRAVITY = 4.0               # mesh sizes per second²
LIFT = 0.15                 # particles start this many mesh sizes in front of the surface
RESTITUTION = 0.45          # speed kept per bounce
JITTER = 0.25               # random share added to the launch / bounce direction
MAX_DENT = 4.0              # dent radius at M = 100 %, texels


class ParticlesTool(SpecialBrush):
    tool_id = 'PARTICLES'
    label = "Particles"
    description = "Throw particles that bounce off the model and dent it (Brushes window: Count, Bounces)"
    outline_color = (0.95, 0.85, 0.30, 0.9)
    defaults = SettingDefaults(size=False, modifier=False, strength=False, alpha=False)
    paints_color = True
    uses_values = frozenset({'strength', 'alpha', 'modifier'})   # M: dent size

    def __init__(self):
        super().__init__()
        self._rng = np.random.default_rng()
        self._region = None

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
        dent = MAX_DENT * float(np.clip(env.modifier, 0.0, 1.0))
        xs, ys, wts = special.chips(impacts, dent, self._rng, w, h)
        if len(xs):
            flat, _view = image_view(env)
            region_paint.blend_texels(flat, ys * w + xs, env.color, wts * env.opacity, blend=env.blend,
                                      alpha_target=env.alpha_opacity, protect_transparent=env.protect_transparent)
            commit(env, flat)
            self._region = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
        env.mark_painted()

    def step_region(self, ctx, env, steps):
        return self._region if self._region is not None else super().step_region(ctx, env, steps)

    # ---- 3D: real collisions with the mesh ---------------------------------------------------

    def _simulate_3d(self, env, count, bounces, w, h):
        """Impact pixels ``[(x, y, energy), ...]``, or None (no mesh / not over it)."""
        from mathutils import Vector
        from ...core.view3d import mesh, raycast
        context = env.context
        mouse = env.state.get('mouse_region')
        cache = mesh.mesh_cache(context)
        region, rv3d = raycast.view_frame(context)
        if mouse is None or cache is None or rv3d is None:
            return None
        hit = raycast.ray_hit(context, *mouse)
        if hit is None:
            return None
        obj = context.active_object
        inv3 = obj.matrix_world.inverted_safe().to_3x3()
        verts = np.asarray(cache.verts)
        size = float(np.linalg.norm(verts.max(axis=0) - verts.min(axis=0))) or 1.0
        if rv3d.is_perspective:
            eye = obj.matrix_world.inverted_safe() @ rv3d.view_matrix.inverted().translation
            forward = (hit.local - eye).normalized()
        else:
            forward = (inv3 @ (rv3d.view_rotation @ Vector((0.0, 0.0, -1.0)))).normalized()
        down = inv3 @ Vector((0.0, 0.0, -1.0))
        down = down.normalized() if down.length > 1e-12 else Vector((0.0, 0.0, -1.0))
        gravity = down * (GRAVITY * size)
        # Spread over the brush on the surface: texels -> object units through the hit face's density.
        density = float(cache.density[hit.tri]) if hit.tri < len(cache.density) else 0.0
        texel = (1.0 / math.sqrt(w * h)) / density if density > 0.0 else size * 0.01
        spread = max(1, env.radius) * texel
        side = forward.orthogonal().normalized()
        up = forward.cross(side).normalized()
        rng = self._rng
        out = []
        for _ in range(max(0, count)):
            a = rng.uniform(0.0, math.tau)
            d = spread * math.sqrt(rng.uniform(0.0, 1.0))
            target = hit.local + side * (math.cos(a) * d) + up * (math.sin(a) * d)
            p = target - forward * (LIFT * size)
            jitter = Vector(rng.normal(0.0, JITTER * 0.5, 3).tolist())
            vel = (forward + jitter).normalized() * (SPEED * size)
            out.extend(self._fly(cache, raycast, p, vel, gravity, bounces, size, w, h))
        return out

    def _fly(self, cache, raycast, p, vel, gravity, bounces, size, w, h):
        from mathutils import Vector
        impacts = []
        energy = 1.0
        left = bounces
        start = p.copy()
        bvh = cache.bvh
        rng = self._rng
        for _ in range(MAX_STEPS):
            vel = vel + gravity * DT
            step = vel * DT
            length = step.length
            if length < 1e-12:
                break
            loc, normal, tri, _dist = bvh.ray_cast(p, step / length, length)
            if loc is None or tri is None:
                p = p + step
                if (p - start).length > size * 2.0:
                    break     # flew off the model
                continue
            x, y = raycast.hit_to_pixel(raycast.hit_at(cache, loc, tri), w, h)
            impacts.append((x, y, energy))
            if left <= 0:
                break
            left -= 1
            n = normal.normalized()
            if n.dot(vel) > 0.0:
                n = -n
            vel = (vel - n * (2.0 * vel.dot(n))) * RESTITUTION
            vel = vel + Vector(rng.normal(0.0, JITTER, 3).tolist()) * vel.length
            energy *= RESTITUTION
            p = loc + n * (size * 1e-4)
        return impacts


def _is_view3d(context):
    space = getattr(context, 'space_data', None)
    return space is not None and space.type == 'VIEW_3D'
