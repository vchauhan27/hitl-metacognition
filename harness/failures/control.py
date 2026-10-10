"""
Failure 2 — Control (stop-and-ask is unavoidable for irreversible actions).

Permission gate + approval scoping. Approvals are stored as (tool_name, scope_key)
tuples, never as bare tool names, so "yes for Priya" can never cover Sam (Plan Part 3).
"""
from typing import Callable, Optional

from harness.core import MonitorSignal
from harness.failures.underconfidence import StandingPermissionChecker

# Tools that leave the system and cannot be easily undone
PERMISSION_TOOLS = ["send_message", "move_event"]

class PermissionGate:
    def __init__(self, contacts: dict | None = None, permission_tools: list | None = None):
        self.contacts = contacts or {}
        self.permission_tools = permission_tools or PERMISSION_TOOLS
        self.standing_checker = StandingPermissionChecker()

    # ---- Scoping -------------------------------------------------------------
    
    def canonical_recipient(self, raw: str) -> str:
        """Maps various ways of referring to a contact (email, first name) to their full lowercase name."""
        raw_l = (raw or "").strip().lower()
        if not raw_l:
            return ""
            
        # 1. Exact match for full name or email
        for name, info in self.contacts.items():
            email = info.split()[0].lower()
            if raw_l == name.lower() or raw_l == email:
                return name.lower()
                
        # 2. Partial match (e.g., just "Priya" instead of "Priya Nair")
        partial_matches = [n for n in self.contacts if raw_l in n.lower()]
        if len(partial_matches) == 1:
            return partial_matches[0].lower()
            
        # 3. Fallback to whatever they typed
        return raw_l

    def recipient_aliases(self, canonical: str) -> list[str]:
        """Returns both the full name and the email for a given contact."""
        for name, info in self.contacts.items():
            if name.lower() == canonical:
                return [name.lower(), info.split()[0].lower()]
        return [canonical] if canonical else []

    def scope_key(self, tool_name: str, tool_args: dict) -> tuple[str, str]:
        """Defines the 'scope' of an action so a yes isn't treated as a blank check."""
        if tool_name == "send_message":
            recipient = str(tool_args.get("to") or tool_args.get("contact") or "")
            return (tool_name, self.canonical_recipient(recipient))
            
        if tool_name in ("create_event", "move_event"):
            time_slot = f"{tool_args.get('day', '')} {tool_args.get('start', '')}".strip()
            return (tool_name, time_slot)
            
        return (tool_name, "")

    # ---- Gate ----------------------------------------------------------------
    
    def check_permission(self, tool_name: str, tool_args: dict, recall_fn: Optional[Callable[[], list]] = None) -> Optional[MonitorSignal]:
        """Blocks gated tools unless the user has already granted standing permission."""
        if tool_name not in self.permission_tools:
            return None
            
        _, scope = self.scope_key(tool_name, tool_args)
        aliases = self.recipient_aliases(scope)
        
        # Check long-term memory for standing permission to avoid over-asking (Underconfidence fix)
        if recall_fn and self.standing_checker.has_standing_permission(tool_name, aliases, recall_fn):
            print(f"\n[HARNESS: Underconfidence] Standing permission found for {tool_name} -> {scope}; not asking.")
            return None
            
        # If no standing permission exists, raise the block
        return MonitorSignal(
            gap_type="permission",
            severity="high",
            message=f"Tool '{tool_name}' to '{scope or 'unknown'}' requires explicit permission.",
            requires_ask=True,
            failure_type="control",
        )