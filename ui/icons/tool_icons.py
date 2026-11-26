"""Pixel Painter's icon set (tool icons from ``textures/``, generated falloff icons)."""


from ..kit.icons import IconSet
from . import falloff_icons
from ...paths import TEXTURES_DIR
from ...tools.catalog import TOOLS



ICONS = IconSet(TEXTURES_DIR, TOOLS.icon_files(), generators=falloff_icons.generators())


def register():
    ICONS.register()


def unregister():
    ICONS.unregister()
