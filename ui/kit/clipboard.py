"""System clipboard text for the kit's input fields (Blender's window manager
clipboard; outside Blender -- tests -- a process-local stand-in)."""

_fallback = [""]


def get_text():
    try:
        import bpy
        return str(bpy.context.window_manager.clipboard or "")
    except Exception:
        return _fallback[0]


def set_text(text):
    text = str(text)
    try:
        import bpy
        bpy.context.window_manager.clipboard = text
        return
    except Exception:
        pass
    _fallback[0] = text
