"""The Particles brush's simulation (tools/special/particle_sim.py) on real meshes.

Needs Blender's ``mathutils`` (BVH trees), so outside Blender these tests are skipped.
Run them with Blender's Python, e.g.:

    blender -b --factory-startup --python-expr "import sys, unittest; sys.argv=['x'];
        unittest.main(module=None, argv=['x', 'discover', '-s', '<addon>/tests', '-p', 'test_particle_sim.py'])"
"""

import importlib.util
import os
import unittest

try:
    import bmesh
    import numpy as np
    from mathutils import Matrix, Vector
    from mathutils.bvhtree import BVHTree
    HAVE_BLENDER = True
except ImportError:
    HAVE_BLENDER = False

_SIM = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools', 'special',
                    'particle_sim.py')


def _load_sim():
    spec = importlib.util.spec_from_file_location('particle_sim', _SIM)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(HAVE_BLENDER, "needs Blender's mathutils / bmesh")
class ParticleSimTest(unittest.TestCase):

    def setUp(self):
        self.sim = _load_sim()

    def _mesh(self, build):
        bm = bmesh.new()
        build(bm)
        bm.normal_update()      # moved / rotated vertices: fresh face normals for the BVH
        verts = np.array([v.co[:] for v in bm.verts])
        return BVHTree.FromBMesh(bm), verts

    def _throw(self, bvh, verts, target, view, bounces, n=8):
        sim = self.sim
        box = sim.bounds(verts)
        size = box[2]
        gravity = sim.gravity_for(size, Vector((0, 0, -1)))
        rng = np.random.default_rng(1)
        bodies = []
        for _ in range(n):
            forward = Vector(view).normalized()
            start = Vector(target) + Vector(rng.normal(0, 0.05, 3).tolist()) - forward * (0.15 * size)
            vel = sim.spread_direction(forward, rng) * sim.launch_speed(size)
            bodies.append(sim.fly(bvh, start, vel, gravity, bounces, box, rng))
        return bodies, box

    def test_slides_down_a_ramp_and_dies_outside_the_box(self):
        def ramp(bm):
            g = bmesh.ops.create_grid(bm, x_segments=8, y_segments=8, size=6.0)
            bmesh.ops.rotate(bm, verts=g['verts'], cent=(0, 0, 0), matrix=Matrix.Rotation(0.6, 3, 'X'))
        bvh, verts = self._mesh(ramp)
        for bounces in (0, 2):
            bodies, box = self._throw(bvh, verts, (0, 0, 0), (0, 0.3, -1), bounces)
            for body in bodies:
                self.assertEqual(body.end, 'OUT')
                self.assertTrue(self.sim.outside(body.path[-1], box))
                slides = sum(1 for c in body.contacts if c[2] < 0.99)
                self.assertGreater(slides, 10)                      # it slid, not just hit
                self.assertLessEqual(len(body.hits), bounces + 1)

    def test_rests_on_a_flat_top(self):
        bvh, verts = self._mesh(lambda bm: bmesh.ops.create_cube(bm, size=2.0))
        bodies, _box = self._throw(bvh, verts, (0.2, 0.1, 1.0), (0, 0.2, -1), 0)
        self.assertGreaterEqual(sum(1 for b in bodies if b.end == 'REST'), 6)

    def test_runs_down_a_wall_over_an_edge(self):
        def roof_block(bm):
            # A box whose top slopes down toward +y, ending in an edge over a vertical wall.
            bmesh.ops.create_cube(bm, size=2.0)
            for v in bm.verts:
                if v.co.z > 0.0 and v.co.y > 0.0:
                    v.co.z = 0.2
        bvh, verts = self._mesh(roof_block)
        bodies, _box = self._throw(bvh, verts, (0.0, -0.3, 0.75), (0, 0, -1), 0)
        # Slid down the top, wrapped over the edge (z = 0.2) and ran on down the wall.
        lowest = min(c[0].z for b in bodies for c in b.contacts)
        self.assertLess(lowest, -0.5)
        on_wall = [c for b in bodies for c in b.contacts if abs(c[0].y - 1.0) < 1e-3 and c[0].z < 0.15]
        self.assertGreater(len(on_wall), 8)

if __name__ == '__main__':
    unittest.main()
