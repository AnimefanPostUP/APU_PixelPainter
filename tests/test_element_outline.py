"""Unit tests for the 3D hover outline of elements (core/view3d/elements.py): open
border edges plus the view silhouette, so closed mesh parts are outlined too.
Plain Python + NumPy (Blender modules stubbed)."""

import importlib
import os
import sys
import types
import unittest

import numpy as np

_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PACKAGE = os.path.basename(_ADDON_DIR)
sys.path.insert(0, os.path.dirname(_ADDON_DIR))

# Blender stubs are added for the import only, then removed again (with the addon
# modules imported here) so the other test files keep their own environment.
_MODULES_BEFORE = set(sys.modules)
for _name in ('bpy', 'mathutils', 'mathutils.bvhtree'):
    sys.modules.setdefault(_name, types.ModuleType(_name))
if not hasattr(sys.modules['mathutils.bvhtree'], 'BVHTree'):
    sys.modules['mathutils.bvhtree'].BVHTree = object
elements = importlib.import_module(f'{_PACKAGE}.core.view3d.elements')
mask_geometry = importlib.import_module(f'{_PACKAGE}.tools.mask.geometry')

for _name in set(sys.modules) - _MODULES_BEFORE:
    del sys.modules[_name]


def cube():
    """Unit cube centred at the origin, 12 outward-facing triangles."""
    v = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], dtype=np.float64) * 0.5
    idx = lambda x, y, z: x * 4 + y * 2 + z
    quads = [
        (idx(0, 0, 0), idx(0, 0, 1), idx(0, 1, 1), idx(0, 1, 0)),  # -X
        (idx(1, 0, 0), idx(1, 1, 0), idx(1, 1, 1), idx(1, 0, 1)),  # +X
        (idx(0, 0, 0), idx(1, 0, 0), idx(1, 0, 1), idx(0, 0, 1)),  # -Y
        (idx(0, 1, 0), idx(0, 1, 1), idx(1, 1, 1), idx(1, 1, 0)),  # +Y
        (idx(0, 0, 0), idx(0, 1, 0), idx(1, 1, 0), idx(1, 0, 0)),  # -Z
        (idx(0, 0, 1), idx(1, 0, 1), idx(1, 1, 1), idx(0, 1, 1)),  # +Z
    ]
    tris = []
    for a, b, c, d in quads:
        tris += [(a, b, c), (a, c, d)]
    tv = np.array(tris, dtype=np.int32)
    return types.SimpleNamespace(verts=v, tri_verts=tv, tri_pos=v[tv])


def edge_set(seg):
    return {tuple(sorted((tuple(np.round(p, 6)) for p in s))) for s in seg}


class ElementOutline3DTest(unittest.TestCase):
    def test_closed_part_has_no_border_but_a_silhouette(self):
        c = cube()
        edges = elements.edge_sets(c, np.ones(12, dtype=bool))
        self.assertEqual(len(elements.outline_from(edges)), 0)
        # Looking straight down +Z (orthographic): the silhouette is the 4 side edges
        # around the top face.
        sil = elements.outline_from(edges, direction=(0.0, 0.0, 1.0))
        self.assertEqual(len(sil), 4)
        # Perspective from a corner: a hexagon (6 edges) around the 3 visible faces.
        sil = elements.outline_from(edges, eye=(3.0, 4.0, 5.0))
        self.assertEqual(len(sil), 6)

    def test_open_patch_keeps_its_border(self):
        c = cube()
        top = np.zeros(12, dtype=bool)
        top[10:12] = True                       # the +Z face only
        edges = elements.edge_sets(c, top)
        border = elements.outline_from(edges)
        self.assertEqual(len(border), 4)
        # Seen from above nothing inside the quad flips: just the border.
        self.assertEqual(edge_set(elements.outline_from(edges, eye=(0.0, 0.0, 5.0))), edge_set(border))

    def test_nothing_chosen(self):
        edges = elements.edge_sets(cube(), np.zeros(12, dtype=bool))
        self.assertEqual(len(elements.outline_from(edges, eye=(0, 0, 5))), 0)


class SharpAreasTest(unittest.TestCase):
    def test_cube_faces_split_at_30_degrees(self):
        c = cube()
        labels = mask_geometry.sharp_labels(c.tri_verts, c.tri_pos, 30.0)
        self.assertEqual(len(set(labels.tolist())), 6)
        for k in range(6):   # the two triangles of a face stay together
            self.assertEqual(labels[2 * k], labels[2 * k + 1])

    def test_cube_is_one_area_above_90_degrees(self):
        c = cube()
        self.assertEqual(len(set(mask_geometry.sharp_labels(c.tri_verts, c.tri_pos, 95.0).tolist())), 1)

    def test_groups_stay_together(self):
        c = cube()
        # Pretend +X and +Y faces are one polygon: they share a label even though sharp.
        group = np.repeat(np.arange(6), 2)
        group[group == 3] = 1
        labels = mask_geometry.sharp_labels(c.tri_verts, c.tri_pos, 30.0, tri_group=group)
        self.assertEqual(len(set(labels.tolist())), 5)
        self.assertEqual(labels[2], labels[6])

    def test_boundaries_3d_are_the_sharp_edges(self):
        c = cube()
        labels = mask_geometry.sharp_labels(c.tri_verts, c.tri_pos, 30.0)
        self.assertEqual(len(elements.label_boundaries_3d(c, labels)), 12)   # the cube's edges
        one = np.zeros(12, dtype=np.int64)
        self.assertEqual(len(elements.label_boundaries_3d(c, one)), 0)       # closed, one area

    def test_boundaries_2d(self):
        labels = np.array([[0, 0, 1],
                           [0, 0, 1],
                           [-1, -1, -1]])
        seg = elements.label_boundaries_2d(labels)
        # Area 0 (2x2): perimeter 8; area 1 (1x2): perimeter 6; they share 2 sides.
        self.assertEqual(len(seg), 8 + 6 - 2)


if __name__ == '__main__':
    unittest.main()
