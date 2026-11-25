namespace PixelPainterNative;

/// <summary>
/// Brush footprints: a kernel ((2r+1)^2 weights, row-major by dy then dx,
/// 0 = not covered) stamped at every interpolation step. Overlapping stamps
/// keep the largest weight; zero weights are never emitted (like the Python
/// ``if w > weights.get(px, 0.0)`` merge).
///
/// Two modes:
/// * local (<c>grid == null</c>): emit every covered pixel with its weight.
/// * stroke grid (<c>grid</c> = w*h floats kept for the whole stroke): raise
///   the grid to the max weight and emit only pixels that were not covered
///   before (their weight is read back from the grid by the caller).
/// </summary>
internal static unsafe class Stamps
{
    private const long LocalGridMaxCells = 1L << 24;   // 64 MB of floats, beyond that use a hash map

    private sealed class Accumulator
    {
        private readonly int _w, _h;
        private readonly float* _grid;            // stroke grid mode
        private readonly List<int>? _added;
        private readonly float[]? _local;         // local mode: bbox grid
        private readonly Dictionary<long, float>? _map;
        private readonly int _x0, _y0, _bw, _bh;

        public Accumulator(int w, int h, float* grid, int* centers, int nc, int r)
        {
            _w = w;
            _h = h;
            _grid = grid;
            if (grid != null)
            {
                _added = new List<int>();
                return;
            }
            int minX = int.MaxValue, minY = int.MaxValue, maxX = int.MinValue, maxY = int.MinValue;
            for (int i = 0; i < nc; i++)
            {
                int cx = centers[2 * i], cy = centers[2 * i + 1];
                minX = Math.Min(minX, cx); maxX = Math.Max(maxX, cx);
                minY = Math.Min(minY, cy); maxY = Math.Max(maxY, cy);
            }
            _x0 = Math.Max(0, minX - r);
            _y0 = Math.Max(0, minY - r);
            int x1 = Math.Min(w - 1, maxX + r), y1 = Math.Min(h - 1, maxY + r);
            _bw = Math.Max(0, x1 - _x0 + 1);
            _bh = Math.Max(0, y1 - _y0 + 1);
            if ((long)_bw * _bh <= LocalGridMaxCells)
                _local = new float[(long)_bw * _bh];
            else
                _map = new Dictionary<long, float>();
        }

        public void Add(int x, int y, float v)
        {
            if (!(v > 0f) || (uint)x >= (uint)_w || (uint)y >= (uint)_h)
                return;
            if (_grid != null)
            {
                long idx = (long)y * _w + x;
                float old = _grid[idx];
                if (v > old)
                {
                    _grid[idx] = v;
                    if (!(old > 0f))
                    {
                        _added!.Add(x);
                        _added.Add(y);
                    }
                }
                return;
            }
            if (_local != null)
            {
                long i = (long)(y - _y0) * _bw + (x - _x0);
                if (v > _local[i])
                    _local[i] = v;
                return;
            }
            long key = (long)y * _w + x;
            if (!_map!.TryGetValue(key, out float cur) || v > cur)
                _map[key] = v;
        }

        /// <returns>Pixel count, or -1 if <paramref name="cap"/> is too small.</returns>
        public int Emit(int* outXY, float* outW, int cap)
        {
            int n = 0;
            if (_added != null)
            {
                int count = _added.Count / 2;
                if (count > cap)
                    return -1;
                for (int i = 0; i < _added.Count; i++)
                    outXY[i] = _added[i];
                if (outW != null)
                    for (int i = 0; i < count; i++)
                        outW[i] = _grid[(long)_added[2 * i + 1] * _w + _added[2 * i]];
                return count;
            }
            if (_local != null)
            {
                for (int y = 0; y < _bh; y++)
                {
                    long row = (long)y * _bw;
                    for (int x = 0; x < _bw; x++)
                    {
                        float v = _local[row + x];
                        if (!(v > 0f))
                            continue;
                        if (n >= cap)
                            return -1;
                        outXY[2 * n] = _x0 + x;
                        outXY[2 * n + 1] = _y0 + y;
                        if (outW != null)
                            outW[n] = v;
                        n++;
                    }
                }
                return n;
            }
            foreach (var (key, v) in _map!)
            {
                if (n >= cap)
                    return -1;
                outXY[2 * n] = (int)(key % _w);
                outXY[2 * n + 1] = (int)(key / _w);
                if (outW != null)
                    outW[n] = v;
                n++;
            }
            return n;
        }
    }

    public static int Kernel(int* centers, int nc, int radius, float* kernel, int w, int h,
                             float* grid, int* outXY, float* outW, int cap)
    {
        if (nc <= 0)
            return 0;
        int r = Math.Max(0, radius);
        int k = 2 * r + 1;
        var acc = new Accumulator(w, h, grid, centers, nc, r);
        for (int i = 0; i < nc; i++)
        {
            int cx = centers[2 * i], cy = centers[2 * i + 1];
            for (int dy = -r; dy <= r; dy++)
            {
                float* krow = kernel + (long)(dy + r) * k + r;
                for (int dx = -r; dx <= r; dx++)
                {
                    float v = krow[dx];
                    if (v > 0f)
                        acc.Add(cx + dx, cy + dy, v);
                }
            }
        }
        return acc.Emit(outXY, outW, cap);
    }

    /// <summary>utils/math_utils.get_spray_pixels at every center: random unique
    /// in-circle offsets, (density * area) per stamp, weights from the kernel.</summary>
    public static int Spray(int* centers, int nc, int radius, double density, float* kernel, int seed,
                            int w, int h, float* grid, int* outXY, float* outW, int cap)
    {
        if (nc <= 0)
            return 0;
        int r = Math.Max(0, radius);
        int k = 2 * r + 1;
        var acc = new Accumulator(w, h, grid, centers, nc, r);
        if (r == 0)
        {
            for (int i = 0; i < nc; i++)
                acc.Add(centers[2 * i], centers[2 * i + 1], 1f);
            return acc.Emit(outXY, outW, cap);
        }
        var rng = new Random(seed);
        int total = Math.Max(1, (int)(Math.PI * r * r));
        int count = Math.Max(1, (int)(density * total));
        long maxAttempts = (long)count * 20;
        long r2 = (long)r * r;
        var seen = new bool[k * k];
        for (int i = 0; i < nc; i++)
        {
            int cx = centers[2 * i], cy = centers[2 * i + 1];
            Array.Clear(seen);
            int got = 0;
            for (long a = 0; a < maxAttempts && got < count; a++)
            {
                int dx = rng.Next(-r, r + 1);
                int dy = rng.Next(-r, r + 1);
                if ((long)dx * dx + (long)dy * dy > r2)
                    continue;
                int ki = (dy + r) * k + (dx + r);
                if (seen[ki])
                    continue;
                seen[ki] = true;
                got++;
                acc.Add(cx + dx, cy + dy, kernel[ki]);
            }
        }
        return acc.Emit(outXY, outW, cap);
    }
}
