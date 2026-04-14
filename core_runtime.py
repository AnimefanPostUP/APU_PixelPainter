"""Core runtime objects for tool tracking and interruptible process handling."""

from dataclasses import dataclass
from typing import Dict, Optional, Set


@dataclass
class ActiveProcess:
    """Represent an interruptible tool process tracked by the core."""

    process_id: str
    owner_tool: str
    interrupt_keys: Set[str]

    def can_interrupt(self, key: str) -> bool:
        """Return True when `key` is allowed to interrupt this process."""
        return key in self.interrupt_keys


class PixelPainterCoreRuntime:
    """Track current/previous tool and active tool-owned processes."""

    def __init__(self):
        self.current_tool_id: Optional[str] = None
        self.previous_tool_id: Optional[str] = None
        self._active_processes: Dict[str, ActiveProcess] = {}

    def set_current_tool(self, tool_id: str) -> None:
        """Update the current tool and remember the previous one."""
        if not tool_id:
            return
        if self.current_tool_id != tool_id:
            self.previous_tool_id = self.current_tool_id
            self.current_tool_id = tool_id

    def register_process(self, process_id: str, owner_tool: str, interrupt_keys: Set[str]) -> None:
        """Register an active process that can be interrupted by specific keys."""
        self._active_processes[process_id] = ActiveProcess(
            process_id=process_id,
            owner_tool=owner_tool,
            interrupt_keys=set(interrupt_keys),
        )

    def clear_process(self, process_id: str) -> None:
        """Remove one active process from the registry."""
        self._active_processes.pop(process_id, None)

    def clear_all_processes(self) -> None:
        """Remove all tracked processes."""
        self._active_processes.clear()

    def interrupt_by_key(self, key: str) -> bool:
        """Interrupt all processes that accept `key`; return True if any stopped."""
        interrupted = False
        for process_id, process in list(self._active_processes.items()):
            if process.can_interrupt(key):
                self._active_processes.pop(process_id, None)
                interrupted = True
        return interrupted
