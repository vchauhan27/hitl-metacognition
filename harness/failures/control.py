"""
Failure 2 — Control (stop-and-ask is unavoidable for irreversible actions).

Permission gate + approval scoping. Approvals are stored as (tool_name, scope_key)
tuples, never as bare tool names, so "yes for Priya" can never cover Sam (Plan Part 3).
"""
from typing import Callable, Optional

from harness.failures.signals import MonitorSignal
from harness.failures.underconfidence import StandingPermissionChecker

# Leaves-the-system actions. create_event removed to stop over-asking on fully specified events.
PERMISSION_TOOLS = ["send_message", "move_event"]


class PermissionGate:
    def __init__(self, contacts: dict | None = None, permission_tools: list | None = None):
        self.contacts = contacts or {}
        self.permission_tools = permission_tools or PERMISSION_TOOLS
        self.standing_checker = StandingPermissionChecker()

    # ---- scoping -------------------------------------------------------------
    def canonical_recipient(self, raw: str) -> str:
        """Map 'Priya', 'priya.nair@example.com', 'Priya Nair' -> 'priya nair' when unambiguous."""
        raw_l = (raw or "").strip().lower()
        if not raw_l:
            return ""
        for name, info in self.contacts.items():
            email = info.split()[0].lower()
            if raw_l in (name.lower(), email):
                return name.lower()
        partial = [n for n in self.contacts if raw_l in n.lower()]
        return partial[0].lower() if len(partial) == 1 else raw_l

    def recipient_aliases(self, canonical: str) -> list[str]:
        for name, info in self.contacts.items():
            if name.lower() == canonical:
                return [name.lower(), info.split()[0].lower()]
        return [canonical] if canonical else []

    def scope_key(self, tool_name: str, tool_args: dict) -> tuple[str, str]:
        if tool_name == "send_message":
            return (tool_name, self.canonical_recipient(str(tool_args.get("to") or tool_args.get("contact") or "")))
        if tool_name in ("create_event", "move_event"):
            return (tool_name, f"{tool_args.get('day', '')} {tool_args.get('start', '')}".strip())
        return (tool_name, "")

    # ---- gate ----------------------------------------------------------------
    def check_permission(self, tool_name: str, tool_args: dict,
                         recall_fn: Optional[Callable[[], list]] = None) -> Optional[MonitorSignal]:
        if tool_name not in self.permission_tools:
            return None
        _, scope = self.scope_key(tool_name, tool_args)
        if recall_fn and self.standing_checker.has_standing_permission(
            tool_name, self.recipient_aliases(scope), recall_fn
        ):
            print(f"\n[HARNESS: Underconfidence] Standing permission found for {tool_name} -> {scope}; not asking.")
            return None
        return MonitorSignal(
            gap_type="permission",
            severity="high",
            message=f"Tool '{tool_name}' to '{scope or 'unknown'}' requires explicit permission.",
            requires_ask=True,
            failure_type="control",
        )
