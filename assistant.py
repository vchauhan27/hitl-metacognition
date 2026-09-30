import os
import sys
from datetime import date
from pathlib import Path
import sqlite3

from dotenv import load_dotenv
from langchain.agents import create_agent
from langgraph.checkpoint.sqlite import SqliteSaver
from langchain_core.messages import HumanMessage, AIMessage, RemoveMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.memory import InMemoryStore

import config
from tools import (
    search_notes, get_calendar, create_event, move_event,
    lookup_contact, draft_message, send_message, remember, recall, Context
)
from harness.ask import ask_user
from harness.hook import execute_with_hook

load_dotenv()

CURRENT_REQUEST = ""

def build_agent(arm: str):
    config.ARM = arm
    
    if arm == "A":
        prompt_path = Path("prompts/bare.txt")
    elif arm == "B":
        prompt_path = Path("prompts/readme.txt")
    elif arm == "C":
        prompt_path = Path("prompts/bare.txt")
    else:
        prompt_path = Path("prompts/readme.txt")
        
    with open(prompt_path, "r") as f:
        prompt_text = f.read().replace("{today}", date.today().isoformat())
        
    all_tools = [
        search_notes, get_calendar, create_event, move_event,
        lookup_contact, draft_message, send_message, remember, recall, ask_user
    ]
    
    side_effect_tools = ["create_event", "move_event", "send_message", "search_notes", "lookup_contact"]
    
    for t in all_tools:
        if t.name in side_effect_tools:
            original_func = getattr(t, "func", None)
            tool_name = t.name
            
            def make_wrapper(orig_f, name):
                def wrapper(*args, **kwargs):
                    return execute_with_hook(
                        request_context_str=CURRENT_REQUEST,
                        tool_name=name,
                        kwargs=kwargs,
                        user_context={"user_id": "me"},
                        original_func=orig_f
                    )
                return wrapper
            
            if original_func:
                setattr(t, "func", make_wrapper(original_func, tool_name))
            
    conn = sqlite3.connect(f"session_memory_{arm}.sqlite", check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    store = InMemoryStore()
    
    agent = create_agent(
        model=config.get_llm(),
        tools=all_tools,
        system_prompt=prompt_text,
        checkpointer=checkpointer,
        store=store,
        context_schema=Context,
    )
    return agent

def main():
    global CURRENT_REQUEST
    print("=" * 70)
    print("PERSONAL ASSISTANT - METACOGNITION TEST")
    print("=" * 70)

    arm = input("Select ARM (A, B, C) [default C]: ").strip().upper()
    if not arm:
        arm = "C"
        
    agent = build_agent(arm)
    thread_id = f"session-{arm}"
    user_id = "me"
    
    while True:
        try:
            print("\n" + "-" * 70)
            question = input(f"[{arm}] you> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break
            
        if not question:
            continue
            
        if question.lower() in {"exit", "quit"}:
            print("\nExiting.")
            break
            
        CURRENT_REQUEST = question
        print("\nAssistant is thinking...\n")
        
        try:
            config_run = RunnableConfig(configurable={"thread_id": thread_id})
            
            result = agent.invoke(
                {"messages": [{"role": "user", "content": question}]},
                config=config_run,
                context=Context(user_id=user_id),
            )
            
            output_text = result["messages"][-1].content
            
            print("=" * 70)
            print("ANSWER")
            print("=" * 70)
            print(output_text)
            
        except Exception as e:
            print("\nAgent error:")
            print(repr(e))

if __name__ == "__main__":
    main()