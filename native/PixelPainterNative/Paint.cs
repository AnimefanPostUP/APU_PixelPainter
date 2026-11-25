namespace PixelPainterNative;

/// <summary>
/// Pixel writes on a flat RGBA float buffer (Blender's Image.pixels layout:
/// rows bottom-up, 4 floats per pixel). Coordinates are (x, y) int pairs;
/// out-of-image coordinates are skipped.
/// </summary>
internal static unsafe class Paint
{
    /// <summary>tools/draw_functions.write_pixels_to_image.</summary>
    /// <param name="basePtr">Optional buffer the destination color / alpha is read from
    /// (pre-stroke snapshot); null = read from <paramref name="buf"/>.</param>
    /// <returns>Number of pixels written.</returns>
    public static int Brush(float* buf, float* basePtr, int w, int h, int* xy, float* weights, int n,
                            float r, float g, float b, int mode, float opacity, float alphaTarget, bool protect)
    {
        float* src = basePtr != null ? basePtr : buf;
        float at = Math.Clamp(alphaTarget, 0f, 1f);
        int count = 0;
        for (int i = 0; i < n; i++)
        {
            int x = xy[2 * i], y = xy[2 * i + 1];
            if ((uint)x >= (uint)w || (uint)y >= (uint)h)
                continue;
            long idx = ((long)y * w + x) * 4;
            if (protect && !(src[idx + 3] > 1e-6f))
                continue;
            float wt = weights != null ? weights[i] : 1f;
            float o = Math.Clamp(opacity * wt, 0f, 1f);
            Blend.Pixel(mode, src[idx], src[idx + 1], src[idx + 2], r, g, b, o,
                        out float orr, out float og, out float ob);
            buf[idx] = Math.Clamp(orr, 0f, 1f);
            buf[idx + 1] = Math.Clamp(og, 0f, 1f);
            buf[idx + 2] = Math.Clamp(ob, 0f, 1f);
            float ad = src[idx + 3];
            buf[idx + 3] = ad + (at - ad) * o;
            count++;
        }
        return count;
    }

    /// <summary>tools/draw_functions.set_pixels_alpha.</summary>
    public static int Alpha(float* buf, int w, int h, int* xy, float* weights, int n,
                            double alpha, double opacity, bool protect)
    {
        double a = Math.Clamp(alpha, 0.0, 1.0);
        double mix = Math.Clamp(opacity, 0.0, 1.0);
        int count = 0;
        for (int i = 0; i < n; i++)
        {
            int x = xy[2 * i], y = xy[2 * i + 1];
            if ((uint)x >= (uint)w || (uint)y >= (uint)h)
                continue;
            long idx = ((long)y * w + x) * 4 + 3;
            double curr = buf[idx];
            if (protect && curr <= 1e-6)
                continue;
            double wt = weights != null ? weights[i] : 1.0;
            buf[idx] = (float)(curr + (a - curr) * mix * wt);
            count++;
        }
        return count;
    }

    /// <summary>EraserTool: alpha -= opacity (floored at 0).</summary>
    public static int Erase(float* buf, int w, int h, int* xy, int n, double opacity)
    {
        int count = 0;
        for (int i = 0; i < n; i++)
        {
            int x = xy[2 * i], y = xy[2 * i + 1];
            if ((uint)x >= (uint)w || (uint)y >= (uint)h)
                continue;
            long idx = ((long)y * w + x) * 4 + 3;
            buf[idx] = (float)Math.Max(0.0, buf[idx] - opacity);
            count++;
        }
        return count;
    }

    /// <summary>tools/mask.restore_blocked: copy back every protected pixel that changed.</summary>
    /// <param name="allowed">One byte per pixel, non-zero = paintable.</param>
    /// <returns>Number of pixels restored.</returns>
    public static long RestoreBlocked(float* after, float* before, byte* allowed, long pixelCount)
    {
        const long Chunk = 1 << 16;
        long chunks = (pixelCount + Chunk - 1) / Chunk;
        long total = 0;
        Parallel.For(0L, chunks,
            () => 0L,
            (c, _, local) =>
            {
                long end = Math.Min(pixelCount, (c + 1) * Chunk);
                for (long p = c * Chunk; p < end; p++)
                {
                    if (allowed[p] != 0)
                        continue;
                    long i = p * 4;
                    // != (not ==) so NaNs count as changed, like NumPy's a4 != b4
                    if (after[i] != before[i] || after[i + 1] != before[i + 1]
                        || after[i + 2] != before[i + 2] || after[i + 3] != before[i + 3])
                    {
                        after[i] = before[i];
                        after[i + 1] = before[i + 1];
                        after[i + 2] = before[i + 2];
                        after[i + 3] = before[i + 3];
                        local++;
                    }
                }
                return local;
            },
            local => Interlocked.Add(ref total, local));
        return total;
    }
}
