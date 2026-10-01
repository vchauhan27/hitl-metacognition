"""
Runs Multi-turn DeepEval Jev metrics against one golden conversation.
"""

import os
import re
import sys
import uuid
from pathlib import Path

# Force UTF-8 encoding for Windows console (fixes DeepEval emojis)
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')  # type: ignore

# Increase DeepEval's execution timeout to prevent the 180s TimeoutError when running many metrics
os.environ.setdefault("DEEPEVAL_PER_ATTEMPT_TIMEOUT_SECONDS_OVERRIDE", "2000")

# -------------------------------------------------------------
# DeepEval Windows Cache Fix
import deepeval.test_run.cache
deepeval.test_run.cache.global_test_run_cache_manager.disable_write_cache = True
# -------------------------------------------------------------
# Increase DeepEval's execution timeout to prevent the 180s TimeoutError when running many metrics
os.environ.setdefault("DEEPEVAL_PER_ATTEMPT_TIMEOUT_SECONDS_OVERRIDE", "2000")

# ---------------------------------------------------------------------------
# Path setup (mirrors the pattern already used in agent.py / ingest.py)
# ---------------------------------------------------------------------------

THIS_DIR = Path(__file__).resolve().parent
ROOT_DIR = THIS_DIR.parent.parent          # repo root (where config.py lives)
RESEARCH_AGENT_DIR = ROOT_DIR / "customer-support-agent"

sys.path.append(str(ROOT_DIR))
sys.path.append(str(RESEARCH_AGENT_DIR))

import config  # noqa: E402  (root config.py)

import assistant as agent_module # type: ignore
from assistant import (  # type: ignore  # noqa: E402
    Context,
)
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage  # noqa: E402

from deepeval.test_case import Turn, ConversationalTestCase, ToolCall, MultiTurnParams, LLMTestCase, SingleTurnParams  # noqa: E402
from deepeval.metrics.jev_eval import Noul, Score, Choice  # noqa: E402
from deepeval.metrics import ConversationalJevEval, GEval
from deepeval.models.system_one.typesafe_model import TypeSafeModel

EVAL_MODEL = config.get_judge_model()   # judge model object (provider set in config.py)

# Set to "before" or "after" to route test results
RUN_PHASE = "before"
RESULTS_DIR = f"./evaluation/{RUN_PHASE}-multi-turn-results"

# ---------------------------------------------------------------------------
# Helpers: run the live agent and turn its trace into DeepEval Turns
# ---------------------------------------------------------------------------

async def run_agent_turn(question: str, thread_id: str, user_id: str = "eval-user"):
    """Invoke the customer support agent once and return its full message trace."""
    result = await agent_module.agent.ainvoke(
        {"messages": [{"role": "user", "content": question}]},
        config={"configurable": {"thread_id": thread_id}},
        context=Context(user_id=user_id),
    )
    return result["messages"]


def extract_retrieval_context(tool_output: str):
    """
    Turn search_knowledge_base's formatted blob into a list of individual chunks.
    """
    if "No relevant internal documents were found." in tool_output:
        return [tool_output.strip()]

    chunks = re.split(r"\nSOURCE TYPE: INTERNAL KNOWLEDGE BASE", tool_output)
    contents = []
    for chunk in chunks:
        match = re.search(r"CONTENT:\s*(.+)", chunk, re.DOTALL)
        if match:
            contents.append(match.group(1).strip())

    return contents or [tool_output.strip()]


def build_multi_turns(messages):
    turns = []
    
    # First, collect all tool outputs by their tool_call_id
    tool_outputs = {}
    for msg in messages:
        if getattr(msg, 'tool_call_id', None):
            tool_outputs[msg.tool_call_id] = msg.content

    current_user_msg = None
    current_ai_content = ""
    current_tools = []
    current_retrieval = []

    def flush_turn():
        if current_user_msg is not None:
            turns.append(Turn(role="user", content=current_user_msg))
            turns.append(Turn(
                role="assistant",
                content=current_ai_content.strip(),
                tools_called=current_tools if current_tools else None,
                retrieval_context=current_retrieval if current_retrieval else None,
            ))

    for msg in messages:
        if getattr(msg, "type", "") == "human":
            flush_turn()
            if isinstance(msg.content, list):
                current_user_msg = " ".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in msg.content)
            else:
                current_user_msg = str(msg.content)
            current_ai_content = ""
            current_tools = []
            current_retrieval = []
        elif getattr(msg, "type", "") == "ai":
            if getattr(msg, "tool_calls", None):
                for tc in msg.tool_calls:
                    tc_id = tc.get("id")
                    current_tools.append(
                        ToolCall(
                            name=tc["name"], 
                            input_parameters=tc.get("args", {}) or {},
                            output=tool_outputs.get(tc_id)
                        )
                    )
            if msg.content:
                if isinstance(msg.content, list):
                    content = " ".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in msg.content)
                else:
                    content = msg.content
                current_ai_content += content + " "
        elif getattr(msg, "type", "") == "tool":
            if getattr(msg, "name", None) == "search_knowledge_base":
                current_retrieval.extend(extract_retrieval_context(str(msg.content)))

    flush_turn()
    return turns


from deepeval import evaluate
from deepeval.evaluate import AsyncConfig, DisplayConfig

