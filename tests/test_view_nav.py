"""View window math (tools/view_nav.py): axis views, level / roll / orbit, fitting."""

import importlib.util
import math
import os
import unittest

import numpy as np

_PATH = os.path.join(os.path.dirname(__file__), '..', 'tools', 'view_nav.py')
_spec = importlib.util.spec_from_file_location('view_nav', _PATH)
nav = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nav)


def is_rotation(m):
    return np.allclose(m.T @ m, np.eye(3), atol=1e-9) and abs(np.linalg.det(m) - 1.0) < 1e-9


class AxisViews(unittest.TestCase):
    def test_all_proper_rotations(self):
        for axis in nav.AXIS_VIEWS:
            self.assertTrue(is_rotation(nav.axis_rotation(axis)), axis)

    def test_front_looks_along_plus_y(self):
        rot = nav.axis_rotation('FRONT')
        np.testing.assert_allclose(-rot[:, 2], (0, 1, 0))
        np.testing.assert_allclose(rot[:, 1], (0, 0, 1))

    def test_right_looks_along_minus_x(self):
        np.testing.assert_allclose(-nav.axis_rotation('RIGHT')[:, 2], (-1, 0, 0))


class LevelRollOrbit(unittest.TestCase):
    def test_level_removes_roll_keeps_direction(self):
        front = nav.axis_rotation('FRONT')
        rolled = nav.roll(nav.orbit(front, 30.0, 20.0), 37.0)
        level = nav.level_rotation(rolled)
        self.assertTrue(is_rotation(level))
        np.testing.assert_allclose(level[:, 2], rolled[:, 2], atol=1e-9)   # same viewing direction
        self.assertAlmostEqual(level[2, 0], 0.0)                           # right axis horizontal
        self.assertGreater(level[2, 1], 0.0)                               # world up is up on screen

    def test_level_top_view_keeps_y_up(self):
        top = nav.roll(nav.axis_rotation('TOP'), 20.0)
        np.testing.assert_allclose(nav.level_rotation(top), nav.axis_rotation('TOP'), atol=1e-9)

    def test_roll_keeps_direction(self):
        front = nav.axis_rotation('FRONT')
        r = nav.roll(front, 15.0)
        np.testing.assert_allclose(r[:, 2], front[:, 2], atol=1e-9)
        self.assertAlmostEqual(math.degrees(math.acos(r[:, 1] @ front[:, 1])), 15.0)

    def test_orbit_yaw_and_pitch(self):
        front = nav.axis_rotation('FRONT')
        side = nav.orbit(front, yaw_deg=90.0)
        np.testing.assert_allclose(side, nav.axis_rotation('RIGHT'), atol=1e-9)
        above = nav.orbit(front, pitch_deg=90.0)
        np.testing.assert_allclose(above[:, 2], (0, 0, 1), atol=1e-9)    # looking down


class Fit(unittest.TestCase):
    cube = np.array([(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], dtype=float) + (5, 2, 1)

    def _projected(self, rot, center, dist, tx, ty, persp):
        view = (self.cube - center) @ rot
        if persp:
            depth = dist - view[:, 2]
            return view[:, 0] / (depth * tx), view[:, 1] / (depth * ty)
        return view[:, 0] / (dist * tx), view[:, 1] / (dist * ty)

    def test_perspective_fills_margin(self):
        rot = nav.orbit(nav.axis_rotation('FRONT'), 30.0, 20.0)
        tx, ty = 0.7, 0.4
        center, dist = nav.fit_view(self.cube, rot, tx, ty, True, margin=0.9)
        np.testing.assert_allclose(center, (5, 2, 1), atol=1e-9)
        px, py = self._projected(rot, center, dist, tx, ty, True)
        extent = max(np.abs(px).max(), np.abs(py).max())
        self.assertAlmostEqual(extent, 0.9, places=6)                 # touches the margin
        self.assertTrue((dist - (self.cube - center) @ rot[:, 2] > 0).all())   # all in front

    def test_ortho_fills_margin(self):
        rot = nav.axis_rotation('TOP')
        center, dist = nav.fit_view(self.cube, rot, 0.5, 0.25, False, margin=1.0)
        px, py = self._projected(rot, center, dist, 0.5, 0.25, False)
        self.assertAlmostEqual(max(np.abs(px).max(), np.abs(py).max()), 1.0)
        self.assertAlmostEqual(np.abs(py).max(), 1.0)                 # the narrow side limits


if __name__ == '__main__':
    unittest.main()
