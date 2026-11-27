"""Tool registry: ordered collection of tool instances plus derived data."""

from typing import Dict, Iterator, List, Optional

from .base import ToolBase


SETTING_CHANNELS = ('size', 'modifier', 'strength', 'alpha')


class ToolRegistry:
    """Ordered tool collection.

    Order matters: it is the order of the mode enum, the tool pie and the
    Shift+1..9 shortcuts.
    """

    def __init__(self, tools=(), default_id: Optional[str] = None):
        self._tools: Dict[str, ToolBase] = {}
        for tool in tools:
            self.register(tool)
        self.default_id = default_id or (next(iter(self._tools)) if self._tools else None)

    def register(self, tool: ToolBase) -> ToolBase:
        if tool.tool_id in self._tools:
            raise ValueError(f"Tool id {tool.tool_id!r} registered twice")
        self._tools[tool.tool_id] = tool
        return tool

    # ---- lookup --------------------------------------------------------------

    def __iter__(self) -> Iterator[ToolBase]:
        return iter(self._tools.values())

    def __len__(self):
        return len(self._tools)

    def __contains__(self, tool_id):
        return tool_id in self._tools

    def ids(self) -> List[str]:
        return list(self._tools)

    def get(self, tool_id: Optional[str]) -> ToolBase:
        """Tool for ``tool_id``; falls back to the default tool."""
        tool = self._tools.get(tool_id) if tool_id else None
        return tool if tool is not None else self._tools[self.default_id]

    def index_of(self, tool_id) -> int:
        return self.ids().index(tool_id)

    def in_group(self, group: str) -> List[ToolBase]:
        """The tools of ``group`` ('MAIN' / 'SPECIAL', ``ToolBase.group``) in order."""
        return [t for t in self if getattr(t, 'group', 'MAIN') == group]

    def by_shortcut_index(self, index: int) -> Optional[ToolBase]:
        """Tool for a 0-based number-key index (Shift+1 -> 0)."""
        ids = self.ids()
        return self._tools[ids[index]] if 0 <= index < len(ids) else None

    # ---- derived data ----------------------------------------------------------

    def enum_items(self):
        """Items for a ``bpy.props.EnumProperty``."""
        return [(t.tool_id, t.label, t.description) for t in self]

    def icon_files(self):
        return {t.tool_id: t.icon for t in self if t.icon}

    def uses_global_default(self, tool_id: str, channel: str) -> bool:
        return bool(getattr(self.get(tool_id).defaults, channel))