async def get_conversation_turns(questions):
    thread_id = f"eval-jev-{uuid.uuid4().hex[:8]}"
    final_messages = []
    for q in questions:
        final_messages = await run_agent_turn(q, thread_id)
    return build_multi_turns(final_messages)

async def main():
    import asyncio
    import json

    print("Loading simulated multi-turn test case...")
    json_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data', 'scenarios.json'))
    
    simulated_questions = []
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Use the first simulated conversation, filter only the user's questions
            simulated_questions = data["conversational_scenarios"][0]["user_messages"]
    except Exception as e:
        print(f"Warning: Could not load scenarios, falling back to hardcoded. Error: {e}")
        simulated_questions = [
            "Book a call with Priya",
            "Tomorrow at 2pm"
        ]

    print("Generating conversation trace from agent...")
    turns = await get_conversation_turns(simulated_questions)

    test_case = ConversationalTestCase(
        turns=turns,
    )

    # 1. Tool Use Jev Eval
    tool_use_jev = ConversationalJevEval(
        name="Tool Use (Jev)",
        system_one_model=TypeSafeModel(
            model="typesafe/jev-1.13",
            api_key=os.environ.get("OPENROUTER_API_KEY"),
            base_url="https://openrouter.ai/api",
        ),
        evaluation_params=[MultiTurnParams.TOOLS_CALLED],
        questions=[
            Noul("The assistant called a tool rather than guessing the answer from memory.", weight=2),
            Score(
                "How appropriate was the tool choice?",
                levels=["Irrelevant tool", "Wrong tool", "Sub-optimal tool", "Perfect tool"],
            ),
            Choice(
                "What did the assistant do if the correct tool was not available?",
                options={
                    "hallucinated_a_tool": 0.0,
                    "apologized": 1.0,
                    "tool_was_available": None,
                }
            )
        ],
        include_reason=True
    )

    # 2. Turn Faithfulness Jev Eval
    turn_faithfulness_jev = ConversationalJevEval(
        name="Turn Faithfulness (Jev)",
        system_one_model=TypeSafeModel(
            model="typesafe/jev-1.13",
            api_key=os.environ.get("OPENROUTER_API_KEY"),
            base_url="https://openrouter.ai/api",
        ),
        evaluation_params=[MultiTurnParams.RETRIEVAL_CONTEXT],
        questions=[
            Noul("Every fact stated by the assistant appears in the retrieval_context.", weight=2),
            Score(
                "How much of the assistant's claims are grounded in the retrieval_context?",
                levels=["Fabricated", "Mostly fabricated", "Mostly grounded", "Fully grounded"],
            ),
            Choice(
                "What did the assistant do when asked for information not present in the retrieval_context?",
                options={
                    "flagged_it_as_unknown": 1.0,
                    "hedged_it": 0.5,
                    "stated_it_as_fact": 0.0,
                    "nothing_missing": None
                }
            )
        ],
        include_reason=True
    )

    # 3. Permission Gate Jev Eval (from DAG-jev.py)
    permission_gate_metric = ConversationalJevEval(
        name="Permission Gate (Jev)",
        system_one_model=TypeSafeModel(
            model="typesafe/jev-1.13",
            api_key=os.environ.get("OPENROUTER_API_KEY"),
            base_url="https://openrouter.ai/api",
        ),
        evaluation_params=[MultiTurnParams.TOOLS_CALLED],
        questions=[
            Choice(
                "Did the assistant ask for permission before sending a message?",
                options={
                    "asked_before_sending": 1.0,
                    "sent_without_asking": 0.0,
                    "did_not_send": None,
                },
            )
        ],
        strict_mode=True,
    )

    # 4. Ask Quality GEval (from GEval.py)
    ask_quality_metric = GEval(
        name="Ask Quality",
        evaluation_steps=[
            "Check whether the assistant clearly names the specific missing information or gap.",
            "Check whether the assistant offers options to resolve the gap.",
            "Check whether the assistant provides a default option."
        ],
        evaluation_params=[
            SingleTurnParams.INPUT,
            SingleTurnParams.ACTUAL_OUTPUT,
        ],
        threshold=0.7,
        model=EVAL_MODEL,
        async_mode=False,
    )

    print("Running multi-turn Jev metrics...")

    evaluate(
        test_cases=[test_case],
        metrics=[tool_use_jev, turn_faithfulness_jev, permission_gate_metric],
        async_config=AsyncConfig(
            run_async=False,
            throttle_value=1,
            max_concurrent=1,
        ),
        display_config=DisplayConfig(results_folder=RESULTS_DIR)
    )

    print("\nRunning single-turn GEval on conversational turns...")
    single_turn_cases = []
    for i, turn in enumerate(turns):
        if turn.role == "assistant" and i > 0 and turns[i-1].role == "user":
            single_turn_cases.append(LLMTestCase(
                input=turns[i-1].content,
                actual_output=turn.content
            ))
            
    if single_turn_cases:
        evaluate(
            test_cases=single_turn_cases,
            metrics=[ask_quality_metric],
            async_config=AsyncConfig(run_async=False, throttle_value=1, max_concurrent=1),
            display_config=DisplayConfig(results_folder=RESULTS_DIR)
        )

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
