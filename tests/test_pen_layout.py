"""Per-project pen layout (tools/pen/layout.py): JSON encode / decode."""

import importlib.util
import json
import os
import unittest

_PATH = os.path.join(os.path.dirname(__file__), '..', 'tools', 'pen', 'layout.py')
_spec = importlib.util.spec_from_file_location('pen_layout', _PATH)
pen_layout = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pen_layout)

DEFAULTS = {'pen_bar_pos': None, 'pen_bar_scale': 1.0, 'pen_mask_panel': False, 'pen_mask_pos': None,
            'pen_view_autofit': True}


class EncodeDecode(unittest.TestCase):
    def test_round_trip(self):
        state = {'pen_bar_pos': (120.5, 800.0), 'pen_bar_scale': 0.75, 'pen_mask_panel': True,
                 'pen_mask_pos': None, 'pen_view_autofit': False, 'other': 1}
        text = pen_layout.encode(state, DEFAULTS)
        self.assertNotIn('other', text)
        self.assertEqual(pen_layout.decode(text, DEFAULTS),
                         {k: state[k] for k in DEFAULTS})

    def test_positions_become_tuples(self):
        text = json.dumps({'version': 1, 'layout': {'pen_bar_pos': [3, 4]}})
        self.assertEqual(pen_layout.decode(text, DEFAULTS), {'pen_bar_pos': (3.0, 4.0)})

    def test_bad_values_skipped(self):
        text = json.dumps({'version': 1, 'layout': {
            'pen_bar_pos': [1], 'pen_bar_scale': "big", 'pen_mask_panel': 1, 'unknown': True,
            'pen_mask_pos': [True, 2], 'pen_view_autofit': False}})
        self.assertEqual(pen_layout.decode(text, DEFAULTS), {'pen_view_autofit': False})

    def test_empty_or_broken(self):
        for text in ("", "not json", "[1, 2]", json.dumps({'layout': 5})):
            self.assertEqual(pen_layout.decode(text, DEFAULTS), {}, text)


if __name__ == '__main__':
    unittest.main()
