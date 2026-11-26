"""Unit tests for the pixel history's step storage (core/history.py): steps keep only
the changed box, and undo / redo transitions rebuild the exact pixels.

    python -m unittest discover -s tests -v
"""

import importlib
import os
import sys
import types
import unittest

import numpy as np

_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PACKAGE = os.path.basename(_ADDON_DIR)
sys.path.insert(0, os.path.dirname(_ADDON_DIR))

# history.py imports bpy and bpy.app.handlers.persistent at module level.
_bpy = sys.modules.setdefault('bpy', types.ModuleType('bpy'))
if 'bpy.app.handlers' not in sys.modules:
    _app = types.ModuleType('bpy.app')
    _handlers = types.ModuleType('bpy.app.handlers')
    _handlers.persistent = lambda fn: fn
    _app.handlers = _handlers
    _bpy.app = _app
    sys.modules['bpy.app'] = _app
    sys.modules['bpy.app.handlers'] = _handlers

history = importlib.import_module(f'{_PACKAGE}.core.history')

W, H = 7, 5
KEY = 1


def image(seed):
    rng = np.random.default_rng(seed)
    return rng.random(W * H * 4, dtype=np.float32)


def paint(buf, x0, y0, x1, y1, value):
    out = buf.copy()
    out.reshape(H, W, 4)[y0:y1, x0:x1] = value
    return out


class HistoryStepTest(unittest.TestCase):

    def setUp(self):
        history.steps.clear()
        # Three steps on one image: s1 -> s2 -> s3 (stamps), each a painted box.
        self.states = [image(0)]
        boxes = [(1, 1, 3, 2, 0.25), (2, 0, 6, 4, 0.5), (0, 3, 2, 5, 0.75)]
        prev = None
        self.stamps = []
        for i, box in enumerate(boxes):
            after = paint(self.states[-1], *box)
            step = history.make_step(KEY, prev, self.states[-1], after, W, H)
            stamp = f"s{i + 1}"
            history.steps[stamp] = step
            self.stamps.append(stamp)
            self.states.append(after)
            prev = stamp

    def tearDown(self):
        history.steps.clear()

    def run_transition(self, current, old, new):
        buf = current.copy()
        plan = history.transition(KEY, old, new)
        self.assertIsNotNone(plan)
        self.assertTrue(history.apply_transition(buf, W, H, plan))
        return buf

    def test_step_keeps_only_the_changed_box(self):
        step = history.steps['s2']
        self.assertEqual(step.region, (0, 4, 2, 6))
        self.assertEqual(step.before.shape, (4, 4, 4))

    def test_no_change_is_no_step(self):
        buf = image(3)
        self.assertIsNone(history.make_step(KEY, None, buf, buf.copy(), W, H))

    def test_undo_one_and_several_steps(self):
        self.assertTrue(np.array_equal(self.run_transition(self.states[3], 's3', 's2'), self.states[2]))
        self.assertTrue(np.array_equal(self.run_transition(self.states[3], 's3', 's1'), self.states[1]))
        self.assertTrue(np.array_equal(self.run_transition(self.states[3], 's3', None), self.states[0]))

    def test_redo_one_and_several_steps(self):
        self.assertTrue(np.array_equal(self.run_transition(self.states[2], 's2', 's3'), self.states[3]))
        self.assertTrue(np.array_equal(self.run_transition(self.states[0], None, 's3'), self.states[3]))

    def test_other_image_size_is_refused(self):
        plan = history.transition(KEY, 's3', 's2')
        buf = np.zeros((W + 1) * H * 4, dtype=np.float32)
        self.assertFalse(history.apply_transition(buf, W + 1, H, plan))

    def test_unconnected_stamps(self):
        self.assertIsNone(history.transition(KEY, 'unknown', 'other'))
        self.assertIsNone(history.transition(2, 's3', 's2'))   # steps of another image


if __name__ == '__main__':
    unittest.main()
