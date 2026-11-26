"""Blender-independent event representation used by the UI kit."""

from dataclasses import dataclass


PRESS = 'PRESS'
RELEASE = 'RELEASE'

# Results returned by Overlay.handle(); map 1:1 onto Blender modal return sets.
RUNNING = 'RUNNING_MODAL'
FINISHED = 'FINISHED'
CANCELLED = 'CANCELLED'
PASS_THROUGH = 'PASS_THROUGH'

NUMBER_KEYS = (
    'ONE', 'TWO', 'THREE', 'FOUR', 'FIVE', 'SIX', 'SEVEN', 'EIGHT', 'NINE',
)
NUMPAD_KEYS = (
    'NUMPAD_1', 'NUMPAD_2', 'NUMPAD_3', 'NUMPAD_4', 'NUMPAD_5',
    'NUMPAD_6', 'NUMPAD_7', 'NUMPAD_8', 'NUMPAD_9',
)


def number_key_index(event_type, include_numpad=True):
    """0-based index for ``ONE``..``NINE`` (and ``NUMPAD_1``..``NUMPAD_9``), else None."""
    if event_type in NUMBER_KEYS:
        return NUMBER_KEYS.index(event_type)
    if include_numpad and event_type in NUMPAD_KEYS:
        return NUMPAD_KEYS.index(event_type)
    return None


@dataclass
class UIEvent:
    """Snapshot of the fields of a ``bpy.types.Event`` that widgets care about.

    ``x``/``y`` are region coordinates.
    """

    type: str
    value: str = 'NOTHING'
    x: float = 0.0
    y: float = 0.0
    shift: bool = False
    ctrl: bool = False
    alt: bool = False
    unicode: str = ''      # the typed character of a key press ('' for others)

    @classmethod
    def from_blender(cls, event, offset=(0.0, 0.0)):
        return cls(
            type=event.type,
            value=event.value,
            x=event.mouse_region_x + offset[0],
            y=event.mouse_region_y + offset[1],
            shift=bool(event.shift),
            ctrl=bool(event.ctrl),
            alt=bool(event.alt),
            unicode=getattr(event, 'unicode', '') or '',
        )

    @property
    def is_press(self):
        return self.value == PRESS

    @property
    def is_release(self):
        return self.value == RELEASE
