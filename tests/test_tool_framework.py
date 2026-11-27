"""Unit tests for the tool framework (core/framework.py) and tool-switch subtools.

Runs with plain Python (no Blender needed) from the addon root:

    python -m unittest discover -s tests -v
"""

import os
import sys
import types
import unittest

_ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PACKAGE = os.path.basename(_ADDON_DIR)
sys.path.insert(0, os.path.dirname(_ADDON_DIR))
sys.modules.setdefault('bpy', types.ModuleType('bpy'))  # the package __init__ imports bpy

import importlib  # noqa: E402

framework = importlib.import_module(f'{_PACKAGE}.core.framework')
tool_switch = importlib.import_module(f'{_PACKAGE}.tools.subtools.tool_switch')

FunctionTool = framework.FunctionTool
HoldTool = framework.HoldTool
InputEvent = framework.InputEvent
Shortcut = framework.Shortcut
ToolFrame = framework.ToolFrame
ToolManager = framework.ToolManager
ShiftToolSwitch = tool_switch.ShiftToolSwitch
TemporaryToolSwitch = tool_switch.TemporaryToolSwitch
ToolSwitchShortcuts = tool_switch.ToolSwitchShortcuts


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeCtx:
    def __init__(self, mode):
        self._mode = mode
        self.wm = types.SimpleNamespace(pixel_painter_temp_smooth_force_global=False)
        self.state = {}

    @property
    def mode(self):
        return self._mode

    def set_mode(self, tool_id):
        self._mode = tool_id

    def redraw(self):
        pass

    def apply_tool_settings(self):
        pass


def ev(type_, value='PRESS', **mods):
    return InputEvent(type_, value, **mods)


class FakePaintTool(ToolFrame):
    """Records presses; carries the standard modifier switches like StrokeTool."""

    def __init__(self, tool_id, log, extra_subtools=()):
        super().__init__()
        self.tool_id = tool_id
        self.log = log
        self.extra_subtools = extra_subtools
        self.interrupts = 0

    def on_register(self):
        if self.tool_id != 'LINE':
            self.add_subtool(TemporaryToolSwitch('LINE', 'ALT'))
        self.add_subtool(ShiftToolSwitch('SMOOTH', 'ERASER'))
        for sub in self.extra_subtools:
            self.add_subtool(sub)
        self.bind(Shortcut('LEFTMOUSE'), lambda ctx, e: self.log.append((self.tool_id, 'LMB')))
        self.bind(Shortcut('RIGHTMOUSE'), lambda ctx, e: self.log.append((self.tool_id, 'RMB')))

    def on_activate(self, ctx, event):
        self.log.append((self.tool_id, 'activate'))

    def on_deactivate(self, ctx):
        self.log.append((self.tool_id, 'deactivate'))

    def on_interrupt(self, ctx):
        self.interrupts += 1


class FakeRegistry:
    def __init__(self, tools):
        self.tools = tools

    def by_shortcut_index(self, index):
        return self.tools[index] if 0 <= index < len(self.tools) else None


def build(mode='SQUARE', extra_subtools=None):
    log = []
    extra_subtools = extra_subtools or {}
    tools = [FakePaintTool(tid, log, extra_subtools.get(tid, ()))
             for tid in ('SQUARE', 'SMOOTH', 'LINE', 'ERASER')]
    manager = ToolManager()
    manager.register_all(tools)
    manager.register(ToolSwitchShortcuts(FakeRegistry(tools)))
    ctx = FakeCtx(mode)
    manager.begin(ctx)
    log.clear()
    return manager, ctx, log, {t.tool_id: t for t in tools}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class ShortcutTest(unittest.TestCase):
    def test_modifier_names_expand_to_both_keys(self):
        sc = Shortcut('SHIFT')
        self.assertTrue(sc.matches(ev('LEFT_SHIFT', shift=True)))
        self.assertTrue(sc.matches(ev('RIGHT_SHIFT', shift=True)))
        self.assertFalse(sc.matches(ev('LEFT_SHIFT', 'RELEASE')))

    def test_modifier_constraints(self):
        sc = Shortcut('E', shift=False)
        self.assertTrue(sc.matches(ev('E')))
        self.assertTrue(sc.matches(ev('E', ctrl=True)))   # ctrl: don't care
        self.assertFalse(sc.matches(ev('E', shift=True)))

    def test_any_value(self):
        sc = Shortcut('MOUSEMOVE', None)
        self.assertTrue(sc.matches(ev('MOUSEMOVE', 'NOTHING')))


