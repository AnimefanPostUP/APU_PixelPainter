"""3D Viewport support (Texture Paint mode): mouse -> texture pixel by ray-casting the
mesh, strokes that never cross UV seams, Edge mode (brushes continue over seams).

mesh.py       the cached evaluated mesh (triangles, UVs, BVH tree)
raycast.py    mouse ray -> hit -> pixel, texel size on screen
islands.py    UV island labels; stamps clipped to their island (UV mode)
stroke_path.py screen-space stroke interpolation
frames.py     triangle frames: UV layout or unfolded around a seed (Edge mode)
surface_path.py shortest path over the surface (Edge-mode Line)
footprint.py  stamp footprints mapped across seams (Edge mode)
patch.py      EdgePatch: the surface around a stamp, for Smooth / Smear
"""
