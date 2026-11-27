namespace PixelPainterNative;

/// <summary>
/// Triangle BVH and ambient-occlusion ray casting (the Extras window's AO tool,
/// tools/extras/ao.py). Python builds the tree once per AO run
/// (<see cref="Build"/>, a handle) and traces chunks of texels against it.
///
/// Rays hit triangles from both sides (like mathutils.bvhtree.BVHTree.ray_cast);
/// a ray is occluded when any triangle lies within (0, reach] along it.
/// </summary>
public static unsafe class Occlusion
{
    private static readonly Dictionary<int, TriangleBvh> Trees = new();
    private static int _next = 1;

    public static int Build(double* tris, int count)
    {
        var bvh = new TriangleBvh(tris, count);
        lock (Trees)
        {
            int id = _next++;
            if (_next <= 0) _next = 1;
            Trees[id] = bvh;
            return id;
        }
    }

    public static int Free(int handle)
    {
        lock (Trees) return Trees.Remove(handle) ? 0 : -1;
    }

    private static TriangleBvh? Get(int handle)
    {
        lock (Trees) return Trees.TryGetValue(handle, out var bvh) ? bvh : null;
    }

    /// <summary>
    /// Share of hemisphere rays hitting the mesh within <paramref name="reach"/> per point.
    /// <paramref name="origins"/>: (n, 3); <paramref name="frames"/>: (n, 3, 3), rows
    /// tangent / bitangent / normal; <paramref name="local"/>: (k, 3) directions around +Z.
    /// Ray direction = local.x * tangent + local.y * bitangent + local.z * normal.
    /// </summary>
    public static int Trace(int handle, double* origins, double* frames, int n, double* local, int k,
                            double reach, double* outp)
    {
        var bvh = Get(handle);
        if (bvh == null || n < 0 || k <= 0) return -1;
        Parallel.For(0, n, i =>
        {
            double* o = origins + i * 3;
            double* f = frames + i * 9;
            int hits = 0;
            for (int j = 0; j < k; j++)
            {
                double lx = local[j * 3], ly = local[j * 3 + 1], lz = local[j * 3 + 2];
                double dx = lx * f[0] + ly * f[3] + lz * f[6];
                double dy = lx * f[1] + ly * f[4] + lz * f[7];
                double dz = lx * f[2] + ly * f[5] + lz * f[8];
                if (bvh.AnyHit(o[0], o[1], o[2], dx, dy, dz, reach)) hits++;
            }
            outp[i] = (double)hits / k;
        });
        return n;
    }
}

/// <summary>Bounding volume hierarchy over triangles (median split, flattened nodes).</summary>
internal sealed unsafe class TriangleBvh
{
    private const int LeafSize = 4;

    private readonly double[] _tri;      // reordered triangles, 9 doubles each
    private readonly double[] _box;      // per node: min xyz, max xyz
    private readonly int[] _first;       // leaf: first triangle; inner: right child (left = node + 1)
    private readonly int[] _count;       // leaf: triangle count; inner: 0
    private int _nodes;

    public TriangleBvh(double* tris, int count)
    {
        _tri = new double[Math.Max(0, count) * 9];
        int capacity = Math.Max(1, 2 * count);
        _box = new double[capacity * 6];
        _first = new int[capacity];
        _count = new int[capacity];
        if (count <= 0) { _nodes = 0; return; }

        var order = new int[count];
        var centroid = new double[count * 3];
        for (int t = 0; t < count; t++)
        {
            order[t] = t;
            double* p = tris + t * 9;
            for (int a = 0; a < 3; a++) centroid[t * 3 + a] = (p[a] + p[3 + a] + p[6 + a]) / 3.0;
        }
        BuildNode(tris, order, centroid, 0, count);
        for (int i = 0; i < count; i++)
        {
            double* p = tris + order[i] * 9;
            for (int a = 0; a < 9; a++) _tri[i * 9 + a] = p[a];
        }
    }

    private int BuildNode(double* tris, int[] order, double[] centroid, int start, int end)
    {
        int node = _nodes++;
        double* lo = stackalloc double[3] { double.MaxValue, double.MaxValue, double.MaxValue };
        double* hi = stackalloc double[3] { double.MinValue, double.MinValue, double.MinValue };
        double* clo = stackalloc double[3] { double.MaxValue, double.MaxValue, double.MaxValue };
        double* chi = stackalloc double[3] { double.MinValue, double.MinValue, double.MinValue };
        for (int i = start; i < end; i++)
        {
            int t = order[i];
            double* p = tris + t * 9;
            for (int v = 0; v < 3; v++)
                for (int a = 0; a < 3; a++)
                {
                    double c = p[v * 3 + a];
                    if (c < lo[a]) lo[a] = c;
                    if (c > hi[a]) hi[a] = c;
                }
            for (int a = 0; a < 3; a++)
            {
                double c = centroid[t * 3 + a];
                if (c < clo[a]) clo[a] = c;
                if (c > chi[a]) chi[a] = c;
            }
        }
        for (int a = 0; a < 3; a++) { _box[node * 6 + a] = lo[a]; _box[node * 6 + 3 + a] = hi[a]; }

        int n = end - start;
        int axis = 0;
        double ext = chi[0] - clo[0];
        if (chi[1] - clo[1] > ext) { axis = 1; ext = chi[1] - clo[1]; }
        if (chi[2] - clo[2] > ext) { axis = 2; ext = chi[2] - clo[2]; }
        if (n <= LeafSize || ext <= 0.0)
        {
            _first[node] = start;
            _count[node] = n;
            return node;
        }
        int mid = start + n / 2;
        SelectNth(order, centroid, axis, start, end - 1, mid);
        BuildNode(tris, order, centroid, start, mid);
        _first[node] = BuildNode(tris, order, centroid, mid, end);
        _count[node] = 0;
        return node;
    }

