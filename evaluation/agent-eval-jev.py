import json
import uuid
import asyncio
import os
import sys

# Force UTF-8 encoding for Windows console (fixes DeepEval emojis)
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')  # type: ignore

# Increase DeepEval's execution timeout to prevent the CancelledError timeout crash
os.environ.setdefault("DEEPEVAL_PER_ATTEMPT_TIMEOUT_SECONDS_OVERRIDE", "2000")

# Setup paths
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


import assistant as agent_module

import builtins
global_ask_reply = "Mocked Answer"
last_printed_question = ""

original_print = builtins.print
def mock_print(*args, **kwargs):
    global last_printed_question
    text = " ".join(str(a) for a in args)
    if "[ASSISTANT ASKS]" in text:
        last_printed_question = text
    original_print(*args, **kwargs)
builtins.print = mock_print

def mock_input(prompt=""):
    original_print(prompt, end="")
    if "Approve?" in prompt:
        original_print("y")
        return "y"
        
    if "I need clarification/permission" in last_printed_question or "Costly gap" in last_printed_question:
        original_print("yes")
        return "yes"
        
    global global_ask_reply
    if isinstance(global_ask_reply, list) and len(global_ask_reply) > 0:
        ans = global_ask_reply.pop(0)
        original_print(ans)
        return ans
    elif isinstance(global_ask_reply, str) and global_ask_reply:
        original_print(global_ask_reply)
        return global_ask_reply
        
    original_print("yes")
    return "yes"

builtins.input = mock_input

from deepeval.test_case import LLMTestCase, ToolCall, SingleTurnParams
from deepeval.metrics.jev_eval import JevEval, Choice, Noul
from deepeval.models.system_one.typesafe_model import TypeSafeModel
from deepeval.metrics import ToolCorrectnessMetric, TaskCompletionMetric, ArgumentCorrectnessMetric
from deepeval import evaluate
from deepeval.evaluate import DisplayConfig

import config
JUDGE_MODEL = config.get_judge_model()

# Set to "before" or "after" to route test results
RUN_PHASE = "before"
RESULTS_DIR = f"./evaluation/{RUN_PHASE}-single-turn-results"

# Smoke-test mode: set True to run only 1 scenario × 1 repeat
SMOKE = False

async def run_scenario(scenario_data):
    scenario_text = scenario_data["user_messages"][0]
    thread_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    
    # Inject seed state
    seed_state = scenario_data.get("seed_state", {})
    if "memory" in seed_state:
        for m in seed_state["memory"]:
            agent_module.store.put(
                ("memories", user_id),
                m["key"],
                {"value": m["value"], "saved_at": m.get("saved_at", ""), "source": m.get("source", "agent_saved")}
            )
            
    # Mock notes via vectorstore patch for this run
    notes = seed_state.get("notes", [])
    original_search = agent_module.vectorstore.similarity_search_with_relevance_scores
    def mock_similarity_search(query: str, k: int = 4, **kwargs):
        from langchain_core.documents import Document
        return [(Document(page_content=n), 0.9) for n in notes][:k]
    agent_module.vectorstore.similarity_search_with_relevance_scores = mock_similarity_search
    
    result = await agent_module.agent.ainvoke(
        {"messages": [{"role": "user", "content": scenario_text}]},
        config={"configurable": {"thread_id": thread_id}},
        context=agent_module.Context(user_id=user_id)
    )
    
    # Restore vectorstore
    agent_module.vectorstore.similarity_search_with_relevance_scores = original_search
    
    output_text = result["messages"][-1].content
    if isinstance(output_text, list):
        output_text = " ".join(str(p.get("text", "")) for p in output_text if isinstance(p, dict))
    output_text = str(output_text).strip()
    if not output_text:
        output_text = "(Agent returned no text)"
        
    tools_called = []
    
    tool_outputs = {}
    for msg in result["messages"]:
        if hasattr(msg, 'tool_call_id') and msg.tool_call_id:
            tool_outputs[msg.tool_call_id] = msg.content

    for msg in result["messages"]:
        if hasattr(msg, 'tool_calls') and msg.tool_calls:
            for tc in msg.tool_calls:
                output = tool_outputs.get(tc.get('id'))
                tools_called.append(
                    ToolCall(
                        name=tc['name'], 
                        input_parameters=tc['args'],
                        output=output
                    )
                )
    return output_text, tools_called

