"""Palette library: palettes shared by all projects, in ``palettes.json`` next to
``settings.json`` in the add-on folder. Read when the library window opens (so
edits from other Blender instances show up), written on every change.
"""

import os
import traceback

from ..tools import color_palette


def library_path():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'palettes.json')


def load():
    path = library_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            return color_palette.decode_library(handle.read())
    except Exception:
        traceback.print_exc()
        return []


def save(palettes):
    path = library_path()
    try:
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as handle:
            handle.write(color_palette.encode_library(palettes))
        os.replace(tmp, path)    # never leave a half-written file
        return True
    except Exception:
        traceback.print_exc()
        return False