    /// <summary>Quickselect: order[k] gets the k-th smallest centroid along axis.</summary>
    private static void SelectNth(int[] order, double[] centroid, int axis, int left, int right, int k)
    {
        while (right > left)
        {
            double pivot = centroid[order[(left + right) >> 1] * 3 + axis];
            int i = left, j = right;
            while (i <= j)
            {
                while (centroid[order[i] * 3 + axis] < pivot) i++;
                while (centroid[order[j] * 3 + axis] > pivot) j--;
                if (i <= j) { (order[i], order[j]) = (order[j], order[i]); i++; j--; }
            }
            if (k <= j) right = j;
            else if (k >= i) left = i;
            else return;
        }
    }

    public bool AnyHit(double ox, double oy, double oz, double dx, double dy, double dz, double tmax)
    {
        if (_nodes == 0) return false;
        double ix = 1.0 / dx, iy = 1.0 / dy, iz = 1.0 / dz;
        int* stack = stackalloc int[128];
        int sp = 0;
        stack[sp++] = 0;
        fixed (double* box = _box)
        fixed (double* tri = _tri)
        {
            while (sp > 0)
            {
                int node = stack[--sp];
                double* b = box + node * 6;
                double t0 = (b[0] - ox) * ix, t1 = (b[3] - ox) * ix;
                double tn = Math.Min(t0, t1), tf = Math.Max(t0, t1);
                t0 = (b[1] - oy) * iy; t1 = (b[4] - oy) * iy;
                tn = Math.Max(tn, Math.Min(t0, t1)); tf = Math.Min(tf, Math.Max(t0, t1));
                t0 = (b[2] - oz) * iz; t1 = (b[5] - oz) * iz;
                tn = Math.Max(tn, Math.Min(t0, t1)); tf = Math.Min(tf, Math.Max(t0, t1));
                // NaN (ray in a slab plane) fails these comparisons: the node is visited (conservative).
                if (tn > tf || tf < 0.0 || tn > tmax) continue;

                int count = _count[node];
                if (count > 0)
                {
                    int first = _first[node];
                    for (int t = first; t < first + count; t++)
                        if (HitsTriangle(tri + t * 9, ox, oy, oz, dx, dy, dz, tmax)) return true;
                }
                else if (sp < 126)
                {
                    stack[sp++] = _first[node];
                    stack[sp++] = node + 1;
                }
                else
                {
                    // Pathologically deep tree: test the subtree's triangles by brute force.
                    if (SubtreeHit(node, tri, ox, oy, oz, dx, dy, dz, tmax)) return true;
                }
            }
        }
        return false;
    }

    private bool SubtreeHit(int node, double* tri, double ox, double oy, double oz,
                            double dx, double dy, double dz, double tmax)
    {
        int count = _count[node];
        if (count > 0)
        {
            int first = _first[node];
            for (int t = first; t < first + count; t++)
                if (HitsTriangle(tri + t * 9, ox, oy, oz, dx, dy, dz, tmax)) return true;
            return false;
        }
        return SubtreeHit(node + 1, tri, ox, oy, oz, dx, dy, dz, tmax)
            || SubtreeHit(_first[node], tri, ox, oy, oz, dx, dy, dz, tmax);
    }

    /// <summary>Möller–Trumbore, both faces; hit when 0 &lt; t &lt;= tmax.</summary>
    private static bool HitsTriangle(double* p, double ox, double oy, double oz,
                                     double dx, double dy, double dz, double tmax)
    {
        double e1x = p[3] - p[0], e1y = p[4] - p[1], e1z = p[5] - p[2];
        double e2x = p[6] - p[0], e2y = p[7] - p[1], e2z = p[8] - p[2];
        double px = dy * e2z - dz * e2y, py = dz * e2x - dx * e2z, pz = dx * e2y - dy * e2x;
        double det = e1x * px + e1y * py + e1z * pz;
        if (Math.Abs(det) < 1e-20) return false;
        double inv = 1.0 / det;
        double sx = ox - p[0], sy = oy - p[1], sz = oz - p[2];
        double u = (sx * px + sy * py + sz * pz) * inv;
        if (u < 0.0 || u > 1.0) return false;
        double qx = sy * e1z - sz * e1y, qy = sz * e1x - sx * e1z, qz = sx * e1y - sy * e1x;
        double v = (dx * qx + dy * qy + dz * qz) * inv;
        if (v < 0.0 || u + v > 1.0) return false;
        double t = (e2x * qx + e2y * qy + e2z * qz) * inv;
        return t > 0.0 && t <= tmax;
    }
}
