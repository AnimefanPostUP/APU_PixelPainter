using System.Runtime.CompilerServices;

namespace PixelPainterNative;

/// <summary>
/// Blend modes, mirroring tools/draw_blending.py.
///
/// The Python reference works on float32 NumPy arrays, so the per-channel modes
/// are evaluated in float (same operation order); the HSV modes go through
/// Python's colorsys in double precision, so they do here too.
/// Ids must match utils/native.py BLEND_IDS.
/// </summary>
internal static class Blend
{
    public const int Mix = 0, Add = 1, Sub = 2, Mul = 3, Darken = 4, Lighten = 5, Screen = 6,
        Overlay = 7, HardLight = 8, SoftLight = 9, Difference = 10, Exclusion = 11,
        ColorDodge = 12, ColorBurn = 13, Color = 14, Hue = 15, Saturation = 16, Value = 17,
        Luminosity = 18;

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    public static bool IsHsv(int mode) => mode >= Color && mode <= Luminosity;

    /// <summary>One channel of a per-channel mode, already mixed by <paramref name="o"/>.</summary>
    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    public static float Channel(int mode, float d, float s, float o)
    {
        switch (mode)
        {
            case Add: return d + s * o;
            case Sub: return d - s * o;
            case Mul: return d + (d * s - d) * o;
            case Darken: return d + (MathF.Min(d, s) - d) * o;
            case Lighten: return d + (MathF.Max(d, s) - d) * o;
            case Screen:
            {
                float t = 1f - (1f - d) * (1f - s);
                return d + (t - d) * o;
            }
            case Overlay:
            {
                float t = d < 0.5f ? 2f * d * s : 1f - 2f * (1f - d) * (1f - s);
                return d + (t - d) * o;
            }
            case HardLight:
            {
                float t = s < 0.5f ? 2f * d * s : 1f - 2f * (1f - d) * (1f - s);
                return d + (t - d) * o;
            }
            case SoftLight:
            {
                float t = (1f - 2f * s) * (d * d) + 2f * s * d;
                return d + (t - d) * o;
            }
            case Difference: return d + (MathF.Abs(d - s) - d) * o;
            case Exclusion:
            {
                float t = d + s - 2f * d * s;
                return d + (t - d) * o;
            }
            case ColorDodge:
            {
                float t = s >= 1f ? 1f : d / (1f - s + 1e-6f);
                return d + (t - d) * o;
            }
            case ColorBurn:
            {
                float t = s <= 0f ? 0f : 1f - (1f - d) / (s + 1e-6f);
                return d + (t - d) * o;
            }
            default: return d + (s - d) * o;   // MIX (and unknown modes, like the Python else branch)
        }
    }

    /// <summary>Target color of an HSV mode (before mixing), as float32 like the Python reference.</summary>
    public static void HsvTarget(int mode, float dr, float dg, float db, float sr, float sg, float sb,
                                 out float tr, out float tg, out float tb)
    {
        RgbToHsv(sr, sg, sb, out double sh, out double ss, out double sv);
        RgbToHsv(dr, dg, db, out double dh, out double ds, out double dv);
        double h, s, v;
        switch (mode)
        {
            case Color: h = sh; s = ss; v = dv; break;
            case Hue: h = sh; s = ds; v = dv; break;
            case Saturation: h = dh; s = ss; v = dv; break;
            default: h = dh; s = ds; v = sv; break;   // VALUE, LUMINOSITY
        }
        HsvToRgb(h, s, v, out double r, out double g, out double b);
        tr = (float)r; tg = (float)g; tb = (float)b;
    }

    /// <summary>Blend one RGB pixel; <paramref name="o"/> is the (clamped) opacity. Output unclamped.</summary>
    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    public static void Pixel(int mode, float dr, float dg, float db, float sr, float sg, float sb, float o,
                             out float r, out float g, out float b)
    {
        if (IsHsv(mode))
        {
            HsvTarget(mode, dr, dg, db, sr, sg, sb, out float tr, out float tg, out float tb);
            r = dr + (tr - dr) * o;
            g = dg + (tg - dg) * o;
            b = db + (tb - db) * o;
            return;
        }
        r = Channel(mode, dr, sr, o);
        g = Channel(mode, dg, sg, o);
        b = Channel(mode, db, sb, o);
    }

    // ---- Python colorsys, line for line -------------------------------------------

    public static void RgbToHsv(double r, double g, double b, out double h, out double s, out double v)
    {
        double maxc = Math.Max(r, Math.Max(g, b));
        double minc = Math.Min(r, Math.Min(g, b));
        double rangec = maxc - minc;
        v = maxc;
        if (minc == maxc)
        {
            h = 0.0; s = 0.0;
            return;
        }
        s = rangec / maxc;
        double rc = (maxc - r) / rangec;
        double gc = (maxc - g) / rangec;
        double bc = (maxc - b) / rangec;
        double hh;
        if (r == maxc) hh = bc - gc;
        else if (g == maxc) hh = 2.0 + rc - bc;
        else hh = 4.0 + gc - rc;
        hh /= 6.0;
        h = hh - Math.Floor(hh);   // Python's (x % 1.0)
    }

    public static void HsvToRgb(double h, double s, double v, out double r, out double g, out double b)
    {
        if (s == 0.0)
        {
            r = g = b = v;
            return;
        }
        int i = (int)(h * 6.0);
        double f = h * 6.0 - i;
        double p = v * (1.0 - s);
        double q = v * (1.0 - s * f);
        double t = v * (1.0 - s * (1.0 - f));
        i = ((i % 6) + 6) % 6;
        switch (i)
        {
            case 0: r = v; g = t; b = p; break;
            case 1: r = q; g = v; b = p; break;
            case 2: r = p; g = v; b = t; break;
            case 3: r = p; g = q; b = v; break;
            case 4: r = t; g = p; b = v; break;
            default: r = v; g = p; b = q; break;
        }
    }
}
