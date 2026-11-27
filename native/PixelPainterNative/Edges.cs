namespace PixelPainterNative;

/// <summary>
/// Per-texel distance to the edge segments of the texel's own element
/// (paint/edge_ramp.segment_distance, the Extras window's Edges tool and Fill's fade-out).
/// </summary>
public static unsafe class Edges
{
    private const int Band = 16;   // image rows per parallel work item

    /// <summary>
    /// <paramref name="seg"/>: (n, 2, 2) segment ends in pixel units; <paramref name="segLabel"/>: (n);
    /// <paramref name="labels"/>: (w * h) element per texel; <paramref name="outp"/>: (w * h), filled
    /// with +inf by the caller, lowered to the distance from each texel center to the nearest segment
    /// of its label whose box (grown by <paramref name="reach"/>) covers the texel.
    /// </summary>
    public static int SegmentDistance(double* seg, int* segLabel, int n, int* labels, int w, int h,
                                      double reach, double* outp)
    {
        if (n <= 0 || w <= 0 || h <= 0) return 0;
        var x0 = new int[n]; var x1 = new int[n]; var y0 = new int[n]; var y1 = new int[n];
        int bands = (h + Band - 1) / Band;
        var count = new int[bands + 1];
        for (int s = 0; s < n; s++)
        {
            double* p = seg + s * 4;
            double lox = Math.Min(p[0], p[2]) - reach, hix = Math.Max(p[0], p[2]) + reach;
            double loy = Math.Min(p[1], p[3]) - reach, hiy = Math.Max(p[1], p[3]) + reach;
            x0[s] = (int)Math.Clamp(Math.Ceiling(lox - 0.5), 0, w);
            x1[s] = (int)Math.Clamp(Math.Floor(hix - 0.5), -1, w - 1);
            y0[s] = (int)Math.Clamp(Math.Ceiling(loy - 0.5), 0, h);
            y1[s] = (int)Math.Clamp(Math.Floor(hiy - 0.5), -1, h - 1);
            if (x1[s] < x0[s] || y1[s] < y0[s]) continue;
            for (int b = y0[s] / Band; b <= y1[s] / Band; b++) count[b + 1]++;
        }
        // Segments per row band (CSR): each band's rows are written by one thread only.
        for (int b = 0; b < bands; b++) count[b + 1] += count[b];
        var members = new int[count[bands]];
        var fill = (int[])count.Clone();
        for (int s = 0; s < n; s++)
        {
            if (x1[s] < x0[s] || y1[s] < y0[s]) continue;
            for (int b = y0[s] / Band; b <= y1[s] / Band; b++) members[fill[b]++] = s;
        }

        Parallel.For(0, bands, b =>
        {
            int rowLo = b * Band, rowHi = Math.Min(h - 1, rowLo + Band - 1);
            for (int m = count[b]; m < count[b + 1]; m++)
            {
                int s = members[m];
                double* p = seg + s * 4;
                double ax = p[0], ay = p[1];
                double abx = p[2] - ax, aby = p[3] - ay;
                double denom = abx * abx + aby * aby;
                if (!(denom > 1e-12)) denom = 1.0;
                int label = segLabel[s];
                int ya = Math.Max(rowLo, y0[s]), yb = Math.Min(rowHi, y1[s]);
                for (int y = ya; y <= yb; y++)
                {
                    double py = y + 0.5;
                    int row = y * w;
                    for (int x = x0[s]; x <= x1[s]; x++)
                    {
                        int flat = row + x;
                        if (labels[flat] != label) continue;
                        double px = x + 0.5;
                        double t = ((px - ax) * abx + (py - ay) * aby) / denom;
                        t = t < 0.0 ? 0.0 : (t > 1.0 ? 1.0 : t);
                        double dx = (ax + abx * t) - px, dy = (ay + aby * t) - py;
                        double d = Math.Sqrt(dx * dx + dy * dy);
                        if (d < outp[flat]) outp[flat] = d;
                    }
                }
            }
        });
        return n;
    }
}
