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

    def lint(self, question: str, options: Optional[list] = None, default_option: Optional[str] = None) -> LinterFeedback:
        """
        Run all linting checks on the proposed ask.
        """
        options = options or []
        
        structure_check = self.check_structure(options, default_option)
        if not structure_check.is_valid:
            return structure_check
            
        return LinterFeedback(True, "Ask approved.")
