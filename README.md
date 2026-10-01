# Personal Assistant Agent (Metacognition Framework)

This repository contains a **Personal Scheduling and Messaging Assistant** powered by a LangGraph AI agent. It is designed to manage calendars, send messages, look up contacts, search personal notes via RAG, and remember user preferences.

This project is a testbed for a **Metacognitive Harness**: a framework that makes the agent ask clarifying questions, disclose assumptions, or admit ignorance at the right moments, rather than guessing or making silent assumptions.

## The Three Arms
The framework runs in three isolated test modes (Arms) to evaluate the effectiveness of the harness vs. prompt engineering:
- **Arm A (Bare)**: Stripped-down prompt with no metacognition instructions. Harness runs in shadow mode (logging only).
- **Arm B (Prompt-only)**: Comprehensive prompt explicitly instructing the model not to guess. Harness runs in shadow mode.
- **Arm C (Harness)**: Stripped-down prompt. Harness runs in enforce mode (actively blocking and intervening).

## Metacognitive Harness
To ensure safety and prevent silent assumptions, the agent incorporates a robust metacognitive layer instead of traditional input/output guardrails:

### 1. Monitor (Deterministic & Jev)
Runs before any side-effect tool and emits signals if it detects:
- **Missing Slots**: Required fields like time or duration are missing.
- **Ambiguous Referents**: Lookups (e.g., "Sam") return multiple matches.
- **Stale Memory**: Relies on a durable fact that is too old.
- **Permission Needed**: Attempts to send messages or move events without standing permission.
- **Vague Wording**: Requests like "sometime next week" (via Jev `Noul` classifier).

### 2. Controller
Decides how to handle the monitor's signals:
- `PROCEED`: Low risk, high confidence.
- `PROCEED_AND_DISCLOSE`: Small gap, cheap to undo (e.g., assumed a time for a meeting). Agent tells the user what it assumed.
- `ASK`: Gap is costly or requires permission.
- `IDK`: No support in notes.

### 3. Pre-Tool-Call Hook
Intercepts side-effect tool executions. In Arm C (`enforce` mode), it uses the controller's decision to either run the tool, run it and append a disclosure, block it and force the agent to call `ask_user` (fail safe on retry), or force an "I don't know" reply.

### 4. Structured Ask Tool
The `ask_user` tool is rigorously structured to prevent "executive asks" (e.g. "what should I do?"). It requires the agent to name the specific gap, what it tried, options, and a default action. A linter rejects lazy requests.

## Tools
The agent uses the following mocked tools to accomplish its tasks:
- **`search_notes(query)`**: Searches the user's personal notes using vector embeddings.
- **`get_calendar(day)`**: Lists calendar events for a specific date.
- **`create_event(day, start, duration, title)`**: Creates a new calendar event.
- **`move_event(day, start, new_day, new_start)`**: Moves an existing event.
- **`lookup_contact(name)`**: Finds contact details by name from the contact book.
- **`draft_message(to, body)`**: Drafts a message without sending.
- **`send_message(to, body)`**: Sends a message to a specific contact.
- **`remember(key, value)`**: Saves a durable fact or preference about the user to long-term memory.
- **`recall()`**: Lists everything currently remembered about the user.
- **`ask_user(gap, tried, options, use, default)`**: Asks the user a clarifying question (linted).

*(Note: Approvals and side-effects for these tools are currently mocked and logged to a trace).*

## Memory Architecture
- **Persistent Memory (Session Checkpointing)**: Uses `SqliteSaver` backed by a SQLite database (`session_memory_{arm}.sqlite`) for persistent conversation threads.
- **Long-Term Memory (Durable Facts)**: Uses `InMemoryStore` for the `remember`/`recall` tools.

## RAG (Retrieval-Augmented Generation)
The agent features a RAG system to access personal notes via **ChromaDB** (`./chroma_db`), populated with `OpenRouterEmbeddings` (`baai/bge-m3`).

## How to Run

1. **Install dependencies:**
   Ensure you have the required packages installed.
   ```bash
   pip install -r requirements.txt
   ```
   *(If using `uv`, you can run `uv pip install -r requirements.txt`)*

2. **Configure Environment Variables:**
   Create a `.env` file in the root directory and add your OpenRouter API key (used for the LLM and Jev):
   ```ini
   OPENROUTER_API_KEY=your_api_key_here
   ```

3. **Start the Assistant:**
   Run the main script. The script will prompt you to select an arm (A, B, or C). 
   ```bash
   python assistant.py
   ```
   - Select **C** to test the full Metacognitive Harness.
   - Select **A** or **B** to run in shadow mode (logging only, without active intervention).

## Evaluation Results

The Metacognitive Harness POC successfully proved its core hypotheses in both single-turn and multi-turn evaluations:

- **Help-Seeking Improved:** The agent improved from asking for help in 16.7% of cases to **66.7%** (+50%) for missing slots and ambiguities.
- **Context Flooding Fixed:** The Turn-By-Turn verification successfully patched the permission bypass vulnerability, improving the Permission Gate pass rate from 12% to **100%**.
- **High Quality Asks:** When forced to ask the user, the agent consistently formats the question well (Ask Quality avg score: **95%**), providing options and a default.
- **Next Steps:** The remaining challenge is Turn Faithfulness; the agent still struggles to restrict answers purely to the retrieval context (passing only 6/33 times).

For full details, see the `evaluation/` directory.
