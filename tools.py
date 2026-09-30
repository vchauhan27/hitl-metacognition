from datetime import datetime, timezone
from dataclasses import dataclass
from langchain.tools import ToolRuntime, tool
import config
from langchain_chroma import Chroma

# ---------------------------------------------------------
# Fake Data & State
# ---------------------------------------------------------

CONTACTS = {
    "Sam Carter": "sam.carter@example.com (engineering)",
    "Sam Patel": "sam.patel@example.com (sales)",
    "Priya Nair": "priya.nair@example.com (design)",
}
CALENDAR = {}
SENT = []
TRACE = []

@dataclass
class Context:
    user_id: str

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def log_trace(tool_name: str, args: dict):
    TRACE.append({"tool": tool_name, "args": args, "timestamp": _now()})

# Initialize Chroma for notes
vectorstore = Chroma(
    collection_name=config.CHROMA_COLLECTION,
    persist_directory=config.CHROMA_DIR,
    embedding_function=config.get_embeddings(),
)

# ---------------------------------------------------------
# Tools
# ---------------------------------------------------------

@tool
def search_notes(query: str) -> str:
    """Search the user's personal notes. Returns passages with a relevance score (0-1)."""
    log_trace("search_notes", {"query": query})
    hits = vectorstore.similarity_search_with_relevance_scores(query, k=3)
    if not hits:
        return "No notes found."
    return "\n".join(f"[score={s:.2f}] {d.page_content}" for d, s in hits)

@tool
def get_calendar(day: str) -> str:
    """List calendar events on a date (YYYY-MM-DD)."""
    log_trace("get_calendar", {"day": day})
    return "\n".join(CALENDAR.get(day, [])) or "No events."

@tool
def create_event(day: str, start: str, duration: str, title: str) -> str:
    """Create a calendar event. day is YYYY-MM-DD, start is HH:MM, duration is e.g. 30 min."""
    log_trace("create_event", {"day": day, "start": start, "duration": duration, "title": title})
    print(f"\n[MOCK APPROVAL] Auto-approved create_event on {day} at {start} for {duration}")
    CALENDAR.setdefault(day, []).append(f"{start} ({duration}) {title}")
    return f"Created '{title}' on {day} at {start} for {duration}."

@tool
def move_event(day: str, start: str, new_day: str, new_start: str) -> str:
    """Move an existing event to a new date/time."""
    log_trace("move_event", {"day": day, "start": start, "new_day": new_day, "new_start": new_start})
    print(f"\n[MOCK APPROVAL] Auto-approved move_event from {day} {start} to {new_day} {new_start}")
    return f"Moved event from {day} {start} to {new_day} {new_start}."

@tool
def lookup_contact(name: str) -> str:
    """Find contacts whose name contains the given text."""
    log_trace("lookup_contact", {"name": name})
    found = [f"{n}: {i}" for n, i in CONTACTS.items() if name.lower() in n.lower()]
    return "\n".join(found) or "No matching contact."

@tool
def draft_message(to: str, body: str) -> str:
    """Draft a message to a contact without sending it."""
    log_trace("draft_message", {"to": to, "body": body})
    return f"Drafted message to {to}."

@tool
def send_message(to: str, body: str) -> str:
    """Send a message to a contact on the user's behalf.
    Requires user approval before sending (mocked here).
    """
    log_trace("send_message", {"to": to, "body": body})
    print(f"\n[MOCK APPROVAL] Auto-approved send_message to {to}")
    SENT.append({"to": to, "body": body})
    return f"Message sent to {to}."

@tool
def remember(key: str, value: str, runtime: ToolRuntime[Context]) -> str:
    """Save a durable fact or preference about the user."""
    log_trace("remember", {"key": key, "value": value})
    if runtime.store is None:
        return "Memory store is not available."
    runtime.store.put(
        ("memories", runtime.context.user_id),
        key,
        {"value": value, "saved_at": _now(), "source": "agent_saved"},
    )
    return f"Remembered {key}."

@tool
def recall(runtime: ToolRuntime[Context]) -> str:
    """List everything remembered about the user."""
    log_trace("recall", {})
    if runtime.store is None:
        return "Memory store is not available."
    items = runtime.store.search(("memories", runtime.context.user_id), limit=50)
    if not items:
        return "No memories yet."
    return "\n".join(f"{i.key}: {i.value['value']} (saved {i.value['saved_at']} source: {i.value.get('source', 'unknown')})" for i in items)
