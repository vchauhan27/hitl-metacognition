import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.tools import ToolRuntime, tool
from langchain_chroma import Chroma
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver
from langchain_core.messages import HumanMessage, AIMessage, RemoveMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.memory import InMemoryStore
from dataclasses import dataclass

import config
import guardrail

# ---------------------------------------------------------
# Environment
# ---------------------------------------------------------

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------
# Fake Data
# ---------------------------------------------------------

CONTACTS = {
    "Sam Carter": "sam.carter@example.com (engineering)",
    "Sam Patel": "sam.patel@example.com (sales)",
    "Priya Nair": "priya.nair@example.com (design)",
}
CALENDAR = {}
SENT = []

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

@dataclass
class Context:
    user_id: str

# ---------------------------------------------------------
# 1. Models & Vector DB
# ---------------------------------------------------------

model = config.get_llm()
embeddings = config.get_embeddings()

vectorstore = Chroma(
    collection_name=config.CHROMA_COLLECTION,
    persist_directory=config.CHROMA_DIR,
    embedding_function=embeddings,
)

# persistent session memory
conn = sqlite3.connect("session_memory.sqlite", check_same_thread=False)
checkpointer = SqliteSaver(conn)
# long memory
store = InMemoryStore()

# ---------------------------------------------------------
# 2. Tools
# ---------------------------------------------------------

@tool
def search_notes(query: str) -> str:
    """Search the user's personal notes. Returns passages with a relevance score (0-1)."""
    hits = vectorstore.similarity_search_with_relevance_scores(query, k=3)
    if not hits:
        return "No notes found."
    return "\n".join(f"[score={s:.2f}] {d.page_content}" for d, s in hits)

@tool
def get_calendar(day: str) -> str:
    """List calendar events on a date (YYYY-MM-DD)."""
    return "\n".join(CALENDAR.get(day, [])) or "No events."

@tool
def create_event(day: str, start: str, title: str) -> str:
    """Create a calendar event. day is YYYY-MM-DD, start is HH:MM.
    Requires user approval before scheduling.
    """
    print(f"\n[APPROVAL NEEDED] create_event on {day} at {start}")
    print(f"Event Title: {title}")
    ok = input("Approve? [y/N]: ").strip().lower()
    if ok == 'y':
        CALENDAR.setdefault(day, []).append(f"{start} {title}")
        return f"Created '{title}' on {day} at {start}."
    else:
        return "User rejected creating the event."

@tool
def lookup_contact(name: str) -> str:
    """Find contacts whose name contains the given text."""
    found = [f"{n}: {i}" for n, i in CONTACTS.items() if name.lower() in n.lower()]
    return "\n".join(found) or "No matching contact."

@tool
def send_message(to: str, body: str) -> str:
    """Send a message to a contact on the user's behalf.
    Requires user approval before sending.
    """
    print(f"\n[APPROVAL NEEDED] send_message to {to}")
    print(f"Message: {body}")
    ok = input("Approve? [y/N]: ").strip().lower()
    if ok == 'y':
        SENT.append({"to": to, "body": body})
        return f"Message sent to {to}."
    else:
        return "User rejected sending the message."

@tool
def remember(key: str, value: str, runtime: ToolRuntime[Context]) -> str:
    """Save a durable fact or preference about the user."""
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
    if runtime.store is None:
        return "Memory store is not available."
    items = runtime.store.search(("memories", runtime.context.user_id), limit=50)
    if not items:
        return "No memories yet."
    return "\n".join(f"{i.key}: {i.value['value']} (saved {i.value['saved_at']})" for i in items)

@tool
def ask_user(question: str, options: list[str] | None = None) -> str:
    """Ask the user a clarifying question and wait for the answer.
    Use when a needed detail is missing or ambiguous.
    """
    print(f"\n[ASSISTANT ASKS] {question}")
    if options:
        print("  options: " + " | ".join(options))
    ans = input("> ")
    return ans

