import json
from datetime import datetime, timezone
from langchain.tools import tool

# ---------------------------------------------------------
# Permission Memory
# ---------------------------------------------------------

PERMISSION_STORE = []

def grant_permission(scope: str, expiry_date: str):
    """Store a standing permission with an exact scope and expiry."""
    PERMISSION_STORE.append({
        "scope": scope,
        "expiry": expiry_date,
        "granted_at": datetime.now(timezone.utc).isoformat()
    })

def has_permission(tool_name: str, context: dict) -> bool:
    """Check if there is an unexpired standing permission for this action."""
    # This is a naive check; in a full implementation, you'd check 'scope' 
    # against 'tool_name' and 'context' and verify the expiry date.
    now = datetime.now(timezone.utc).isoformat()
    for perm in PERMISSION_STORE:
        if perm["scope"] == tool_name and perm["expiry"] > now:
            return True
    return False

# ---------------------------------------------------------
# Linter
# ---------------------------------------------------------

BANNED_PHRASES = [
    "what should i do",
    "how should i proceed",
    "can you clarify",
    "what do you want me to do"
]

def lint_ask(gap: str, tried: str, options: list[str], use: str, default: str) -> str | None:
    """Returns an error message if the ask is lazy, else None."""
    if not gap or not tried or not use or not default:
        return "Missing required fields in ask_user."
    
    text_to_check = f"{gap} {use} {default}".lower()
    for phrase in BANNED_PHRASES:
        if phrase in text_to_check:
            return f"Lazy ask rejected. Do not use phrases like '{phrase}'."
            
    if not options or len(options) == 0:
        return "Must provide at least one option."
        
    return None

# ---------------------------------------------------------
# Tool
# ---------------------------------------------------------

@tool
def ask_user(gap: str, tried: str, options: list[str], use: str, default: str) -> str:
    """Ask the user a clarifying question.
    Requires structured fields:
    - gap: The specific gap in information (e.g., 'time and duration missing').
    - tried: What you already tried (e.g., 'searched notes for Priya').
    - options: A list of options for the user.
    - use: What will be done with the answer.
    - default: The default action if they just say 'yes' or 'proceed'.
    """
    error = lint_ask(gap, tried, options, use, default)
    if error:
        return f"LINTER ERROR: {error}"
        
    print(f"\n[ASSISTANT ASKS]")
    print(f"Gap: {gap}")
    print(f"Tried: {tried}")
    print(f"Options: {', '.join(options)}")
    print(f"Will do: {use}")
    print(f"Default: {default}")
    
    # In shadow mode, this might just take input.
    ans = input("> ")
    return ans
