"""Class-based menu controllers for Pixel Painter UI entry points."""

import bpy


class MenuControllerBase:
    """Base class for menu actions that can be invoked by the core."""

    menu_id = 'BASE_MENU'

    def open(self, context, **kwargs) -> bool:
        """Open the menu and return whether invocation succeeded."""
        raise NotImplementedError()


class PieMenuController(MenuControllerBase):
    """Controller for custom radial pie menus."""

    menu_id = 'PIE_MENU'

    def open(self, context, pie_type='MODE') -> bool:
        # Use Blender operator invoke flow first; fallback to explicit override
        # context for edge cases where region routing fails.
        opened = False
        try:
            result = bpy.ops.image.pixel_painter_custom_pie('INVOKE_DEFAULT', pie_type=pie_type)
            opened = ('RUNNING_MODAL' in result) or ('FINISHED' in result)
        except Exception:
            opened = False

        if opened:
            return True

        try:
            area = context.area
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            override = {
                'window': context.window,
                'screen': context.screen,
                'area': area,
                'region': region,
            }
            bpy.ops.image.pixel_painter_custom_pie(override, 'INVOKE_DEFAULT', pie_type=pie_type)
            return True
        except Exception:
            return False


class ColorPickerMenuController(MenuControllerBase):
    """Logical controller for the interactive color picker process."""

    menu_id = 'COLOR_PICKER'

    def open(self, context, **kwargs) -> bool:
        # Color picker lives inside the modal tool as a process state.
        # The controller exists so future dedicated menus can share one API.
        del context, kwargs
        return True


class ColorSelectorMenuController(MenuControllerBase):
    """Logical controller for color target selection UI."""

    menu_id = 'COLOR_SELECTOR'

    def open(self, context, **kwargs) -> bool:
        # Selection is currently toggled in modal logic; this class keeps
        # a stable hook for future stand-alone selector panels.
        del context, kwargs
        return True


class MenuControllerRegistry:
    """Registry that resolves menu controllers by identifier."""

    def __init__(self):
        self._controllers = {
            'PIE_MENU': PieMenuController(),
            'COLOR_PICKER': ColorPickerMenuController(),
            'COLOR_SELECTOR': ColorSelectorMenuController(),
        }

    def open_menu(self, menu_id: str, context, **kwargs) -> bool:
        """Open one menu controller if present."""
        controller = self._controllers.get(menu_id)
        if controller is None:
            return False
        return controller.open(context, **kwargs)
