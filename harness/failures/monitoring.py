"""
Failure 1 — Monitoring (the agent does not notice what it does not know).
Detects stale memory, ambiguous contacts, and hallucinated arguments.
"""
import datetime
import logging
import os
import requests
import re
from typing import Optional

from config import get_jev_model_name, MEMORY_AGE_LIMIT_DAYS
from harness.core import MonitorSignal

log = logging.getLogger("monitoring")
JEV_URL = "https://openrouter.ai/api/alpha/decisions"

# Quoted spans are event titles ('buy milk', "morning run"), not scheduling info.
_QUOTED_RE = re.compile(r"(?<!\w)'[^']*'(?!\w)|\"[^\"]*\"")
_ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_WEEKDAY_RE = re.compile(
    r"\b(mon(?:day)?|tue(?:s|sday)?|wed(?:nesday)?|thu(?:r|rs|rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b"
)
_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _strip_quoted(text: str) -> str:
    return _QUOTED_RE.sub(" ", text or "")


def _day_conflict(text: str, arg_day) -> Optional[str]:
    """Compare the day the user asked for with the day the agent chose.

    Returns a description of what the user asked for if the agent's day contradicts it,
    or None if it matches or cannot be compared (month names, ordinals, unparseable args).
    """
    try:
        chosen = datetime.date.fromisoformat(str(arg_day))
    except (TypeError, ValueError):
        return None
    today = datetime.date.today()
    low = text.lower()

    isos = sorted(set(_ISO_RE.findall(text)))
    if isos:
        return None if chosen.isoformat() in isos else ", ".join(isos)

    ok_dates, weekdays, asked = set(), set(), []
    if re.search(r"\b(today|tonight)\b", low):
        ok_dates.add(today)
        asked.append("today")
    if re.search(r"\btomorrow\b", low):
        ok_dates.add(today + datetime.timedelta(days=1))
        asked.append("tomorrow")
    for m in _WEEKDAY_RE.finditer(low):
        weekdays.add(_DAYS.index(m.group(1)[:3]))
        asked.append(m.group(1))
    if not asked:
        return None
    if chosen in ok_dates:
        return None
    if chosen.weekday() in weekdays and 0 <= (chosen - today).days <= 13:
        return None
    return ", ".join(asked)

class MonitoringChecks:
    """Deterministic gap detectors (no AI logic)."""

    def check_stale_memory(self, memory_timestamp_iso: str, max_days: int = MEMORY_AGE_LIMIT_DAYS) -> Optional[MonitorSignal]:
        """Flags memory that is older than the allowed limit."""
        if not memory_timestamp_iso:
            return None
            
        try:
            mem_date = datetime.datetime.fromisoformat(memory_timestamp_iso)
            now = datetime.datetime.now(datetime.timezone.utc)
            if mem_date.tzinfo is None:
                now = datetime.datetime.now()
                
            age_days = (now - mem_date).days
            if age_days > max_days:
                return MonitorSignal(
                    gap_type="stale_memory",
                    severity="medium",
                    message=f"Memory is {age_days} days old. Please confirm it is still accurate.",
                    requires_ask=True,
                    failure_type="monitoring"
                )
        except ValueError:
            pass
        return None

    def check_ambiguous_contact_from_text(self, tool_output: str) -> Optional[MonitorSignal]:
        """Checks if a contact lookup returned multiple matches."""
        matches = [line.split(":")[0].strip() for line in tool_output.splitlines() if "@" in line]
        if len(matches) > 1:
            return MonitorSignal(
                gap_type="ambiguity",
                severity="high",
                message=f"Found {len(matches)} matching contacts: {', '.join(matches)}. Which one do you mean?",
                requires_ask=True,
                failure_type="monitoring",
                options=matches
            )
        return None

    def check_ambiguous_contact_pre(self, text: str, contacts: dict) -> Optional[MonitorSignal]:
        """Checks if the user vaguely referred to a contact (e.g., 'Sam' when there are two Sams)."""
        if not text:
            return None
            
        text_l = text.lower()
        
        # 1. If they used the exact full name or email, it's not ambiguous
        for name, info in contacts.items():
            email = info.split()[0].lower()
            if name.lower() in text_l or email in text_l:
                return None
                
        # 2. Group all contacts by their first name
        by_first_name = {}
        for full_name in contacts:
            first_name = full_name.split()[0].lower()
            by_first_name.setdefault(first_name, []).append(full_name)
            
        # 3. Check if the user used a first name that belongs to multiple people
        for first_name, full_names in by_first_name.items():
            if first_name in text_l.split() and len(full_names) > 1:
                return MonitorSignal(
                    gap_type="ambiguity",
                    severity="high",
                    message=f"Found multiple people named '{first_name}': {', '.join(full_names)}. Which one do you mean?",
                    requires_ask=True,
                    failure_type="monitoring",
                    options=full_names
                )
        return None


