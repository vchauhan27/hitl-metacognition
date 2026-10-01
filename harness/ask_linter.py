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
    """
    Ask Linter / Help Tutor
    Ensures that when the agent asks a question, it is structured, specific, and not lazy.
    """
    
    def __init__(self):
        self.model = get_jev_model_name()
        self.api_key = os.environ.get("OPENROUTER_API_KEY")

    def check_structure(self, options: Optional[list], default_option: Optional[str]) -> LinterFeedback:
        """
        Deterministic Python check for structural requirements.
        """
        if not options or len(options) < 2:
            return LinterFeedback(
                False, 
                "Ask rejected: You must provide at least two specific options for the user to choose from."
            )
            
        if not default_option:
            return LinterFeedback(
                False, 
                "Ask rejected: You must provide a default_option."
            )
            
        if default_option not in options:
            return LinterFeedback(
                False, 
                "Ask rejected: The default_option must be one of the choices in the options list."
            )
            
        return LinterFeedback(True, "")

    def check_quality(self, question: str, options: list) -> LinterFeedback:
        """
        Jev Fuzzy Check for 'Executive Asking' (lazy questions).
        """
        if not self.api_key:
            return LinterFeedback(True, "")

        payload = {
            "model": self.model,
            "state": {
                "question": question,
                "options": str(options)
            },
            "questions": {
                "is_lazy": {
                    "type": "noul",
                    "instructions": "Is this a lazy, 'executive' ask?",
                    "criteria": {
                        "true": "The ask is vague or generic (e.g., 'What should I do?', 'Can you clarify?').",
                        "false": "The ask is highly specific and names the exact missing information (e.g., 'Which time?', 'I found two people named Sam, which one?')."
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
            
            noul_score = result.get("answers", {}).get("is_lazy", {}).get("noul", 0.0)
            
            if noul_score > 0.85:
                return LinterFeedback(
                    False, 
                    f"Ask rejected: Lazy question detected (confidence: {noul_score:.2f}). Please rewrite the question to specifically name the gap you are trying to resolve."
                )
        except Exception as e:
            log.warning(f"Jev API call failed in Linter: {e}")
            
        return LinterFeedback(True, "")

    def lint(self, question: str, options: Optional[list] = None, default_option: Optional[str] = None) -> LinterFeedback:
        """
        Run all linting checks on the proposed ask.
        """
        options = options or []
        
        # 1. Deterministic Structure Check
        structure_check = self.check_structure(options, default_option)
        if not structure_check.is_valid:
            return structure_check
            
        # 2. Jev Quality Check
        quality_check = self.check_quality(question, options)
        if not quality_check.is_valid:
            return quality_check
            
        return LinterFeedback(True, "Ask approved.")
