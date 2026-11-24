"""Pen bar tool: on-screen controls for pen / tablet painting -- the pen menu and the
color selector (see :mod:`ui.pen_bar`).

A global, ``screen_space`` tool: the core offers it every event before its
cursor-over-image gating, so the bar works anywhere in the editor. Shown
while ``pixel_painter_pen_bar`` is enabled. Besides forwarding events to the
widgets it

* runs the armed eyedropper on the next canvas press,
* edits the pen's color for the color pad (keeping hue / saturation through
  grey and black, where RGB has none) -- applied on release (the original
  stays marked until the old / new bubble is tapped), or with Preview on
  (``pixel_painter_pen_color_preview``, set in the settings popup) kept
  pending (the brush keeps its color) until the old / new bubble is tapped, and
* with the RMB lock on, turns pen-tip (left button) presses into right
  button presses, so the pen paints with the secondary color / RMB settings.
"""

import colorsys
import traceback

import bpy

from ..core.context import ToolContext
from ..core.framework import ToolFrame
from ..ui.kit import Theme, UIEvent, hsv_for_rgb
from ..ui.pen_bar import LAYOUT_STATE, PenBar
from ..utils import blender_utils, palette_library
from . import blend_modes, color_history, color_palette, falloff, mask
from .subtools.pen import PenEyedropperTool



def _side_insets(area, region):
    """Widths of overlapping sidebar regions covering the WINDOW region.

    The toolbar (TOOLS) is ignored: the bar sits at the editor edge, over the
    toolbar's empty lower part (the session sees pen events before the toolbar).
    """
    left = right = 0.0
    for other in area.regions:
        if other.type != 'UI' or other.width <= 1 or other.height <= 1:
            continue
        if other.x + other.width * 0.5 < region.x + region.width * 0.5:
            left = max(left, other.x + other.width - region.x)
        else:
            right = max(right, region.x + region.width - other.x)
    return max(0.0, left), max(0.0, right)


