import os
import logging
from typing import Optional
import requests

from config import get_jev_model_name

log = logging.getLogger("ask_linter")

class LinterFeedback:
    def __init__(self, is_valid: bool, feedback: str):
        self.is_valid = is_valid
        self.feedback = feedback


class AskLinter:
    """Ensures that when the agent asks a question, it is structured, specific, and not lazy."""
    
    def __init__(self):
        self.model = get_jev_model_name()
        self.api_key = os.environ.get("OPENROUTER_API_KEY")

    def check_structure(self, options: Optional[list], default_option: Optional[str]) -> LinterFeedback:
        """Deterministic Python check for structural requirements."""
        if not options or len(options) < 2:
            return LinterFeedback(False, "Ask rejected: You must provide at least two specific options for the user to choose from.")
        if not default_option:
            return LinterFeedback(False, "Ask rejected: You must provide a default_option.")
        if default_option not in options:
            return LinterFeedback(False, "Ask rejected: The default_option must be one of the choices in the options list.")
        return LinterFeedback(True, "")

    def check_quality_with_jev(self, question: str, options: list) -> LinterFeedback:
        """Uses Jev to determine if the question is unacceptably vague (lazy)."""
        if not self.api_key:
            log.warning("OPENROUTER_API_KEY not set.")
            return LinterFeedback(True, "")

        payload = {
            "model": self.model,
            "state": {
                "proposed_question": question,
                "proposed_options": str(options)
            },
            "questions": {
                "is_lazy": {
                    "type": "noul",
                    "instructions": "Is the proposed question unacceptably lazy, vague, or open-ended? A question is LAZY if it does not explicitly suggest concrete options.",
                    "criteria": {
                        "true": "The question is lazy, abstract, or dumps cognitive load on the user.",
                        "false": "The question is highly specific and mentions exact gaps."
                    }
                }
            }
        }
        
        try:
            res = requests.post("https://openrouter.ai/api/alpha/decisions", headers={"Authorization": f"Bearer {self.api_key}"}, json=payload, timeout=15)
            res.raise_for_status()
            
            is_lazy = res.json().get("answers", {}).get("is_lazy", {}).get("noul", 0.0)
            if is_lazy > 0.75:
                return LinterFeedback(False, "Ask rejected by Jev: Your question is too vague or lazy. You must explicitly mention the exact context you are missing.")
        except Exception as e:
            log.warning(f"AskLinter Jev API call failed: {e}")
            
        return LinterFeedback(True, "")

    def lint(self, question: str, options: Optional[list] = None, default_option: Optional[str] = None) -> LinterFeedback:
        """Run all linting checks on the proposed ask."""
        options = options or []
        
        structure_check = self.check_structure(options, default_option)
        if not structure_check.is_valid:
            return structure_check
            
        quality_check = self.check_quality_with_jev(question, options)
        if not quality_check.is_valid:
            return quality_check
            
        return LinterFeedback(True, "Ask approved.")