"""Blender wiring for UI-kit overlays: draw handler, timer and modal operator.

Subclass :class:`OverlayOperator` together with ``bpy.types.Operator`` and
implement :meth:`OverlayOperator.build_overlay`::

    class MY_OT_pie(OverlayOperator, bpy.types.Operator):
        bl_idname = "image.my_pie"
        bl_label = "My Pie"

        def build_overlay(self, context, event):
            menu = RadialMenu()
            menu.add_item(BubbleButton("A", on_click=lambda: print("A")))
            return menu

The draw callback never references the operator instance (Blender may free
it while a handler is registered); it reads the module-level session.
Only one overlay session is active at a time; opening another one replaces it.
"""

import traceback

import bpy

from .events import CANCELLED, FINISHED, PASS_THROUGH, UIEvent
from .overlay import Overlay
from .theme import Theme


class _Session:
    __slots__ = ('overlay', 'area', 'space_type', 'draw_handle', 'timer', 'token',
                 'start_cursor', 'warped', 'draw_failed')

    def __init__(self, overlay, area, space_type, token, start_cursor):
        self.overlay = overlay
        self.area = area
        self.space_type = space_type
        self.token = token
        self.start_cursor = start_cursor
        self.draw_handle = None
        self.timer = None
        self.warped = False
        self.draw_failed = False


_session = None
_next_token = 0


def active_overlay():
    """The currently shown overlay, or None."""
    return _session.overlay if _session is not None else None


def _draw_callback():
    session = _session
    if session is None:
        return
    try:
        if bpy.context.area != session.area:
            return  # only draw in the editor that opened the overlay
    except Exception:
        pass
    try:
        session.overlay.draw()
    except Exception:
        if not session.draw_failed:  # report once, not every frame
            session.draw_failed = True
            traceback.print_exc()


def force_cleanup(window_manager=None):
    """Tear down the active overlay session (safe to call any time, e.g. on reload)."""
    global _session
    session, _session = _session, None
    if session is None:
        return
    if session.draw_handle is not None:
        try:
            session.space_type.draw_handler_remove(session.draw_handle, 'WINDOW')
        except Exception:
            pass
    if session.timer is not None:
        wm = window_manager
        if wm is None:
            try:
                wm = bpy.context.window_manager
            except Exception:
                wm = None
        if wm is not None:
            try:
                wm.event_timer_remove(session.timer)
            except Exception:
                pass
    try:
        session.area.tag_redraw()
    except Exception:
        pass


def _operator_from_idname(idname):
    category, name = idname.split('.', 1)
    return getattr(getattr(bpy.ops, category), name)


class OverlayOperator:
    """Mixin for modal operators that display a widget overlay."""

    overlay_area_type = 'IMAGE_EDITOR'
    overlay_space_type = 'SpaceImageEditor'
    overlay_timer_interval = 1.0 / 60.0
    overlay_fit_region = True     # shift the overlay to stay inside the editor
    overlay_warp_back = True      # after confirming, return the cursor to its start

    # ---- hooks for subclasses ----------------------------------------------

    def build_overlay(self, context, event):
        """Return the root widget to display."""
        raise NotImplementedError

    def make_theme(self, context):
        return Theme.for_context(context)

    def pass_through(self, context, event):
        """Return True to close the overlay and hand ``event`` to Blender."""
        return False

    # ---- operator API ------------------------------------------------------

    def execute(self, context):
        # Button / menu clicks call execute() without an event. Re-invoke from
        # a timer, restoring the original window/area (timers have no area).
        window, area = context.window, context.area
        region = next((r for r in area.regions if r.type == 'WINDOW'), None) if area else None
        props = {
            p.identifier: getattr(self, p.identifier)
            for p in self.properties.bl_rna.properties
            if p.identifier != 'rna_type'
        }
        op = _operator_from_idname(self.bl_idname)

        def _reinvoke():
            try:
                with bpy.context.temp_override(window=window, area=area, region=region):
                    op('INVOKE_DEFAULT', **props)
            except Exception:
                traceback.print_exc()
            return None

        bpy.app.timers.register(_reinvoke, first_interval=0.01)
        return {'FINISHED'}

    def invoke(self, context, event):
        global _session, _next_token
        area = context.area
        if area is None or area.type != self.overlay_area_type:
            return {'CANCELLED'}
        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
        if region is None:
            return {'CANCELLED'}

        force_cleanup(context.window_manager)

        # Work in WINDOW-region coordinates regardless of which region invoked us.
        self._region_xy = (region.x, region.y)
        origin = (event.mouse_x - region.x, event.mouse_y - region.y)
        root = self.build_overlay(context, event)
        if root is None:
            return {'CANCELLED'}
        overlay = Overlay(
            root,
            theme=self.make_theme(context),
            origin=origin,
            trigger_key=event.type if event.value == 'PRESS' else None,
        )

        _next_token += 1
        self._token = _next_token
        space_type = getattr(bpy.types, self.overlay_space_type)
        session = _Session(overlay, area, space_type, self._token, (event.mouse_x, event.mouse_y))

        if self.overlay_fit_region:
            dx, dy = overlay.fit_inside(region.width, region.height)
            if dx or dy:
                try:
                    context.window.cursor_warp(int(event.mouse_x + dx), int(event.mouse_y + dy))
                    session.warped = True
                except Exception:
                    pass

        session.draw_handle = space_type.draw_handler_add(_draw_callback, (), 'WINDOW', 'POST_PIXEL')
        session.timer = context.window_manager.event_timer_add(self.overlay_timer_interval, window=context.window)
        _session = session

        context.window_manager.modal_handler_add(self)
        area.tag_redraw()
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        session = _session
        if session is None or session.token != getattr(self, '_token', None):
            return {'CANCELLED'}  # replaced by another overlay or cleaned up
        if context.area is None or context.area.type != self.overlay_area_type:
            self._finish(context, warp=False)
            return {'CANCELLED'}

        if self.pass_through(context, event):
            self._finish(context, warp=False)
            return {'PASS_THROUGH'}

        rx, ry = self._region_xy
        ui_event = UIEvent(
            type=event.type, value=event.value,
            x=event.mouse_x - rx, y=event.mouse_y - ry,
            shift=bool(event.shift), ctrl=bool(event.ctrl), alt=bool(event.alt),
        )
        try:
            result = session.overlay.handle(ui_event)
        except Exception:
            traceback.print_exc()
            self._finish(context, warp=False)
            return {'CANCELLED'}

        session.area.tag_redraw()
        if result == FINISHED:
            self._finish(context, warp=self.overlay_warp_back)
            return {'FINISHED'}
        if result == CANCELLED:
            self._finish(context, warp=session.warped)
            return {'CANCELLED'}
        if result == PASS_THROUGH:
            return {'PASS_THROUGH'}
        return {'RUNNING_MODAL'}

    def _finish(self, context, warp):
        session = _session
        if session is not None and warp and session.start_cursor is not None:
            try:
                context.window.cursor_warp(int(session.start_cursor[0]), int(session.start_cursor[1]))
            except Exception:
                pass
        force_cleanup(context.window_manager)
