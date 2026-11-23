"""Pixel Painter's icon set (tool and falloff icons from ``textures/``)."""

import os

from .kit.icons import IconSet
from ..tools import falloff
from ..tools.catalog import TOOLS


TEXTURES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "textures")

ICONS = IconSet(TEXTURES_DIR, {**TOOLS.icon_files(), **falloff.icon_files()})


def register():
    ICONS.register()


def unregister():
    ICONS.unregister()
