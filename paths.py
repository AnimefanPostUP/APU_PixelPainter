"""Files and folders of the add-on, in one place (modules never count ``dirname`` levels)."""

import os

ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
TEXTURES_DIR = os.path.join(ADDON_DIR, "textures")
NATIVE_RUNTIMES_DIR = os.path.join(ADDON_DIR, "native", "runtimes")
PALETTE_LIBRARY_FILE = os.path.join(ADDON_DIR, "palettes.json")
SETTINGS_FILE = os.path.join(ADDON_DIR, "settings.json")
