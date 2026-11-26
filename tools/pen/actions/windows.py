"""The floating windows (Mask / View / Settings / Palettes), the View window's
navigation and the pixel grid overlay.
"""

import traceback

import bpy

from .. import view_nav


GRID_DEFAULT_OPACITY = 0.5     # a grid toggled on at 0 % starts here


class WindowActions:
    """Part of :class:`.bar.PenBarTool` (a mixin: uses its state)."""

    # ---- Mask / View / Settings / Palettes windows ----------------------------------------

    def panel_open(self, name):
        """Is the window ``name`` ('mask' / 'view' / 'settings' / 'library') shown?"""
        return bool(self._c().state.get(f'pen_{name}_panel'))

    def toggle_panel(self, name):
        state = self._c().state
        state[f'pen_{name}_panel'] = not state.get(f'pen_{name}_panel')

    # ---- View window (tools/view_nav.py) ---------------------------------------------------

    def in_view3d(self):
        area = self._c().area
        return area is not None and area.type == 'VIEW_3D'

    def view_compact(self):
        """The View window shows only the Orient dial."""
        return bool(self._c().state.get('pen_view_compact', False))

    def toggle_view_compact(self):
        state = self._c().state
        state['pen_view_compact'] = not state.get('pen_view_compact', False)

    def view_autofit(self):
        return bool(self._c().state.get('pen_view_autofit', True))

    def toggle_view_autofit(self):
        state = self._c().state
        state['pen_view_autofit'] = not state.get('pen_view_autofit', True)

    def _nav(self, fn, *args, fit=None):
        ctx = self._c()
        try:
            if fit is None:
                fn(ctx.context, ctx.area, *args)
            else:
                fn(ctx.context, ctx.area, *args, self.view_autofit() if fit else False)
        except Exception:
            traceback.print_exc()

    def view_axis(self, axis):
        self._nav(view_nav.view_axis, axis, fit=True)

    def view_orbit(self, yaw, pitch):
        self._nav(view_nav.view_orbit, yaw, pitch, fit=True)

    def view_roll(self, degrees):
        self._nav(view_nav.view_roll, degrees, fit=True)

    def view_level(self):
        self._nav(view_nav.view_level, fit=True)

    def view_perspective(self):
        return view_nav.is_perspective(self._c().area)

    def toggle_view_perspective(self):
        self._nav(view_nav.toggle_perspective, fit=True)

    def view_fit(self):
        """3D: frame the object exactly; Image Editor: fit the image."""
        if self.in_view3d():
            self._nav(view_nav.view_fit)
        else:
            self._run_deferred(lambda: bpy.ops.image.view_all(fit_view=True))

    def view_center(self):
        """3D: pivot on the object (no zoom); Image Editor: center the image."""
        if self.in_view3d():
            self._nav(view_nav.view_center)
        else:
            self._run_deferred(lambda: bpy.ops.image.view_all(fit_view=False))

    def view_zoom(self, step):
        """Zoom in (step > 0) / out around the view's center."""
        if self.in_view3d():
            self._run_deferred(lambda: bpy.ops.view3d.zoom(delta=step))
        else:
            # zoom about the view's center (view_zoom_in / _out zoom toward a location)
            try:
                zoom = float(self._c().area.spaces.active.zoom[0])
            except Exception:
                return
            ratio = zoom * (1.25 if step > 0 else 0.8)
            self._run_deferred(lambda: bpy.ops.image.view_zoom_ratio(ratio=ratio))

    def view_one_to_one(self):
        """Image Editor: 1 image pixel = 1 screen pixel."""
        if not self.in_view3d():
            self._run_deferred(lambda: bpy.ops.image.view_zoom_ratio(ratio=1.0))

    # ---- pixel grid overlay ----------------------------------------------------------

    def grid_shown(self):
        return bool(self.wm_get('grid_show', True)) and self.grid_opacity() > 0.0

    def grid_opacity(self):
        return float(self.wm_get('grid_opacity', 0.0) or 0.0)

    def toggle_grid(self):
        """On / off; turning on a grid at 0 % brings it to GRID_DEFAULT_OPACITY."""
        if self.grid_shown():
            self.wm_set('grid_show', False)
            return
        if self.grid_opacity() <= 0.0:
            self.wm_set('grid_opacity', GRID_DEFAULT_OPACITY)
        self.wm_set('grid_show', True)

    def set_grid_opacity(self, value):
        """Adjust (also shows the grid)."""
        self.wm_set('grid_opacity', max(0.0, min(1.0, value)))
        if not self.wm_get('grid_show', True):
            self.wm_set('grid_show', True)
