"""Pen menu metrics: the dial's rings and arcs (degrees, counter-clockwise from the
right), sizes in unscaled px, category tints, window and drag constants.
"""




BAR_SCALE = 1.5          # everything (menu, color selector, flyouts) is this much larger than the kit default
# Each element's own size (resize triangle), relative to BAR_SCALE.
SCALE_LIMITS = {'bar': (0.2, 2.0), 'color': (0.5, 2.0), 'mask': (0.4, 2.0), 'view': (0.4, 2.0),
                'settings': (0.4, 2.0), 'library': (0.4, 2.0), 'extras': (0.4, 2.0),
                'brushes': (0.4, 2.0)}
# Tool state keys holding the elements' size and position; Reset Pen UI restores these.
LAYOUT_STATE = {
    'pen_bar_scale': 1.0, 'pen_bar_pos': None,       # pos: (x0, y1) top-left in region px, None = default
    'pen_color_scale': 1.0, 'pen_color_pos': None,
    'pen_mask_scale': 0.8, 'pen_mask_pos': None,
    'pen_view_scale': 0.8, 'pen_view_pos': None,
    'pen_settings_scale': 0.8, 'pen_settings_pos': None,
    'pen_library_scale': 0.8, 'pen_library_pos': None,
    'pen_extras_scale': 0.8, 'pen_extras_pos': None,
    'pen_brushes_scale': 0.8, 'pen_brushes_pos': None,
}
# Windows besides the menu and the color selector, opened from the Windows ring
# (content: ui/pen/windows/, ui/pen/windows/settings.py, ui/pen/windows/palettes.py); shown while
# the state 'pen_<name>_panel' is set. Movable, resizable, lockable; kept per project.
TOOL_WINDOWS = ('mask', 'view', 'settings', 'library', 'extras', 'brushes')
POINTER_TYPES = {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'LEFTMOUSE', 'MIDDLEMOUSE', 'RIGHTMOUSE',
                  'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'TIMER'}
COLOR_SHAPES = (('SHEET', "Sheet"), ('SQUARE', "Square"), ('TRIANGLE', "Triangle"), ('WHEEL', "Wheel"))
COLOR_WIDTH = 220.0      # the color selector's width at scale 1, unscaled px
HANDLE_SIZE = 18.0      # resize triangle legs, unscaled px (follows the UI scale, not the element's)
WINDOW_MARGIN = 4.0      # elements keep this far from the editor borders, unscaled px
FLYOUT_GAP = 10.0        # unscaled px between the menu and flyouts / readouts
SIZE_STEP_PX = 12.0      # drag distance per size step
MAX_SIZE = 64

CHANNEL_LABELS = {'size': "Size", 'strength': "Strength", 'alpha': "Alpha", 'modifier': "Modifier"}
# Pens cannot scroll: these sliders replace the wheel controls of the strength bubble.
# Listed counter-clockwise (Modifier lowest, Strength next to the top).
SLIDERS = (('modifier', "M", (0.84, 0.95, 0.36, 1.0)),
           ('alpha', "A", (0.80, 0.83, 0.90, 1.0)),
           ('strength', "S", (0.96, 0.38, 0.47, 1.0)))
ARM_HINTS = {'EYEDROPPER_PRIMARY': "Tap canvas: pick the primary color",
             'EYEDROPPER_SECONDARY': "Tap canvas: pick the secondary color"}
# Blend flyout columns after Favorites (titles as in the Shift+W pie).
BLEND_GROUPS = (("Contrast", 'CONTRAST'), ("Math", 'MATH'), ("HSL/HSV", 'HSL'))

# Dial (unscaled px; angles in degrees counter-clockwise from +x, 90 = up).
DIAL_GAP = 2.5                 # spacing between segments of a category / rings / the Size knob
GROUP_GAP = 14.0               # spacing between categories (a divider line runs through it)
SQUARE_HALF = 172.0                  # half size of the enclosing square
HISTORY_DEPTH = 14.0                 # the gradient slider / color history band / each palette band
PALETTE_ROWS = 2                     # palette bands; color_palette.PALETTE_SIZE slots split between them
PALETTE_DEPTH = PALETTE_ROWS * HISTORY_DEPTH + (PALETTE_ROWS - 1) * DIAL_GAP
CORNER_GAP = 4.0                     # circle -> first band (divider lines end in the bands' end gaps)
# The circle fills the square except for the palette bands' depth on each side;
# the rings keep their original proportions (designed for an outer radius of 115).
DIAL_RADIUS = SQUARE_HALF - CORNER_GAP - PALETTE_DEPTH
_RING_SCALE = DIAL_RADIUS / 115.0
SIZE_RADIUS = 30.0 * _RING_SCALE
INNER_RING = (SIZE_RADIUS + DIAL_GAP, 72.5 * _RING_SCALE)
OUTER_RING = (INNER_RING[1] + DIAL_GAP, DIAL_RADIUS)
SLIDER_ARC = (15.0, 90.0)      # S / A / M, through both rings
TOOL_ARC = (90.0, 210.0)       # tools, half in each ring
# Bottom: Undo / Redo in the inner ring; outside them (outer ring) the favorite blend
# modes in rows; right of them the falloff. (Blend: the bottom-left corner.)
HISTORY_ARC = (210.0, 322.5)   # Undo / Redo (inner ring)
FAVORITES_ARC = HISTORY_ARC    # the favorite blend modes (outer ring)
FAVORITE_ROWS = 2              # the favorites split into this many rings (the outer one takes the odd one)
# Top-right corner, past the color history: Pixel / Free (spacing) and Alphalock as
# one capsule (an arc band with round ends; radii: BRUSH_MODE_RING, below).
BRUSH_MODE_ARC = (25.0, 65.0)
BLEND_GRADIENT = ((0.16, 0.16, 0.16), (0.78, 0.78, 0.78))   # the Blend button: dark gray -> light gray
INNER_FILL = (0.26, 0.26, 0.26, 0.95)   # the inner ring is a bit lighter than the outer
# Category tints (mixed lightly into the segment fills).
TINT_TOOLS = (0.35, 0.58, 1.00)
TINT_MODES = (1.00, 0.62, 0.25)
TINT_HISTORY = (0.95, 0.40, 0.45)
TINT_FALLOFF = (1.00, 0.55, 0.15)    # orange
TINT_CUSTOM = (1.00, 0.80, 0.20)     # the Custom falloff and its curve button stand out
CUSTOM_TINT_AMOUNT = 0.45
# Falloff (bottom right): the Shape field in the outer ring, reaching in through the
# outer half of the inner ring (no gap), and in the inner half Custom | Curve.
FALLOFF_FIELD_ARC = (322.5, 375.0)
FALLOFF_SPLIT = (INNER_RING[0] + INNER_RING[1]) * 0.5   # Custom / Curve end here, the field starts here
FAVORITE_FONT = 16.0                 # favorite blend modes: largest label size
FAVORITE_TEXT_PAD = 2.0              # their labels keep this far from the segment's side edges
FAVORITE_CAPS_LETTERS = 4            # names this short (or shorter) are written in capitals
# One label size for all: made so the widest of these fits (five letters / four capitals).
FAVORITE_SIZE_TEXTS = ("Dodge", "LUMI", "NORM")
FAVORITE_TEXT_COLOR = (0.80, 0.80, 0.80)   # light gray
FIELD_MARKER_RADIUS = 9.0
FIELD_EDGE_MARGIN = 0.5              # the marker's center keeps this much of its radius from the field's edges
FIELD_PREVIEW_SCALE = 1.6            # corner preview discs (a quarter shows), relative to a quadrant icon
FIELD_GUIDE_GRAY = (0.55, 0.55, 0.55)
FIELD_GUIDE_ALPHA = 0.8
FIELD_CROSS_ARM = 0.9                # the marker cross: arm length relative to FIELD_MARKER_RADIUS
FIELD_CURVE_SAMPLES = 32             # points of the falloff curve drawn in the field
FIELD_CURVE_FILL = (0.30, 0.30, 0.30)   # between the curve and the field's inner edge (field: theme surface)
# Corner buttons: between the dial's circle and its enclosing square (angles as above).
CORNER_INNER = OUTER_RING[1] + CORNER_GAP
CORNER_CHAMFER = 30.0                # the square's corners are cut: room for the lock / X / resize triangle
# Top left: the gradient slider (tertiary color) along the circle; then secondary's
# Picker | secondary | Swap + tertiary bubble | primary | primary's Picker (the colors
# toward the corner; all with round corners). Swap sits by the circle, the tertiary
# bubble behind it toward the square's corner (not cut: the menu's lock is bottom left).
COLORS_ARC = (90.0, 180.0)
HISTORY_BAND_ARC = SLIDER_ARC        # top right: the color history, outside S / A / M
GRADIENT_MARKER = 3.0                # the gradient slider's marker: half width, unscaled px
COLORS_WEIGHTS = (2.0, 1.6, 1.4, 1.6, 2.0)
SWAP_DEPTH = 27.0                    # Swap's radial depth; the Mix bubble sits past it
COLOR_ROUND = 6.0                    # corner radius of the color section's buttons
MIX_BUBBLE_MARGIN = 1.5              # the tertiary bubble keeps this far from its slot's edges
COLOR_WHEEL_ARC = (270.0, 350.0)     # bottom right: the palette (2 bands along the circle)
# Palettes: a capsule in the gap right of the circle, centered on the right (as deep
# as the palette bands; Color / Library: the Windows ring).
PALETTE_BUTTON_ARC = (350.0, 370.0)
COLOR_CORNER_INNER = CORNER_INNER + HISTORY_DEPTH + DIAL_GAP
BRUSH_MODE_RING = (COLOR_CORNER_INNER, COLOR_CORNER_INNER + 26.0)
# Bottom left, a capsule along the circle: Windows, Save, Grid, Blend (Blend ends at the
# bottom, where the palette band starts; the band stays inside the square there).
BOTTOM_LEFT_INNER = CORNER_INNER
BOTTOM_LEFT_RING = (BOTTOM_LEFT_INNER, SQUARE_HALF - 2.0)
BOTTOM_LEFT_ARC = (192.0, 270.0)
_BL_SHARE = (BOTTOM_LEFT_ARC[1] - BOTTOM_LEFT_ARC[0]) / 4.0
WINDOWS_ARC = (BOTTOM_LEFT_ARC[0], BOTTOM_LEFT_ARC[0] + _BL_SHARE)   # Windows' share
# The Windows popup: a ring over the dial's inner ring (around the Size knob, hiding the
# inner ring while open). Entries counter-clockwise from WINDOW_RING_START, each the same
# angle; their order roughly follows where the old corner buttons sat.
WINDOW_RING = INNER_RING
WINDOW_RING_COVER = OUTER_RING[1]    # the backdrop reaches this far: hides both rings (the tools too)
WINDOW_RING_START = 165.0            # Settings at the bottom left, by the Windows button
WINDOW_RING_BACKDROP = (0.16, 0.16, 0.16, 0.97)
# Its outer ring (over the dial's outer ring): further windows, WINDOW_OUTER_STEP degrees
# each from WINDOW_OUTER_START -- Brushes right outside Extras.
WINDOW_OUTER_RING = OUTER_RING
WINDOW_OUTER_START = 105.0
WINDOW_OUTER_STEP = 60.0
TINT_WINDOWS = (0.62, 0.70, 0.95)
GRID_DRAG_PX = 120.0                 # unscaled px of vertical drag for 0 -> 100 % grid opacity
TINT_GRID = (0.55, 0.78, 0.95)
TINT_SAVE = (0.45, 0.80, 0.45)
TINT_MASK = (0.78, 0.52, 1.00)
TINT_VIEW = (0.40, 0.85, 0.95)
TINT_EXTRAS = (0.35, 0.95, 0.75)
# The Extras window's categories: tools in the pen menu's tool blue, then one tint per kind of setting.
TINT_EXTRAS_TOOLS = TINT_TOOLS        # Fill / Edges / AO
TINT_EXTRAS_SOURCE = TINT_MASK        # UV Islands / Mesh Parts (what the mask chooses too)
TINT_EXTRAS_EDGES = TINT_MODES        # which model edges: Angle / All / Marked
TINT_EXTRAS_OPTIONS = TINT_CUSTOM     # placement, Fade, Curve
TINT_EXTRAS_VALUES = TINT_EXTRAS      # the sliders
TINT_EXTRAS_ALL = (0.95, 0.30, 0.30)  # All (every island / part at once): red, like the Mask window's Clear
TINT_BRUSHES = (0.95, 0.55, 0.30)   # the Brushes window (special brushes): rust orange
MASK_PICK_HINT = "Tap islands / parts to toggle them (Edit again: done)"
DRAG_THRESHOLD = 6.0                 # unscaled px a color must be dragged before it counts as a drag (else: tap)
CURVE_EDITOR_SIZE = (220.0, 150.0)
BLEND_ENTRY_SIZE = (84.0, 26.0)      # Blend flyout: a mode ...
BLEND_STAR_SIZE = (24.0, 26.0)       # ... and its favorite star on the right
BLEND_STAR_GAP = 2.0
STAR_COLOR = (1.00, 0.80, 0.25)      # a favorite's star (gold)
CURVE_MODES = (('MOVE', "Move"), ('ADD', "Add"), ('DRAW', "Draw"))
FALLOFF_PREVIEW_SIZE = 56.0          # the falloff disc beside the readout while the field is dragged
CURVE_PRESET_SIZE = (52.0, 40.0)     # the curve flyout's preset buttons (icon + label)
CURVE_PRESET_COLUMNS = 4
CURVE_HINTS = {'MOVE': "Drag anchors; drag out of the box: remove",
               'ADD': "Tap to add an anchor (keep the pen down to place it)",
               'DRAW': "Draw the falloff: center left, edge right"}

CORNER_RADIUS = 6.0     # lock / X in the elements' top corners (drawn); taps hit a larger area
CORNER_HIT = 9.0
CORNER_INSET = 4.0
PANEL_PADDING = 4.0
SHAPE_PAD = 5.0          # shaped window backgrounds reach this far past the parts, unscaled px
CORNER_CAP = 0.6       # a window's rounded corners: at most this share of the resize triangle's legs
# The menu's default spot keeps this far from the editor edge (unscaled px; the panel padding is inside it).
EDGE_GAP = 0.3 * 2.0 * 19.0


def clamp_scale(name, scale):
    lo, hi = SCALE_LIMITS[name]
    return max(lo, min(hi, scale))
