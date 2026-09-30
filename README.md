# Personal Assistant Agent

This repository contains a **Personal Scheduling and Messaging Assistant** powered by a LangGraph AI agent. It is designed to manage calendars, send messages, look up contacts, search personal notes via RAG, and remember user preferences using multiple forms of memory.

## What the Agent Does
The agent acts as a personal assistant that handles daily scheduling and communication tasks. It is equipped with tools to interact with a mock calendar, contact book, vector database of notes, and a long-term memory store. A key aspect of the agent is its interactive capability—it requires explicit user approval before performing sensitive actions (like creating events or sending messages) and can ask clarifying questions if details are ambiguous.

## The Agent Prompt
The agent is guided by the following strict system prompt:

```text
You are a personal scheduling and messaging assistant. Today is {today}.

CRITICAL RULES:
1. ISOLATE TASKS: Treat each new user request as a completely separate task. DO NOT carry over subjects, meetings, or context from previous requests unless the user explicitly refers to them.
2. CHAIN TOOLS: If you are asked to schedule something for a role (e.g. 'the person who owns the technical sections'), ALWAYS use `search_notes` first to find their name, then use `lookup_contact` to get their email.
3. RESOLVE AMBIGUITY: If the user provides a partial name (like 'Sam'), you MUST use `lookup_contact`. If multiple people match, you MUST use `ask_user` to clarify which person they mean before doing anything else.
4. NO GUESSING: If a required detail (time, duration, exact person) is missing or ambiguous after using your tools, call `ask_user`. Do not guess.
5. Keep replies short and direct.
```

## Tools
The agent uses the following tools to accomplish its tasks:
- **`search_notes(query)`**: Searches the user's personal notes using vector embeddings.
- **`get_calendar(day)`**: Lists calendar events for a specific date.
- **`create_event(day, start, title)`**: Creates a new calendar event. (Requires user approval via CLI).
- **`lookup_contact(name)`**: Finds contact details by name from the contact book.
- **`send_message(to, body)`**: Sends a message to a specific contact. (Requires user approval via CLI).
- **`remember(key, value)`**: Saves a durable fact or preference about the user to long-term memory.
- **`recall()`**: Lists everything currently remembered about the user.
- **`ask_user(question, options)`**: Asks the user a clarifying question and blocks until an answer is received via CLI input.

## Memory Architecture
The agent leverages three distinct types of memory to provide a seamless and context-aware experience:

### 1. Short-Term Memory (Context Summarization)
The agent maintains ongoing conversation history using state tracking. To prevent the context window from overflowing, it employs a **Context Summarization** strategy. Once the conversation exceeds a threshold (10 messages), the agent summarizes the older messages (while keeping the 4 most recent messages intact). The summarized version replaces the old messages, freeing up context space while retaining the gist of the conversation history.

### 2. Persistent Memory (Session Checkpointing)
The agent uses `langgraph.checkpoint.sqlite.SqliteSaver` backed by a SQLite database (`session_memory.sqlite`) as a persistent checkpointer. This allows the session memory (the current conversation thread) to persist across different script executions, enabling the user to exit and return without losing their place in the ongoing conversation thread.

### 3. Long-Term Memory (Durable Facts)
The agent uses a `langgraph.store.memory.InMemoryStore` to manage durable facts and preferences about the user. The agent explicitly uses the `remember` and `recall` tools to write to and read from this store, enabling it to remember user facts (like "favorite fruit is pineapple") across extended interactions.

## RAG (Retrieval-Augmented Generation)
The agent features a RAG system to access the user's personal notes. It uses a **ChromaDB** vector store (`./chroma_db`) populated with embeddings generated via `OpenRouterEmbeddings` (`baai/bge-m3` model). When the agent needs to find information in notes, it uses the `search_notes` tool, which performs a similarity search with relevance scoring against the Chroma vector database and returns the most relevant note passages.

## Guardrail System
To ensure safety and relevance, the agent incorporates a robust **Guardrail Pipeline** powered by `TypeSafe (Jev)`. Every request and response is screened through this system before being processed or shown to the user:
- **Input Screening**: User messages are checked for prompt injections (jailbreaks), off-topic requests (only scheduling, contacts, messaging, notes, and general conversation are allowed), and overall severity/harm.
- **Output Screening**: The agent's replies are checked to ensure they do not violate policy (e.g., complying with something it should have refused) and do not contain severe/harmful content.
- **Fail Closed**: If the Guardrail API fails, the system defaults to blocking the request and returns a safe "service error" message.
