
import bpy
import numpy as np
from bpy.types import Operator
from bpy.props import StringProperty
from mathutils import Vector


# bmesh will be injected by the main addon
bmesh = None

def set_bmesh_module(bmesh_module):
    global bmesh
    bmesh = bmesh_module

# Helper: Point in triangle using barycentric coordinates

# Robust 2D cross product sign method
def cross2d(a, b):
    return a.x * b.y - a.y * b.x

def point_in_triangle(pt, v1, v2, v3):
    # All cross products must have the same sign for the point to be inside
    d1 = cross2d(v2 - v1, pt - v1)
    d2 = cross2d(v3 - v2, pt - v2)
    d3 = cross2d(v1 - v3, pt - v3)
    has_neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
    has_pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
    return not (has_neg and has_pos)

class APU_OT_PaintSelectedFacesUV(Operator):
    bl_idname = "apu.paint_selected_faces_uv"
    bl_label = "Paint Selected Faces (UV)"
    bl_description = "Paint all selected faces in the LMB color using UVs"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        global bmesh
        if bmesh is None:
            self.report({'ERROR'}, "bmesh module not injected.")
            return {'CANCELLED'}
        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            self.report({'WARNING'}, "Active object is not a mesh.")
            return {'CANCELLED'}
        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.active
        if uv_layer is None:
            self.report({'WARNING'}, "No UV map found.")
            return {'CANCELLED'}
        image = context.space_data.image
        if image is None:
            self.report({'WARNING'}, "No image found in UV/Image Editor.")
            return {'CANCELLED'}
        # Get color from addon, fallback to brush color
        color = None
        if hasattr(context.scene, 'apu_pixel_painter_lmb_color'):
            color = context.scene.apu_pixel_painter_lmb_color
        if color is None or not isinstance(color, (tuple, list)) or len(color) < 3:
            brush = getattr(getattr(context.tool_settings, 'image_paint', None), 'brush', None)
            if brush:
                color = tuple(getattr(brush, 'color', (1,1,1))) + (1.0,)
            else:
                color = (1,1,1,1)
        width, height = image.size
        pixels = np.array(image.pixels[:]).reshape((height, width, 4))
        # Triangulate all selected faces (in a copy)
        # Create a new BMesh from the mesh data for safe triangulation
        bm_copy = bmesh.new()
        bm_copy.from_mesh(obj.data)
        uv_layer_copy = bm_copy.loops.layers.uv.active
        import bmesh.utils
        import bmesh.ops
        # Store all selected vert indices in the original mesh
        selected_vert_indices = {v.index for f in bm.faces if f.select for v in f.verts}
        print(f"Selected verts before triangulation: {len(selected_vert_indices)}")
        print(f"Verts before triangulation: {len(bm_copy.verts)}")
        selected_verts_after = {v.index for f in bm_copy.faces if f.select for v in f.verts}
        print(f"Selected verts after triangulation (before tri op): {len(selected_verts_after)}")
        # After triangulation, select faces if any of their verts were in the original selected verts
        for f in bm_copy.faces:
            f.select = any(v.index in selected_vert_indices for v in f.verts)
        # Triangulate all selected faces
        import bmesh.ops
        bmesh.ops.triangulate(bm_copy, faces=[f for f in bm_copy.faces if f.select])
        print(f"Verts after triangulation: {len(bm_copy.verts)}")
        # Reselect faces after triangulation if any of their verts are in the original selected set
        for f in bm_copy.faces:
            f.select = any(v.index in selected_vert_indices for v in f.verts)
        selected_verts_after_tri = {v.index for f in bm_copy.faces if f.select for v in f.verts}
        print(f"Selected verts after triangulation: {len(selected_verts_after_tri)}")
        faces_to_paint = [f for f in bm_copy.faces if f.select]
        texture_name = getattr(image, 'name', 'Unknown')
        if not faces_to_paint:
            self.report({'WARNING'}, f"No selected faces to paint. Texture: {texture_name}")
            return {'CANCELLED'}
        # Triangulate all selected faces
        tris = []
        bmesh.ops.triangulate(bm_copy, faces=faces_to_paint)
        for face in bm_copy.faces:
            if face.select and len(face.loops) == 3:
                tris.append(face)
        print(f"faces_to_paint: {len(faces_to_paint)}, tris after triangulation: {len(tris)}")
        painted_pixels = 0
        iterated_pixels = 0
        print(f"Image size: {width}x{height}")
        import math
        for face in tris:
            uvs = [Vector(l[uv_layer_copy].uv) for l in face.loops]
            uv_debug = ', '.join([f"({uv.x:.4f}, {uv.y:.4f})" for uv in uvs])
            print(f"Triangle UVs: {uv_debug}")
            min_uv_x = min([uv.x for uv in uvs])
            max_uv_x = max([uv.x for uv in uvs])
            min_uv_y = min([uv.y for uv in uvs])
            max_uv_y = max([uv.y for uv in uvs])
            print(f"Raw UV bounds: x({min_uv_x:.4f}-{max_uv_x:.4f}), y({min_uv_y:.4f}-{max_uv_y:.4f})")
            min_u = max(int(math.floor(min_uv_x * width)), 0)
            max_u = min(int(math.ceil(max_uv_x * width)), width)
            min_v = max(int(math.floor(min_uv_y * height)), 0)
            max_v = min(int(math.ceil(max_uv_y * height)), height)
            print(f"Pixel bounding box: u({min_u}-{max_u}), v({min_v}-{max_v})")

            # Find triangle center in UV space
            center_uv = (uvs[0] + uvs[1] + uvs[2]) / 3.0
            # Segment bounding box into 4 zones
            zone_counts = {'LT': 0, 'LB': 0, 'RT': 0, 'RB': 0}
            for y in range(min_v, max_v):
                for x in range(min_u, max_u):
                    iterated_pixels += 1
                    # Pixel corners in UV space
                    px = x / width
                    py = y / height
                    px1 = (x + 1) / width
                    py1 = (y + 1) / height
                    corners = [Vector((px, py)), Vector((px1, py)), Vector((px, py1)), Vector((px1, py1))]
                    # Check which zone the pixel is in (by center)
                    cx = (x + 0.5) / width
                    cy = (y + 0.5) / height
                    zone = ''
                    if cx < center_uv.x and cy < center_uv.y:
                        zone = 'LB'
                    elif cx < center_uv.x and cy >= center_uv.y:
                        zone = 'LT'
                    elif cx >= center_uv.x and cy < center_uv.y:
                        zone = 'RB'
                    else:
                        zone = 'RT'
                    # Paint if any corner is inside the triangle
                    if any(point_in_triangle(corner, uvs[0], uvs[1], uvs[2]) for corner in corners):
                        pixels[y, x, :3] = color[:3]
                        pixels[y, x, 3] = 1.0
                        painted_pixels += 1
                        zone_counts[zone] += 1
            print(f"Zone pixel counts: {zone_counts}")
        print(f"Iterated {iterated_pixels} pixels in bounding boxes, painted {painted_pixels}.")
        image.pixels = pixels.flatten()
        image.update()
        bm_copy.free()
        self.report({'INFO'}, f"Painted {painted_pixels} pixels on {len(faces_to_paint)} selected faces. Texture: {texture_name}, Color: {color}")
        return {'FINISHED'}

def register():
    bpy.utils.register_class(APU_OT_PaintSelectedFacesUV)

def unregister():
    bpy.utils.unregister_class(APU_OT_PaintSelectedFacesUV)
