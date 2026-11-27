"""The Particles brush's bodies in the 3D Viewport (needs only ``mathutils``: a BVH of the
mesh in object space).

A body flies under gravity and collides with the mesh (a BVH ray cast along every time
step). A hit fast enough bounces off (while it has bounces left, losing energy); after
that -- or when it lands too gently -- it **slides**: it moves along the face under the
part of gravity along it, slowed by friction, follows the surface over bends (a short
ray back onto the surface every step), runs along walls it meets, wraps around edges
onto the next face when slow (``WRAP_SPEED``; fast ones fly off and fall), and falls
again under a real overhang (it clings to walls and
slight overhangs: ``ADHESION``). It paints where it lands and all along its slide.

A body dies when it is outside the mesh's bounding box scaled by ``BOUNDS_SCALE`` around
its center -- once it has touched the mesh, or while flying away from it (a body launched
from outside the box toward the mesh lives) --, when it comes to rest (friction holds
it), or after ``MAX_STEPS``.
"""

from mathutils import Vector


DT = 1.0 / 90.0             # time step, s
MAX_STEPS = 900             # safety cap per body (10 s)
RESTITUTION = 0.15          # bounce: share of the speed into the surface that comes back out
GLANCE = 0.7                # bounce: share of the speed along the surface that is kept
                            # (small hops that settle into a slide, not shots off the model)
BOUNCE_SPEED = 0.6          # mesh sizes / s into the surface needed to bounce (slower: it slides)
FRICTION = 0.25             # sliding friction coefficient
ADHESION = 0.3              # it clings to the surface: falls off only where gravity pulls it away harder
                            # than this share of itself (walls and slight overhangs keep it: runs down them)
JITTER = 0.12               # random share added to bounce directions
WRAP_SPEED = 1.2            # mesh sizes / s: slower bodies wrap around edges and run down the next
                            # face; faster ones fly off the edge
BOUNDS_SCALE = 2.0          # dies outside the bounding box scaled by this around its center
SLIDE_WEIGHT = 0.6          # paint strength of the slide (impacts: 1, less after bounces)
PATH_EVERY = 2              # every n-th step is kept for the display
LIFT = 1e-4                 # kept this far off the surface (mesh sizes)
SAME_FACE = 0.995           # a hit ahead whose normal is this close to the current one is the face it
                            # slides on (a ray along the surface grazing it), not a wall


def bounds(verts):
    """``(center, half extents)`` of the (V, 3) vertex array; flat sides get a minimum."""
    lo = Vector([float(v) for v in verts.min(axis=0)])
    hi = Vector([float(v) for v in verts.max(axis=0)])
    size = (hi - lo).length or 1.0
    half = (hi - lo) * 0.5
    half = Vector([max(c, size * 0.05) for c in half])
    return (lo + hi) * 0.5, half, size


def outside(p, box, scale=BOUNDS_SCALE):
    center, half, _size = box
    d = p - center
    return any(abs(d[i]) > half[i] * scale for i in range(3))


def gone(p, vel, box, touched):
    """Dead: outside the scaled box, and it has touched the mesh or flies away from it."""
    return outside(p, box) and (touched or (p - box[0]).dot(vel) > 0.0)


def _toward(normal, direction):
    """``normal`` flipped to face against ``direction`` (the side the body comes from)."""
    n = normal.normalized()
    return -n if n.dot(direction) > 0.0 else n


def _jitter(rng, amount):
    return Vector(rng.normal(0.0, amount, 3).tolist())


def _wrap(bvh, q, n, step, length, eps):
    """The face past a convex edge: looking back from just below / beyond the edge
    (``q`` lies past it) toward the body. ``(loc, normal facing the body's side, tri)`` or None."""
    reach = length + eps * 8.0
    origin = q - n * reach
    back = -step / length
    loc, normal, tri, _d = bvh.ray_cast(origin, back, reach * 2.0)
    if loc is None:
        return None
    n2 = normal.normalized()
    if n2.dot(step) < 0.0:      # the new face looks the way the body went over the edge
        n2 = -n2
    return loc, n2, tri


class Body:
    """One body's result: ``contacts`` ``[(loc, tri, weight), ...]`` (where it paints),
    ``path`` (the flight / slide, for the display), ``hits`` (its impacts)."""

    __slots__ = ('contacts', 'path', 'hits', 'end')

    def __init__(self, start):
        self.contacts = []
        self.path = [start.copy()]
        self.hits = []
        self.end = None      # why it died: 'OUT' / 'REST' / 'STEPS'


