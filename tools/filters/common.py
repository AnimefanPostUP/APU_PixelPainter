"""Shared by the filter tools.
"""



from ...utils import pixel_io


def visible_alpha_pixels(img, pixels, alpha_threshold=1e-6):
    """Return only pixels whose destination alpha is above threshold."""
    if not pixels:
        return []
    w, h = img.size
    arr = pixel_io.buffer(img)   # read only
    visible = []
    for (px, py) in pixels:
        if 0 <= px < w and 0 <= py < h:
            if arr[(py * w + px) * 4 + 3] > alpha_threshold:
                visible.append((px, py))
    return visible
