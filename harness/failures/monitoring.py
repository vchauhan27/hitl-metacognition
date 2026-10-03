"""
Failure 1 — Monitoring (the agent does not notice what it does not know).

Gap detection: stale memory, ambiguous contact (from lookup_contact RESULTS),
and the Jev assumption sensor for invented arguments.
"""
import datetime
import logging
import os
from typing import Optional

import requests

from config import get_jev_model_name, MEMORY_AGE_LIMIT_DAYS
from harness.failures.signals import MonitorSignal

log = logging.getLogger("monitoring")

JEV_ASSUMPTION_THRESHOLD = 0.75   # Catch missing slots scoring in the low 0.80s
JEV_URL = "https://openrouter.ai/api/alpha/decisions"


class MonitoringChecks:
    """Deterministic gap detectors (no LLM)."""

    def check_stale_memory(self, memory_timestamp_iso: str,
                           max_days_old: int = MEMORY_AGE_LIMIT_DAYS) -> Optional[MonitorSignal]:
        if not memory_timestamp_iso:
            return None
        try:
            mem_date = datetime.datetime.fromisoformat(memory_timestamp_iso)
            now = datetime.datetime.now(datetime.timezone.utc)
            if mem_date.tzinfo is None:
                now = datetime.datetime.now()
            age_days = (now - mem_date).days
            if age_days > max_days_old:
                return MonitorSignal(
                    gap_type="stale_memory",
                    severity="medium",
                    message=f"Memory is {age_days} days old (threshold: {max_days_old} days).",
                    requires_ask=True,
                    failure_type="monitoring",
                )
        except ValueError:
            log.warning(f"Failed to parse memory timestamp: {memory_timestamp_iso}")
        return None

    def check_ambiguous_contact(self, lookup_results: list) -> Optional[MonitorSignal]:
        if len(lookup_results) > 1:
            names = [line.split(":")[0].strip() for line in lookup_results]
            return MonitorSignal(
                gap_type="ambiguity",
                severity="high",
                message=f"I found {len(names)} matching contacts: {', '.join(names)}. Which one do you mean?",
                requires_ask=True,
                failure_type="monitoring",
                options=names,
            )
        return None

    def check_ambiguous_contact_from_text(self, tool_output: str) -> Optional[MonitorSignal]:
        """Plan Part 12 / Gap 1: works on the raw lookup_contact ToolMessage text."""
        matches = [line for line in str(tool_output).splitlines() if "@" in line]
        return self.check_ambiguous_contact(matches)


class JevAssumptionSensor:
    """Fuzzy detectors via Jev (invented args, ungrounded answers)."""

    def __init__(self, threshold: float = JEV_ASSUMPTION_THRESHOLD):
        self.model = get_jev_model_name()
        self.api_key = os.environ.get("OPENROUTER_API_KEY")
        self.threshold = threshold

    @staticmethod
    def _args_are_grounded(tool_args: dict, retrieval_context: str) -> bool:
        """Skip Jev entirely if every arg value already appears verbatim in grounded context."""
        ctx = (retrieval_context or "").lower()
        for k, v in tool_args.items():
            if not str(v).strip():
                continue
            # Skip dates/days from string matching because LLM computes them accurately
            # from relative words ("tomorrow") which breaks verbatim matching.
            if k in ("day", "date"):
                continue
            if str(v).lower() not in ctx:
                return False
        return True

    def check_assumptions(self, user_input: str, tool_name: str, tool_args: dict, retrieval_context: str = "") -> Optional[MonitorSignal]:
        """
        Missing Slot & Vague Wording: Did the agent invent arguments?
        """
        if not self.api_key:
            log.warning("OPENROUTER_API_KEY not set.")
            return None
            
        if self._args_are_grounded(tool_args, retrieval_context):
            return None

        # Build next-7-days calendar so Jev can detect relative-date mismatches
        today = datetime.date.today()
        upcoming_days = {
            (today + datetime.timedelta(days=i)).strftime("%A"): (today + datetime.timedelta(days=i)).isoformat()
            for i in range(7)
        }

        # Build Jev noul request
        payload = {
            "model": self.model,
            "state": {
                "user_input": user_input,
                "proposed_tool": tool_name,
                "proposed_args": str(tool_args),
                "retrieval_context": retrieval_context,
                "today_date": today.isoformat(),
                "today_weekday": today.strftime("%A"),
                "upcoming_days": str(upcoming_days),
            },
            "questions": {
                "is_assumed": {
                    "type": "noul",
                    "instructions": (
                        "Did the agent silently assume or guess any of the proposed arguments "
                        "that were NOT explicitly provided in the user input? "
                        "Pay special attention to dates: if the user said a weekday (e.g. 'Monday') "
                        "but the proposed date is today's date or does not match the named weekday "
                        "in upcoming_days, that is a date assumption."
                    ),
                    "criteria": {
                        "true": "The agent invented, guessed, or hallucinated arguments (e.g. missing time, wrong date, missing name).",
                        "false": "The user input completely and explicitly specifies all the provided arguments, including any dates resolving correctly to named weekdays."
                    }
                }
            }
        }
        
        try:
            response = requests.post(
                "https://openrouter.ai/api/alpha/decisions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=15.0
            )
            response.raise_for_status()
            result = response.json()
            
            noul_score = result.get("answers", {}).get("is_assumed", {}).get("noul", 0.0)
            
            if noul_score > self.threshold:
                return MonitorSignal(
                    gap_type="missing_slot",
                    severity="high",
                    message=f"Agent guessed arguments not in input (confidence: {noul_score:.2f}).",
                    requires_ask=True,
                    failure_type="monitoring"
                )
        except Exception as e:
            log.warning(f"Jev API call failed: {e}")
            
        return None
