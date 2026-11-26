"""C# native backend: pixel-heavy work in a compiled library, Python as fallback.

The library is ``native/PixelPainterNative`` (C#, compiled with NativeAOT into
a plain native library -- no .NET runtime needed) and is loaded with ctypes
from ``native/runtimes/<rid>/``. Build it with ``native/build.ps1``.

* :func:`enabled` -- the library loaded *and* the ``pixel_painter_use_native``
  setting is on (default). Every caller keeps its Python implementation and
  only takes the native branch when this is True.
* The wrappers take NumPy arrays; image buffers are flat float32 RGBA arrays
  (``Image.pixels`` layout) and are modified in place.
* A wrapper returns ``None`` when the library reports a failure, so callers can
  fall back to Python for that call.

No ``bpy`` at import time (unit tests load this module without Blender).
"""

import ctypes
import os
import platform
import shutil
import sys
import tempfile

import numpy as np

from ..paths import NATIVE_RUNTIMES_DIR


API_VERSION = 3  # must match Exports.ApiVersion in native/PixelPainterNative/Exports.cs
SETTING = 'pixel_painter_use_native'

# Blend mode ids, must match Blend.cs.
BLEND_IDS = {
    'MIX': 0, 'ADD': 1, 'SUB': 2, 'MUL': 3, 'DARKEN': 4, 'LIGHTEN': 5, 'SCREEN': 6,
    'OVERLAY': 7, 'HARDLIGHT': 8, 'SOFTLIGHT': 9, 'DIFFERENCE': 10, 'EXCLUSION': 11,
    'COLORDODGE': 12, 'COLORBURN': 13, 'COLOR': 14, 'HUE': 15, 'SATURATION': 16,
    'VALUE': 17, 'LUMINOSITY': 18,
}

RUNTIMES_DIR = NATIVE_RUNTIMES_DIR

_lib = None
_error = None        # why the library is unavailable (str) or None
_tried = False
_override = None     # tests: force enabled() True / False


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def _rid():
    machine = platform.machine().lower()
    arch = {'amd64': 'x64', 'x86_64': 'x64', 'arm64': 'arm64', 'aarch64': 'arm64'}.get(machine, machine)
    if sys.platform.startswith('win'):
        return f'win-{arch}', 'PixelPainterNative.dll'
    if sys.platform == 'darwin':
        return f'osx-{arch}', 'PixelPainterNative.dylib'
    return f'linux-{arch}', 'PixelPainterNative.so'


def library_path():
    rid, name = _rid()
    return os.path.join(RUNTIMES_DIR, rid, name)


_P = ctypes.c_void_p
_I = ctypes.c_int
_L = ctypes.c_longlong
_F = ctypes.c_float
_D = ctypes.c_double

_SIGNATURES = {
    'pp_api_version': (_I, ()),
    'pp_paint': (_I, (_P, _P, _I, _I, _P, _P, _I, _F, _F, _F, _I, _F, _F, _I)),
    'pp_set_alpha': (_I, (_P, _I, _I, _P, _P, _I, _D, _D, _I)),
    'pp_erase': (_I, (_P, _I, _I, _P, _I, _D)),
    'pp_smooth': (_I, (_P, _I, _I, _P, _P, _I, _I, _D, _I, _P)),
    'pp_smear': (_I, (_P, _I, _I, _P, _P, _I, _D, _D, _D, _D, _I, _P)),
    'pp_stamp_kernel': (_I, (_P, _I, _I, _P, _I, _I, _P, _P, _P, _P, _P, _I)),
    'pp_stamp_spray': (_I, (_P, _I, _I, _D, _P, _I, _I, _I, _P, _P, _P, _P, _P, _I)),
    'pp_raster_labels': (_I, (_P, _P, _I, _I, _I, _I, _P)),
    'pp_restore_blocked': (_L, (_P, _P, _P, _L)),
    'pp_blend_region': (_I, (_P, _P, _P, _L, _I, _F)),
    'pp_blit_region': (_I, (_P, _I, _I, _P, _I, _I, _I, _I, _I, _I, _I, _I, _I, _I, _I, _F)),
    'pp_raster_triangles': (_I, (_P, _I, _I, _I, _D, _P)),
    'pp_fill_uv_triangles': (_L, (_P, _I, _I, _P, _I, _F, _F, _F)),
}


