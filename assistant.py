import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.tools import tool
from langchain_chroma import Chroma
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.runnables import RunnableConfig
from langgraph.store.memory import InMemoryStore
from dataclasses import dataclass

from config import get_llm, get_embeddings, CHROMA_COLLECTION, CHROMA_DIR

from harness.core import HarnessModelWrapper, PERMISSION_PREFIX
from harness.failures.executive_asking import AskLinter


load_dotenv()

BASE_DIR = Path(__file__).resolve().parent


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


model_base = get_llm()

# long memory — created before the model so it can be injected into the harness
store = InMemoryStore()

# Harness wraps the model, couples failures/* modules to every tool call.
model = HarnessModelWrapper(model_base, store=store, contacts=CONTACTS)

embeddings = get_embeddings()

vectorstore = Chroma(
    collection_name=CHROMA_COLLECTION,
    persist_directory=CHROMA_DIR,
    embedding_function=embeddings,
)

checkpointer = MemorySaver()


@tool
def create_event(day: str, start: str, title: str) -> str:
    """Create a calendar event. day is YYYY-MM-DD, start is HH:MM.
    """
    CALENDAR.setdefault(day, []).append(f"{start} {title}")
    return f"Created '{title}' on {day} at {start}."

@tool
def lookup_contact(name: str) -> str:
    """Find contacts whose name contains the given text."""
    found = [f"{n}: {i}" for n, i in CONTACTS.items() if name.lower() in n.lower()]
    return "\n".join(found) or "No matching contact."

@tool
def send_message(to: str, body: str) -> str:
    """Send a message to a contact on the user's behalf.
    """
    SENT.append({"to": to, "body": body})
    return f"Message sent to {to}."



from typing import Callable, Optional
linter = AskLinter()
EVAL_ASK_HANDLER: Optional[Callable] = None

@tool
def ask_user(question: str, options: list[str], default_option: str) -> str:
    """Ask the user a clarifying question and wait for the answer.
    Use when a needed detail is missing or ambiguous.
    CRITICAL: `options` must be a list of at least two specific choices. `default_option` must be one of the `options`.
    """
    # Executive-asking fix: lint agent-authored asks. Harness-generated permission asks
    # are structured by construction, so they skip the linter.
    if linter and not question.startswith(PERMISSION_PREFIX):
        feedback = linter.lint(question, options, default_option)
        if not feedback.is_valid:
            print(f"\n[HARNESS: AskLinter] Rejected question: {feedback.feedback}")
            return f"[HARNESS: AskLinter] {feedback.feedback}"
        print(f"\n[HARNESS: AskLinter] Approved question format.")

    if EVAL_ASK_HANDLER:
        return EVAL_ASK_HANDLER(question, options, default_option)

    print(f"\n[ASSISTANT ASKS] {question}")
    if options:
        print("  options: " + " | ".join(options))
        if default_option:
            print("  default: " + default_option)
    ans = input("> ")
    if not ans.strip() and default_option:
        return default_option
    return ans


SYSTEM_PROMPT = (
    "You are a professional personal assistant. Today is {today} ({weekday}).\n\n"
    "Core principles:\n"
    "- Ask before acting ONLY when a detail is missing. If all information is provided, DO NOT ask for permission, just execute the tool.\n"
    "- Never guess. If a name, time, or contact is not explicitly provided, use your tools to look it up or ask.\n"
    "- Do not send messages or notifications unless explicitly requested by the user.\n"
    "- Resolve names via tools. Use `lookup_contact` for people.\n"
    "- Resolve dates precisely. Calculate the ISO date silently based on today's date. Do not ask the user to confirm relative dates (e.g., 'tomorrow').\n"
    "- Scope permissions narrowly. A user approval for one action does not cover other actions or recipients.\n"
    "- Act once. If a tool has already succeeded, do not repeat that step.\n"
    "- Confirm only facts. Only state what was confirmed by a tool result — do not infer or embellish.\n"
    "- Be concise in all replies."
).format(
    today=date.today().isoformat(),
    weekday=date.today().strftime("%A")
)

agent = create_agent( # type: ignore
    model=model,  # type: ignore
    tools=[
        create_event,
        lookup_contact,
        send_message,
        ask_user
    ],
    system_prompt=SYSTEM_PROMPT,
    checkpointer=checkpointer,
    store=store,
    context_schema=Context,
)



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