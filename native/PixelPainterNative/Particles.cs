namespace PixelPainterNative;

/// <summary>
/// The Particles brush's body simulation (tools/special/particle_sim.fly), step for step,
/// against a <see cref="TriangleBvh"/> (handle from <see cref="Occlusion.Build"/>).
///
/// The tuning constants come from Python on every call (<c>prm</c>, see
/// <see cref="Prm"/>), so particle_sim.py stays the one place they are set. The random
/// bounce jitter is drawn by Python too: <c>jitter</c> holds one (x, y, z) row per bounce.
/// </summary>
public static unsafe class Particles
{
    /// <summary>Indices into the constants array (utils/native.PARTICLE_PARAMS).</summary>
    private enum Prm
    {
        Dt, MaxSteps, Restitution, Glance, BounceSpeed, Friction, Adhesion, WrapSpeed,
        BoundsScale, SlideWeight, PathEvery, Lift, SameFace, Count
    }

    public const int End_Out = 1, End_Rest = 2, End_Steps = 3;

    private struct V
    {
        public double X, Y, Z;
        public V(double x, double y, double z) { X = x; Y = y; Z = z; }
        public static V operator +(V a, V b) => new(a.X + b.X, a.Y + b.Y, a.Z + b.Z);
        public static V operator -(V a, V b) => new(a.X - b.X, a.Y - b.Y, a.Z - b.Z);
        public static V operator -(V a) => new(-a.X, -a.Y, -a.Z);
        public static V operator *(V a, double s) => new(a.X * s, a.Y * s, a.Z * s);
        public static V operator /(V a, double s) => new(a.X / s, a.Y / s, a.Z / s);
        public double Dot(V b) => X * b.X + Y * b.Y + Z * b.Z;
        public double Length => Math.Sqrt(X * X + Y * Y + Z * Z);
        public V Normalized() { double l = Length; return l > 0.0 ? this / l : new V(0, 0, 0); }
        public bool Same(V b) => X == b.X && Y == b.Y && Z == b.Z;
    }

    private sealed class Output
    {
        private readonly double* _contacts; private readonly int* _tris; private readonly double* _path;
        private readonly double* _hits; private readonly int _cap;
        public int Contacts, Path, Hits;
        public Output(double* contacts, int* tris, double* path, double* hits, int cap)
        { _contacts = contacts; _tris = tris; _path = path; _hits = hits; _cap = cap; }

        public void Contact(V loc, int tri, double weight)
        {
            if (Contacts >= _cap) return;
            double* c = _contacts + Contacts * 4;
            c[0] = loc.X; c[1] = loc.Y; c[2] = loc.Z; c[3] = weight;
            _tris[Contacts++] = tri;
        }

        public void PathPoint(V p)
        {
            if (Path >= _cap) return;
            double* q = _path + Path++ * 3;
            q[0] = p.X; q[1] = p.Y; q[2] = p.Z;
        }

        public V LastPath => new(_path[(Path - 1) * 3], _path[(Path - 1) * 3 + 1], _path[(Path - 1) * 3 + 2]);

        public void Hit(V p)
        {
            if (Hits >= _cap) return;
            double* q = _hits + Hits++ * 3;
            q[0] = p.X; q[1] = p.Y; q[2] = p.Z;
        }
    }

    private static bool Cast(TriangleBvh bvh, V o, V d, double dist, out V loc, out V normal, out int tri)
    {
        if (bvh.Nearest(o.X, o.Y, o.Z, d.X, d.Y, d.Z, dist, out double t, out tri,
                        out double nx, out double ny, out double nz))
        {
            loc = o + d * t;
            normal = new V(nx, ny, nz);
            return true;
        }
        loc = normal = default;
        return false;
    }

    private static V Toward(V normal, V direction)
    {
        V n = normal.Normalized();
        return n.Dot(direction) > 0.0 ? -n : n;
    }

