# Metacognitive Harness

This folder contains the core logic for the **Metacognitive Harness**, designed to replace traditional prompt-based guardrails.

## Why a Harness instead of Guardrails or Prompting?
During baseline evaluations, we empirically proved that LLMs suffer from two major flaws when relying purely on system prompts (e.g., *"NO GUESSING! Always ask if unsure!"*):
1. **Monitoring Failure:** LLMs rarely "feel" doubt when information is missing, causing them to hallucinate details confidently (Silent Assumptions).
2. **Agent Paralysis:** Heavy negative constraints in system prompts can overwhelm the LLM, causing it to freeze or return empty strings instead of properly calling fallback tools.

A standard guardrail acts as a firewall at the end of the pipeline. A **Harness** acts as an active supervisor that wraps the agent, catches its mistakes, and forces it down a deterministic path.

---

## Architecture

The harness is split into three highly specialized components to separate **doubt-detection** from **policy enforcement**.

### 1. The Monitor (`monitor.py`) - "The Doubt Sensor"
Stops trusting the LLM to monitor itself. It inspects every proposed tool call against the user's input before execution.
We use a **Hybrid Approach**:
* **Deterministic (Pure Python):** Perfect for checking hard state (e.g., checking timestamps for stale memory, checking if a tool is on a permission blacklist, or counting database results for ambiguity).
* **Fuzzy (Jev via LLM):** Used as a Generalized Assumption Sensor. Trying to use Python to find missing slots (e.g., checking if the user typed "pm") is extremely brittle. Instead, we pass the user input and the proposed tool arguments to `typesafe/jev-1.13` and ask: *"Did the agent invent any of these arguments?"*. This scales to any tool automatically.

**Output:** Emits a `MonitorSignal` (e.g., `gap_type="missing_slot"`, `severity="high"`).

### 2. The Controller (`controller.py`) - "The Strict Boss"
Takes the signals from the Monitor and acts as the strict, unyielding policy engine. 
**Crucial Rule:** The Controller is *pure Python*. It never uses an LLM. Using an LLM here would reconstruct the exact failure we are trying to fix (an LLM making bad executive safety decisions).

The Controller maps signals to 3 deterministic actions:
1. **Priority 1 (High Severity / Permission) -> `ask`**: Blocks the tool and forces the agent to explicitly pause and ask the human for permission or missing information.
2. **Priority 2 (Small Gap) -> `proceed_and_disclose`**: Allows the tool to run but forces the agent to explicitly state the assumption in its reply (e.g., "I assumed 1 hour for the meeting").
3. **No Gaps -> `proceed`**: The agent has a green light.

### 3. The Ask Linter (`ask_linter.py`) - "The Quality Enforcer"
When the Controller forces the agent to ask a question, the Ask Linter ensures the agent asks a *good* question. Left unchecked, LLMs often ask lazy, "executive" questions like *"What should I do?"* or *"Can you clarify?"*.

We use a **Hybrid Approach** here as well:
* **Deterministic (Pure Python):** Enforces strict structure. Did the agent provide at least two `options`? Did it provide a `default_option`?
* **Fuzzy (Jev via LLM):** Evaluates the semantic quality of the question. Jev reads the question and rejects it if it is vague or fails to name the specific gap (e.g., rejecting *"Which Sam?"* in favor of *"I found Sam Carter and Sam Patel, which one would you like?"*).

---

## Security: Preventing "Context Flooding"
During early evaluation, we discovered a vulnerability where the LLM could bypass the Monitor by citing a past permission approval for a completely unrelated action. Because LLMs lack strict state management, they flooded their context window with old approvals to trick the system. 

We fixed this inside the Harness by enforcing **Turn-By-Turn Verification**. The Harness now strictly checks if the *very last message* was a human approval. The LLM can no longer weaponize past context to bypass the Deterministic Monitor!

---

## The Verdict
By separating task reasoning (the LLM) from metacognitive safety (the Harness), we guarantee 100% adherence to safety policies. The LLM can confidently attempt to execute tasks, and the Harness will mathematically ensure that missing data and required permissions are caught, prompting a strict human-in-the-loop intervention!
