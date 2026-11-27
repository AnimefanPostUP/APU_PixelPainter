"""Actions of the Extras window (Fill / Edges / Ambient Occlusion, tools/extras/).
"""

from ....model import value_curve
from ...extras import tool as extras_tool
from .mask import next_source

EXTRAS_TOOLS = ('FILL', 'EDGES', 'AO')


class ExtrasActions:
    """Part of :class:`.bar.PenBarTool` (a mixin: uses its state)."""

    def extras_mode(self):
        return self._c().state.get('extras_mode')

    def extras_selected(self, mode):
        return self.extras_mode() == mode

    def _arm_extras(self, mode):
        ctx = self._c()
        extras_tool.set_mode(ctx.state, mode)
        if mode is not None:
            ctx.state['extras_last_mode'] = mode
        ctx.state['extras_status'] = None
        ctx.redraw()

    def toggle_extras_mode(self, mode):
        """Arm ``mode`` (tapping the armed one disarms it)."""
        self._arm_extras(None if self.extras_mode() == mode else mode)

    def extras_tool(self):
        """The tool the Extras window shows: the armed one, else the last armed (Fill at first)."""
        state = self._c().state
        mode = state.get('extras_mode') or state.get('extras_last_mode')
        return mode if mode in EXTRAS_TOOLS else EXTRAS_TOOLS[0]

    def extras_run_all(self):
        """Run the shown tool on every island / part."""
        extras_tool.run(self._c(), self.extras_tool(), None)

    def extras_status(self):
        return self._c().state.get('extras_status') or ""

    def extras_source(self):
        return self.wm_get('extras_source', 'UV_ISLAND')

    def toggle_extras_source(self):
        self.wm_set('extras_source', next_source(self.extras_source()))

    # ---- curves: 'ao' (AO) / 'edge' (Edges falloff) / 'fill' (Fill fade-out), model/value_curve.py --------------------

    def extras_curve_open(self):
        """The curve section under the circle is folded out."""
        return bool(self._c().state.get('pen_extras_curve'))

    def toggle_extras_curve(self):
        state = self._c().state
        state['pen_extras_curve'] = not state.get('pen_extras_curve')

    def extras_curve_points(self, kind):
        return value_curve.from_text(self.wm_get(f'extras_{kind}_curve', ""), kind)

    def set_extras_curve_points(self, kind, points):
        self.wm_set(f'extras_{kind}_curve', value_curve.to_text(points))

    def extras_curve_sampler(self, kind):
        points = self.extras_curve_points(kind)
        return lambda t: value_curve.sample(points, t)

    def load_extras_curve_preset(self, kind, preset_id):
        points = value_curve.preset(kind, preset_id)
        if points is not None:
            self.set_extras_curve_points(kind, points)
