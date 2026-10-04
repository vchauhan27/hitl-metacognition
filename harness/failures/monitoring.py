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

    def check_ambiguous_contact_pre(self, text: str, contacts: dict) -> Optional[MonitorSignal]:
        """Pre-check: looks for ambiguous first names in side-effect tool arguments."""
        if not text:
            return None
        text_l = text.lower()
        words = text_l.split()
        
        # Check if any full name or email is present exactly; if so, not ambiguous for that person
        for name, info in contacts.items():
            if name.lower() in text_l or info.split()[0].lower() in text_l:
                return None
                
        # Group contacts by first name
        by_first = {}
        for name in contacts:
            first = name.split()[0].lower()
            by_first.setdefault(first, []).append(name)
            
        # If the text contains a first name that maps to multiple contacts, it's ambiguous
        for first, full_names in by_first.items():
            if first in words and len(full_names) > 1:
                return MonitorSignal(
                    gap_type="ambiguity",
                    severity="high",
                    message=f"I found {len(full_names)} matching contacts for '{first}': {', '.join(full_names)}. Which one do you mean?",
                    requires_ask=True,
                    failure_type="monitoring",
                    options=full_names,
                )
        return None


class JevAssumptionSensor:
    """Fuzzy detectors via Jev (invented args, ungrounded answers)."""

    def __init__(self, threshold: float = JEV_ASSUMPTION_THRESHOLD):
        self.model = get_jev_model_name()
        self.api_key = os.environ.get("OPENROUTER_API_KEY")
        self.threshold = threshold

    def check_assumptions(self, user_input: str, tool_name: str, tool_args: dict, retrieval_context: str = "") -> Optional[MonitorSignal]:
        """
        Missing Slot & Vague Wording: Did the agent invent arguments?
        """
        if not self.api_key:
            log.warning("OPENROUTER_API_KEY not set.")
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
                },
                "is_costly": {
                    "type": "noul",
                    "instructions": (
                        "If the agent assumed any arguments, would a wrong guess be costly or hard to undo? "
                        "A wrong or missing date, a wrong or unconfirmed person, or an unconfirmed recipient is costly. "
                        "A missing time of day or a minor default is cheap."
                    ),
                    "criteria": {
                        "true": "A wrong guess would be costly: wrong day, wrong person, or hard to reverse.",
                        "false": "A wrong guess is cheap to fix, such as a default time of day."
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
            
            ans = result.get("answers", {})
            assumed = ans.get("is_assumed", {}).get("noul", 0.0)
            costly = ans.get("is_costly", {}).get("noul", 0.0)

            if assumed <= self.threshold:
                return None
            if costly > self.threshold:
                return MonitorSignal(
                    gap_type="missing_slot", severity="high",
                    message=f"Agent assumed costly details not in the input (confidence: {assumed:.2f}).",
                    requires_ask=True, failure_type="monitoring")
            return MonitorSignal(
                gap_type="minor_missing_slot", severity="low",
                message=f"I assumed some details you did not specify ({tool_args}). Tell me if you want them changed.",
                requires_ask=False, failure_type="monitoring")
        except Exception as e:
            log.warning(f"Jev API call failed: {e}")
            
        return None