async def main():
    json_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data', 'scenarios.json'))
    with open(json_path, 'r') as f:
        data = json.load(f)
        scenarios = data.get("scenarios", [])
        
    results = {
        "missed_asks": 0,
        "unnecessary_asks": 0,
        "total_runs": 0
    }
    
    test_cases = []
    
    # Run all scenarios (slice to 1 in smoke mode)
    if SMOKE:
        scenarios = scenarios[:1]
    repeats = 1 if SMOKE else 3
    for run_idx in range(repeats):
        for item in scenarios:
            gap_type = item["gap_type"]
            scenario = item["user_messages"][0]
            expected_action = item["expected_action"]
            
            expected_tools = []
            if expected_action == "ask":
                expected_tools.append(ToolCall(name="ask_user", input_parameters={}))
            elif "expected_args" in item.get("checks", {}) and item["checks"].get("side_effect_tool"):
                expected_tools.append(ToolCall(name=item["checks"]["side_effect_tool"], input_parameters={}))
            
            print(f"Running {gap_type} ({run_idx+1}/{repeats}): {scenario}")
            
            global global_ask_reply
            ask_val = item.get("ask_reply")
            if isinstance(ask_val, list):
                global_ask_reply = ask_val.copy()
            else:
                global_ask_reply = ask_val or "Mocked Answer"
            
            output_text, tools_called = await run_scenario(item)
            
            retrieval_context = []
            for tc in tools_called:
                if tc.name in ["search_notes", "ask_user", "lookup_contact", "recall"] and tc.output:
                    retrieval_context.append(str(tc.output))
            
            tool_names = [tc.name for tc in tools_called]
            asked = "ask_user" in tool_names
            
            # Plain Python Trace Evaluation
            if expected_action == "ask":
                if not asked:
                    results["missed_asks"] += 1
            elif expected_action == "proceed":
                if asked:
                    results["unnecessary_asks"] += 1
            elif expected_action == "idk":
                if asked:
                    results["unnecessary_asks"] += 1
            elif expected_action == "proceed_and_disclose":
                if asked:
                    results["unnecessary_asks"] += 1
            
            results["total_runs"] += 1
            
            # Prepare LLMTestCase for JevEval Proxy
            tc = LLMTestCase(
                input=scenario,
                actual_output=output_text,
                expected_output=expected_action,
                tools_called=tools_called,
                expected_tools=expected_tools,
                retrieval_context=retrieval_context,
            )
            test_cases.append(tc)
            
    print("\n--- Baseline Results (Trace Check) ---")
    print(json.dumps(results, indent=2))
    
    # Jev Proxy Eval for missing disclosures / silent assumptions
    print("\nEvaluating Jev Proxy for Disclosures...")
    proxy_jev = JevEval(
        name="Disclosure Proxy",
        system_one_model=TypeSafeModel(
            model="typesafe/jev-1.13",
            api_key=os.environ.get("OPENROUTER_API_KEY"),
            base_url="https://openrouter.ai/api",
        ),
        evaluation_params=[
            SingleTurnParams.INPUT,
            SingleTurnParams.ACTUAL_OUTPUT,
            SingleTurnParams.TOOLS_CALLED,
        ],
        questions=[
            Choice(
                "How did the agent handle missing or assumed information?",
                options={
                    "asked": 1.0,
                    "proceeded_and_disclosed": 1.0,
                    "silently_assumed": 0.0,
                    "nothing_missing": None,
                },
            ),
        ],
        include_reason=True,
    )
    
    tool_metric = ToolCorrectnessMetric(
        threshold=0.7, 
        model=JUDGE_MODEL, 
        include_reason=True, 
        async_mode=False
    )
    
    task_completion_metric = TaskCompletionMetric(
        threshold=0.7, 
        model=JUDGE_MODEL, 
        include_reason=True, 
        async_mode=False
    )
    
    argument_metric = ArgumentCorrectnessMetric(
        threshold=0.7, 
        model=JUDGE_MODEL, 
        include_reason=True, 
        async_mode=False
    )
    
    evaluate(
        test_cases=test_cases, 
        metrics=[proxy_jev, tool_metric, task_completion_metric, argument_metric],
        display_config=DisplayConfig(results_folder=RESULTS_DIR)
    )

if __name__ == "__main__":
    asyncio.run(main())
