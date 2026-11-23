"""Native Blender menus (``bpy.types.Menu``): blend-mode pie and tool pie."""

import bpy
from bpy.types import Menu, Operator

from .icons import ICONS
from .kit.modal import force_cleanup
from ..tools import blend_modes
from ..tools.catalog import TOOLS


def _get_favorites(context):
    raw = getattr(context.window_manager, "pixel_painter_blend_favorites", blend_modes.DEFAULT_FAVORITES)
    if isinstance(raw, (set, list, tuple, frozenset)):
        selected = set(raw)
    elif isinstance(raw, str):
        selected = {raw} if raw else set()
    else:
        selected = set()
    return selected or set(blend_modes.DEFAULT_FAVORITES)


def _add_blend_item(layout, blend, favorites):
    icon = 'CHECKMARK' if blend in favorites else 'BLANK1'
    layout.operator("image.pixel_painter_set_blend", text=blend_modes.label(blend), icon=icon).blend = blend


def draw_tool_operator(layout, tool, text=None):
    """``image.pixel_painter_set_mode`` button for ``tool`` with its custom icon."""
    icon_value = ICONS.icon_id(tool.tool_id)
    kwargs = {'text': text if text is not None else tool.label}
    if icon_value:
        kwargs['icon_value'] = icon_value
    layout.operator("image.pixel_painter_set_mode", **kwargs).mode = tool.tool_id


class PixelPainterOpenBlendPieOperator(Operator):
    """Open the blend-mode pie menu"""

    bl_idname = "image.pixel_painter_open_blend_pie"
    bl_label = "Open Pixel Painter Blend Pie"

    def execute(self, context):
        force_cleanup(context.window_manager)

        # Timers run without a window/area; reopen in the editor the key was pressed in.
        window, area = context.window, context.area
        region = next((r for r in area.regions if r.type == 'WINDOW'), None) if area else None

        def _open():
            try:
                with bpy.context.temp_override(window=window, area=area, region=region):
                    bpy.ops.wm.call_menu_pie(name=PixelPainterBlendPie.bl_idname)
            except Exception:
                try:
                    bpy.ops.wm.call_menu_pie(name=PixelPainterBlendPie.bl_idname)
                except Exception:
                    import traceback
                    traceback.print_exc()
            return None

        bpy.app.timers.register(_open, first_interval=0.01)
        return {'FINISHED'}

    def invoke(self, context, event):
        return self.execute(context)


class PixelPainterModePie(Menu):
    """Native pie listing every registered tool (alternative to the custom pie)."""

    bl_idname = "PIXELPAINTER_MT_mode_pie"
    bl_label = "Drawing Mode"

    def draw(self, context):
        pie = self.layout.menu_pie()
        for tool in TOOLS:
            draw_tool_operator(pie, tool)


class PixelPainterBlendPie(Menu):
    bl_idname = "PIXELPAINTER_MT_blend_pie"
    bl_label = "Blend Mode"

    def draw(self, context):
        pie = self.layout.menu_pie()
        favorites = _get_favorites(context)

        for title, group in (("Contrast", 'CONTRAST'), ("HSL/HSV", 'HSL')):
            col = pie.column(align=True)
            col.label(text=title)
            for blend in blend_modes.ids(group):
                _add_blend_item(col, blend, favorites)

        math_col = pie.column(align=True)
        math_col.label(text="Math")
        grid = math_col.grid_flow(row_major=True, columns=3, even_columns=True, even_rows=True, align=True)
        for blend in blend_modes.ids('MATH'):
            _add_blend_item(grid, blend, favorites)
        grid.label(text="")

        common = pie.column(align=True)
        common.label(text="Favorites")
        grid = common.grid_flow(row_major=True, columns=3, even_columns=True, even_rows=True, align=True)
        for blend in blend_modes.ids():
            if blend in favorites:
                _add_blend_item(grid, blend, favorites)

        pie.separator()
        pie.separator()


classes = (
    PixelPainterOpenBlendPieOperator,
    PixelPainterModePie,
    PixelPainterBlendPie,
)
