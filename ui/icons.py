"""Pixel Painter's icon set (tool icons from ``textures/``, generated falloff icons)."""

import os

from .kit.icons import IconSet
from . import falloff_icons
from ..tools.catalog import TOOLS


TEXTURES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "textures")

ICONS = IconSet(TEXTURES_DIR, TOOLS.icon_files(), generators=falloff_icons.generators())


def register():
    ICONS.register()


def unregister():
    ICONS.unregister()
