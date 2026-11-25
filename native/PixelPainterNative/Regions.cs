namespace PixelPainterNative;

/// <summary>Selection regions (tools/draw_blending.blend_region_pixels, tools/selection_ops.blit_region).</summary>
internal static unsafe class Regions
{
    /// <summary>Blend <paramref name="n"/> RGBA pixels: RGB by the blend mode with the clamped
    /// opacity (not clamped afterwards), alpha toward the source alpha by the raw opacity (clamped).</summary>
    public static void BlendPixel(float* d, float* s, float* o, int mode, float rgbOpacity, float alphaOpacity)
    {
        Blend.Pixel(mode, d[0], d[1], d[2], s[0], s[1], s[2], rgbOpacity, out float r, out float g, out float b);
        float a = d[3] + (s[3] - d[3]) * alphaOpacity;
        o[0] = r;
        o[1] = g;
        o[2] = b;
        o[3] = Math.Clamp(a, 0f, 1f);
    }

    public static void BlendRegion(float* dst, float* src, float* outp, long n, int mode, float opacity)
    {
        float op = Math.Clamp(opacity, 0f, 1f);
        const long Chunk = 4096;
        long chunks = (n + Chunk - 1) / Chunk;
        Parallel.For(0L, chunks, c =>
        {
            long end = Math.Min(n, (c + 1) * Chunk);
            for (long i = c * Chunk; i < end; i++)
                BlendPixel(dst + i * 4, src + i * 4, outp + i * 4, mode, op, opacity);
        });
    }

    /// <summary>Nearest-neighbor scale <paramref name="region"/> (rw x rh) onto the destination
    /// box (destW x destH at destLeft/destBottom) and blend it into the clip box of the image.</summary>
    public static void Blit(float* buf, int w, int h, float* region, int rw, int rh,
                            int destLeft, int destBottom, int destW, int destH,
                            int clipL, int clipB, int clipR, int clipT, int mode, float opacity)
    {
        float op = Math.Clamp(opacity, 0f, 1f);
        int sxMax = Math.Max(0, rw - 1), syMax = Math.Max(0, rh - 1);
        double dxDen = Math.Max(1, destW - 1), dyDen = Math.Max(1, destH - 1);
        Parallel.For(clipB, clipT + 1, y =>
        {
            int dy = y - destBottom;
            int sy = destH > 1 ? (int)Math.Round(dy / dyDen * syMax, MidpointRounding.ToEven) : 0;
            sy = Math.Clamp(sy, 0, rh - 1);
            float* pix = stackalloc float[4];
            for (int x = clipL; x <= clipR; x++)
            {
                int dx = x - destLeft;
                int sx = destW > 1 ? (int)Math.Round(dx / dxDen * sxMax, MidpointRounding.ToEven) : 0;
                sx = Math.Clamp(sx, 0, rw - 1);
                float* d = buf + ((long)y * w + x) * 4;
                BlendPixel(d, region + ((long)sy * rw + sx) * 4, pix, mode, op, opacity);
                d[0] = pix[0]; d[1] = pix[1]; d[2] = pix[2]; d[3] = pix[3];
            }
        });
    }
}
