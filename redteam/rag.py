import sys
import os
from typing import Optional
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

import assistant as research_agent # type: ignore
from guardrail import check_input, check_output # type: ignore
graph = research_agent.agent
Context = research_agent.Context

from deepteam import red_team
from deepteam.test_case import RTTurn, ToolCall
from deepteam.vulnerabilities import (
    Robustness, PIILeakage, PromptLeakage,
    CrossContextRetrieval, Misinformation, Hallucination
)
from deepteam.attacks.single_turn import (
    PromptInjection, ContextFlooding,
    SyntheticContextInjection, Roleplay, Leetspeak
)

async def model_callback(input: str, turns: list[RTTurn] | None = None) -> RTTurn:
    input_res = check_input(input)
    if not input_res["allowed"]:
        return RTTurn(
            role="assistant",
            content="Input blocked by guardrails:\n" + str(input_res.get("message", "")),
            tools_called=[],
            retrieval_context=[]
        )

    history = []
    for turn in (turns or []):
        if turn.role == "user":
            history.append(HumanMessage(content=turn.content))
        elif turn.role == "assistant":
            history.append(AIMessage(content=turn.content))
            
    history.append(HumanMessage(content=input))
    old_msg_count = len(history)
    
    state = {"messages": history}
    result = await graph.ainvoke(
        state,  # type: ignore
        config={"configurable": {"thread_id": "red-team-session"}},
        context=Context(user_id="red-team-user"),
    )
    
    new_messages = result["messages"][old_msg_count:]
    last_msg = result["messages"][-1]
    
    tools_called = []
    for msg in new_messages:
        if getattr(msg, "type", "") == "ai" and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                output = ""
                for m in new_messages:
                    if getattr(m, "type", "") == "tool" and getattr(m, "tool_call_id", "") == tc.get("id"):
                        output = str(m.content)
                        break
                tools_called.append(
                    ToolCall(
                        name=tc.get("name", ""),
                        input_parameters=tc.get("args", {}),
                        output=output
                    )
                )

    # Extract retrieval context for RAG evaluation
    retrieval_context = []
    for tc in tools_called:
        if tc.name == "retrieve_documents":
            retrieval_context.append(tc.output)

    output_text = str(last_msg.content)
    output_res = check_output(input, output_text)
    if not output_res["allowed"]:
        return RTTurn(
            role="assistant",
            content="Output blocked by guardrails:\n" + str(output_res.get("message", "")),
            tools_called=tools_called,
            retrieval_context=retrieval_context
        )

    return RTTurn(
        role="assistant",
        content=output_text,
        retrieval_context=retrieval_context,
        tools_called=tools_called
    )

if __name__ == "__main__":
    rag_vulnerabilities = [
        Robustness(),
        PIILeakage(),
        PromptLeakage(),
        CrossContextRetrieval(),
        Misinformation(),
        Hallucination(),
    ]

    import sys, os
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from config import get_attacker_model, get_redteam_judge_model
    
    risk_assessment = red_team(
        simulator_model=get_attacker_model(),
        evaluation_model=get_redteam_judge_model(),
        model_callback=model_callback,  # type: ignore
        target_purpose="AI Customer Support Agent with RAG that analyzes internal documentation and knowledge base.",
        vulnerabilities=rag_vulnerabilities,
        attacks=[  # type: ignore
            PromptInjection(),
            ContextFlooding(),
            SyntheticContextInjection(target_information="Historical test logs and code changes"),
            Roleplay(),
            Leetspeak(),
        ],
        attacks_per_vulnerability_type=1,
    )

    risk_assessment.save(to="./deepteam-results/")

    import os, glob
    list_of_files = glob.glob('./deepteam-results/*.json')
    if list_of_files:
        latest_file = max(list_of_files, key=os.path.getctime)
        new_name = "./deepteam-results/rag_results.json"
        if os.path.exists(new_name) and latest_file != os.path.abspath(new_name).replace('\\\\', '/'):
            try: os.remove(new_name)
            except: pass
        if latest_file != new_name and not latest_file.endswith("rag_results.json"):
            os.rename(latest_file, new_name)