def _shadow_copy(path):
    """Load a versioned copy, so the library in native/runtimes is never locked by
    Blender (a loaded library is locked on Windows): it can be rebuilt while Blender
    runs, and a reloaded addon picks up the new build. Falls back to the original path."""
    try:
        stat = os.stat(path)
        folder = os.path.join(tempfile.gettempdir(), 'pixel_painter_native')
        os.makedirs(folder, exist_ok=True)
        base, ext = os.path.splitext(os.path.basename(path))
        target = os.path.join(folder, f"{base}-{stat.st_mtime_ns:x}-{stat.st_size:x}{ext}")
        if not os.path.isfile(target):
            shutil.copy2(path, target + '.tmp')
            os.replace(target + '.tmp', target)
        for name in os.listdir(folder):   # older builds (ones still loaded stay locked)
            if name.startswith(base + '-') and os.path.join(folder, name) != target:
                try:
                    os.remove(os.path.join(folder, name))
                except OSError:
                    pass
        return target
    except Exception:
        return path


def _load():
    global _lib, _error, _tried
    if _tried:
        return _lib
    _tried = True
    path = library_path()
    if not os.path.isfile(path):
        _error = f"Library not built for this platform ({_rid()[0]}): run native/build.ps1"
        return None
    try:
        lib = ctypes.CDLL(_shadow_copy(path))
        for name, (restype, argtypes) in _SIGNATURES.items():
            fn = getattr(lib, name)
            fn.restype = restype
            fn.argtypes = argtypes
        version = lib.pp_api_version()
        if version != API_VERSION:
            _error = f"Library API version {version}, expected {API_VERSION}: rebuild native/"
            return None
        _lib = lib
    except Exception as exc:  # missing export, wrong architecture, ...
        _error = f"Could not load {os.path.basename(path)}: {exc}"
        _lib = None
    return _lib


def available():
    """The native library is loaded and usable."""
    return _load() is not None


def status():
    """Short human-readable state for the settings UI."""
    if available():
        return "C# backend loaded"
    return _error or "C# backend unavailable"


def set_override(value):
    """Tests: ``True`` / ``False`` force :func:`enabled`, ``None`` reads the setting again."""
    global _override
    _override = value


def enabled():
    """Use the native backend: library loaded and the setting on."""
    if _override is not None:
        return bool(_override) and available()
    if not available():
        return False
    try:
        import bpy
        return bool(getattr(bpy.context.window_manager, SETTING, True))
    except Exception:
        return True


# ---------------------------------------------------------------------------
# Array helpers
# ---------------------------------------------------------------------------

def _ptr(arr):
    return None if arr is None else arr.ctypes.data


def _image_buffer(buf, w, h):
    if (not isinstance(buf, np.ndarray) or buf.dtype != np.float32 or not buf.flags.c_contiguous
            or not buf.flags.writeable or buf.size != w * h * 4):
        raise ValueError("image buffer must be a writable, contiguous float32 array of w * h * 4")
    return buf


def coords(pixels):
    """``(N, 2)`` contiguous int32 array from an array or an iterable of ``(x, y)``."""
    if isinstance(pixels, np.ndarray):
        return np.ascontiguousarray(pixels, dtype=np.int32).reshape(-1, 2)
    if not isinstance(pixels, (list, tuple)):
        pixels = list(pixels)
    if not pixels:
        return np.zeros((0, 2), dtype=np.int32)
    return np.ascontiguousarray(np.array(pixels, dtype=np.int32).reshape(-1, 2))


def weights_array(weights, n):
    if weights is None:
        return None
    arr = np.ascontiguousarray(weights, dtype=np.float32).reshape(-1)
    if arr.size != n:
        raise ValueError("weights must match the pixel count")
    return arr


def blend_id(blend):
    return BLEND_IDS.get(blend, 0)


def _ok(result):
    return result is not None and result > -1000


# ---------------------------------------------------------------------------
# Pixel kernels (buffers modified in place; return None on failure)
# ---------------------------------------------------------------------------

def paint(buf, w, h, xy, weights, color, blend, opacity, alpha, protect, base=None):
    """tools/paint.pixels.write_pixels_to_image on ``buf``. ``base``: read dst from there."""
    lib = _load()
    _image_buffer(buf, w, h)
    if base is not None:
        base = np.ascontiguousarray(base, dtype=np.float32)
        if base.size != buf.size:
            raise ValueError("base buffer size mismatch")
    xy = coords(xy)
    wts = weights_array(weights, len(xy))
    r = lib.pp_paint(_ptr(buf), _ptr(base), w, h, _ptr(xy), _ptr(wts), len(xy),
                     float(color[0]), float(color[1]), float(color[2]),
                     blend_id(blend), float(opacity), float(alpha), int(bool(protect)))
    return r if _ok(r) else None


def set_alpha(buf, w, h, xy, weights, alpha, opacity, protect):
    lib = _load()
    _image_buffer(buf, w, h)
    xy = coords(xy)
    wts = weights_array(weights, len(xy))
    r = lib.pp_set_alpha(_ptr(buf), w, h, _ptr(xy), _ptr(wts), len(xy),
                         float(alpha), float(opacity), int(bool(protect)))
    return r if _ok(r) else None


