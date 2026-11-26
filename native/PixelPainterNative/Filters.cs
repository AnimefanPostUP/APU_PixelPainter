namespace PixelPainterNative;

/// <summary>Smooth and Smear (tools/draw_tool_smooth.py). Both read the original
/// image and write the results afterwards, so pixels never see each other's output.
///
/// <c>valid</c> (optional, one byte per pixel, null = every pixel) marks the pixels a
/// filter may read from. Edge mode (core/view3d.py, EdgePatch) filters a patch unfolded
/// across UV seams; texels off the surface are invalid and never sampled.</summary>
internal static unsafe class Filters
{
    // Summed-area table limit (cells); 7 doubles per cell -> ~56 MB at the limit.
    private const long SatMaxCells = 1L << 20;

    private static int Select(float* buf, int w, int h, int* xy, float* weights, int n, bool protect,
                              int[] sel, out int minX, out int minY, out int maxX, out int maxY)
    {
        minX = minY = int.MaxValue;
        maxX = maxY = int.MinValue;
        int m = 0;
        for (int i = 0; i < n; i++)
        {
            int x = xy[2 * i], y = xy[2 * i + 1];
            if ((uint)x >= (uint)w || (uint)y >= (uint)h)
                continue;
            float wt = weights != null ? weights[i] : 1f;
            if (!(wt > 0f))
                continue;
            if (protect && !((double)buf[((long)y * w + x) * 4 + 3] > 1e-6))
                continue;
            sel[m++] = i;
            if (x < minX) minX = x;
            if (x > maxX) maxX = x;
            if (y < minY) minY = y;
            if (y > maxY) maxY = y;
        }
        return m;
    }

    /// <summary>Alpha-weighted box blur of radius <paramref name="radius"/> at each pixel
    /// (plain mean where the box is fully transparent), mixed by opacity * weight.</summary>
    public static int Smooth(float* buf, int w, int h, int* xy, float* weights, int n,
                             int radius, double opacity, bool protect, byte* valid = null)
    {
        if (n <= 0)
            return 0;
        int r = Math.Max(0, radius);
        var sel = new int[n];
        int m = Select(buf, w, h, xy, weights, n, protect, sel, out int minX, out int minY, out int maxX, out int maxY);
        if (m == 0)
            return 0;

        int X0 = Math.Max(0, minX - r), X1 = Math.Min(w - 1, maxX + r);
        int Y0 = Math.Max(0, minY - r), Y1 = Math.Min(h - 1, maxY + r);
        int bw = X1 - X0 + 1, bh = Y1 - Y0 + 1;
        var outRgb = new float[m * 3];

        if ((long)(bw + 1) * (bh + 1) <= SatMaxCells)
            SmoothSat(buf, w, xy, weights, valid, sel, m, r, opacity, X0, Y0, X1, Y1, outRgb);
        else
            SmoothDirect(buf, w, h, xy, weights, valid, sel, m, r, opacity, outRgb);

        for (int j = 0; j < m; j++)
        {
            int i = sel[j];
            long idx = ((long)xy[2 * i + 1] * w + xy[2 * i]) * 4;
            buf[idx] = outRgb[3 * j];
            buf[idx + 1] = outRgb[3 * j + 1];
            buf[idx + 2] = outRgb[3 * j + 2];
        }
        return m;
    }

    private static void Mix(float* buf, long idx, double wt, double opacity,
                            double asum, double sar, double sag, double sab,
                            double sr, double sg, double sb, long count, float[] outRgb, int j)
    {
        if (count <= 0)
        {
            // nothing readable in the box (Edge mode): keep the pixel
            outRgb[3 * j] = buf[idx]; outRgb[3 * j + 1] = buf[idx + 1]; outRgb[3 * j + 2] = buf[idx + 2];
            return;
        }
        float ar, ag, ab;
        if (asum > 1e-6)
        {
            ar = (float)(sar / asum); ag = (float)(sag / asum); ab = (float)(sab / asum);
        }
        else
        {
            ar = (float)(sr / count); ag = (float)(sg / count); ab = (float)(sb / count);
        }
        float f = (float)(opacity * wt);
        float orr = buf[idx], og = buf[idx + 1], ob = buf[idx + 2];
        outRgb[3 * j] = orr + (ar - orr) * f;
        outRgb[3 * j + 1] = og + (ag - og) * f;
        outRgb[3 * j + 2] = ob + (ab - ob) * f;
    }

