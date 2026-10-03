import logging
from typing import List

# Shared signal definition (emitted by every module in harness/failures/)
from harness.failures.signals import MonitorSignal

log = logging.getLogger("controller")

class ControllerAction:
    def __init__(self, action: str, reason: str, signals: List[MonitorSignal]):
        # Valid actions: 'proceed', 'proceed_and_disclose', 'ask', 'idk'
        self.action = action
        self.reason = reason
        self.signals = signals

    def __repr__(self):
        return f"ControllerAction(action='{self.action}', reason='{self.reason}')"


class Controller:
    """
    The fixed policy that maps Monitor signals to deterministic actions.
    This entirely removes the burden of metacognition from the LLM.
    """
    
    def __init__(self):
        # We define which gaps are considered "small gaps" (cheap to undo).
        # For example, adding a reminder with no specific time might be cheap to undo,
        # but booking a flight is costly. 
        self.small_gaps = ["minor_missing_slot", "cheap_assumption"]

    def decide(self, signals: List[MonitorSignal]) -> ControllerAction:
        """
        Evaluate the signals and return the safest bounded action.
        Precedence: idk > ask > proceed_and_disclose > proceed
        """
        if not signals:
            return ControllerAction("proceed", "No gaps detected. High confidence.", [])
            
        # Priority 1: Knowledge gaps -> Ask human for missing info
        for sig in signals:
            if sig.gap_type == "knowledge_gap":
                return ControllerAction(
                    "ask", 
                    "Agent attempting to hallucinate facts without RAG support. Seeking human help.", 
                    signals
                )
                
        # Priority 2: High severity gaps or strict permissions -> Ask
        for sig in signals:
            if sig.severity in ["high", "medium"] or sig.requires_ask:
                return ControllerAction(
                    "ask", 
                    f"Costly gap or permission rule fired: {sig.message}", 
                    signals
                )
                
        # Priority 3: Small gaps, cheap to undo -> Proceed and disclose
        for sig in signals:
            if sig.gap_type in self.small_gaps or sig.severity == "low":
                return ControllerAction(
                    "proceed_and_disclose", 
                    f"Small gap detected, proceeding with disclosure: {sig.message}", 
                    signals
                )
                
        # Fallback safe default
        return ControllerAction("ask", "Unhandled gap type, defaulting to safe ask.", signals)