    /// <summary>
    /// One body. <paramref name="box"/>: center xyz, half extents xyz, size. Outputs (each
    /// <paramref name="cap"/> rows): contacts (x, y, z, weight) + their triangles, path
    /// points, hit points; <paramref name="counts"/> = (contacts, path, hits, end code).
    /// </summary>
    public static int Fly(int handle, double* start, double* velocity, double* gravity, int bounces,
                          double* box, double* jitter, double* prm, int prmCount,
                          double* contacts, int* contactTris, double* path, double* hits, int cap, int* counts)
    {
        var bvh = Occlusion.Get(handle);
        if (bvh == null || prmCount < (int)Prm.Count || cap < 2) return -1;
        double dt = prm[(int)Prm.Dt];
        int maxSteps = (int)prm[(int)Prm.MaxSteps];
        double restitution = prm[(int)Prm.Restitution], glance = prm[(int)Prm.Glance];
        double bounceSpeed = prm[(int)Prm.BounceSpeed], friction = prm[(int)Prm.Friction];
        double adhesion = prm[(int)Prm.Adhesion], wrapSpeed = prm[(int)Prm.WrapSpeed];
        double boundsScale = prm[(int)Prm.BoundsScale], slideWeight = prm[(int)Prm.SlideWeight];
        int pathEvery = Math.Max(1, (int)prm[(int)Prm.PathEvery]);
        double liftShare = prm[(int)Prm.Lift], sameFace = prm[(int)Prm.SameFace];

        var center = new V(box[0], box[1], box[2]);
        var half = new V(box[3], box[4], box[5]);
        double size = box[6];
        double eps = size * liftShare;
        var grav = new V(gravity[0], gravity[1], gravity[2]);
        double gravLen = grav.Length;

        bool Outside(V p)
        {
            V d = p - center;
            return Math.Abs(d.X) > half.X * boundsScale || Math.Abs(d.Y) > half.Y * boundsScale
                || Math.Abs(d.Z) > half.Z * boundsScale;
        }
        bool Gone(V p, V vel, bool touched) => Outside(p) && (touched || (p - center).Dot(vel) > 0.0);

        var o = new Output(contacts, contactTris, path, hits, cap);
        var p = new V(start[0], start[1], start[2]);
        var vel = new V(velocity[0], velocity[1], velocity[2]);
        o.PathPoint(p);
        double energy = 1.0;
        int left = bounces, used = 0;
        bool sliding = false;
        V n = default;
        int end = End_Steps;
        for (int stepNo = 0; stepNo < maxSteps; stepNo++)
        {
            bool keep = stepNo % pathEvery == 0;
            V step;
            double length;
            V loc, normal;
            int tri;
            if (!sliding)
            {
                vel = vel + grav * dt;
                step = vel * dt;
                length = step.Length;
                if (length < 1e-12) { end = End_Rest; break; }
                if (!Cast(bvh, p, step / length, length, out loc, out normal, out tri))
                {
                    p = p + step;
                    if (keep) o.PathPoint(p);
                    if (Gone(p, vel, o.Contacts > 0)) { end = End_Out; break; }
                    continue;
                }
                n = Toward(normal, step);
                o.Contact(loc, tri, energy);
                o.Hit(loc);
                o.PathPoint(loc);
                double into = -vel.Dot(n);
                if (left > 0 && into > bounceSpeed * size)
                {
                    left--;
                    V alongFace = vel + n * into;
                    vel = alongFace * glance + n * (into * restitution);
                    V jit = jitter != null && used < bounces
                        ? new V(jitter[used * 3], jitter[used * 3 + 1], jitter[used * 3 + 2]) : default;
                    used++;
                    vel = vel + jit * vel.Length;
                    energy *= 0.5 + 0.5 * restitution;
                    p = loc + n * eps;
                    continue;
                }
                vel = vel + n * into;
                p = loc + n * eps;
                sliding = true;
                continue;
            }

            // ---- sliding along the surface ----
            double press = -grav.Dot(n);
            if (press < -adhesion * gravLen) { sliding = false; continue; }
            V along = grav + n * press;
            vel = vel + along * dt;
            double speed = vel.Length;
            double grip = Math.Max(0.0, press);
            double brake = friction * grip * dt;
            if (speed <= brake)
            {
                if (along.Length <= friction * grip) { end = End_Rest; break; }
                vel = new V(0, 0, 0);
                continue;
            }
            vel = vel * (1.0 - brake / speed);
            step = vel * dt;
            length = step.Length;
            if (length < 1e-12) continue;
            if (Cast(bvh, p, step / length, length, out loc, out normal, out tri)
                && Math.Abs(normal.Normalized().Dot(n)) < sameFace)
            {
                n = Toward(normal, step);
                vel = vel - n * vel.Dot(n);
                p = loc + n * eps;
                o.Contact(loc, tri, slideWeight * energy);
                o.PathPoint(loc);
                continue;
            }
            V q = p + step;
            if (!Cast(bvh, q, -n, Math.Max(length * 2.0, eps * 8.0), out loc, out normal, out tri))
            {
                bool wrapped = false;
                V n2 = default;
                if (vel.Length < wrapSpeed * size)
                {
                    // _wrap: look back from just below / beyond the edge toward the body
                    double reach = length + eps * 8.0;
                    V origin = q - n * reach;
                    V back = -step / length;
                    if (Cast(bvh, origin, back, reach * 2.0, out loc, out normal, out tri))
                    {
                        n2 = normal.Normalized();
                        if (n2.Dot(step) < 0.0) n2 = -n2;
                        wrapped = true;
                    }
                }
                if (!wrapped)
                {
                    p = q;
                    sliding = false;
                    if (keep) o.PathPoint(p);
                    continue;
                }
                double sp = vel.Length;
                V heading = -n - n2 * (-n).Dot(n2);
                vel = heading.Length > 1e-12 ? heading.Normalized() * sp : vel - n2 * vel.Dot(n2);
                n = n2;
                p = loc + n * eps;
                o.Contact(loc, tri, slideWeight * energy);
                o.PathPoint(p);
                continue;
            }
            V m = normal.Normalized();
            if (m.Dot(n) < 0.0) m = -m;
            double sp2 = vel.Length;
            vel = vel - m * vel.Dot(m);
            if (vel.Length > 1e-12) vel = vel.Normalized() * sp2;
            n = m;
            p = loc + n * eps;
            o.Contact(loc, tri, slideWeight * energy);
            if (keep) o.PathPoint(p);
            if (Gone(p, vel, true)) { end = End_Out; break; }
        }
        if (!o.LastPath.Same(p)) o.PathPoint(p);
        counts[0] = o.Contacts; counts[1] = o.Path; counts[2] = o.Hits; counts[3] = end;
        return o.Contacts;
    }
}
