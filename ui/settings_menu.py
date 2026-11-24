"""Settings popup: rarely changed options, grouped in tabs under a header bar.

Opened by ``image.pixel_painter_open_settings`` (the pen bar's *Settings*
button, the N-panel and the tool header). It is a popover panel, so it works
in the Image Editor and the 3D Viewport alike and redraws when a tab changes.
The selected tab is ``pixel_painter_settings_tab`` (remembered).

To add a category: add an item to ``SETTINGS_TABS`` and a ``_draw_<id>``
function to ``_TAB_DRAWERS``.
"""

import bpy
from bpy.types import Operator, Panel

from ..tools import blend_modes
from ..tools.catalog import TOOLS, falloff_property_for
from .tool_settings_ui import draw_falloff_section

SETTINGS_PANEL_ID = "IMAGE_PT_pixel_painter_settings"

# (id, label, icon) -- order = order in the header bar.
SETTINGS_TABS = (
    ('COLOR', "Color Selector", 'COLOR'),
    ('TOOLS', "Tools", 'TOOL_SETTINGS'),
    ('BLENDING', "Blending", 'OVERLAY'),
    ('FALLOFF', "Falloff", 'SMOOTHCURVE'),
    ('PEN', "Pen", 'GREASEPENCIL'),
    ('DISPLAY', "Display", 'HIDE_OFF'),
    ('SHORTCUTS', "Shortcuts", 'INFO'),
)


def tab_enum_items():
    return [(tab_id, label, f"{label} settings", icon, i) for i, (tab_id, label, icon) in enumerate(SETTINGS_TABS)]


def _hints(layout, lines):
    col = layout.column(align=True)
    col.scale_y = 0.8
    for line in lines:
        col.label(text=line)


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

def _draw_color(layout, context):
    wm = context.window_manager
    layout.label(text="Layout")
    row = layout.row(align=True)
    row.scale_y = 1.2
    row.prop(wm, "pixel_painter_color_selector_layout", expand=True)
    row = layout.row(align=True)
    row.label(text="Color Model")
    row.prop(wm, "pixel_painter_color_selector_model", expand=True)
    row = layout.row(align=True)
    row.label(text="Sliders")
    sliders = row.row(align=True)
    sliders.operator("image.pixel_painter_color_sliders_none", text="None",
                     depress=not wm.pixel_painter_color_selector_sliders)
    sliders.prop(wm, "pixel_painter_color_selector_sliders", expand=True)
    _hints(layout, (
        "Used by the pen bar color pad and the E color selector.",
        "Every part is swiped like a touchpad (pen friendly); a tap jumps.",
        "Sliders: RGB / HSV / HSL channel bars under the selector (any combination).",
    ))

    layout.separator()
    layout.label(text="Pen Color Selector")
    layout.prop(wm, "pixel_painter_pen_color_preview", text="Preview", toggle=True, icon='HIDE_OFF')
    _hints(layout, (
        "On: the pad only previews; the brush keeps its color",
        "until the old / new bubble is tapped (applies it).",
        "Off: the pad color applies when the pen is lifted;",
        "tapping the bubble makes it the new reference.",
    ))


_CHANNELS = (("size", "Size", False), ("strength", "Strength", True),
             ("alpha", "Alpha", True), ("modifier", "Modifier", True))


def _draw_tools(layout, context):
    wm = context.window_manager
    mode = wm.pixel_painter_mode

    layout.label(text="Tool")
    grid = layout.grid_flow(row_major=True, columns=4, even_columns=True, align=True)
    for tool in TOOLS:
        grid.prop_enum(wm, "pixel_painter_mode", tool.tool_id)

    layout.separator()
    layout.label(text=f"Per-Tool Settings: {TOOLS.get(mode).label}")
    box = layout.box().column(align=True)
    for channel, label, slider in _CHANNELS:
        row = box.row(align=True)
        use_global = f'pixel_painter_{mode}_use_global_{channel}'
        row.prop(wm, use_global, text=f"Global {label}", toggle=True)
        sub = row.row(align=True)
        sub.enabled = not getattr(wm, use_global, True)
        sub.prop(wm, f'pixel_painter_{mode}_{channel}', text=label, slider=slider)
    _hints(layout, ("Global: the tool uses the shared value.",))

    layout.separator()
    layout.operator("image.pixel_painter_reset_tool_settings", text="Reset Tool Settings", icon='LOOP_BACK')

    layout.separator()
    _draw_mask(layout, context)