class JevAssumptionSensor:
    """Uses an external AI judge (Jev) to catch hallucinated arguments."""

    def __init__(self, threshold: float = 0.75):
        self.model = get_jev_model_name()
        self.api_key = os.environ.get("OPENROUTER_API_KEY")
        self.threshold = threshold

    def _get_upcoming_days(self) -> dict:
        """Helper to give the AI context about the next 7 days."""
        today = datetime.date.today()
        return {
            (today + datetime.timedelta(days=i)).strftime("%A"): (today + datetime.timedelta(days=i)).isoformat()
            for i in range(7)
        }

    def check_assumptions(self, user_input: str, tool_name: str, tool_args: dict, retrieval_context: str = "") -> Optional[MonitorSignal]:
        """Asks Jev if the agent invented arguments (like a missing time or name)."""
        if tool_name == "create_event":
            day_pattern = re.compile(
                r"\b(today|tomorrow|tonight|"
                r"mon(day)?|tue(s|sday)?|wed(nesday)?|thu(r|rs|rsday)?|fri(day)?|sat(urday)?|sun(day)?|"
                r"jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|june?|july?|aug(ust)?|sep(t|tember)?|oct(ober)?|nov(ember)?|dec(ember)?)\b|"
                r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}|\b\d{1,2}(st|nd|rd|th)\b",
                re.IGNORECASE,
            )
            clean_input = _strip_quoted(user_input)
            day_in_input = bool(day_pattern.search(clean_input))
            
            # Broaden time check with word boundaries
            time_pattern = re.compile(
                r"\b(noon|midnight|morning|afternoon|evening)\b|"
                r"\b\d{1,2}:\d{2}\b|"
                r"\b\d{1,2}\s*(am|pm|h)\b",
                re.IGNORECASE
            )
            start_in_input = bool(time_pattern.search(clean_input))
            
            if not day_in_input:
                return MonitorSignal(
                    gap_type="missing_slot", severity="high",
                    message=f"Agent assumed a date/day that was not explicitly mentioned.",
                    requires_ask=True, failure_type="monitoring"
                )
            conflict = _day_conflict(clean_input, tool_args.get("day"))
            if conflict:
                return MonitorSignal(
                    gap_type="missing_slot", severity="high",
                    message=f"Agent chose {tool_args.get('day')} but the request implies: {conflict}.",
                    requires_ask=True, failure_type="monitoring"
                )
            if not start_in_input:
                return MonitorSignal(
                    gap_type="minor_missing_slot", severity="low",
                    message=f"I assumed a time of day you did not specify. Tell me if you want it changed.",
                    requires_ask=False, failure_type="monitoring"
                )
            return None

        if not self.api_key:
            return None

        today = datetime.date.today()
        payload = {
            "model": self.model,
            "state": {
                "user_input": user_input,
                "proposed_tool": tool_name,
                "proposed_args": str(tool_args),
                "retrieval_context": retrieval_context,
                "today_date": today.isoformat(),
                "upcoming_days": str(self._get_upcoming_days()),
            },
            "questions": {
                "is_assumed": {
                    "type": "noul",
                    "instructions": "Did the agent silently guess any arguments NOT explicitly provided in the user input? Pay attention to relative dates.",
                    "criteria": {
                        "true": "The agent invented, guessed, or hallucinated arguments.",
                        "false": "The user input completely specifies all provided arguments."
                    }
                },
                "day_or_person_assumed": {
                    "type": "noul",
                    "instructions": "If the agent assumed arguments, was the date/day or the recipient assumed?",
                    "criteria": {
                        "true": "A wrong guess would be costly: wrong day, wrong person, or hard to reverse.",
                        "false": "Neither the day nor the recipient was assumed."
                    }
                }
            }
        }
        
        try:
            response = requests.post(JEV_URL, headers={"Authorization": f"Bearer {self.api_key}"}, json=payload, timeout=15)
            response.raise_for_status()
            answers = response.json().get("answers", {})
            
            assumed_score = answers.get("is_assumed", {}).get("noul", 0.0)
            costly_score = answers.get("day_or_person_assumed", {}).get("noul", 0.0)

            if assumed_score <= self.threshold:
                return None  # No assumptions detected
                
            if costly_score > self.threshold:
                return MonitorSignal(
                    gap_type="missing_slot", severity="high",
                    message=f"Agent assumed costly details not in the input (confidence: {assumed_score:.2f}).",
                    requires_ask=True, failure_type="monitoring"
                )
                
            return MonitorSignal(
                gap_type="minor_missing_slot", severity="low",
                message=f"I assumed some details you did not specify ({tool_args}). Tell me if you want them changed.",
                requires_ask=False, failure_type="monitoring"
            )
            
        except Exception as e:
            log.warning(f"Jev API call failed: {e}")
            return None