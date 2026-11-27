"""Unit tests for tools/pickers.py: one canvas picker (secondary tool) at a time.

    python -m unittest discover -s tests -v
"""

import importlib
import os
import sys
import types
import unittest

_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PACKAGE = os.path.basename(_ADDON_DIR)
sys.path.insert(0, os.path.dirname(_ADDON_DIR))
sys.modules.setdefault('bpy', types.ModuleType('bpy'))  # the package __init__ imports bpy

pickers = importlib.import_module(f'{_PACKAGE}.tools.pickers')


class PickersTest(unittest.TestCase):

    def setUp(self):
        self._saved = dict(pickers._RELEASE)
        pickers._RELEASE.clear()
        pickers.register('A', lambda state: state.__setitem__('a', False))
        pickers.register('B', lambda state: state.__setitem__('b', False))
        pickers.register('C', lambda state: state.__setitem__('c', False))

    def tearDown(self):
        pickers._RELEASE.clear()
        pickers._RELEASE.update(self._saved)

    def test_claim_stops_the_others(self):
        state = {'a': True, 'b': True, 'c': True}
        pickers.claim(state, 'B')
        self.assertEqual(state, {'a': False, 'b': True, 'c': False})

    def test_failing_release_does_not_block_the_rest(self):
        def broken(state):
            raise RuntimeError("boom")
        pickers.register('A', broken)
        state = {'b': True, 'c': True}
        stderr, sys.stderr = sys.stderr, open(os.devnull, 'w')
        try:
            pickers.claim(state, 'B')
        finally:
            sys.stderr.close()
            sys.stderr = stderr
        self.assertEqual(state, {'b': True, 'c': False})


if __name__ == '__main__':
    unittest.main()
