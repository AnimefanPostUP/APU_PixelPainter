using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;

[module: SkipLocalsInit]

namespace PixelPainterNative;

/// <summary>
/// C ABI of the library (loaded by utils/native.py with ctypes).
///
/// Conventions: images are flat float32 RGBA buffers (w * h * 4), coordinates
/// are int32 (x, y) pairs, weights are float32 (null = 1.0), flags are int
/// (0 / 1). Every entry point catches exceptions -- an exception must never
/// cross into Blender -- and returns a negative value on failure, which makes
/// the Python side fall back to its own implementation.
///
/// Bump <see cref="ApiVersion"/> (and utils/native.API_VERSION) whenever a
/// signature changes.
/// </summary>
public static unsafe class Exports
{
    public const int ApiVersion = 1;
    private const int Failed = -1000;

    [UnmanagedCallersOnly(EntryPoint = "pp_api_version")]
    public static int ApiVersionExport() => ApiVersion;

    [UnmanagedCallersOnly(EntryPoint = "pp_paint")]
    public static int PaintExport(float* buf, float* basePtr, int w, int h, int* xy, float* weights, int n,
                                  float r, float g, float b, int blend, float opacity, float alpha, int protect)
    {
        try { return Paint.Brush(buf, basePtr, w, h, xy, weights, n, r, g, b, blend, opacity, alpha, protect != 0); }
        catch { return Failed; }
    }

    [UnmanagedCallersOnly(EntryPoint = "pp_set_alpha")]
    public static int SetAlphaExport(float* buf, int w, int h, int* xy, float* weights, int n,
                                     double alpha, double opacity, int protect)
    {
        try { return Paint.Alpha(buf, w, h, xy, weights, n, alpha, opacity, protect != 0); }
        catch { return Failed; }
    }

    [UnmanagedCallersOnly(EntryPoint = "pp_erase")]
    public static int EraseExport(float* buf, int w, int h, int* xy, int n, double opacity)
    {
        try { return Paint.Erase(buf, w, h, xy, n, opacity); }
        catch { return Failed; }
    }

    [UnmanagedCallersOnly(EntryPoint = "pp_smooth")]
    public static int SmoothExport(float* buf, int w, int h, int* xy, float* weights, int n,
                                   int radius, double opacity, int protect)
    {
        try { return Filters.Smooth(buf, w, h, xy, weights, n, radius, opacity, protect != 0); }
        catch { return Failed; }
    }

    [UnmanagedCallersOnly(EntryPoint = "pp_smear")]
    public static int SmearExport(float* buf, int w, int h, int* xy, float* weights, int n,
                                  double dx, double dy, double reach, double opacity, int protect)
    {
        try { return Filters.Smear(buf, w, h, xy, weights, n, dx, dy, reach, opacity, protect != 0); }
        catch { return Failed; }
    }

    [UnmanagedCallersOnly(EntryPoint = "pp_stamp_kernel")]
    public static int StampKernelExport(int* centers, int nc, int radius, float* kernel, int w, int h,
                                        float* grid, int* outXY, float* outW, int cap)
    {
        try { return Stamps.Kernel(centers, nc, radius, kernel, w, h, grid, outXY, outW, cap); }
        catch { return Failed; }
    }

    [UnmanagedCallersOnly(EntryPoint = "pp_stamp_spray")]
    public static int StampSprayExport(int* centers, int nc, int radius, double density, float* kernel, int seed,
                                       int w, int h, float* grid, int* outXY, float* outW, int cap)
    {
        try { return Stamps.Spray(centers, nc, radius, density, kernel, seed, w, h, grid, outXY, outW, cap); }
        catch { return Failed; }
    }

    [UnmanagedCallersOnly(EntryPoint = "pp_restore_blocked")]
    public static long RestoreBlockedExport(float* after, float* before, byte* allowed, long pixelCount)
    {
        try { return Paint.RestoreBlocked(after, before, allowed, pixelCount); }
        catch { return Failed; }
    }

    [UnmanagedCallersOnly(EntryPoint = "pp_blend_region")]
    public static int BlendRegionExport(float* dst, float* src, float* outp, long n, int blend, float opacity)
    {
        try { Regions.BlendRegion(dst, src, outp, n, blend, opacity); return 0; }
        catch { return Failed; }
    }

    [UnmanagedCallersOnly(EntryPoint = "pp_blit_region")]
    public static int BlitRegionExport(float* buf, int w, int h, float* region, int rw, int rh,
                                       int destLeft, int destBottom, int destW, int destH,
                                       int clipL, int clipB, int clipR, int clipT, int blend, float opacity)
    {
        try
        {
            Regions.Blit(buf, w, h, region, rw, rh, destLeft, destBottom, destW, destH,
                         clipL, clipB, clipR, clipT, blend, opacity);
            return 0;
        }
        catch { return Failed; }
    }

    [UnmanagedCallersOnly(EntryPoint = "pp_raster_triangles")]
    public static int RasterTrianglesExport(double* tris, int count, int w, int h, double grow, byte* mask)
    {
        try { Raster.Triangles(tris, count, w, h, grow, mask); return 0; }
        catch { return Failed; }
    }

    [UnmanagedCallersOnly(EntryPoint = "pp_fill_uv_triangles")]
    public static long FillUvTrianglesExport(float* buf, int w, int h, double* tris, int count,
                                             float r, float g, float b)
    {
        try { return Raster.FillUv(buf, w, h, tris, count, r, g, b); }
        catch { return Failed; }
    }
}
