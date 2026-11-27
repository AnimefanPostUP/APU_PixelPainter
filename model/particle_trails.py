"""The Particles brush's visual display (pure, no Blender): the paths of the last thrown
bodies and their impacts, fading out over ``LIFE`` seconds.

Points are opaque to this module -- world-space ``(x, y, z)`` in the 3D Viewport, image
pixels ``(x, y)`` in the Image Editor; the overlay projects them to the screen.
"""

LIFE = 0.6            # seconds a trail stays visible after its throw
MAX_TRAILS = 160      # older trails are dropped first beyond this


class Trail:
    __slots__ = ('born', 'path', 'hits')

    def __init__(self, born, path, hits):
        self.born = born
        self.path = list(path)     # the flight, in order
        self.hits = list(hits)     # where it dented the paint

    def fade(self, now, life=LIFE):
        """1 when just thrown -> 0 after ``life`` seconds."""
        return max(0.0, 1.0 - (now - self.born) / life)


class Trails:
    """The live trails of one display space ('3D' world points or '2D' image pixels)."""

    def __init__(self, life=LIFE, limit=MAX_TRAILS):
        self.life = life
        self.limit = limit
        self.space = None
        self.items = []

    def add(self, now, space, path, hits):
        """Record one body's flight; switching the space (3D <-> 2D) drops the old ones."""
        if space != self.space:
            self.items = []
            self.space = space
        if len(path) < 2 and not hits:
            return
        self.items.append(Trail(now, path, hits))
        if len(self.items) > self.limit:
            del self.items[:len(self.items) - self.limit]

    def live(self, now):
        """``[(trail, fade), ...]`` still visible (the faded ones are dropped)."""
        self.items = [t for t in self.items if t.fade(now, self.life) > 0.0]
        return [(t, t.fade(now, self.life)) for t in self.items]

    def clear(self):
        self.items = []