def erase(buf, w, h, xy, opacity):
    lib = _load()
    _image_buffer(buf, w, h)
    xy = coords(xy)
    r = lib.pp_erase(_ptr(buf), w, h, _ptr(xy), len(xy), float(opacity))
    return r if _ok(r) else None


def valid_mask(valid, w, h):
    """``(w * h,)`` contiguous uint8 array of a readable-pixel mask (None = every pixel)."""
    if valid is None:
        return None
    arr = np.ascontiguousarray(valid, dtype=np.uint8).reshape(-1)
    if arr.size != w * h:
        raise ValueError("valid mask must have w * h entries")
    return arr


def smooth(buf, w, h, xy, weights, radius, opacity, protect=False, valid=None):
    """``valid``: optional per-pixel mask of the pixels the blur may read (Edge mode)."""
    lib = _load()
    _image_buffer(buf, w, h)
    xy = coords(xy)
    wts = weights_array(weights, len(xy))
    valid = valid_mask(valid, w, h)
    r = lib.pp_smooth(_ptr(buf), w, h, _ptr(xy), _ptr(wts), len(xy),
                      int(radius), float(opacity), int(bool(protect)), _ptr(valid))
    return r if _ok(r) else None


def smear(buf, w, h, xy, weights, dx, dy, reach, opacity, protect=False, valid=None):
    """``valid``: optional per-pixel mask of the pixels the smear may pull from (Edge mode)."""
    lib = _load()
    _image_buffer(buf, w, h)
    xy = coords(xy)
    wts = weights_array(weights, len(xy))
    valid = valid_mask(valid, w, h)
    r = lib.pp_smear(_ptr(buf), w, h, _ptr(xy), _ptr(wts), len(xy),
                     float(dx), float(dy), float(reach), float(opacity), int(bool(protect)), _ptr(valid))
    return r if _ok(r) else None


# ---------------------------------------------------------------------------
# Brush footprints
# ---------------------------------------------------------------------------

def _stamp_capacity(centers, radius, w, h, grid):
    k = 2 * max(0, int(radius)) + 1
    if grid is not None:
        return min(len(centers) * k * k, w * h)
    lo = np.maximum(centers.min(axis=0) - radius, 0)
    hi = np.minimum(centers.max(axis=0) + radius, (w - 1, h - 1))
    area = int(max(0, hi[0] - lo[0] + 1)) * int(max(0, hi[1] - lo[1] + 1))
    return min(len(centers) * k * k, area)


# Island clipping label per stamp center (Stamps.cs).
CLIP_NONE = -2   # stamp not clipped
CLIP_SKIP = -1   # stamp paints nothing


def _stamp_call(fn_name, centers, radius, w, h, grid, islands, *args):
    lib = _load()
    centers = coords(centers)
    if len(centers) == 0:
        return np.zeros((0, 2), dtype=np.int32), np.zeros(0, dtype=np.float32)
    if grid is not None:
        if grid.dtype != np.float32 or grid.size != w * h or not grid.flags.c_contiguous:
            raise ValueError("stroke grid must be a contiguous float32 array of w * h")
    label_map = center_labels = None
    if islands is not None:
        label_map, center_labels = islands
        label_map = np.ascontiguousarray(label_map, dtype=np.int32)
        center_labels = np.ascontiguousarray(center_labels, dtype=np.int32)
        if label_map.size != w * h or center_labels.size != len(centers):
            raise ValueError("island labels: size mismatch")
    cap = _stamp_capacity(centers, int(radius), w, h, grid)
    out_xy = np.empty((max(cap, 1), 2), dtype=np.int32)
    out_w = np.empty(max(cap, 1), dtype=np.float32)
    n = getattr(lib, fn_name)(_ptr(centers), len(centers), int(radius), *args,
                              w, h, _ptr(grid), _ptr(label_map), _ptr(center_labels),
                              _ptr(out_xy), _ptr(out_w), cap)
    if not _ok(n) or n < 0:
        return None
    return out_xy[:n], out_w[:n]


def stamp(centers, radius, kernel, w, h, grid=None, islands=None):
    """Stamp ``kernel`` ((2r+1)^2 float32, row-major dy then dx, 0 = uncovered) at every center.

    Returns ``(xy (N, 2) int32, weights (N,) float32)``: without ``grid`` every
    covered in-image pixel with its max weight; with a stroke ``grid`` (w*h
    float32, updated in place) only the pixels covered for the first time.
    ``islands`` = ``(label_map (w*h int32), center_labels (N,) int32)`` clips
    each stamp to the pixels carrying its center's label (``CLIP_NONE`` /
    ``CLIP_SKIP`` per center). ``None`` on failure.
    """
    kernel = np.ascontiguousarray(kernel, dtype=np.float32)
    return _stamp_call('pp_stamp_kernel', centers, radius, w, h, grid, islands, _ptr(kernel))


