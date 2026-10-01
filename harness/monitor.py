import datetime
import logging
import os
from typing import Optional
import requests
from config import get_jev_model_name

log = logging.getLogger("monitor")

class MonitorSignal:
    def __init__(self, gap_type: str, severity: str, message: str, requires_ask: bool = False):
        self.gap_type = gap_type
        self.severity = severity  # 'low', 'medium', 'high'
        self.message = message
        self.requires_ask = requires_ask

    def __repr__(self):
        return f"MonitorSignal({self.gap_type}, {self.severity}, requires_ask={self.requires_ask})"


class DeterministicMonitor:
    """
    Deterministic checks for the Metacognitive Harness.
    These are computable rules that do not require an LLM.
    """
    
    def __init__(self):
        # Tools that act on the user's behalf or leave the system
        self.permission_tools = ["send_message", "create_event", "move_event"]
        
    def check_permission(self, tool_name: str) -> Optional[MonitorSignal]:
        if tool_name in self.permission_tools:
            return MonitorSignal(
                gap_type="permission",
                severity="high",
                message=f"Tool '{tool_name}' requires explicit permission or disclosure.",
                requires_ask=True
            )
        return None

    def check_stale_memory(self, memory_timestamp_iso: str, max_days_old: int = 30) -> Optional[MonitorSignal]:
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
                    requires_ask=True
                )
        except ValueError:
            log.warning(f"Failed to parse memory timestamp: {memory_timestamp_iso}")
            
        return None
        
    def check_ambiguous_contact(self, lookup_results: list) -> Optional[MonitorSignal]:
        if len(lookup_results) > 1:
            return MonitorSignal(
                gap_type="ambiguity",
                severity="high",
                message=f"Multiple contacts found: {len(lookup_results)} matches.",
                requires_ask=True
            )
        return None


class JevMonitor:
    """
    Generalized Assumption Sensor using Jev.
    Replaces brittle Python string-matching for semantic understanding.
    """
    def __init__(self):
        self.model = get_jev_model_name()
        self.api_key = os.environ.get("OPENROUTER_API_KEY")

    def check_assumptions(self, user_input: str, tool_name: str, tool_args: dict) -> Optional[MonitorSignal]:
        """
        Missing Slot & Vague Wording: Did the agent invent arguments?
        """
        if not self.api_key:
            log.warning("OPENROUTER_API_KEY not set.")
            return None

        # Build Jev noul request
        payload = {
            "model": self.model,
            "state": {
                "user_input": user_input,
                "proposed_tool": tool_name,
                "proposed_args": str(tool_args)
            },
            "questions": {
                "is_assumed": {
                    "type": "noul",
                    "instructions": "Did the agent silently assume or guess any of the proposed arguments that were NOT explicitly provided in the user input?",
                    "criteria": {
                        "true": "The agent invented, guessed, or hallucinated arguments (e.g. missing time, missing name).",
                        "false": "The user input completely and explicitly specifies all the provided arguments."
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
            
            if noul_score > 0.8:
                return MonitorSignal(
                    gap_type="missing_slot",
                    severity="high",
                    message=f"Generalized Assumption Detected: Agent guessed arguments not in input (confidence: {noul_score:.2f})",
                    requires_ask=True
                )
        except Exception as e:
            log.warning(f"Jev API call failed: {e}")
            
        return None
