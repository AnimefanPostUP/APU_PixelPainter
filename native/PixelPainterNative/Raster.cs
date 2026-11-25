namespace PixelPainterNative;

/// <summary>UV triangle rasterization (tools/mask_geometry.raster_triangles,
/// core/view3d island maps, ui/paint_selected_faces_uv). Triangles are 6 doubles
/// each: u0 v0 u1 v1 u2 v2.</summary>
internal static unsafe class Raster
{
    /// <summary>One triangle in pixel space: bounding box and inside test (pixel centers).</summary>
    private struct Tri
    {
        public int X0, Y0, X1, Y1;   // pixel box, end exclusive
        private double _ax, _ay, _bx, _by, _cx, _cy;
        private double _e0x, _e0y, _e1x, _e1y, _e2x, _e2y, _l0, _l1, _l2;
        private double _sign, _reach;

        /// <returns>False for degenerate or off-image triangles.</returns>
        public bool Setup(double* p, int w, int h, double grow)
        {
            _ax = p[0] * w; _ay = p[1] * h; _bx = p[2] * w; _by = p[3] * h; _cx = p[4] * w; _cy = p[5] * h;
            double e1x = _bx - _ax, e1y = _by - _ay, e2x = _cx - _ax, e2y = _cy - _ay;
            double cross = e1x * e2y - e1y * e2x;
            if (Math.Abs(cross) < 1e-12)
                return false;
            long lox = (long)Math.Floor(Math.Min(_ax, Math.Min(_bx, _cx)) - grow);
            long loy = (long)Math.Floor(Math.Min(_ay, Math.Min(_by, _cy)) - grow);
            long hix = (long)Math.Ceiling(Math.Max(_ax, Math.Max(_bx, _cx)) + grow);
            long hiy = (long)Math.Ceiling(Math.Max(_ay, Math.Max(_by, _cy)) + grow);
            X0 = (int)Math.Max(0, lox);
            Y0 = (int)Math.Max(0, loy);
            X1 = (int)Math.Min(w, hix + 1);
            Y1 = (int)Math.Min(h, hiy + 1);
            if (X0 >= X1 || Y0 >= Y1)
                return false;
            _sign = cross > 0 ? 1.0 : -1.0;
            _reach = grow + 1e-6;
            _e0x = _bx - _ax; _e0y = _by - _ay; _l0 = Math.Sqrt(_e0x * _e0x + _e0y * _e0y);
            _e1x = _cx - _bx; _e1y = _cy - _by; _l1 = Math.Sqrt(_e1x * _e1x + _e1y * _e1y);
            _e2x = _ax - _cx; _e2y = _ay - _cy; _l2 = Math.Sqrt(_e2x * _e2x + _e2y * _e2y);
            return true;
        }

        private bool Edge(double ex, double ey, double len, double vx, double vy, double px, double py)
        {
            if (len < 1e-12)
                return true;
            double dist = _sign * (ex * (py - vy) - ey * (px - vx)) / len;
            return dist >= -_reach;
        }

        public bool Inside(int x, int y)
        {
            double px = x + 0.5, py = y + 0.5;
            return Edge(_e0x, _e0y, _l0, _ax, _ay, px, py)
                && Edge(_e1x, _e1y, _l1, _bx, _by, px, py)
                && Edge(_e2x, _e2y, _l2, _cx, _cy, px, py);
        }
    }

    /// <summary>Mark every pixel whose center lies inside a triangle, edges pushed out by
    /// <paramref name="grow"/> pixels. <paramref name="mask"/> has one byte per pixel.</summary>
    public static void Triangles(double* tris, int count, int w, int h, double grow, byte* mask)
    {
        Parallel.For(0, count, t =>
        {
            var tri = new Tri();
            if (!tri.Setup(tris + (long)t * 6, w, h, grow))
                return;
            for (int y = tri.Y0; y < tri.Y1; y++)
            {
                byte* row = mask + (long)y * w;
                for (int x = tri.X0; x < tri.X1; x++)
                    if (tri.Inside(x, y))
                        row[x] = 1;
            }
        });
    }

    private static int Find(int[] parent, int i)
    {
        while (parent[i] != i)
        {
            parent[i] = parent[parent[i]];
            i = parent[i];
        }
        return i;
    }

    /// <summary>Label map: every pixel whose center lies inside a triangle gets that triangle's
    /// label (<paramref name="outMap"/> = -1 elsewhere). Labels meeting on a pixel (overlapping
    /// UVs) are merged; <paramref name="triLabels"/> is rewritten with the merged labels.</summary>
    public static void Labels(double* tris, int* triLabels, int count, int labelCount, int w, int h, int* outMap)
    {
        long n = (long)w * h;
        for (long i = 0; i < n; i++)
            outMap[i] = -1;
        var parent = new int[Math.Max(1, labelCount)];
        for (int i = 0; i < parent.Length; i++)
            parent[i] = i;
        var tri = new Tri();
        for (int t = 0; t < count; t++)
        {
            int label = triLabels[t];
            if ((uint)label >= (uint)labelCount || !tri.Setup(tris + (long)t * 6, w, h, 0.0))
                continue;
            for (int y = tri.Y0; y < tri.Y1; y++)
            {
                int* row = outMap + (long)y * w;
                for (int x = tri.X0; x < tri.X1; x++)
                {
                    if (!tri.Inside(x, y))
                        continue;
                    int cur = row[x];
                    if (cur < 0)
                    {
                        row[x] = label;
                    }
                    else if (cur != label)
                    {
                        int a = Find(parent, cur), b = Find(parent, label);
                        if (a != b)
                            parent[Math.Max(a, b)] = Math.Min(a, b);
                    }
                }
            }
        }
        for (long i = 0; i < n; i++)
            if (outMap[i] >= 0)
                outMap[i] = Find(parent, outMap[i]);
        for (int t = 0; t < count; t++)
            if ((uint)triLabels[t] < (uint)labelCount)
                triLabels[t] = Find(parent, triLabels[t]);
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
