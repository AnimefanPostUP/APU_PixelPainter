"""Shared runtime state ("blackboard") read by tools and canvas overlays.

The draw handler must NOT hold a reference to the operator instance because
Blender frees the instance while the handler may still be registered, so
everything the overlays draw lives in this module-level dict.

There is no central key table: whoever owns a key declares it with
:func:`declare`. Tools do so through their ``state_defaults`` /
``persistent_state`` class attributes (see :class:`core.framework.ToolFrame`),
which the :class:`core.framework.ToolManager` declares on registration;
non-tool modules (core session, overlays, draw handlers) call :func:`declare`
at import time.
"""

from ..utils.settings_service import PixelPainterSettingsService


STATE = {}
SETTINGS = PixelPainterSettingsService()

_DEFAULTS = {}         # key -> default, filled by declare()
_PERSISTENT = set()    # keys that survive the end of a modal session


def declare(defaults, persistent=()):
    """Register state keys owned by the caller.

    ``defaults`` maps key -> default value (use immutable defaults; mutable
    caches are created by the owner when needed). ``persistent`` names keys
    that :func:`reset_session` keeps (e.g. GPU handles that are cleaned up
    explicitly). Several owners may declare the same key, but only with the
    same default.
    """
    for key, value in defaults.items():
        if key in _DEFAULTS and _DEFAULTS[key] != value:
            raise ValueError(
                f"State key {key!r} declared with conflicting defaults: "
                f"{_DEFAULTS[key]!r} vs {value!r}")
        _DEFAULTS[key] = value
        STATE.setdefault(key, value)
    unknown = set(persistent) - _DEFAULTS.keys()
    if unknown:
        raise ValueError(f"Persistent state keys without a default: {sorted(unknown)}")
    _PERSISTENT.update(persistent)


def reset_session():
    """Reset all declared per-session keys to their defaults."""
    for key, value in _DEFAULTS.items():
        if key not in _PERSISTENT:
            STATE[key] = value