def _draw_mask(layout, context):
    from ..core.state import STATE
    wm = context.window_manager
    layout.label(text="Paint Mask (pen menu, top right)", icon='MOD_MASK')
    row = layout.row(align=True)
    row.prop(wm, "pixel_painter_mask_enabled", text="Mask", toggle=True)
    row.prop(wm, "pixel_painter_mask_invert", text="Invert", toggle=True, icon='ARROW_LEFTRIGHT')
    row.prop(wm, "pixel_painter_mask_show", text="Show", toggle=True, icon='HIDE_OFF')
    row = layout.row(align=True)
    row.prop(wm, "pixel_painter_mask_source", expand=True)
    layout.prop(wm, "pixel_painter_mask_grow", text="Grow (px)")
    row = layout.row(align=True)
    picking = bool(STATE.get('mask_picking'))
    row.operator("image.pixel_painter_mask_pick", text="Done Picking" if picking else "Pick on Canvas",
                 icon='RESTRICT_SELECT_OFF', depress=picking)
    row.operator("image.pixel_painter_mask_clear", text="Clear", icon='X')
    _hints(layout, (
        "Pick: tap islands / parts on the canvas to toggle them (drag: several).",
        "Only the chosen ones are painted; Invert protects them instead.",
        "Uses the active and the selected mesh objects. Chosen parts are saved",
        "in the .blend. Grow: extra pixels around each island (edge pixels).",
    ))


def _draw_blending(layout, context):
    wm = context.window_manager
    brush = context.tool_settings.image_paint.brush
    if brush:
        row = layout.row(align=True)
        row.label(text="Blend Mode")
        row.prop(brush, "blend", text="")
        layout.separator()

    layout.label(text="Favorites (Shift+W pie, pen bar Blend flyout)")
    split = layout.box().split(factor=0.5, align=True)
    columns = (
        (split.column(align=True), (("Common", 'COMMON'), ("Contrast", 'CONTRAST'))),
        (split.column(align=True), (("Math", 'MATH'), ("HSL/HSV", 'HSL'))),
    )
    for col, groups in columns:
        for i, (title, group) in enumerate(groups):
            if i:
                col.separator()
            col.label(text=title)
            for blend in blend_modes.ids(group):
                col.prop_enum(wm, "pixel_painter_blend_favorites", blend)


def _draw_falloff(layout, context):
    wm = context.window_manager
    layout.label(text="Falloff per Tool")
    box = layout.box().column(align=True)
    for tool in TOOLS:
        if not tool.falloff_property:
            continue
        row = box.split(factor=0.35, align=True)
        row.label(text=tool.label)
        row.prop(wm, tool.falloff_property, text="")

    layout.separator()
    prop_name = falloff_property_for(wm.pixel_painter_mode)
    layout.label(text=f"Active Tool: {TOOLS.get(wm.pixel_painter_mode).label}")
    draw_falloff_section(layout, context, prop_name)
    if getattr(wm, prop_name) != 'CUSTOM':
        _hints(layout, ("Pick 'Custom' to edit the falloff curve.",))


_PRESSURE_CHANNELS = (("size", "Size"), ("strength", "Strength"), ("alpha", "Alpha"), ("modifier", "Modifier"))


def _draw_pen(layout, context):
    wm = context.window_manager
    layout.prop(wm, "pixel_painter_pen_bar", text="Pen Bar", toggle=True, icon='GREASEPENCIL')
    row = layout.row(align=True)
    row.label(text="Default Side")
    row.prop_enum(wm, "pixel_painter_pen_bar_side", 'LEFT', text="Left")
    row.prop_enum(wm, "pixel_painter_pen_bar_side", 'RIGHT', text="Right")
    layout.operator(RESET_PEN_UI_OPERATOR, icon='LOOP_BACK')

    layout.separator()
    layout.label(text="Pen Pressure Affects", icon='STYLUS_PRESSURE')
    row = layout.row(align=True)
    for channel, text in _PRESSURE_CHANNELS:
        row.prop(wm, f"pixel_painter_pen_pressure_{channel}", text=text, toggle=True)
    layout.prop(wm, "pixel_painter_pen_pressure_min", text="Minimum Pressure", slider=True)

    layout.separator()
    layout.label(text="Save Image (pen menu, top right)", icon='FILE_TICK')
    row = layout.row(align=True)
    row.prop(wm, "pixel_painter_save_image_method", expand=True)
    folder = layout.row(align=True)
    folder.enabled = wm.pixel_painter_save_image_method == 'FILE'
    folder.prop(wm, "pixel_painter_save_image_folder", text="Folder")
    layout.prop(wm, "pixel_painter_save_image_blend", text="Also Save .blend", toggle=True, icon='BLENDER')
    _hints(layout, (
        "Auto: repack packed images, save images with a file, pack new ones.",
        "Pack: always pack into the .blend. File: always write a file;",
        "images without one go to the folder (// = next to the .blend).",
        "Packed pixels only reach the disk when the .blend is saved.",
    ))
    layout.operator("image.pixel_painter_save_image", text="Save Image Now", icon='FILE_TICK')

    layout.separator()
    layout.label(text="Pen Bar Usage")
    _hints(layout.box(), (
        "Size: press and drag up/down; S / A / M: press or drag",
        "Background: drag to move the menu / color selector",
        "Corner triangle: drag to resize; padlock: lock both",
        "Reset Pen UI: default size and position",
        "Color: shows the color selector (swipe, tap jumps)",
        "Bubble: old/new color (tap: accept new)",
        "Colors: tap to paint with it, arrows swap them",
        "Color history (along the circle): tap to paint with it",
        "Curve (beside Custom falloff): edit / draw the curve",
        "Settings: opens this menu",
        "Save (top right): saves the image; dot = unsaved",
        "Picker: arm, then tap the canvas",
        "Blend: press, drag onto entry, lift",
        "RMB: pen paints the secondary color",
    ))


