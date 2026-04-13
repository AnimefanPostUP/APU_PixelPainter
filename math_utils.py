"""Pure math and discrete geometry helpers — no Blender dependencies."""
import math
import random


def convert_uv_coord(u, v, w, h):
    """Convert UV [0-1] coordinates to integer image pixel coordinates."""
    return int(u * w), int(v * h)


def get_pixels_in_shape(cx, cy, radius, mode):
    """Return set of (px, py) image pixels covered by the brush shape.

    mode: 'SQUARE' or 'CIRCLE'
    """
    pixels = set()
    if radius == 0:
        pixels.add((cx, cy))
    elif mode == 'SQUARE':
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                pixels.add((cx + dx, cy + dy))
    else:  # CIRCLE
        r2 = radius * radius
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if dx * dx + dy * dy <= r2:
                    pixels.add((cx + dx, cy + dy))
    return pixels


def get_line_pixels(x0, y0, x1, y1):
    """Bresenham integer line — returns ordered list of (px, py) from (x0,y0) to (x1,y1)."""
    pixels = []
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    while True:
        pixels.append((x0, y0))
        if x0 == x1 and y0 == y1:
            break
        e2 = err * 2
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy
    return pixels


# ---------------------------------------------------------------------------
# Falloff
# ---------------------------------------------------------------------------

def get_falloff(t, falloff_type):
    """Return a weight in [0, 1] for a normalised distance t in [0, 1].

    t = 0 is the brush centre (full strength), t = 1 is the edge (zero strength).
    """
    t = max(0.0, min(1.0, t))
    if falloff_type == 'CONSTANT':
        return 1.0
    elif falloff_type == 'LINEAR':
        return 1.0 - t
    elif falloff_type == 'SMOOTH':
        # Inverse smoothstep: ease-in/out between 1 (centre) and 0 (edge)
        return 1.0 - t * t * (3.0 - 2.0 * t)
    elif falloff_type == 'SPHERE':
        # Dome shape: sqrt(1 - t²)
        return math.sqrt(max(0.0, 1.0 - t * t))
    elif falloff_type == 'SHARPEN':
        # Quadratic: drops off quickly toward the edge
        return (1.0 - t) ** 2
    return 1.0


# ---------------------------------------------------------------------------
# Weighted circle and spray pixel sets
# ---------------------------------------------------------------------------

def get_pixels_in_circle_weighted(cx, cy, radius, falloff_type='CONSTANT'):
    """Return (pixels, weights) for a filled circle with distance falloff.

    pixels  — list of (px, py) integer image coordinates
    weights — parallel list of float [0, 1] falloff weights
    """
    if radius == 0:
        return [(cx, cy)], [1.0]
    pixels  = []
    weights = []
    r2 = radius * radius
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            if dx * dx + dy * dy <= r2:
                dist = math.sqrt(dx * dx + dy * dy)
                pixels.append((cx + dx, cy + dy))
                weights.append(get_falloff(dist / radius, falloff_type))
    return pixels, weights


def get_spray_pixels(cx, cy, radius, spray_strength, falloff_type='CONSTANT'):
    """Return (pixels, weights) for a randomised spray brush.

    spray_strength — float [0.01, 1.0]: fraction of the circle area to sample
                     per call.  A value of 1.0 fills the entire circle each frame.
    falloff_type   — controls pixel weight (and thus opacity) by distance.
    """
    if radius == 0:
        return [(cx, cy)], [1.0]

    # Target pixel count: fraction of circle area (π r²)
    total_area = max(1, int(math.pi * radius * radius))
    count      = max(1, int(spray_strength * total_area))

    r2      = radius * radius
    pixels  = []
    weights = []
    seen    = set()
    max_attempts = count * 20

    for _ in range(max_attempts):
        if len(pixels) >= count:
            break
        dx = random.randint(-radius, radius)
        dy = random.randint(-radius, radius)
        if dx * dx + dy * dy > r2:
            continue
        pt = (cx + dx, cy + dy)
        if pt in seen:
            continue
        seen.add(pt)
        dist = math.sqrt(dx * dx + dy * dy)
        pixels.append(pt)
        weights.append(get_falloff(dist / radius, falloff_type))

    return pixels, weights


def get_outline_edges(pixels):
    """Return (p0, p1) corner pairs for the outer contour of a pixel set."""
    edges = []
    for (px, py) in pixels:
        if (px, py + 1) not in pixels:
            edges.append(((px, py + 1), (px + 1, py + 1)))
        if (px, py - 1) not in pixels:
            edges.append(((px, py), (px + 1, py)))
        if (px + 1, py) not in pixels:
            edges.append(((px + 1, py), (px + 1, py + 1)))
        if (px - 1, py) not in pixels:
            edges.append(((px, py), (px, py + 1)))
    return edges
