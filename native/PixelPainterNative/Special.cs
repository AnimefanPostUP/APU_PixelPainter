namespace PixelPainterNative;

/// <summary>
/// Kernels of the special brushes (paint/special.py, tools/special/):
/// <see cref="NoiseBlur"/> runs a whole draw step of the Noise Blur brush,
/// <see cref="Heal"/> the Repair brush's healing of one stamp.
/// </summary>
public static unsafe class Special
{
    private const int ParallelMin = 2048;   // stamp pixels before a stamp is split over threads

    /// <summary>
    /// Noise Blur stamps at <paramref name="centers"/>, one after the other, into the image
    /// <paramref name="buf"/> (in place). Each covered pixel (kernel weight &gt; 0) becomes the
    /// average of <paramref name="samples"/> random pixels within <paramref name="scatter"/> px,
    /// read from the image as it was before the stamp, blended in by weight * opacity.
    /// Island clipping as in <see cref="Stamps"/>; <paramref name="protect"/>: transparent
    /// pixels are left alone and alpha is kept. Returns the number of pixels written.
    /// </summary>
    public static int NoiseBlur(float* buf, int w, int h, int* centers, int nc, int r, float* kernel,
                                int* labelMap, int* centerLabels, bool protect, double scatter, int samples,
                                uint seed, double opacity)
    {
        int k = 2 * r + 1;
        samples = Math.Max(1, samples);
        double reach = Math.Max(0.0, scatter);
        var px = new List<int>(k * k);
        var wt = new List<float>(k * k);
        float[] result = Array.Empty<float>();
        int written = 0;
        for (int i = 0; i < nc; i++)
        {
            int cx = centers[2 * i], cy = centers[2 * i + 1];
            int label = labelMap == null || centerLabels == null ? Stamps.NoClip : centerLabels[i];
            if (label == Stamps.Skip) continue;
            px.Clear();
            wt.Clear();
            for (int dy = -r; dy <= r; dy++)
            {
                int y = cy + dy;
                if ((uint)y >= (uint)h) continue;
                for (int dx = -r; dx <= r; dx++)
                {
                    int x = cx + dx;
                    if ((uint)x >= (uint)w) continue;
                    float kw = kernel[(dy + r) * k + dx + r];
                    if (!(kw > 0f)) continue;
                    int flat = y * w + x;
                    if (label != Stamps.NoClip && labelMap[flat] != label) continue;
                    if (protect && !(buf[flat * 4 + 3] > 1e-6f)) continue;
                    px.Add(flat);
                    wt.Add(kw);
                }
            }
            int n = px.Count;
            if (n == 0) continue;
            if (result.Length < n * 4) result = new float[n * 4];
            ulong stampSeed = Mix(seed ^ ((ulong)(uint)i << 32));
            var pxs = px; var res = result;
            void Sample(int j)
            {
                int flat = pxs[j];
                int x = flat % w, y = flat / w;
                float r0 = 0f, g0 = 0f, b0 = 0f, a0 = 0f;
                ulong state = Mix(stampSeed + (ulong)j * 0x9E3779B97F4A7C15UL);
                for (int s = 0; s < samples; s++)
                {
                    state = Mix(state + 0x632BE59BD9B4E019UL);
                    double ang = (state >> 11) * (1.0 / (1UL << 53)) * Math.Tau;
                    state = Mix(state + 0x632BE59BD9B4E019UL);
                    double rad = reach * Math.Sqrt((state >> 11) * (1.0 / (1UL << 53)));
                    int sx = (int)Math.Clamp(Math.Round(x + Math.Cos(ang) * rad), 0, w - 1);
                    int sy = (int)Math.Clamp(Math.Round(y + Math.Sin(ang) * rad), 0, h - 1);
                    float* p = buf + ((long)sy * w + sx) * 4;
                    r0 += p[0]; g0 += p[1]; b0 += p[2]; a0 += p[3];
                }
                res[j * 4] = r0 / samples; res[j * 4 + 1] = g0 / samples;
                res[j * 4 + 2] = b0 / samples; res[j * 4 + 3] = a0 / samples;
            }
            if (n >= ParallelMin) Parallel.For(0, n, Sample);
            else for (int j = 0; j < n; j++) Sample(j);

            for (int j = 0; j < n; j++)
            {
                float t = (float)Math.Clamp(wt[j] * opacity, 0.0, 1.0);
                float* d = buf + (long)px[j] * 4;
                d[0] += (result[j * 4] - d[0]) * t;
                d[1] += (result[j * 4 + 1] - d[1]) * t;
                d[2] += (result[j * 4 + 2] - d[2]) * t;
                if (!protect) d[3] += (result[j * 4 + 3] - d[3]) * t;
            }
            written += n;
        }
        return written;
    }