def _draw_display(layout, context):
    wm = context.window_manager
    row = layout.row(align=True)
    row.prop(wm, "pixel_painter_grid_show", text="", icon='MESH_GRID')
    row.prop(wm, "pixel_painter_grid_opacity", text="Grid Opacity", slider=True)


_SHORTCUTS = (
    ("LMB", "Paint with primary color"),
    ("RMB", "Paint with secondary color"),
    ("Select: Drag LMB", "Create or move selection"),
    ("Select: Edge/Corner Drag", "Resize selection box"),
    ("Select: RMB", "Clear selection box"),
    ("Select: Ctrl+C / Ctrl+V", "Copy and paste selection"),
    ("Hold Shift", "Smooth while held"),
    ("Hold Alt", "Line draw while held"),
    ("Hold Ctrl", "Pick image color"),
    ("Shift+1..9", "Select tool"),
    ("E", "Open color selector (selected layout)"),
    ("Shift+E", "Open strength/alpha bubble"),
    ("W", "Open brush type menu"),
    ("Shift+W", "Open blend mode pie"),
    ("Ctrl+Z", "Undo"),
    ("Ctrl+Shift+Z", "Redo"),
    ("Q / Esc", "Exit tool"),
)


def _draw_shortcuts(layout, context):
    col = layout.column(align=True)
    for key_text, action_text in _SHORTCUTS:
        row = col.split(factor=0.4, align=True)
        row.label(text=key_text)
        row.label(text=action_text)


_TAB_DRAWERS = {
    'COLOR': _draw_color,
    'TOOLS': _draw_tools,
    'BLENDING': _draw_blending,
    'FALLOFF': _draw_falloff,
    'PEN': _draw_pen,
    'DISPLAY': _draw_display,
    'SHORTCUTS': _draw_shortcuts,
}


# ---------------------------------------------------------------------------
# Popup
# ---------------------------------------------------------------------------

class IMAGE_PT_pixel_painter_settings(Panel):
    """Pixel Painter settings: header bar with categories, the selected one below."""
    bl_idname = SETTINGS_PANEL_ID
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'HEADER'
    bl_label = "Pixel Painter Settings"
    bl_ui_units_x = 30

    def draw(self, context):
        wm = context.window_manager
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        layout.label(text="Pixel Painter Settings", icon='PREFERENCES')
        header = layout.row(align=True)
        header.scale_y = 1.25
        header.prop(wm, "pixel_painter_settings_tab", expand=True)
        layout.separator()

        drawer = _TAB_DRAWERS.get(wm.pixel_painter_settings_tab)
        if drawer is not None:
            drawer(layout.column(), context)


class PixelPainterOpenSettingsOperator(Operator):
    """Open the Pixel Painter settings"""
    bl_idname = "image.pixel_painter_open_settings"
    bl_label = "Pixel Painter Settings"

    tab: bpy.props.EnumProperty(
        name="Tab", items=[('KEEP', "Keep", "Open the last used tab")]
        + [(t, label, "") for t, label, _icon in SETTINGS_TABS],
        default='KEEP', options={'SKIP_SAVE'})

    def execute(self, context):
        if self.tab != 'KEEP':
            context.window_manager.pixel_painter_settings_tab = self.tab
        bpy.ops.wm.call_panel(name=SETTINGS_PANEL_ID, keep_open=True)
        return {'FINISHED'}


class PixelPainterColorSlidersNoneOperator(Operator):
    """Hide all channel sliders under the color selector"""
    bl_idname = "image.pixel_painter_color_sliders_none"
    bl_label = "No Sliders"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        context.window_manager.pixel_painter_color_selector_sliders = set()
        return {'FINISHED'}


RESET_PEN_UI_OPERATOR = "image.pixel_painter_reset_pen_ui"


class PixelPainterResetPenUIOperator(Operator):
    """Reset the size and position of the pen menu and the color selector"""
    bl_idname = RESET_PEN_UI_OPERATOR
    bl_label = "Reset Pen UI"

    def execute(self, context):
        from ..core.state import STATE
        from .pen_bar import LAYOUT_STATE
        STATE.update(LAYOUT_STATE)
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type in {'IMAGE_EDITOR', 'VIEW_3D'}:
                    area.tag_redraw()
        return {'FINISHED'}


def draw_settings_button(layout, text="Settings"):
    """Button opening the settings popup (N-panel / header)."""
    layout.popover(panel=SETTINGS_PANEL_ID, text=text, icon='PREFERENCES')


classes = (
    IMAGE_PT_pixel_painter_settings,
    PixelPainterOpenSettingsOperator,
    PixelPainterColorSlidersNoneOperator,
    PixelPainterResetPenUIOperator,
)
