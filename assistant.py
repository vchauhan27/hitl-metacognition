import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.tools import ToolRuntime, tool
from langchain_chroma import Chroma
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, AIMessage, RemoveMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.memory import InMemoryStore
from dataclasses import dataclass

import config

# from harness.monitor import DeterministicMonitor, JevMonitor
# from harness.controller import Controller
# from harness.ask_linter import AskLinter

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

model_base = config.get_llm()

# class HarnessModelWrapper:
#     def __init__(self, model):
#         self.model = model
#         self.det_monitor = DeterministicMonitor()
#         self.jev_monitor = JevMonitor()
#         self.controller = Controller()
# 
#     def bind_tools(self, *args, **kwargs):
#         return HarnessModelWrapper(self.model.bind_tools(*args, **kwargs))
# 
#     def with_config(self, *args, **kwargs):
#         return HarnessModelWrapper(self.model.with_config(*args, **kwargs))
#         
#     def _apply_harness(self, input_data, ai_message):
#         # Extract user input for JevMonitor and check for recent permissions
#         user_inputs = []
#         approved_tools = set()
#         messages = input_data.get("messages", []) if isinstance(input_data, dict) else input_data
#         
#         for i, m in enumerate(messages):
#             if getattr(m, "type", None) == "human" or getattr(m, "__class__", None) and m.__class__.__name__ == "HumanMessage":
#                 content = m.content
#                 if isinstance(content, list):
#                     content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
#                 user_inputs.append(str(content))
#                 approved_tools.clear() # Reset permissions on new human message
#             elif getattr(m, "type", None) == "tool" or getattr(m, "__class__", None) and m.__class__.__name__ == "ToolMessage":
#                 if getattr(m, "name", None) == "ask_user":
#                     ans = str(m.content).strip().lower()
#                     user_inputs.append(ans)
#                     if ans in ["yes", "y", "sure", "ok", "approve"]:
#                         if i > 0:
#                             prev_m = messages[i-1]
#                             if getattr(prev_m, "type", None) == "ai" or getattr(prev_m, "__class__", None) and prev_m.__class__.__name__ == "AIMessage":
#                                 for tcall in getattr(prev_m, "tool_calls", []):
#                                     if tcall.get("name") == "ask_user":
#                                         q = tcall.get("args", {}).get("question", "")
#                                         import re
#                                         match = re.search(r"run (\w+) with args", q)
#                                         if match:
#                                             approved_tools.add(match.group(1))
# 
# 
#         combined_user_input = "\n".join(user_inputs)
# 
#         # Collect retrieval context for Knowledge Gap monitor.
#         # Includes: search_notes output, lookup_contact output, recall output,
#         # ask_user responses, and raw human messages — all are grounded sources.
#         retrieval_context_parts = []
#         if messages:
#             for m in messages:
#                 is_tool_msg = (
#                     getattr(m, "type", None) == "tool"
#                     or (getattr(m, "__class__", None) and m.__class__.__name__ == "ToolMessage")
#                 )
#                 is_human_msg = (
#                     getattr(m, "type", None) == "human"
#                     or (getattr(m, "__class__", None) and m.__class__.__name__ == "HumanMessage")
#                 )
#                 if is_tool_msg:
#                     tool_name = getattr(m, "name", None)
#                     # Read tools: direct retrieval sources
#                     # Write tools: their output IS grounding for the confirmation message
#                     # (e.g. "Event created: Call with Priya on 2026-10-05 at 14:00"
#                     #  grounds "I've booked your call for Monday at 2pm")
#                     if tool_name in (
#                         "search_notes", "lookup_contact", "recall", "ask_user",
#                         "create_event", "send_message", "move_event", "remember",
#                         "get_calendar",
#                     ):
#                         retrieval_context_parts.append(str(m.content))
#                 elif is_human_msg:
#                     content = m.content
#                     if isinstance(content, list):
#                         content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
#                     retrieval_context_parts.append(str(content))
#         retrieval_context = "\n".join(retrieval_context_parts)
# 
#         new_tool_calls = []
#         forced_content = ai_message.content or ""
# 
#         # No tool calls and no content — nothing to intercept
#         if not getattr(ai_message, "tool_calls", None):
#             return ai_message
# 
# 
#         
#         for tc in ai_message.tool_calls:
#             signals = []
#             
#             # Skip all checks if the user explicitly approved via ask_user
#             has_permission = tc["name"] in approved_tools
#             if not has_permission:
#                 sig = self.det_monitor.check_permission(tc["name"])
#                 if sig:
#                     print(f"\n[HARNESS: DeterministicMonitor] {sig.message}")
#                     sig.message = f"[DeterministicMonitor] {sig.message}"
#                     signals.append(sig)
#                 
#                 if tc["name"] != "ask_user":
#                     sig = self.jev_monitor.check_assumptions(combined_user_input, tc["name"], tc["args"])
#                     if sig:
#                         print(f"\n[HARNESS: JevMonitor] {sig.message}")
#                         sig.message = f"[JevMonitor] {sig.message}"
#                         signals.append(sig)
#                 
#             action = self.controller.decide(signals)
#             if action.action != "proceed":
#                 print(f"[HARNESS: Controller] Overriding agent to: {action.action.upper()}")
#             
#             if action.action == "idk":
#                 ai_message.content = "I don't know."
#                 ai_message.tool_calls = []
#                 return ai_message
#             elif action.action == "ask":
#                 question = f"I need clarification/permission to run {tc['name']} with args {tc['args']}. Reason: [HARNESS: Controller] {action.reason}"
#                 tc["name"] = "ask_user"
#                 tc["args"] = {
#                     "question": question,
#                     "options": ["yes", "no"],
#                     "default_option": "no"
#                 }
#                 new_tool_calls.append(tc)
#             elif action.action == "proceed_and_disclose":
#                 if not forced_content:
#                     forced_content = ""
#                 forced_content += f"\n[Disclosure: {action.reason}]"
#                 new_tool_calls.append(tc)
#             else:
#                 new_tool_calls.append(tc)
#                 
#         ai_message.tool_calls = new_tool_calls
#         if forced_content:
#             ai_message.content = forced_content.strip()
#         return ai_message
# 
#     def invoke(self, input_data, config=None, **kwargs):
#         res = self.model.invoke(input_data, config=config, **kwargs)
#         return self._apply_harness(input_data, res)
# 
#     async def ainvoke(self, input_data, config=None, **kwargs):
#         res = await self.model.ainvoke(input_data, config=config, **kwargs)
#         return self._apply_harness(input_data, res)
#         
#     def __getattr__(self, name):
#         return getattr(self.model, name)
# 
# model = HarnessModelWrapper(model_base)
model = model_base
embeddings = config.get_embeddings()

