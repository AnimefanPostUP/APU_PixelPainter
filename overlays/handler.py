"""The session's draw handlers (POST_PIXEL, and POST_VIEW in the 3D Viewport): added
when a session starts, removed explicitly (they survive the session end).
"""



from ..core.state import declare as declare_state


# Draw handler handles: survive a session end, removed explicitly.
declare_state({
    'draw_handler':      None,  # POST_PIXEL handler
    'draw_handler_view': None,  # POST_VIEW handler (3D Viewport surface outline)
    'draw_space':        None,
}, persistent=('draw_handler', 'draw_handler_view', 'draw_space'))



# ---------------------------------------------------------------------------
# Draw handler management
# ---------------------------------------------------------------------------

def register_draw_handler(state, space, context, callback, view_callback=None):
    """Register a POST_PIXEL draw callback (and optionally a POST_VIEW one) in *state*."""
    state['draw_handler'] = space.draw_handler_add(callback, (context,), 'WINDOW', 'POST_PIXEL')
    state['draw_handler_view'] = (
        space.draw_handler_add(view_callback, (context,), 'WINDOW', 'POST_VIEW')
        if view_callback is not None else None)
    state['draw_space']   = space


def remove_draw_handler(state):
    """Remove the registered draw handler stored in *state*, if any."""
    space   = state.get('draw_space')
    for key in ('draw_handler', 'draw_handler_view'):
        handler = state.get(key)
        if handler is not None and space is not None:
            try:
                space.draw_handler_remove(handler, 'WINDOW')
            except Exception:
                pass
        state[key] = None
    state['draw_space']   = None