# ---------------------------------------------------------
# 3. Agent
# ---------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a personal scheduling and messaging assistant. Today is {today}.\n\n"
    "CRITICAL RULES:\n"
    "1. ISOLATE TASKS: Treat each new user request as a completely separate task. DO NOT carry over subjects, meetings, or context from previous requests unless the user explicitly refers to them.\n"
    "2. CHAIN TOOLS: If you are asked to schedule something for a role (e.g. 'the person who owns the technical sections'), ALWAYS use `search_notes` first to find their name, then use `lookup_contact` to get their email.\n"
    "3. RESOLVE AMBIGUITY: If the user provides a partial name (like 'Sam'), you MUST use `lookup_contact`. If multiple people match, you MUST use `ask_user` to clarify which person they mean before doing anything else.\n"
    "4. NO GUESSING: If a required detail (time, duration, exact person) is missing or ambiguous after using your tools, call `ask_user`. Do not guess.\n"
    "5. Keep replies short and direct."
).format(today=date.today().isoformat())

agent = create_agent(
    model=model,
    tools=[
        search_notes,
        get_calendar,
        create_event,
        lookup_contact,
        send_message,
        remember,
        recall,
        ask_user
    ],
    system_prompt=SYSTEM_PROMPT,
    checkpointer=checkpointer,
    store=store,
    context_schema=Context,
)

# ---------------------------------------------------------
# 4. Run agent
# ---------------------------------------------------------

def main():
    print("=" * 70)
    print("PERSONAL ASSISTANT")
    print("=" * 70)

    thread_id = "session-1"
    user_id = "me"
    
    while True:
        try:
            print("\n" + "-" * 70)
            question = input("you> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break
            
        if not question:
            continue
            
        if question.lower() in {"exit", "quit"}:
            print("\nExiting.")
            break
            
        print("\nAssistant is thinking...\n")
        
        try:
            input_res = guardrail.check_input(question)
            if not input_res["allowed"]:
                print("=" * 70)
                print("BLOCKED: Input violated guardrails.")
                print("=" * 70)
                print(f"- {input_res.get('message', 'No reason provided.')}")
                continue

            config = RunnableConfig(configurable={"thread_id": thread_id})
            
            # --- CONTEXT SUMMARIZATION (80% THRESHOLD) ---
            state = agent.get_state(config)
            if state and state.values:
                messages = state.values.get("messages", [])
                # 10 messages threshold for the proof-of-concept
                if len(messages) > 10:
                    print("\n[MEMORY] Context threshold reached! Summarizing older messages...")
                    old_messages = messages[:-4]  # Keep the last 4 messages intact
                    
                    summary_prompt = "Summarize the following conversation history briefly:\n"
                    for m in old_messages:
                        role = "User" if isinstance(m, HumanMessage) else ("Assistant" if isinstance(m, AIMessage) else "System")
                        if hasattr(m, 'content'):
                            summary_prompt += f"{role}: {m.content}\n"
                    
                    summary = model.invoke([HumanMessage(content=summary_prompt)])
                    delete_msgs = [RemoveMessage(id=m.id) for m in old_messages if getattr(m, 'id', None)]
                    summary_msg = AIMessage(content=f"Summary of previous conversation: {summary.content}")
                    
                    agent.update_state(config, {"messages": delete_msgs + [summary_msg]})
                    print("[MEMORY] Summarization complete.")
            # ---------------------------------------------

            result = agent.invoke(
                {"messages": [{"role": "user", "content": question}]},
                config=config,
                context=Context(user_id=user_id),
            )
            
            output_text = result["messages"][-1].content
            
            output_res = guardrail.check_output(question, output_text)
            if not output_res["allowed"]:
                print("=" * 70)
                print("BLOCKED: Output violated guardrails.")
                print("=" * 70)
                print(f"- {output_res.get('message', 'No reason provided.')}")
                continue
            
            print("=" * 70)
            print("ANSWER")
            print("=" * 70)
            print(output_text)
            
        except Exception as e:
            print("\nAgent error:")
            print(repr(e))

if __name__ == "__main__":
    main() 