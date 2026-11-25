namespace PixelPainterNative;

/// <summary>UV triangle rasterization (tools/mask_geometry.raster_triangles,
/// ui/paint_selected_faces_uv). Triangles are 6 doubles each: u0 v0 u1 v1 u2 v2.</summary>
internal static unsafe class Raster
{
    /// <summary>Mark every pixel whose center lies inside a triangle, edges pushed out by
    /// <paramref name="grow"/> pixels. <paramref name="mask"/> has one byte per pixel.</summary>
    public static void Triangles(double* tris, int count, int w, int h, double grow, byte* mask)
    {
        double reach = grow + 1e-6;
        Parallel.For(0, count, t =>
        {
            double* p = tris + (long)t * 6;
            double ax = p[0] * w, ay = p[1] * h, bx = p[2] * w, by = p[3] * h, cx = p[4] * w, cy = p[5] * h;
            double e1x = bx - ax, e1y = by - ay, e2x = cx - ax, e2y = cy - ay;
            double cross = e1x * e2y - e1y * e2x;
            if (Math.Abs(cross) < 1e-12)
                return;
            long lox = (long)Math.Floor(Math.Min(ax, Math.Min(bx, cx)) - grow);
            long loy = (long)Math.Floor(Math.Min(ay, Math.Min(by, cy)) - grow);
            long hix = (long)Math.Ceiling(Math.Max(ax, Math.Max(bx, cx)) + grow);
            long hiy = (long)Math.Ceiling(Math.Max(ay, Math.Max(by, cy)) + grow);
            int x0 = (int)Math.Max(0, lox), y0 = (int)Math.Max(0, loy);
            int x1 = (int)Math.Min(w, hix + 1), y1 = (int)Math.Min(h, hiy + 1);
            if (x0 >= x1 || y0 >= y1)
                return;
            double sign = cross > 0 ? 1.0 : -1.0;
            Span<double> vx = stackalloc double[] { ax, bx, cx };
            Span<double> vy = stackalloc double[] { ay, by, cy };
            Span<double> ex = stackalloc double[3];
            Span<double> ey = stackalloc double[3];
            Span<double> len = stackalloc double[3];
            for (int i = 0; i < 3; i++)
            {
                int j = (i + 1) % 3;
                ex[i] = vx[j] - vx[i];
                ey[i] = vy[j] - vy[i];
                len[i] = Math.Sqrt(ex[i] * ex[i] + ey[i] * ey[i]);
            }
            for (int y = y0; y < y1; y++)
            {
                double py = y + 0.5;
                byte* row = mask + (long)y * w;
                for (int x = x0; x < x1; x++)
                {
                    double px = x + 0.5;
                    bool inside = true;
                    for (int i = 0; i < 3 && inside; i++)
                    {
                        if (len[i] < 1e-12)
                            continue;
                        double dist = sign * (ex[i] * (py - vy[i]) - ey[i] * (px - vx[i])) / len[i];
                        inside = dist >= -reach;
                    }
                    if (inside)
                        row[x] = 1;
                }
            }
        });
    }

    private static double Cross(float ax, float ay, float bx, float by) => (double)ax * by - (double)ay * bx;

    private static bool CornerInside(float ptx, float pty, float* v)
    {
        // ui/paint_selected_faces_uv.point_in_triangle: mathutils vectors are float32,
        // the cross products are Python floats.
        double d1 = Cross(v[2] - v[0], v[3] - v[1], ptx - v[0], pty - v[1]);
        double d2 = Cross(v[4] - v[2], v[5] - v[3], ptx - v[2], pty - v[3]);
        double d3 = Cross(v[0] - v[4], v[1] - v[5], ptx - v[4], pty - v[5]);
        bool hasNeg = d1 < 0 || d2 < 0 || d3 < 0;
        bool hasPos = d1 > 0 || d2 > 0 || d3 > 0;
        return !(hasNeg && hasPos);
    }

    /// <summary>Fill every pixel with any corner inside a UV triangle with an opaque color.</summary>
    /// <returns>Painted pixel count (a pixel counts once per triangle covering it).</returns>
    public static long FillUv(float* buf, int w, int h, double* tris, int count, float r, float g, float b)
    {
        long total = 0;
        float* v = stackalloc float[6];
        for (int t = 0; t < count; t++)
        {
            for (int i = 0; i < 6; i++)
                v[i] = (float)tris[(long)t * 6 + i];
            double minU = Math.Min(v[0], Math.Min(v[2], v[4])), maxU = Math.Max(v[0], Math.Max(v[2], v[4]));
            double minV = Math.Min(v[1], Math.Min(v[3], v[5])), maxV = Math.Max(v[1], Math.Max(v[3], v[5]));
            int x0 = (int)Math.Max(Math.Floor(minU * w), 0), x1 = (int)Math.Min(Math.Ceiling(maxU * w), w);
            int y0 = (int)Math.Max(Math.Floor(minV * h), 0), y1 = (int)Math.Min(Math.Ceiling(maxV * h), h);
            for (int y = y0; y < y1; y++)
            {
                float py = (float)((double)y / h), py1 = (float)((double)(y + 1) / h);
                for (int x = x0; x < x1; x++)
                {
                    float px = (float)((double)x / w), px1 = (float)((double)(x + 1) / w);
                    if (CornerInside(px, py, v) || CornerInside(px1, py, v)
                        || CornerInside(px, py1, v) || CornerInside(px1, py1, v))
                    {
                        float* d = buf + ((long)y * w + x) * 4;
                        d[0] = r; d[1] = g; d[2] = b; d[3] = 1f;
                        total++;
                    }
                }
            }
        }
        return total;
    }
}