    private static void SmoothSat(float* buf, int w, int* xy, float* weights, byte* valid, int[] sel, int m,
                                  int r, double opacity, int X0, int Y0, int X1, int Y1, float[] outRgb)
    {
        int bw = X1 - X0 + 1, bh = Y1 - Y0 + 1;
        int sw = bw + 1;
        const int C = 8;   // a, a*r, a*g, a*b, r, g, b, count (readable pixels)
        var sat = new double[(long)sw * (bh + 1) * C];
        var row = new double[C];
        for (int y = 0; y < bh; y++)
        {
            Array.Clear(row);
            long src = ((long)(Y0 + y) * w + X0) * 4;
            long prev = (long)y * sw * C;
            long cur = (long)(y + 1) * sw * C;
            for (int x = 0; x < bw; x++, src += 4)
            {
                if (valid == null || valid[src >> 2] != 0)
                {
                    double pr = buf[src], pg = buf[src + 1], pb = buf[src + 2], pa = buf[src + 3];
                    row[0] += pa; row[1] += pa * pr; row[2] += pa * pg; row[3] += pa * pb;
                    row[4] += pr; row[5] += pg; row[6] += pb; row[7] += 1;
                }
                long o = cur + (x + 1) * C, po = prev + (x + 1) * C;
                for (int c = 0; c < C; c++)
                    sat[o + c] = sat[po + c] + row[c];
            }
        }

        Parallel.For(0, m, j =>
        {
            int i = sel[j];
            int px = xy[2 * i], py = xy[2 * i + 1];
            int x0 = Math.Max(X0, px - r) - X0, x1 = Math.Min(X1, px + r) - X0 + 1;
            int y0 = Math.Max(Y0, py - r) - Y0, y1 = Math.Min(Y1, py + r) - Y0 + 1;
            Span<double> s = stackalloc double[C];
            long a = ((long)y1 * sw + x1) * C, b = ((long)y0 * sw + x1) * C;
            long c0 = ((long)y1 * sw + x0) * C, d = ((long)y0 * sw + x0) * C;
            for (int c = 0; c < C; c++)
                s[c] = sat[a + c] - sat[b + c] - sat[c0 + c] + sat[d + c];
            double wt = weights != null ? weights[i] : 1.0;
            Mix(buf, ((long)py * w + px) * 4, wt, opacity, s[0], s[1], s[2], s[3], s[4], s[5], s[6],
                (long)Math.Round(s[7]), outRgb, j);
        });
    }

    private static void SmoothDirect(float* buf, int w, int h, int* xy, float* weights, byte* valid, int[] sel,
                                     int m, int r, double opacity, float[] outRgb)
    {
        Parallel.For(0, m, j =>
        {
            int i = sel[j];
            int px = xy[2 * i], py = xy[2 * i + 1];
            int x0 = Math.Max(0, px - r), x1 = Math.Min(w - 1, px + r);
            int y0 = Math.Max(0, py - r), y1 = Math.Min(h - 1, py + r);
            double asum = 0, sar = 0, sag = 0, sab = 0, sr = 0, sg = 0, sb = 0;
            long count = 0;
            for (int y = y0; y <= y1; y++)
            {
                long p = ((long)y * w + x0) * 4;
                for (int x = x0; x <= x1; x++, p += 4)
                {
                    if (valid != null && valid[p >> 2] == 0)
                        continue;
                    count++;
                    double pr = buf[p], pg = buf[p + 1], pb = buf[p + 2], pa = buf[p + 3];
                    asum += pa; sar += pa * pr; sag += pa * pg; sab += pa * pb;
                    sr += pr; sg += pg; sb += pb;
                }
            }
            double wt = weights != null ? weights[i] : 1.0;
            Mix(buf, ((long)py * w + px) * 4, wt, opacity, asum, sar, sag, sab, sr, sg, sb, count, outRgb, j);
        });
    }

    /// <summary>Pull color from (x - dx*reach, y - dy*reach), mixed by opacity * weight.
    /// Without <c>valid</c> the source is clamped to the image; with it, a source outside
    /// the buffer or on an invalid pixel leaves the pixel unchanged.</summary>
    public static int Smear(float* buf, int w, int h, int* xy, float* weights, int n,
                            double dx, double dy, double reach, double opacity, bool protect,
                            byte* valid = null)
    {
        if (n <= 0)
            return 0;
        var sel = new int[n];
        int m = Select(buf, w, h, xy, weights, n, protect, sel, out _, out _, out _, out _);
        if (m == 0)
            return 0;
        var outRgb = new float[m * 3];
        for (int j = 0; j < m; j++)
        {
            int i = sel[j];
            int px = xy[2 * i], py = xy[2 * i + 1];
            int sx = (int)Math.Round(px - dx * reach, MidpointRounding.ToEven);   // Python round()
            int sy = (int)Math.Round(py - dy * reach, MidpointRounding.ToEven);
            long d = ((long)py * w + px) * 4;
            if (valid != null && ((uint)sx >= (uint)w || (uint)sy >= (uint)h || valid[(long)sy * w + sx] == 0))
            {
                outRgb[3 * j] = buf[d]; outRgb[3 * j + 1] = buf[d + 1]; outRgb[3 * j + 2] = buf[d + 2];
                continue;
            }
            sx = Math.Clamp(sx, 0, w - 1);
            sy = Math.Clamp(sy, 0, h - 1);
            long s = ((long)sy * w + sx) * 4;
            double wt = weights != null ? weights[i] : 1.0;
            float f = (float)(opacity * wt);
            outRgb[3 * j] = buf[d] + (buf[s] - buf[d]) * f;
            outRgb[3 * j + 1] = buf[d + 1] + (buf[s + 1] - buf[d + 1]) * f;
            outRgb[3 * j + 2] = buf[d + 2] + (buf[s + 2] - buf[d + 2]) * f;
        }
        for (int j = 0; j < m; j++)
        {
            int i = sel[j];
            long d = ((long)xy[2 * i + 1] * w + xy[2 * i]) * 4;
            buf[d] = outRgb[3 * j];
            buf[d + 1] = outRgb[3 * j + 1];
            buf[d + 2] = outRgb[3 * j + 2];
        }
        return m;
    }
}