vectorstore = Chroma(
    collection_name=config.CHROMA_COLLECTION,
    persist_directory=config.CHROMA_DIR,
    embedding_function=embeddings,
)

checkpointer = MemorySaver()
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

# linter = AskLinter()

@tool
def ask_user(question: str, options: list[str], default_option: str) -> str:
    """Ask the user a clarifying question and wait for the answer.
    Use when a needed detail is missing or ambiguous.
    CRITICAL: `options` must be a list of at least two specific choices. `default_option` must be one of the `options`.
    """
#     feedback = linter.lint(question, options, default_option)
#     if not feedback.is_valid:
#         print(f"\n[HARNESS: AskLinter] Rejected question: {feedback.feedback}")
#         return f"[HARNESS: AskLinter] {feedback.feedback}"
#     else:
#         print(f"\n[HARNESS: AskLinter] Approved question format.")

    print(f"\n[ASSISTANT ASKS] {question}")
    if options:
        print("  options: " + " | ".join(options))
        if default_option:
            print("  default: " + default_option)
    ans = input("> ")
    if not ans.strip() and default_option:
        return default_option
    return ans

# ---------------------------------------------------------
# 3. Agent
# ---------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a professional personal assistant. Today is {today} ({weekday}).\n\n"
    "Core principles:\n"
    "- Ask before acting. Confirm every missing or ambiguous detail with the user before calling any tool.\n"
    "- Never guess. If a name, date, time, or contact is not explicitly provided, use your tools to look it up or ask.\n"
    "- Resolve names via tools. Use `lookup_contact` for people and `search_notes` for roles or context.\n"
    "- Resolve dates precisely. Convert relative terms like 'Monday' or 'tomorrow' to a concrete date before acting.\n"
    "- Scope permissions narrowly. A user approval for one action does not cover other actions or recipients.\n"
    "- Act once. If a tool has already succeeded, do not repeat that step.\n"
    "- Confirm only facts. Only state what was confirmed by a tool result — do not infer or embellish.\n"
    "- Be concise in all replies."
).format(
    today=date.today().isoformat(),
    weekday=date.today().strftime("%A")
)

agent = create_agent(
    model=model,  # type: ignore
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
            # input_res = guardrail.check_input(question)
            # if not input_res["allowed"]:
            #     print("=" * 70)
            #     print("BLOCKED: Input violated guardrails.")
            #     print("=" * 70)
            #     print(f"- {input_res.get('message', 'No reason provided.')}")
            #     continue

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
            
            # output_res = guardrail.check_output(question, output_text)
            # if not output_res["allowed"]:
            #     print("=" * 70)
            #     print("BLOCKED: Output violated guardrails.")
            #     print("=" * 70)
            #     print(f"- {output_res.get('message', 'No reason provided.')}")
            #     continue
            
            print("=" * 70)
            print("ANSWER")
            print("=" * 70)
            print(output_text)
            
        except Exception as e:
            print("\nAgent error:")
            print(repr(e))

if __name__ == "__main__":
    main() 