def spray(centers, radius, density, kernel, seed, w, h, grid=None, islands=None):
    """utils/math_utils.get_spray_pixels at every center, merged like :func:`stamp`."""
    kernel = np.ascontiguousarray(kernel, dtype=np.float32)
    return _stamp_call('pp_stamp_spray', centers, radius, w, h, grid, islands,
                       float(density), _ptr(kernel), int(seed) & 0x7FFFFFFF)


# ---------------------------------------------------------------------------
# Mask, regions, rasterization
# ---------------------------------------------------------------------------

def restore_blocked(after, before, allowed):
    """Copy protected pixels (``allowed`` False) that changed from ``before`` back into ``after``.

    Returns the number restored (None on failure)."""
    lib = _load()
    allowed = np.ascontiguousarray(allowed, dtype=bool)
    before = np.ascontiguousarray(before, dtype=np.float32)
    if after.dtype != np.float32 or not after.flags.c_contiguous or after.size != allowed.size * 4 \
            or before.size != after.size:
        raise ValueError("restore_blocked: size / layout mismatch")
    r = lib.pp_restore_blocked(_ptr(after), _ptr(before), _ptr(allowed.view(np.uint8)), allowed.size)
    return r if _ok(r) else None


def blend_region(dst_rgba, src_rgba, blend, opacity):
    """tools/paint.blending.blend_region_pixels with a scalar opacity; returns a new array."""
    lib = _load()
    dst = np.ascontiguousarray(dst_rgba, dtype=np.float32)
    src = np.ascontiguousarray(src_rgba, dtype=np.float32)
    out = np.empty_like(dst)
    r = lib.pp_blend_region(_ptr(dst), _ptr(src), _ptr(out), dst.size // 4, blend_id(blend), float(opacity))
    return out if _ok(r) else None


def blit_region(buf, w, h, region, dest_left, dest_bottom, dest_w, dest_h, clip, blend, opacity):
    """Nearest-neighbor scale ``region`` (rh, rw, 4) to the destination box and blend it into
    ``clip`` = (left, bottom, right, top) of the image buffer."""
    lib = _load()
    _image_buffer(buf, w, h)
    region = np.ascontiguousarray(region, dtype=np.float32)
    rh, rw = region.shape[:2]
    r = lib.pp_blit_region(_ptr(buf), w, h, _ptr(region), rw, rh, int(dest_left), int(dest_bottom),
                           int(dest_w), int(dest_h), int(clip[0]), int(clip[1]), int(clip[2]), int(clip[3]),
                           blend_id(blend), float(opacity))
    return r if _ok(r) else None


def raster_triangles(tri_uv, width, height, grow=0.0):
    """Bool mask (width * height) of pixel centers inside the UV triangles (T, 3, 2)."""
    lib = _load()
    tris = np.ascontiguousarray(tri_uv, dtype=np.float64).reshape(-1, 6)
    mask = np.zeros(int(width) * int(height), dtype=np.uint8)
    r = lib.pp_raster_triangles(_ptr(tris), len(tris), int(width), int(height), float(grow), _ptr(mask))
    return mask.view(bool) if _ok(r) else None


def raster_labels(tri_uv, tri_labels, label_count, width, height):
    """Label map (width * height int32, -1 = no triangle) of pixel centers inside the UV
    triangles (T, 3, 2). Labels meeting on a pixel are merged; returns
    ``(label_map, merged tri_labels)`` or None."""
    lib = _load()
    tris = np.ascontiguousarray(tri_uv, dtype=np.float64).reshape(-1, 6)
    labels = np.ascontiguousarray(tri_labels, dtype=np.int32).copy()
    out = np.empty(int(width) * int(height), dtype=np.int32)
    r = lib.pp_raster_labels(_ptr(tris), _ptr(labels), len(tris), int(label_count),
                             int(width), int(height), _ptr(out))
    return (out, labels) if _ok(r) else None


def fill_uv_triangles(buf, w, h, tri_uv, color):
    """Paint pixels with any corner inside a UV triangle (T, 3, 2) opaque ``color``."""
    lib = _load()
    _image_buffer(buf, w, h)
    tris = np.ascontiguousarray(tri_uv, dtype=np.float64).reshape(-1, 6)
    r = lib.pp_fill_uv_triangles(_ptr(buf), w, h, _ptr(tris), len(tris),
                                 float(color[0]), float(color[1]), float(color[2]))
    return r if _ok(r) else None
