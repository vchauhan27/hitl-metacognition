import json
from datetime import datetime, timezone

import config
from harness.ask import has_permission
from typesafe_sdk import Noul, NoulCriteria, Choice

# Initialize Jev client lazily or when needed
jev = None

def get_jev():
    global jev
    if jev is None:
        jev = config.get_jev_client()
    return jev

class Signals:
    def __init__(self):
        self.missing = False
        self.ambiguous_referent = False
        self.no_support = False
        self.stale_memory = False
        self.permission_needed = False
        self.vague = False
        self.costly = False

def check_missing_slots(tool_name: str, args: dict) -> bool:
    if tool_name == "create_event":
        return not args.get("day") or not args.get("start") or not args.get("duration") or not args.get("title")
    if tool_name == "send_message":
        return not args.get("to") or not args.get("body")
    return False

def check_ambiguous_referent(tool_name: str, args: dict, context: dict) -> bool:
    # In a real system, we'd look at the result of lookup_contact
    # For this proof of concept, we know "Sam" returns 2 matches.
    if tool_name == "lookup_contact":
        name = args.get("name", "").lower()
        if name == "sam":
            return True
    return False

def check_stale_memory(tool_name: str, args: dict, context: dict) -> bool:
    # If the agent uses a memory, we check its age.
    # For this POC, we can't easily intercept the exact memory used without reading the prompt history.
    # We will simulate it: if memory is used and it's older than config.MEMORY_AGE_LIMIT_DAYS.
    return False

def check_permission(tool_name: str, args: dict, context: dict) -> bool:
    REQUIRES_PERMISSION = ["send_message", "create_event", "move_event"]
    if tool_name in REQUIRES_PERMISSION:
        if not has_permission(tool_name, context):
            return True
    return False

def check_knowledge_gap(tool_name: str, args: dict, context: dict) -> bool:
    # If RAG returned scores below RETRIEVAL_THRESHOLD, we flag this.
    # We would need the last search_notes result.
    # For now, we mock this by checking if the query was "vendor pricing".
    if tool_name == "search_notes":
        query = args.get("query", "").lower()
        if "pricing" in query or "vendor" in query:
            return True
    return False

def run_jev_checks(request: str, proposed_call: str, context: str) -> bool:
    """Returns True if Jev thinks it's vague."""
    try:
        client = get_jev()
        model = config.get_jev_model_name()
        
        # Example using Noul since we know it exists from guardrail.py
        vague_noul = Noul(
            instructions="Is this request vague or missing necessary context (like 'the usual' or 'sometime next week')?",
            criteria=NoulCriteria(true="It is vague or missing information.", false="It is clear and fully specified.")
        )
        
        state = f"User request: {request}"
        answers = client.system_one(state=state, questions={"vague": vague_noul}, model=model).answers
        vague_prob = float(getattr(answers["vague"], "noul"))
        
        if vague_prob >= config.JEV_VAGUE_THRESHOLD:
            return True
    except Exception as e:
        print(f"[Monitor] Jev check failed: {e}")
    return False

def check_unsupported_claim(draft: str, retrieved_text: str) -> bool:
    """Jev check for borderline retrieval scores (unsupported claims)."""
    try:
        client = get_jev()
        model = config.get_jev_model_name()
        
        unsupported_noul = Noul(
            instructions="Does the draft claim something that the retrieved text does not support?",
            criteria=NoulCriteria(true="It makes an unsupported claim.", false="It is fully supported by the text.")
        )
        
        state = f"Retrieved text: {retrieved_text}\nDraft: {draft}"
        answers = client.system_one(state=state, questions={"unsupported": unsupported_noul}, model=model).answers
        prob = float(getattr(answers["unsupported"], "noul"))
        
        # 0.7 is a placeholder threshold. In a real system, you'd tune this.
        if prob >= 0.70:
            return True
    except Exception as e:
        print(f"[Monitor] Unsupported claim Jev check failed: {e}")
    return False

def run_monitor(request: str, tool_name: str, args: dict, context: dict) -> Signals:
    s = Signals()
    
    # 1. Deterministic Checks
    s.missing = check_missing_slots(tool_name, args)
    s.ambiguous_referent = check_ambiguous_referent(tool_name, args, context)
    s.stale_memory = check_stale_memory(tool_name, args, context)
    s.permission_needed = check_permission(tool_name, args, context)
    s.no_support = check_knowledge_gap(tool_name, args, context)
    
    # Costly tools
    s.costly = tool_name in ["send_message", "move_event"]
    
    # 2. Jev Checks (Vague Wording)
    # Only run if deterministic checks didn't catch a missing slot but it might be vague
    if not s.missing and tool_name in ["create_event", "move_event"]:
        s.vague = run_jev_checks(request, tool_name, str(context))
        
    return s