class RoutingTest(unittest.TestCase):
    def test_bind_consumes_unless_false(self):
        root = ToolFrame()
        seen = []
        root.bind(Shortcut('A'), lambda ctx, e: False)
        root.bind(Shortcut('A'), lambda ctx, e: seen.append('second'))
        root.setup(ToolManager())
        event = ev('A')
        root.dispatch(None, event)
        self.assertEqual(seen, ['second'])
        self.assertTrue(event.consumed)

    def test_subtool_shortcuts_only_while_parent_selected(self):
        popup = ToolFrame()
        popup.triggers = (Shortcut('E'),)
        manager, ctx, log, tools = build(extra_subtools={'SMOOTH': (popup,)})
        manager.dispatch(ctx, ev('E'))
        self.assertFalse(popup.is_active)          # SQUARE selected: SMOOTH's subtool unreachable
        ctx.set_mode('SMOOTH')
        manager.dispatch(ctx, ev('E'))
        self.assertTrue(popup.is_active)

    def test_exclusive_subtool_blocks_parent(self):
        popup = ToolFrame()
        popup.triggers = (Shortcut('E'),)
        popup.exclusive = True
        manager, ctx, log, tools = build(extra_subtools={'SQUARE': (popup,)})
        manager.dispatch(ctx, ev('E'))
        self.assertEqual(tools['SQUARE'].interrupts, 1)  # parent work aborted on takeover
        event = ev('LEFTMOUSE')
        manager.dispatch(ctx, event)
        self.assertEqual(log, [])                  # parent did not paint
        self.assertFalse(event.consumed)           # ...and Blender may still see it
        popup.deactivate(ctx)
        manager.dispatch(ctx, ev('LEFTMOUSE'))
        self.assertEqual(log, [('SQUARE', 'LMB')])

    def test_hold_tool_with_function_callbacks(self):
        calls = []
        parent = ToolFrame()
        hold = parent.add_subtool(HoldTool('SHIFT', on_hold=lambda c: calls.append('hold'),
                                           on_release=lambda c: calls.append('release')))
        parent.setup(ToolManager())
        parent.dispatch(None, ev('LEFT_SHIFT', shift=True))
        self.assertTrue(hold.is_active)
        parent.dispatch(None, ev('MOUSEMOVE', 'NOTHING', shift=True))
        self.assertTrue(hold.is_active)
        parent.dispatch(None, ev('MOUSEMOVE', 'NOTHING'))  # release event was missed
        self.assertFalse(hold.is_active)
        self.assertEqual(calls, ['hold', 'release'])


class TemporarySwitchTest(unittest.TestCase):
    def test_alt_switches_to_line_and_back(self):
        manager, ctx, log, tools = build()
        manager.dispatch(ctx, ev('LEFT_ALT', alt=True))
        self.assertEqual(ctx.mode, 'LINE')
        manager.dispatch(ctx, ev('LEFTMOUSE', alt=True))
        self.assertIn(('LINE', 'LMB'), log)
        self.assertNotIn(('SQUARE', 'LMB'), log)
        manager.dispatch(ctx, ev('LEFT_ALT', 'RELEASE'))
        self.assertEqual(ctx.mode, 'SQUARE')
        self.assertIs(manager.base_tool, tools['SQUARE'])

    def test_alt_click_as_first_event(self):
        manager, ctx, log, tools = build()
        manager.dispatch(ctx, ev('LEFTMOUSE', alt=True))  # e.g. the invoke press
        self.assertEqual(ctx.mode, 'LINE')
        self.assertIn(('LINE', 'LMB'), log)

    def test_shift_lmb_smooth_rmb_eraser(self):
        manager, ctx, log, tools = build()
        manager.dispatch(ctx, ev('LEFT_SHIFT', shift=True))
        self.assertEqual(ctx.mode, 'SMOOTH')
        self.assertTrue(ctx.wm.pixel_painter_temp_smooth_force_global)
        manager.dispatch(ctx, ev('RIGHTMOUSE', shift=True))
        self.assertEqual(ctx.mode, 'ERASER')
        self.assertIn(('ERASER', 'RMB'), log)
        manager.dispatch(ctx, ev('LEFTMOUSE', shift=True))
        self.assertEqual(ctx.mode, 'SMOOTH')
        self.assertIn(('SMOOTH', 'LMB'), log)
        manager.dispatch(ctx, ev('LEFT_SHIFT', 'RELEASE'))
        self.assertEqual(ctx.mode, 'SQUARE')
        self.assertFalse(ctx.wm.pixel_painter_temp_smooth_force_global)

    def test_shift_e_reaches_parent_subtool(self):
        strength = ToolFrame()
        strength.triggers = (Shortcut('E', shift=True),)
        manager, ctx, log, tools = build(extra_subtools={'SQUARE': (strength,)})
        manager.dispatch(ctx, ev('LEFT_SHIFT', shift=True))
        manager.dispatch(ctx, ev('E', shift=True))
        self.assertEqual(ctx.mode, 'SQUARE')       # Shift override ended first
        self.assertTrue(strength.is_active)

    def test_nested_shift_then_alt(self):
        manager, ctx, log, tools = build()
        manager.dispatch(ctx, ev('LEFT_SHIFT', shift=True))
        manager.dispatch(ctx, ev('LEFT_ALT', shift=True, alt=True))
        self.assertEqual(ctx.mode, 'LINE')
        manager.dispatch(ctx, ev('LEFT_ALT', 'RELEASE', shift=True))
        self.assertEqual(ctx.mode, 'SMOOTH')
        manager.dispatch(ctx, ev('LEFT_SHIFT', 'RELEASE'))
        self.assertEqual(ctx.mode, 'SQUARE')

    def test_shift_release_while_alt_held_restores_selected_tool(self):
        manager, ctx, log, tools = build()
        manager.dispatch(ctx, ev('LEFT_SHIFT', shift=True))
        manager.dispatch(ctx, ev('LEFT_ALT', shift=True, alt=True))
        manager.dispatch(ctx, ev('LEFT_SHIFT', 'RELEASE', alt=True))
        self.assertEqual(ctx.mode, 'SQUARE')
        self.assertFalse(tools['LINE'].is_active)
        self.assertFalse(tools['SMOOTH'].is_active)