def fly(bvh, p, vel, gravity, bounces, box, rng):
    """Simulate one body from ``p`` with velocity ``vel`` (object space)."""
    size = box[2]
    eps = size * LIFT
    body = Body(p)
    energy = 1.0
    left = int(bounces)
    sliding = False
    n = None                      # the surface normal while sliding (toward the body)
    for step_no in range(MAX_STEPS):
        keep = step_no % PATH_EVERY == 0
        if not sliding:
            vel = vel + gravity * DT
            step = vel * DT
            length = step.length
            if length < 1e-12:
                body.end = 'REST'
                break
            loc, normal, tri, _d = bvh.ray_cast(p, step / length, length)
            if loc is None:
                p = p + step
                if keep:
                    body.path.append(p.copy())
                if gone(p, vel, box, bool(body.contacts)):
                    body.end = 'OUT'
                    break
                continue
            n = _toward(normal, step)
            body.contacts.append((loc.copy(), tri, energy))
            body.hits.append(loc.copy())
            body.path.append(loc.copy())
            into = -vel.dot(n)
            if left > 0 and into > BOUNCE_SPEED * size:
                left -= 1
                along_face = vel + n * into
                vel = along_face * GLANCE + n * (into * RESTITUTION)
                vel = vel + _jitter(rng, JITTER) * vel.length
                energy *= 0.5 + 0.5 * RESTITUTION
                p = loc + n * eps
                continue
            vel = vel + n * into          # landed: keep the motion along the face
            p = loc + n * eps
            sliding = True
            continue

        # ---- sliding along the surface ----
        press = -gravity.dot(n)           # how hard gravity pushes into the face (< 0: pulls off it)
        if press < -ADHESION * gravity.length:    # a real overhang: it falls off
            sliding = False
            continue
        along = gravity + n * press       # gravity's part along the face
        vel = vel + along * DT
        speed = vel.length
        grip = max(0.0, press)            # friction only where it is pressed onto the face
        brake = FRICTION * grip * DT
        if speed <= brake:
            if along.length <= FRICTION * grip:    # friction holds it
                body.end = 'REST'
                break
            vel = Vector((0.0, 0.0, 0.0))
            continue
        vel = vel * (1.0 - brake / speed)
        step = vel * DT
        length = step.length
        if length < 1e-12:
            continue
        loc, normal, tri, _d = bvh.ray_cast(p, step / length, length)
        if loc is not None and abs(normal.normalized().dot(n)) < SAME_FACE:   # a wall: slide along it
            n = _toward(normal, step)
            vel = vel - n * vel.dot(n)
            p = loc + n * eps
            body.contacts.append((loc.copy(), tri, SLIDE_WEIGHT * energy))
            body.path.append(loc.copy())
            continue
        q = p + step
        loc, normal, tri, _d = bvh.ray_cast(q, -n, max(length * 2.0, eps * 8.0))
        if loc is None:                   # the surface drops away: an edge
            wrapped = _wrap(bvh, q, n, step, length, eps) if vel.length < WRAP_SPEED * size else None
            if wrapped is None:           # too fast (or nothing there): it flies off and falls
                p = q
                sliding = False
                if keep:
                    body.path.append(p.copy())
                continue
            loc, n2, tri = wrapped        # clings: around the edge, on down the next face
            speed = vel.length
            heading = -n - n2 * (-n).dot(n2)
            vel = heading.normalized() * speed if heading.length > 1e-12 else vel - n2 * vel.dot(n2)
            n = n2
            p = loc + n * eps
            body.contacts.append((loc.copy(), tri, SLIDE_WEIGHT * energy))
            body.path.append(p.copy())
            continue
        n2 = normal.normalized()
        if n2.dot(n) < 0.0:
            n2 = -n2
        speed = vel.length                # turn the motion onto the new face, same speed
        vel = vel - n2 * vel.dot(n2)
        if vel.length > 1e-12:
            vel = vel.normalized() * speed
        n = n2
        p = loc + n * eps
        body.contacts.append((loc.copy(), tri, SLIDE_WEIGHT * energy))
        if keep:
            body.path.append(p.copy())
        if gone(p, vel, box, True):
            body.end = 'OUT'
            break
    else:
        body.end = 'STEPS'
    if body.path[-1] != p:
        body.path.append(p.copy())
    return body


LAUNCH = 0.8                # launch speed, mesh sizes per second (they start close to the surface)


def launch_speed(size):
    """Launch speed for a mesh of ``size`` (its bounding box diagonal)."""
    return LAUNCH * size


def gravity_for(size, down):
    return down * (4.0 * size)


def spread_direction(forward, rng, jitter=0.12):
    return (forward + _jitter(rng, jitter)).normalized()

