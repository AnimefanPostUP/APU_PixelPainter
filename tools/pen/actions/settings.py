"""WindowManager settings access for the pen windows (``wm_get`` / ``wm_set`` / flags / ranges).
"""

import traceback

import bpy

from ....ui.pen.metrics import LAYOUT_STATE


class SettingsActions:
    """Part of :class:`.bar.PenBarTool` (a mixin: uses its state)."""

    # ---- settings (the pen settings flyout, ui/pen/windows/settings.py) ----------------------------

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
        """Reset Pen UI: default size and position of the menu and its windows."""
        self._c().state.update(LAYOUT_STATE)