class ManagerTest(unittest.TestCase):
    def test_shift_number_selects_and_sticks(self):
        manager, ctx, log, tools = build()
        manager.dispatch(ctx, ev('LEFT_SHIFT', shift=True))   # Shift override -> SMOOTH
        manager.dispatch(ctx, ev('THREE', shift=True))         # Shift+3 -> LINE
        self.assertEqual(ctx.mode, 'LINE')
        manager.dispatch(ctx, ev('LEFT_SHIFT', 'RELEASE'))
        self.assertEqual(ctx.mode, 'LINE')                     # releasing Shift must not revert
        self.assertIs(manager.base_tool, tools['LINE'])

    def test_selecting_the_current_stand_in(self):
        manager, ctx, log, tools = build()
        manager.dispatch(ctx, ev('LEFT_SHIFT', shift=True))   # SMOOTH is a stand-in
        manager.dispatch(ctx, ev('TWO', shift=True))           # Shift+2 -> SMOOTH for real
        self.assertEqual(ctx.mode, 'SMOOTH')
        self.assertIs(manager.base_tool, tools['SMOOTH'])
        self.assertIsNone(tools['SMOOTH'].host)
        manager.dispatch(ctx, ev('LEFT_SHIFT', 'RELEASE'))
        self.assertEqual(ctx.mode, 'SMOOTH')

    def test_external_mode_change_switches_tool(self):
        manager, ctx, log, tools = build()
        ctx.set_mode('ERASER')                                 # e.g. picked in a pie menu
        manager.dispatch(ctx, ev('LEFTMOUSE'))
        self.assertEqual(log, [('SQUARE', 'deactivate'), ('ERASER', 'activate'), ('ERASER', 'LMB')])

    def test_end_restores_temporary_mode(self):
        manager, ctx, log, tools = build()
        manager.dispatch(ctx, ev('LEFT_ALT', alt=True))
        manager.end(ctx)
        self.assertEqual(ctx.mode, 'SQUARE')
        self.assertFalse(any(t.is_active for t in manager.tools))


class SecondaryToolTest(unittest.TestCase):
    """ToolManager.secondary_tool: the temporary tool holding the mouse (selected tool dotted)."""

    class Picker(ToolFrame):          # like E / the Ctrl eyedropper: secondary while active
        secondary = True

    class ArmedGlobal(ToolFrame):     # like MaskTool / ExtrasTool: always active, armed by state
        is_global = True

        def holds_mouse(self, ctx):
            return bool(ctx.state.get('armed'))

    def test_empty_by_default(self):
        manager, ctx, _log, _tools = build()
        self.assertIsNone(manager.secondary_tool(ctx))

    def test_active_secondary_subtool(self):
        picker = self.Picker()
        picker.triggers = (Shortcut('E'),)
        manager, ctx, _log, _tools = build(extra_subtools={'SQUARE': (picker,)})
        manager.dispatch(ctx, ev('E'))
        self.assertIs(manager.secondary_tool(ctx), picker)
        picker.deactivate(ctx)
        self.assertIsNone(manager.secondary_tool(ctx))

    def test_tool_switch_is_not_secondary(self):
        manager, ctx, _log, _tools = build()
        manager.dispatch(ctx, ev('LEFT_ALT', alt=True))
        self.assertEqual(ctx.mode, 'LINE')
        self.assertIsNone(manager.secondary_tool(ctx))

    def test_secondary_inside_stand_in(self):
        picker = self.Picker()
        picker.triggers = (Shortcut('E', alt=None),)
        manager, ctx, _log, _tools = build(extra_subtools={'LINE': (picker,)})
        manager.dispatch(ctx, ev('LEFT_ALT', alt=True))
        manager.dispatch(ctx, ev('E', alt=True))
        self.assertIs(manager.secondary_tool(ctx), picker)

    def test_global_armed_by_state(self):
        manager, ctx, _log, _tools = build()
        tool = manager.register(self.ArmedGlobal())
        tool.activate(ctx)
        self.assertIsNone(manager.secondary_tool(ctx))
        ctx.state['armed'] = True
        self.assertIs(manager.secondary_tool(ctx), tool)


if __name__ == '__main__':
    unittest.main()