    private static ulong Mix(ulong z)
    {
        z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9UL;
        z = (z ^ (z >> 27)) * 0x94D049BB133111EBUL;
        return z ^ (z >> 31);
    }

    /// <summary>
    /// paint/special.heal: per stamp pixel, the source texture shifted by the border
    /// differences (Shepard interpolation, weights 1 / max(d², 0.25)), and toward the smooth
    /// border fill by 1 - <paramref name="texture"/>. Colors are (·, 4) floats, positions (·, 2).
    /// </summary>
    public static int Heal(float* srcInner, float* srcRing, float* dstRing, float* innerXY, float* ringXY,
                           int n, int m, double texture, float* outp)
    {
        if (n <= 0) return 0;
        if (m <= 0) return -1;
        float t = (float)Math.Clamp(texture, 0.0, 1.0);
        var diff = new float[m * 4];
        for (int q = 0; q < m * 4; q++) diff[q] = dstRing[q] - srcRing[q];
        void One(int i)
        {
            float x = innerXY[2 * i], y = innerXY[2 * i + 1];
            double sw = 0, c0 = 0, c1 = 0, c2 = 0, c3 = 0, m0 = 0, m1 = 0, m2 = 0, m3 = 0;
            for (int q = 0; q < m; q++)
            {
                float dx = x - ringXY[2 * q], dy = y - ringXY[2 * q + 1];
                double wq = 1.0 / Math.Max(dx * dx + dy * dy, 0.25f);
                sw += wq;
                int b = q * 4;
                c0 += wq * diff[b]; c1 += wq * diff[b + 1]; c2 += wq * diff[b + 2]; c3 += wq * diff[b + 3];
                if (t < 1f)
                {
                    m0 += wq * dstRing[b]; m1 += wq * dstRing[b + 1];
                    m2 += wq * dstRing[b + 2]; m3 += wq * dstRing[b + 3];
                }
            }
            double inv = 1.0 / sw;
            float* s = srcInner + i * 4;
            float* o = outp + i * 4;
            double h0 = s[0] + c0 * inv, h1 = s[1] + c1 * inv, h2 = s[2] + c2 * inv, h3 = s[3] + c3 * inv;
            if (t < 1f)
            {
                double mm0 = m0 * inv, mm1 = m1 * inv, mm2 = m2 * inv, mm3 = m3 * inv;
                h0 = mm0 + (h0 - mm0) * t; h1 = mm1 + (h1 - mm1) * t;
                h2 = mm2 + (h2 - mm2) * t; h3 = mm3 + (h3 - mm3) * t;
            }
            o[0] = (float)Math.Clamp(h0, 0.0, 1.0); o[1] = (float)Math.Clamp(h1, 0.0, 1.0);
            o[2] = (float)Math.Clamp(h2, 0.0, 1.0); o[3] = (float)Math.Clamp(h3, 0.0, 1.0);
        }
        if ((long)n * m >= 1L << 16) Parallel.For(0, n, One);
        else for (int i = 0; i < n; i++) One(i);
        return n;
    }
}
