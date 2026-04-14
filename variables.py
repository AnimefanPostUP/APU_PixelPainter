"""Typed variable metadata and global/tool sync management for Pixel Painter."""

from dataclasses import dataclass
from typing import Any, Dict, Optional, Type


@dataclass
class ToolVariable:
    """Describe one tool setting and hold both global and local values.

    `sync_with_global=True` means the tool reads/writes the global value.
    """

    name: str
    value_type: Type
    value: Any
    description: str = ""
    sync_with_global: bool = True
    local_value: Any = None

    def __post_init__(self):
        if self.local_value is None:
            self.local_value = self.value


class ToolVariableStore:
    """Store global variables and per-tool variable descriptors.

    The store is intentionally Blender-agnostic so tools can be unit tested
    with simple Python values.
    """

    def __init__(self):
        self._global_variables: Dict[str, ToolVariable] = {}
        self._tool_variables: Dict[str, Dict[str, ToolVariable]] = {}

    def register_global(self, name: str, value_type: Type, default: Any, description: str = "") -> None:
        """Register a new global variable descriptor with a default value."""
        self._global_variables[name] = ToolVariable(
            name=name,
            value_type=value_type,
            value=default,
            description=description,
            sync_with_global=True,
            local_value=default,
        )

    def register_tool_variable(self, tool_id: str, name: str, value_type: Type, default: Any,
                               description: str = "", sync_with_global: bool = True) -> None:
        """Register one variable for a specific tool."""
        if tool_id not in self._tool_variables:
            self._tool_variables[tool_id] = {}
        self._tool_variables[tool_id][name] = ToolVariable(
            name=name,
            value_type=value_type,
            value=default,
            description=description,
            sync_with_global=sync_with_global,
            local_value=default,
        )

    def set_global(self, name: str, value: Any) -> None:
        """Update a global variable value if the descriptor exists."""
        var = self._global_variables.get(name)
        if var is None:
            return
        var.value = value

    def set_tool_value(self, tool_id: str, name: str, value: Any) -> None:
        """Update one tool variable, respecting sync-to-global when enabled."""
        var = self._tool_variables.get(tool_id, {}).get(name)
        if var is None:
            return
        if var.sync_with_global and name in self._global_variables:
            self._global_variables[name].value = value
            var.value = value
        else:
            var.local_value = value

    def set_sync_to_global(self, tool_id: str, name: str, sync_with_global: bool) -> None:
        """Toggle temporary sync behavior for one tool variable."""
        var = self._tool_variables.get(tool_id, {}).get(name)
        if var is None:
            return
        var.sync_with_global = bool(sync_with_global)

    def get_tool_value(self, tool_id: str, name: str, fallback: Optional[Any] = None) -> Any:
        """Read one effective tool variable value (global when synced, else local)."""
        var = self._tool_variables.get(tool_id, {}).get(name)
        if var is None:
            return fallback
        if var.sync_with_global and name in self._global_variables:
            global_var = self._global_variables[name]
            var.value = global_var.value
            return global_var.value
        return var.local_value

    def describe(self, tool_id: str, name: str) -> Optional[ToolVariable]:
        """Return the variable descriptor for UI/inspection use."""
        return self._tool_variables.get(tool_id, {}).get(name)


def build_default_variable_store() -> ToolVariableStore:
    """Build the default variable registry used by the core runtime."""
    store = ToolVariableStore()
    store.register_global('size', int, 1, 'Brush radius in image pixels')
    store.register_global('modifier', float, 0.5, 'Generic modifier value')
    store.register_global('falloff', str, 'CONSTANT', 'Circle/Spray falloff profile')

    for tool_id in ('SQUARE', 'LINE', 'CIRCLE', 'SPRAY', 'SMOOTH', 'SMEAR'):
        store.register_tool_variable(tool_id, 'size', int, 1, 'Tool-local brush radius', sync_with_global=True)
        store.register_tool_variable(tool_id, 'modifier', float, 0.5, 'Tool-local modifier', sync_with_global=True)
        store.register_tool_variable(tool_id, 'falloff', str, 'CONSTANT', 'Tool-local falloff', sync_with_global=True)

    return store
