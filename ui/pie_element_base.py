class PieElementBase:
    """
    Base class for pie menu elements with animation and event hooks.
    """
    STATUS_RUNNING = 'RUNNING'
    STATUS_FINISH = 'FINISH'

    def __init__(self):
        self.anim_state = 0.0
        self._highlighted = False
        self._selected = False

    def on_highlight(self):
        """Called when the element is highlighted (hovered)."""
        self._highlighted = True
        return self.STATUS_RUNNING

    def on_unhighlight(self):
        """Called when the element is no longer highlighted."""
        self._highlighted = False
        return self.STATUS_RUNNING

    def on_select(self):
        """Called when the element is selected."""
        self._selected = True
        return self.STATUS_FINISH

    def on_deselect(self):
        """Called when the element is deselected."""
        self._selected = False
        return self.STATUS_RUNNING

    @property
    def curve_anchor(self):
        """Return the anchor point for curve drawing (override in subclass)."""
        return None

    def update_animation(self, dt):
        """Update animation state (override in subclass if needed)."""
        pass
