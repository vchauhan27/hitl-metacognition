# Evaluation Suite

This folder contains the evaluation scripts used to measure the performance of the metacognitive harness (the guardrail). The evaluation is designed strictly around a **Before vs. After** methodology to mathematically prove the reduction in silent assumptions and missed asks.

To eliminate "judge noise" where possible and reduce testing costs, the evaluation suite is split into two specialized tracks: **Single-Turn** and **Multi-Turn**.

## 1. Single-Turn Tests (The Main Track)
**File:** `agent-eval-jev.py`

This script evaluates the **Monitor**. It tests whether the agent correctly notices when it is missing information or when a request is ambiguous.

* **How it works:** It loads the single-turn scenarios from `data/scenarios.json` and runs each scenario 3 times with fresh thread IDs.
* **Metrics Included:**
  * **Trace Baseline:** Deterministically checks if the agent made silent assumptions or missed necessary asks without relying on AI judges.
  * **Tool Correctness:** Checks if the agent called the exact expected tools (e.g., `ask_user` when there is a gap).
  * **Disclosure Proxy (JevEval):** Checks if the agent stated its assumptions when proceeding with minor gaps.
  * **Knowledge Gap Proxy (JevEval):** Reads the `search_notes` retrieval context to check if the agent flagged missing info as unknown or falsely stated it as fact.

**To run:**
```bash
python evaluation\agent-eval-jev.py
```

## 2. Multi-Turn Tests (The Conversational Track)
**File:** `multi-turn-eval-jev.py`

This script evaluates the **Execution & Ask Tool**. Once the Monitor notices a gap, this suite tests if the agent asks a high-quality question, respects permission boundaries, and correctly uses conversational context.

* **How it works:** It simulates a multi-turn conversation using the `conversational_scenarios` from `data/scenarios.json`.
* **Metrics Included:**
  * **Tool Use & Turn Faithfulness (JevEval):** Checks if the agent hallucinated tools and if claims are grounded in retrieval context.
  * **Permission Gate (JevEval):** Checks if the assistant strictly asked for permission before executing side-effect tools (like `send_message`).
  * **Ask Quality (G-Eval):** A subjective rubric that verifies if the agent's questions clearly name the specific gap, offer options, and provide a default (rejecting lazy "what should I do?" prompts).

**To run:**
```bash
python evaluation\multi-turn-eval-jev.py
```

## Workflow
1. **The Baseline ("Before"):** Run both scripts against the base `assistant.py` (with guardrails disabled). Record the missed asks and failed metrics.
2. **Build the Harness:** Implement the Monitor, Controller, and Ask Linter.
3. **The Final Eval ("After"):** Run both scripts again to prove the guardrail correctly intercepted the failures.
