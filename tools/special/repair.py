"""Repair: a healing brush as in photo editors.

The brush copies texture from a source patch and shifts its colors so they meet the
surroundings at the brush's border (``paint.special.heal``): blemishes, seams and
scratches disappear without a visible patch.

* **Auto** (spot healing): every stamp looks around itself for the patch whose border
  matches best (``paint.special.best_offset``) and heals from there.
* **Source** (healing / clone): the right button sets the source pixel (like Alt+click
  in photo editors); the next stroke fixes the offset from its start to the source and
  keeps it (aligned) until a new source is set. The source is read from the stroke's
  starting image, so the stroke never copies what it just painted.

Texture (Brushes window): 1 = the source's full texture, 0 = only a smooth fill from
the border colors. Strength blends the result in.
"""

import numpy as np

from ...paint import special
from ..base import SettingDefaults
from .common import SpecialBrush, commit, falloff_lut, image_view, island_keep, opaque_keep, wm_value


SOURCE_COLOR = (0.30, 1.00, 0.55, 0.95)


class RepairTool(SpecialBrush):
    tool_id = 'REPAIR'
    label = "Repair"
    description = "Healing brush: texture from a source, colors matched to the surroundings (right button: set the source)"
    outline_color = (0.30, 1.00, 0.55, 0.9)
    defaults = SettingDefaults(size=False, modifier=False, strength=False, alpha=False)
    falloff_property = 'pixel_painter_repair_falloff'
    uses_values = frozenset({'strength'})

    def uses_stroke_snapshot(self, env):
        return True

    def stamp_spacing(self, env):
        return max(1.0, env.radius * 0.35)

    # ---- right button: the source -------------------------------------------------------

    def on_press(self, ctx):
        if ctx.state.get('use_secondary'):
            self._set_source(ctx)
            return
        if wm_value(ctx, 'repair_mode', 'AUTO') == 'SOURCE' and ctx.state.get('repair_source') is not None \
                and ctx.state.get('repair_offset') is None and ctx.cursor[0] is not None:
            sx, sy = ctx.state['repair_source']
            ctx.state['repair_offset'] = (sx - ctx.cursor[0], sy - ctx.cursor[1])   # aligned from now on
        super().on_press(ctx)

    def _set_source(self, ctx):
        cx, cy = ctx.cursor
        if cx is None:
            return
        ctx.state['repair_source'] = (int(cx), int(cy))
        ctx.state['repair_offset'] = None
        try:
            ctx.wm.pixel_painter_repair_mode = 'SOURCE'
        except Exception:
            pass

    def continue_stroke(self, ctx, event):
        if self.is_stroking and ctx.state.get('use_secondary'):
            self._set_source(ctx)     # dragging with the right button moves the source
            ctx.redraw()
            return None
        return super().continue_stroke(ctx, event)

    # ---- painting ------------------------------------------------------------------------

    def on_draw(self, env):
        if env.state.get('use_secondary'):
            return
        w, h = env.img.size
        centers = self.spaced_steps(env)
        back = env.state.get('stroke_back_buffer')
        if not centers or back is None:
            env.mark_painted()
            return
        flat, view = image_view(env)
        source_img = back.reshape(h, w, 4)
        lut = falloff_lut(env, self.falloff_property)
        texture = float(wm_value(env, 'repair_texture', 1.0))
        offset = env.state.get('repair_offset') if wm_value(env, 'repair_mode', 'AUTO') == 'SOURCE' else None
        r = max(1, int(env.radius))
        for cx, cy in centers:
            xs, ys, wts, _d = special.disk(cx, cy, r, lut, w, h)
            keep = island_keep(env, cx, cy, xs, ys)
            if env.protect_transparent:
                keep &= opaque_keep(view, xs, ys)
            xs, ys, wts = xs[keep], ys[keep], wts[keep]
            rx, ry = special.ring(cx, cy, r, w, h)
            if len(xs) == 0 or len(rx) == 0:
                continue
            if offset is None:
                found = special.best_offset(view, cx, cy, r, rx, ry)
                if found is None:
                    continue
                ox, oy = found
                src = view           # spot healing reads around itself (the current image)
            else:
                ox, oy = offset
                src = source_img
            sxi = np.clip(xs + ox, 0, w - 1)
            syi = np.clip(ys + oy, 0, h - 1)
            sxr = np.clip(rx + ox, 0, w - 1)
            syr = np.clip(ry + oy, 0, h - 1)
            healed = special.heal(src[syi, sxi], src[syr, sxr], view[ry, rx],
                                  np.stack((xs, ys), axis=1), np.stack((rx, ry), axis=1), texture)
            dst = view[ys, xs]
            k = np.clip(wts * env.opacity, 0.0, 1.0)[:, None]
            out = dst + (healed - dst) * k
            if env.protect_transparent:
                out[:, 3] = dst[:, 3]
            view[ys, xs] = out
        commit(env, flat)
        env.mark_painted()

    def step_region(self, ctx, env, steps):
        region = super().step_region(ctx, env, steps)
        if region is None:
            return None
        pad = int(np.ceil(special.HEAL_RING_WIDTH)) + 1
        x0, y0, x1, y1 = region
        return x0 - pad, y0 - pad, x1 + pad, y1 + pad

    # ---- overlay: the source ---------------------------------------------------------------

    def draw_overlay(self, ctx):
        """Image Editor: a cross on the source pixel (and where the stroke copies from)."""
        source = ctx.state.get('repair_source')
        if source is None or ctx.is_3d or wm_value(ctx, 'repair_mode', 'AUTO') != 'SOURCE':
            return
        try:
            from ...overlays.special import draw_source_marker
            offset = ctx.state.get('repair_offset')
            cursor = ctx.cursor
            live = None
            if offset is not None and cursor[0] is not None:
                live = (cursor[0] + offset[0], cursor[1] + offset[1])
            draw_source_marker(ctx.context, source, live, SOURCE_COLOR)
        except Exception:
            pass
