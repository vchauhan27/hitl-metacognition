"""
Failure 4 — Underconfidence (over-asking).

Before the control gate raises a permission ask, check whether memory already holds
an unexpired standing permission covering this exact action + recipient.
"""
import datetime
import re
from typing import Callable, Iterable


class StandingPermissionChecker:
    def has_standing_permission(self, tool_name: str, recipient_aliases: Iterable[str],
                                recall_fn: Callable[[], list]) -> bool:
        """recipient_aliases: every form the recipient may appear as (name, email, ...)."""
        aliases = [a.lower() for a in recipient_aliases if a]
        if not aliases:
            return False
        for m in recall_fn() or []:
            val = str((m.get("value") or {}).get("value", "")).lower()
            if (
                self._mentions_tool(tool_name, val)
                and any(a in val for a in aliases)
                and not self._is_expired(val)
            ):
                return True
        return False

    @staticmethod
    def _mentions_tool(tool_name: str, value: str) -> bool:
        """Match the tool by its id ('send_message') or natural language ('send message(s)')."""
        t = tool_name.lower()
        words = t.replace("_", " ")  # 'send message'
        return t in value or words in value or (words + "s") in value

    @staticmethod
    def _is_expired(value: str) -> bool:
        match = re.search(r"expires (\d{4}-\d{2}-\d{2})", value, re.IGNORECASE)
        if match:
            return datetime.date.today() > datetime.date.fromisoformat(match.group(1))
        return False