class PenBarTool(ToolFrame):
    label = "Pen Bar"
    is_global = True
    screen_space = True
    priority = 200

    state_defaults = {
        'pen_armed':         None,   # 'EYEDROPPER_PRIMARY' / '_SECONDARY': runs on the next canvas press
        'pen_pick_target':   None,   # the color the running pen eyedropper sets ('PRIMARY' / 'SECONDARY')
        'pen_rmb_lock':      False,  # the pen tip paints like the right mouse button
        'pen_bar_collapsed': False,
        'pen_color_panel':   True,   # the color selector is shown
        **LAYOUT_STATE,              # menu / color selector size and position (Reset Pen UI)
        'pen_bar_locked':    False,  # menu: no moving / resizing
        'pen_color_locked':  False,  # color selector: no moving / resizing
        'pen_palette_view':  False,  # the palette band shows the project's palettes (else the active one's colors)
        'pen_palette_status': None,  # last message of the palette library window (also set by palette_ops)
        'pen_hsv':           None,   # (rgb, hsv) last written by the color pad
        'pen_color_original': None,  # (target, hsv) before the pad edits: bubble + cross compare to it
        'pen_color_pending': None,   # (target, hsv) Preview: pad color not yet applied to the brush
    }
    persistent_state = ('pen_rmb_lock', 'pen_bar_collapsed', 'pen_color_panel',
                        *LAYOUT_STATE, 'pen_bar_locked', 'pen_color_locked', 'pen_palette_view')

    def __init__(self, registry):
        super().__init__()
        self.registry = registry
        self.bar = None             # built on first use (needs the icon set)
        self._ctx = None            # ToolContext of the event / draw being handled
        self._remap_release = False
        self._library = None        # palette library (palettes.json), loaded on first use

    def on_register(self):
        # No triggers: the bar starts them for the next canvas press.
        self.eyedropper = self.add_subtool(PenEyedropperTool())

    @staticmethod
    def enabled(ctx):
        return bool(getattr(ctx.wm, 'pixel_painter_pen_bar', False))

    # ---- lifecycle -------------------------------------------------------------------

    def on_interrupt(self, ctx):
        if self.bar is not None:
            self.bar.end_drag()

    def on_deactivate(self, ctx):
        if self.bar is not None:
            self.bar.reset()
        self._remap_release = False

    # ---- events ----------------------------------------------------------------------

    def on_event(self, ctx, event):
        if not self.enabled(ctx):
            if self.bar is not None and self.bar.busy():
                self.bar.reset()
            return
        self._ctx = ctx
        try:
            self._handle(ctx, event)
        finally:
            self._ctx = None

    def _handle(self, ctx, event):
        bar = self._layout(ctx)
        mouse = ctx.mouse_region(event)
        if bar is not None and mouse is not None:
            ui_event = UIEvent(type=event.type, value=event.value, x=mouse[0], y=mouse[1],
                               shift=event.shift, ctrl=event.ctrl, alt=event.alt)
            if bar.handle(ui_event):
                event.consume()
                return

        armed = ctx.state.get('pen_armed')
        if armed and event.is_press:
            if event.type == 'LEFTMOUSE':
                ctx.state['pen_armed'] = None
                ctx.state['pen_pick_target'] = 'SECONDARY' if armed == 'EYEDROPPER_SECONDARY' else 'PRIMARY'
                self.eyedropper.activate(ctx, event)
                event.consume()
                return
            if event.type in {'ESC', 'RIGHTMOUSE'}:
                ctx.state['pen_armed'] = None
                event.consume()
                return

        self._remap_rmb(ctx, event)

    def _remap_rmb(self, ctx, event):
        """RMB lock: the pen tip (LMB) acts as the right mouse button for everything after us."""
        if event.type != 'LEFTMOUSE':
            return
        if event.is_press:
            # Not while a sub-mode UI is open (E color selector, Shift+E): the pen operates it;
            # not while picking mask islands (a tap toggles, RMB would end picking).
            self._remap_release = (bool(ctx.state.get('pen_rmb_lock')) and not ctx.state.get('sub_mode')
                                   and not ctx.state.get('mask_picking'))
        if self._remap_release:
            event.type = 'RIGHTMOUSE'
            if event.is_release:
                self._remap_release = False

    # ---- drawing ---------------------------------------------------------------------

    def draw_overlay(self, ctx):
        if not self.enabled(ctx):
            return
        self._ctx = ctx
        try:
            bar = self._layout(ctx)
            if bar is not None:
                bar.draw()
        finally:
            self._ctx = None

    def _layout(self, ctx):
        area, region = ctx.area, ctx.region
        if area is None or region is None:
            return None
        if self.bar is None:
            self.bar = PenBar(self)
        left, right = _side_insets(area, region)
        side = getattr(ctx.wm, 'pixel_painter_pen_bar_side', 'LEFT')
        self.bar.layout(region.width, region.height, side, left, right, Theme.for_context(ctx.context))
        return self.bar

    # ---- actions used by ui.pen_bar.PenBar -------------------------------------------

    def _c(self):
        return self._ctx if self._ctx is not None else ToolContext(bpy.context, self.manager)

    @staticmethod
    def _button(ctx):
        return 'RMB' if ctx.state.get('pen_rmb_lock') else 'LMB'

    def get_value(self, channel):
        ctx = self._c()
        settings, mode, force_global = ctx.settings, ctx.mode, ctx.force_global
        if channel == 'size':
            return settings.get_tool_size(ctx.context, mode, force_global=force_global)
        getter = getattr(settings, f'get_tool_{channel}')
        return getter(ctx.context, mode, force_global=force_global, button=self._button(ctx))

    def set_value(self, channel, value):
        ctx = self._c()
        settings, mode, force_global = ctx.settings, ctx.mode, ctx.force_global
        if channel == 'size':
            settings.set_tool_size(ctx.context, mode, value, force_global=force_global)
        else:
            setter = getattr(settings, f'set_tool_{channel}')
            setter(ctx.context, mode, value, force_global=force_global, button=self._button(ctx))
        ctx.apply_tool_settings()

    def pen_rgb(self):
        """The color the pen paints (the secondary one with the RMB lock)."""
        return tuple(self._pen_color(self._c()))

    def _pen_color(self, ctx):
        if ctx.state.get('pen_rmb_lock'):
            return ctx.settings.get_brush_secondary_rgb(ctx.context)
        return ctx.settings.get_brush_rgb(ctx.context)

    def _applied_hsv(self, ctx):
        """HSV of the color the pen paints. While the color is the one the pad wrote,
        the pad's own HSV is returned (hue / saturation survive grey and black)."""
        rgb = tuple(self._pen_color(ctx))
        hsv = hsv_for_rgb(rgb, ctx.state.get('pen_hsv'))
        ctx.state['pen_hsv'] = (rgb, hsv)
        return hsv

    def _original(self, ctx):
        """HSV from before the pad edits of the color the pen paints now, or None."""
        original = ctx.state.get('pen_color_original')
        if not original:
            return None
        target, hsv = original
        return hsv if target == self._button(ctx) else None  # RMB lock switched: other color

    def _pending(self, ctx):
        """Preview: HSV picked on the pad but not yet applied to the pen's color, or None."""
        pending = ctx.state.get('pen_color_pending')
        if not pending or not self._preview_on(ctx):
            return None
        target, hsv = pending
        return hsv if target == self._button(ctx) else None  # RMB lock switched: other color

    def pen_hsv(self):
        ctx = self._c()
        pending = self._pending(ctx)
        return pending if pending is not None else self._applied_hsv(ctx)

    def set_pen_hsv(self, h, s, v):
        """The color pad's commit (with Preview on: every step while the pen is down).

        With Preview on the color is only kept pending; the bubble applies it."""
        ctx = self._c()
        if self._preview_on(ctx):
            ctx.state['pen_color_pending'] = (self._button(ctx), (h, s, v))
            return
        if self._original(ctx) is None:
            ctx.state['pen_color_original'] = (self._button(ctx), self._applied_hsv(ctx))
        self._apply_hsv(ctx, h, s, v)

    def original_hsv(self):
        """Marked on the pad (cross + ticks): the applied color while a Preview is
        pending, else the color from before the pad edits until the bubble is tapped."""
        ctx = self._c()
        if self._pending(ctx) is not None:
            return self._applied_hsv(ctx)
        return self._original(ctx)

    def has_color_change(self):
        old, new = self.preview_colors()
        return any(abs(a - b) > 1e-4 for a, b in zip(old, new))

    def preview_colors(self):
        """(old, new) RGB for the preview bubble."""
        ctx = self._c()
        applied = tuple(self._pen_color(ctx))
        pending = self._pending(ctx)
        if pending is not None:
            return applied, colorsys.hsv_to_rgb(*pending)
        original = self._original(ctx)
        return (colorsys.hsv_to_rgb(*original) if original is not None else applied), applied

    def accept_color_change(self):
        """The bubble: applies a pending Preview color; the current color becomes the reference."""
        ctx = self._c()
        pending = self._pending(ctx)
        if pending is not None:
            self._apply_hsv(ctx, *pending)
        ctx.state['pen_color_pending'] = None
        ctx.state['pen_color_original'] = None

    @staticmethod
    def _preview_on(ctx):
        # Toggling the property discards a pending color (its update callback, properties.py).
        return bool(getattr(ctx.wm, 'pixel_painter_pen_color_preview', False))

    def color_preview(self):
        return self._preview_on(self._c())

    def color_layout(self):
        return getattr(self._c().wm, 'pixel_painter_color_selector_layout', 'SHEET')

    def color_model(self):
        return getattr(self._c().wm, 'pixel_painter_color_selector_model', 'HSV')

    def color_sliders(self):
        return set(getattr(self._c().wm, 'pixel_painter_color_selector_sliders', set()))

    def _apply_hsv(self, ctx, h, s, v):
        rgb = colorsys.hsv_to_rgb(h, s, v)
        if ctx.state.get('pen_rmb_lock'):
            ctx.settings.set_brush_secondary_rgb(ctx.context, *rgb)
        else:
            ctx.settings.set_brush_rgb(ctx.context, *rgb)
            ctx.state['sub_color_h'], ctx.state['sub_color_s'], ctx.state['sub_color_v'] = h, s, v
        # Cache what was actually stored (the color may be clamped / quantized).
        ctx.state['pen_hsv'] = (tuple(self._pen_color(ctx)), (h, s, v))

    def color_panel_open(self):
        return bool(self._c().state.get('pen_color_panel'))

    def toggle_color_panel(self):
        state = self._c().state
        state['pen_color_panel'] = not state.get('pen_color_panel')

    def texel_screen_px(self):
        """Screen pixels per image pixel at the current zoom (None if unknown)."""
        ctx = self._c()
        if ctx.is_3d:
            return ctx.state.get('view3d_texel_px')
        v2d, img = ctx.v2d, ctx.image
        if v2d is None or img is None or img.size[0] == 0:
            return None
        x0, _ = v2d.view_to_region(0.0, 0.0, clip=False)
        x1, _ = v2d.view_to_region(1.0 / img.size[0], 0.0, clip=False)
        return abs(x1 - x0)

    def brush_shape(self):
        return self.registry.get(self._c().mode).outline_shape

    def armed(self):
        return self._c().state.get('pen_armed')

    def toggle_arm(self, kind):
        state = self._c().state
        state['pen_armed'] = None if state.get('pen_armed') == kind else kind

    def colors(self):
        ctx = self._c()
        return ctx.settings.get_brush_rgb(ctx.context), ctx.settings.get_brush_secondary_rgb(ctx.context)

    def mix_color(self):
        """The primary and secondary color mixed half and half."""
        primary, secondary = self.colors()
        if primary is None or secondary is None:
            return primary or secondary
        return tuple((p + s) * 0.5 for p, s in zip(primary[:3], secondary[:3]))

    def use_mix_color(self):
        """The active color (secondary with the RMB lock) becomes the mix."""
        rgb = self.mix_color()
        if rgb is not None:
            self.set_color('SECONDARY' if self.rmb_lock() else 'PRIMARY', rgb)

    def swap_colors(self):
        ctx = self._c()
        primary, secondary = self.colors()
        ctx.settings.set_brush_rgb(ctx.context, *secondary)
        ctx.settings.set_brush_secondary_rgb(ctx.context, *primary)

    def spacing(self):
        return getattr(self._c().wm, 'pixel_painter_spacing', 'FREE')

    def toggle_spacing(self):
        wm = self._c().wm
        wm.pixel_painter_spacing = 'FREE' if self.spacing() == 'PIXEL' else 'PIXEL'

    def alpha_lock(self):
        return bool(getattr(self._c().wm, 'pixel_painter_protect_transparent', False))

    def toggle_alpha_lock(self):
        wm = self._c().wm
        wm.pixel_painter_protect_transparent = not self.alpha_lock()

    def rmb_lock(self):
        return bool(self._c().state.get('pen_rmb_lock'))

    def set_rmb_lock(self, value):
        if bool(value) != self.rmb_lock():
            self.toggle_rmb_lock()

    def toggle_rmb_lock(self):
        state = self._c().state
        state['pen_rmb_lock'] = not state.get('pen_rmb_lock')
        self._c().apply_tool_settings()

    def tools(self):
        return list(self.registry)

    def active_tool(self):
        return self._c().mode

    def select_tool(self, tool_id):
        ctx = self._c()
        self.manager.select(ctx, tool_id)
        ctx.apply_tool_settings()

    # ---- settings (the pen settings flyout, ui/pen_settings.py) ----------------------------

    def wm_get(self, name, default=None):
        """WindowManager property ``pixel_painter_<name>``."""
        return getattr(self._c().wm, f'pixel_painter_{name}', default)

    def wm_set(self, name, value):
        try:
            setattr(self._c().wm, f'pixel_painter_{name}', value)
        except Exception:
            traceback.print_exc()
        self._c().apply_tool_settings()

    def wm_flag(self, name, item):
        """Is ``item`` in the enum-flag property ``name``?"""
        return item in set(self.wm_get(name, set()) or set())

    def wm_toggle_flag(self, name, item):
        flags = set(self.wm_get(name, set()) or set())
        flags ^= {item}
        self.wm_set(name, flags)

    def wm_range(self, name):
        """``(min, max, is_int)`` of a number property (soft limits)."""
        try:
            prop = self._c().wm.bl_rna.properties[f'pixel_painter_{name}']
            return float(prop.soft_min), float(prop.soft_max), prop.type == 'INT'
        except Exception:
            return 0.0, 1.0, False

    def reset_tool_settings(self):
        self._run_deferred(lambda: bpy.ops.image.pixel_painter_reset_tool_settings())

    def reset_layout(self):
        """Reset Pen UI: default size and position of the menu and the color selector."""
        self._c().state.update(LAYOUT_STATE)

    # ---- color history ------------------------------------------------------------------

    def color_history(self):
        return color_history.colors(self._c().state)

    def use_history_color(self, rgb):
        """Paint with ``rgb`` from the history (the secondary color with the RMB lock)."""
        ctx = self._c()
        if ctx.state.get('pen_rmb_lock'):
            ctx.settings.set_brush_secondary_rgb(ctx.context, *rgb)
        else:
            ctx.settings.set_brush_rgb(ctx.context, *rgb)
        ctx.state['pen_color_pending'] = None

    # ---- palettes: per project (the scene, saved in the .blend), library (palettes.json) ----

    def color_drag_enabled(self):
        return bool(self.wm_get('pen_color_drag', True))

    def project(self):
        scene = self._c().context.scene
        return color_palette.decode_project(getattr(scene, 'pixel_painter_palettes', "") if scene else "")

    def _store_project(self, project):
        scene = self._c().context.scene
        if scene is not None and hasattr(scene, 'pixel_painter_palettes'):
            scene.pixel_painter_palettes = color_palette.encode_project(project)

    # The active palette's colors (the palette band's color view).

    def palette(self):
        active = color_palette.active_palette(self.project())
        return list(active["colors"]) if active else [None] * color_palette.PALETTE_SIZE

    def set_palette_slot(self, index, rgb):
        self._store_project(color_palette.edit_active(
            self.project(), lambda pal: color_palette.with_color(pal, index, rgb)))

    def swap_palette_slots(self, i, j):
        self._store_project(color_palette.edit_active(
            self.project(), lambda pal: color_palette.with_swapped_colors(pal, i, j)))

    def clear_palette(self):
        """Empty the active palette's colors (it keeps its name and slot)."""
        self._store_project(color_palette.edit_active(
            self.project(), lambda pal: dict(pal, colors=[None] * color_palette.PALETTE_SIZE)))

    # The project's palettes (the palette band's palette view).

    def palette_view(self):
        return bool(self._c().state.get('pen_palette_view'))

    def set_palette_view(self, on):
        self._c().state['pen_palette_view'] = bool(on)

    def active_palette_index(self):
        return self.project()["active"]

    def active_palette(self):
        return color_palette.active_palette(self.project())

    def project_palette(self, index):
        return self.project()["palettes"][index]

    def select_palette(self, index):
        """Make slot ``index`` the active palette (an empty slot gets a new, empty palette)."""
        project = self.project()
        if project["palettes"][index] is None:
            project = color_palette.with_palette(project, index,
                                                 color_palette.empty_palette(color_palette.next_name(project)))
        self._store_project(color_palette.with_active(project, index))

    def set_project_palette(self, index, palette):
        """Slot ``index`` set to a copy of ``palette`` (None deletes the palette)."""
        self._store_project(color_palette.with_palette(self.project(), index, palette))

    def swap_project_palettes(self, i, j):
        self._store_project(color_palette.with_swapped_palettes(self.project(), i, j))

    def set_active_palette(self, palette):
        """Replace the active palette's colors (paste)."""
        self._store_project(color_palette.edit_active(
            self.project(), lambda pal: dict(pal, colors=list(palette["colors"]))))

    # Library: not synced with the project; palettes are copied in and out.

    def library(self, reload=False):
        if self._library is None or reload:
            self._library = palette_library.load()
        return self._library

    def library_add(self, palette):
        self._library = self.library() + [dict(palette, colors=list(palette["colors"]))]
        palette_library.save(self._library)

    def library_delete(self, index):
        lib = list(self.library())
        if 0 <= index < len(lib):
            del lib[index]
            self._library = lib
            palette_library.save(lib)

    def palette_from_image(self):
        """Pick an image file; its pixel colors become a new palette (ui/palette_ops.py)."""
        self._run_deferred(lambda: bpy.ops.image.pixel_painter_palette_from_image('INVOKE_DEFAULT'))

    # Clipboard.

    def copy_palette(self, palette):
        """Put ``palette`` on the system clipboard (JSON with hex colors)."""
        try:
            self._c().wm.clipboard = color_palette.to_text(palette)
            return True
        except Exception:
            traceback.print_exc()
            return False

    def clipboard_palette(self):
        """The palette in the clipboard text (our JSON or any #rrggbb codes), or None."""
        try:
            return color_palette.from_text(self._c().wm.clipboard)
        except Exception:
            return None

    def set_color(self, which, rgb):
        """Set the primary ('PRIMARY') or secondary ('SECONDARY') color."""
        ctx = self._c()
        if which == 'SECONDARY':
            ctx.settings.set_brush_secondary_rgb(ctx.context, *rgb)
        else:
            ctx.settings.set_brush_rgb(ctx.context, *rgb)
        ctx.state['pen_color_pending'] = None

    # ---- custom falloff curve (the brush's falloff CurveMapping) ---------------------------

    def _curve_map(self):
        brush = self._c().context.tool_settings.image_paint.brush
        mapping = getattr(brush, 'curve', None) if brush is not None else None
        if mapping is None or not len(mapping.curves):
            return None, None
        return mapping, mapping.curves[0]

    def custom_curve_points(self):
        try:
            _mapping, curve = self._curve_map()
            return [tuple(p.location) for p in curve.points] if curve is not None else []
        except Exception:
            return []

    def set_custom_curve_points(self, points):
        """Replace the curve's anchors (at least 2, sorted by x; auto handles)."""
        points = sorted(points)
        if len(points) < 2:
            return
        try:
            mapping, curve = self._curve_map()
            if curve is None:
                return
            pts = curve.points
            while len(pts) > len(points):
                pts.remove(pts[len(pts) - 1])
            while len(pts) < len(points):
                pts.new(0.5, 0.5)
            for point, (x, y) in zip(pts, points):
                point.location = (x, y)
                point.handle_type = 'AUTO'
            mapping.update()
        except Exception:
            traceback.print_exc()
        self.use_custom_falloff()

    def reset_custom_curve(self):
        self.set_custom_curve_points(falloff.CUSTOM_DEFAULT_POINTS)

    def use_custom_falloff(self):
        """Editing the curve selects the Custom falloff (so the edit shows)."""
        if self.active_falloff() != 'CUSTOM':
            self.set_falloff('CUSTOM')

    def custom_curve_sampler(self):
        ctx = self._c()
        try:
            return ctx.settings.get_falloff_curve_sampler(ctx.context)
        except Exception:
            return None

    def _falloff_property(self, ctx):
        return self.registry.get(ctx.mode).falloff_property or falloff.DEFAULT_FALLOFF_PROPERTY

    def active_falloff(self):
        ctx = self._c()
        return getattr(ctx.wm, self._falloff_property(ctx), None)

    def set_falloff(self, preset_id):
        ctx = self._c()
        setattr(ctx.wm, self._falloff_property(ctx), preset_id)

    def blend_favorites(self):
        """Blend ids marked as favorites in the settings (the pie's defaults when none)."""
        raw = getattr(self._c().wm, 'pixel_painter_blend_favorites', None)
        selected = set(raw) if isinstance(raw, (set, list, tuple, frozenset)) else set()
        return selected or set(blend_modes.DEFAULT_FAVORITES)

    def active_blend(self):
        return blender_utils.get_brush_blend_mode(self._c().context)

    def set_blend(self, blend):
        try:
            brush = self._c().context.tool_settings.image_paint.brush
            if brush is not None:
                brush.blend = blend
        except Exception:
            traceback.print_exc()

    def collapsed(self):
        return bool(self._c().state.get('pen_bar_collapsed'))

    def set_collapsed(self, collapsed):
        self._c().state['pen_bar_collapsed'] = bool(collapsed)

    def get_state(self, key):
        """Pen UI layout state (``pen_bar_*`` / ``pen_color_*`` size, position, lock)."""
        return self._c().state.get(key)

    def set_state(self, key, value):
        self._c().state[key] = value

    # ---- paint mask (tools/mask.py) ---------------------------------------------------

    def mask_enabled(self):
        return bool(self.wm_get('mask_enabled', False))

    def toggle_mask(self):
        on = not self.mask_enabled()
        self.wm_set('mask_enabled', on)
        if not on and self.mask_picking():
            mask.set_picking(self._c().state, self._c().context, False)

    def mask_source(self):
        return self.wm_get('mask_source', 'UV_ISLAND')

    def toggle_mask_source(self):
        self.wm_set('mask_source', 'MESH_PART' if self.mask_source() == 'UV_ISLAND' else 'UV_ISLAND')

    def mask_inverted(self):
        return bool(self.wm_get('mask_invert', False))

    def toggle_mask_invert(self):
        self.wm_set('mask_invert', not self.mask_inverted())

    def mask_picking(self):
        return bool(self._c().state.get('mask_picking'))

    def toggle_mask_pick(self):
        ctx = self._c()
        mask.set_picking(ctx.state, ctx.context, not self.mask_picking())

    def clear_mask(self):
        mask.clear(self._c().context)

    def save_image(self):
        """Save the painted image (how: settings > Pen > Save Image, ui/image_save_ops.py)."""
        self._run_deferred(lambda: bpy.ops.image.pixel_painter_save_image())

    def image_unsaved(self):
        """The painted image has changes that are not saved / packed yet."""
        try:
            image = self._c().image
            return bool(image is not None and image.is_dirty)
        except Exception:
            return False

    def undo(self):
        self._run_deferred(lambda: bpy.ops.ed.undo())

    def redo(self):
        self._run_deferred(lambda: bpy.ops.ed.redo())

    def _run_deferred(self, fn):
        """Call ``fn`` (an operator call) on the next tick, outside the modal event handler."""
        ctx = self._c()
        window, area, region = ctx.context.window, ctx.area, ctx.region

        def _run():
            try:
                with bpy.context.temp_override(window=window, area=area, region=region):
                    fn()
            except Exception:
                traceback.print_exc()
            return None

        bpy.app.timers.register(_run, first_interval=0.0)
