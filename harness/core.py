# ==========================================
# harness/core.py (Merged Wrapper & Controller)
# ==========================================
"""Shared signal type emitted by every failure module and consumed by the Controller."""


class MonitorSignal:
    def __init__(self, gap_type: str, severity: str, message: str, requires_ask: bool = False,
                 failure_type: str = "", options: list | None = None):
        self.gap_type = gap_type
        self.severity = severity  # 'low', 'medium', 'high'
        self.message = message
        self.requires_ask = requires_ask
        # Which human failure type this signal is a fix for (monitoring / control / ...)
        self.failure_type = failure_type
        # Optional concrete choices to offer the user when the Controller routes to "ask"
        self.options = options or []

    def __repr__(self):
        return (f"MonitorSignal({self.failure_type}:{self.gap_type}, {self.severity}, "
                f"requires_ask={self.requires_ask})")


import logging
from typing import List

log = logging.getLogger("controller")

# Global event list for evaluation scripts to read from
INTERVENTION_EVENTS = []

class ControllerAction:
    def __init__(self, action: str, reason: str, signals: List[MonitorSignal]):
        # Valid actions: 'proceed', 'proceed_and_disclose', 'ask'
        self.action = action
        self.reason = reason
        self.signals = signals

    def __repr__(self):
        return f"ControllerAction(action='{self.action}', reason='{self.reason}')"


class Controller:
    """
    The fixed policy that maps Monitor signals to deterministic actions.
    This entirely removes the burden of metacognition from the LLM.
    """
    
    def __init__(self):
        # We define which gaps are considered "small gaps" (cheap to undo).
        # For example, adding a reminder with no specific time might be cheap to undo,
        # but booking a flight is costly. 
        self.small_gaps = ["minor_missing_slot", "cheap_assumption"]

    def decide(self, signals: List[MonitorSignal]) -> ControllerAction:
        """
        Evaluate the signals and return the safest bounded action.
        Precedence: ask > proceed_and_disclose > proceed
        """
        if not signals:
            return ControllerAction("proceed", "No gaps detected. High confidence.", [])
            
        # Priority 1: Knowledge gaps -> Ask human for missing info
        for sig in signals:
            if sig.gap_type == "knowledge_gap":
                return ControllerAction(
                    "ask", 
                    "Agent attempting to hallucinate facts without RAG support. Seeking human help.", 
                    signals
                )
                
        # Priority 2: High severity gaps or strict permissions -> Ask
        for sig in signals:
            if sig.severity in ["high", "medium"] or sig.requires_ask:
                return ControllerAction(
                    "ask", 
                    f"Costly gap or permission rule fired: {sig.message}", 
                    signals
                )
                
        # Priority 3: Small gaps, cheap to undo -> Proceed and disclose
        for sig in signals:
            if sig.gap_type in self.small_gaps or sig.severity == "low":
                return ControllerAction(
                    "proceed_and_disclose", 
                    f"Small gap detected, proceeding with disclosure: {sig.message}", 
                    signals
                )
                
        # Fallback safe default
        return ControllerAction("ask", "Unhandled gap type, defaulting to safe ask.", signals)


"""
HarnessModelWrapper — couples the failure modules to the LangGraph agent.

Wraps the chat model. After every model call it inspects the proposed tool calls and,
via the Controller, may rewrite them into a structured `ask_user`, drop them, or
attach a disclosure. Implements the plan's harness fixes:

  Part 3  approval scope       -> approvals keyed by (tool, recipient) and reset each human turn
  Part 4  standing permissions -> PermissionGate consults memory before asking (underconfidence)
  Part 5  proactive recall     -> harness reads memory itself and flags stale preferences
  Part 6  Jev false alarms     -> threshold 0.90 + grounding pre-check, side-effect tools only
  Part 9  refusal path         -> a "no" to a harness ask blocks that exact action
  Part 12 post-tool hook       -> ambiguous lookup_contact RESULTS block create_event/send_message
  Part 12 store injection      -> store passed at construction (falls back to runtime.store)
"""
import re
from typing import Any

from harness.failures.control import PermissionGate
from harness.failures.monitoring import MonitoringChecks, JevAssumptionSensor
from harness.failures.executive_asking import AskLinter

# Marker embedded in harness permission asks. The eval mocks key off this phrase.
PERMISSION_PREFIX = "I need clarification/permission"
SCOPE_RE = re.compile(r"\[scope: ([\w]+)\|([^\]]*)\]")
AFFIRMATIVE_RE = re.compile(r"^\s*(y|yes|yep|sure|ok|okay|approve|approved|go ahead|send it|do it)\b", re.I)

SIDE_EFFECT_TOOLS = {"create_event", "send_message", "move_event"}
GROUNDING_TOOLS = {"search_notes", "lookup_contact", "recall", "get_calendar", "ask_user"}


def _mtype(m) -> str:
    t = getattr(m, "type", None)
    if t:
        return t
    if isinstance(m, dict):
        role = str(m.get("role") or "")
        return {"user": "human", "assistant": "ai"}.get(role, role)
    return ""


def _text(content) -> str:
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict))
    return str(content or "")


class HarnessModelWrapper:
    def __init__(self, model, store=None, contacts: dict | None = None, user_id: str | None = None):
        self.model = model
        self.store = store
        self.contacts = contacts or {}
        self.default_user_id = user_id
        self.gate = PermissionGate(contacts=self.contacts)
        self.monitoring = MonitoringChecks()
        self.jev = JevAssumptionSensor(threshold=0.75)
        self.controller = Controller()
        self.ask_linter = AskLinter()

    def _clone(self, model):
        return HarnessModelWrapper(model, store=self.store, contacts=self.contacts, user_id=self.default_user_id)

    def bind_tools(self, *args, **kwargs):
        return self._clone(self.model.bind_tools(*args, **kwargs))

    def with_config(self, *args, **kwargs):
        return self._clone(self.model.with_config(*args, **kwargs))

    def __getattr__(self, name):
        return getattr(self.model, name)

    # ------------------------------------------------------------------ memory
    def _runtime(self):
        try:
            from langgraph.runtime import get_runtime
            return get_runtime()
        except Exception:
            return None

    def _recall_fn(self):
        rt = self._runtime()
        store = self.store or getattr(rt, "store", None)
        ctx = getattr(rt, "context", None)
        user_id = getattr(ctx, "user_id", None) or self.default_user_id
        if store is None or not user_id:
            return lambda: []

        def recall():
            items = store.search(("memories", user_id), limit=50)
            return [{"key": i.key, "value": i.value} for i in items]
        return recall

    # ------------------------------------------------------------------ helpers
    def _contact_names_mentioned(self, text_lower: str, names: list[str]) -> bool:
        for n in names:
            info = self.contacts.get(n, "")
            email = info.split()[0].lower() if info else ""
            if n.lower() in text_lower or (email and email in text_lower):
                return True
        return False

    def _stale_memory_signals(self, tc_name: str, scope: str, recall_fn) -> list[MonitorSignal]:
        """Part 5: the harness pulls memory itself — fires even if the agent never called recall()."""
        out = []
        aliases = self.gate.recipient_aliases(scope) if tc_name == "send_message" else []
        for mem in recall_fn():
            key, val = mem["key"], mem.get("value") or {}
            text = str(val.get("value", ""))
            if key.startswith("standing_permission") or "scope:" in text.lower():
                continue  # permissions are handled by the control/underconfidence path
            if tc_name == "send_message" and not any(a in text.lower() for a in aliases):
                continue  # only preferences about this recipient matter for a message
            sig = self.monitoring.check_stale_memory(val.get("saved_at", ""))
            if sig:
                sig.message = (f"Stored preference '{key}' (\"{text}\") is outdated — {sig.message} "
                               f"Please confirm it still applies before I proceed.")
                out.append(sig)
        return out

    # ------------------------------------------------------------------ core
    RELATIVE_DAY_RE = re.compile(
        r"\b(today|tomorrow|tonight|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I)
    DISCLOSURE_RE = re.compile(r"\[Disclosure:.*?\]", re.S)

    def _carry_disclosure(self, messages, ai_message):
        last_human = max((i for i, m in enumerate(messages) if _mtype(m) == "human"), default=-1)
        found = []
        for m in messages[last_human + 1:]:
            if _mtype(m) == "ai":
                found += self.DISCLOSURE_RE.findall(_text(getattr(m, "content", "")))
        text = _text(ai_message.content)
        missing = [d for d in dict.fromkeys(found) if d not in text]
        if missing:
            ai_message.content = (text + "\n" + "\n".join(missing)).strip()
        return ai_message

    def _apply_harness(self, input_data, ai_message):
        messages = input_data.get("messages", []) if isinstance(input_data, dict) else list(input_data or [])
        tool_calls = list(getattr(ai_message, "tool_calls", None) or [])
        if not tool_calls:
            return self._carry_disclosure(messages, ai_message)

        # Current turn = everything after the last human message (approvals never cross turns).
        last_human = max((i for i, m in enumerate(messages) if _mtype(m) == "human"), default=-1)
        turn = messages[last_human + 1:]

        user_inputs, grounding = [], []
        if last_human != -1:
            user_inputs.append(_text(getattr(messages[last_human], "content", "")))
            
        for i, m in enumerate(messages):
            t = _mtype(m)
            if t == "human":
                grounding.append(_text(getattr(m, "content", "")))
            elif t == "tool" and getattr(m, "name", None) in GROUNDING_TOOLS:
                grounding.append(_text(m.content))
                if m.name == "ask_user" and i > last_human:
                    user_inputs.append(_text(m.content))
        combined_user_input = "\n".join(user_inputs)
        user_text_lower = combined_user_input.lower()
        retrieval_context = "\n".join(grounding)

        # Approval ledger for THIS turn, scoped as (tool, recipient/slot) tuples.
        ask_questions = {}
        for m in turn:
            if _mtype(m) == "ai":
                for tcall in getattr(m, "tool_calls", None) or []:
                    if tcall.get("name") == "ask_user":
                        ask_questions[tcall.get("id")] = tcall.get("args", {}).get("question", "")
        approved, denied = set(), set()
        for m in turn:
            if _mtype(m) == "tool" and getattr(m, "name", None) == "ask_user":
                match = SCOPE_RE.search(ask_questions.get(getattr(m, "tool_call_id", None), ""))
                if match:
                    scope = (match.group(1), match.group(2))
                    (approved if AFFIRMATIVE_RE.match(_text(m.content)) else denied).add(scope)

        # Post-tool-result hook: most recent lookup_contact result in this turn.
        ambiguity_sig = None
        for m in reversed(turn):
            if _mtype(m) == "tool" and getattr(m, "name", None) == "lookup_contact":
                ambiguity_sig = self.monitoring.check_ambiguous_contact_from_text(_text(m.content))
                if ambiguity_sig and self._contact_names_mentioned(user_text_lower, ambiguity_sig.options):
                    ambiguity_sig = None  # user already named exactly who they meant
                break

        recall_fn = self._recall_fn()
        forced_content = _text(ai_message.content)
        new_tool_calls = []

        # Anti-loop check: track previously executed side-effect tools in this turn
        executed_side_effects = set()
        for m in turn:
            if _mtype(m) == "ai":
                for tcall in getattr(m, "tool_calls", None) or []:
                    if tcall["name"] in SIDE_EFFECT_TOOLS:
                        executed_side_effects.add((tcall["name"], str(tcall.get("args", {}))))

        # Catch and reject conversational questions
        has_ask_tool = any(tc["name"] == "ask_user" for tc in tool_calls)
        if not has_ask_tool and forced_content and "?" in forced_content:
            return {
                "linter_rejected": True,
                "tool_call": None,
                "feedback": "Ask rejected: You asked a question using conversational text. You MUST use the `ask_user` tool to ask questions so the UI can render structured options.",
                "ai_message": ai_message
            }

        for tc in tool_calls:
            name, args = tc["name"], dict(tc.get("args") or {})
            
            # Prevent infinite loops (e.g. LLM repeating same action after PROCEED_AND_DISCLOSE)
            if name in SIDE_EFFECT_TOOLS and (name, str(args)) in executed_side_effects:
                if not forced_content:
                    forced_content = "Action complete."
                continue

            if name not in SIDE_EFFECT_TOOLS:
                if name == "ask_user":
                    q = str(args.get("question", ""))
                    opts = args.get("options", [])
                    d_opt = str(args.get("default_option", ""))
                    fb = self.ask_linter.lint(q, opts, d_opt)
                    if not fb.is_valid:
                        return {"linter_rejected": True, "tool_call": tc, "feedback": fb.feedback, "ai_message": ai_message}
                new_tool_calls.append(tc)
                continue

            scope = self.gate.scope_key(name, args)
            if scope in denied:
                print(f"\n[HARNESS: Control] User denied {scope}; blocking the action.")
                forced_content = f"Understood — I won't {name.replace('_', ' ')} ({scope[1] or 'as requested'})."
                new_tool_calls = [t for t in new_tool_calls if t["name"] not in SIDE_EFFECT_TOOLS]
                break
            if scope in approved:
                new_tool_calls.append(tc)   # user approved this exact action this turn
                continue

            signals = []
            if not ambiguity_sig:
                text_to_check = str(args.get("to") or "") if name == "send_message" else str(args.get("title") or "") if name == "create_event" else ""
                ambiguity_sig = self.monitoring.check_ambiguous_contact_pre(text_to_check, self.contacts)
            
            if ambiguity_sig:
                signals.append(ambiguity_sig)
            sig = self.gate.check_permission(name, args, recall_fn=recall_fn)
            if sig:
                signals.append(sig)
            signals.extend(self._stale_memory_signals(name, scope[1], recall_fn))
            if not ambiguity_sig and name in SIDE_EFFECT_TOOLS:
                sig = self.jev.check_assumptions(combined_user_input, name, args, retrieval_context)
                if sig:
                    signals.append(sig)

            for s in signals:
                print(f"\n[HARNESS: {s.failure_type or 'monitor'}] {s.message}")

            action = self.controller.decide(signals)
            if action.action == "proceed":
                new_tool_calls.append(tc)
                continue
            
            INTERVENTION_EVENTS.append({
                "action": action.action,
                "tool": name,
                "signals": [s.__dict__ for s in signals]
            })
            
            print(f"[HARNESS: Controller] Overriding agent to: {action.action.upper()}")


            if action.action == "proceed_and_disclose":
                forced_content += f"\n[Disclosure: {' '.join(s.message for s in signals)}]"
                new_tool_calls.append(tc)
                continue

            # action == "ask": one targeted ask, drop remaining side-effect calls this step.
            if ambiguity_sig:
                ask_args = {
                    "question": ambiguity_sig.message,
                    "options": ambiguity_sig.options,
                    "default_option": ambiguity_sig.options[0],
                }
            else:
                reasons = " ".join(s.message for s in signals)
                target = f" for '{scope[1]}'" if scope[1] else ""
                marker = f"[scope: {scope[0]}|{scope[1]}]"
                # Fix 3: give stale-memory asks their own prefix so the scripted reply is used
                if any(s.gap_type == "stale_memory" for s in signals):
                    # Monitoring ask, not a permission ask: answered by the user, not auto-approved.
                    question = (f"Before I run {name}{target}: {reasons} "
                                f"Should I go ahead (and update the preference)? {marker}")
                    ask_args = {"question": question, "options": ["yes", "no"], "default_option": "no"}
                elif any(s.gap_type == "missing_slot" for s in signals):
                    question = (f"You didn't say when. Should I book '{args.get('title')}' on "
                                f"{args.get('day')} at {args.get('start')}? {marker}")
                    ask_args = {"question": question,
                                "options": [f"Yes, {args.get('day')} {args.get('start')}", "No, I'll give a day and time"],
                                "default_option": "No, I'll give a day and time"}
                else:
                    question = (f"{PERMISSION_PREFIX} to run {name}{target} with args {args}. "
                                f"Reason: [HARNESS: Controller] {reasons} {marker}")
                    ask_args = {"question": question, "options": ["yes", "no"], "default_option": "no"}
            new_tool_calls = [t for t in new_tool_calls if t["name"] not in SIDE_EFFECT_TOOLS]
            new_tool_calls.append({**tc, "name": "ask_user", "args": ask_args})
            break

        ai_message.tool_calls = new_tool_calls
        if forced_content.strip():
            ai_message.content = forced_content.strip()
        if not new_tool_calls:
            return self._carry_disclosure(messages, ai_message)
        return ai_message

    # ------------------------------------------------------------------ invoke
    def invoke(self, input_data, config=None, **kwargs) -> Any:
        # Clone input_data so we can mutate the messages list during retries
        messages = input_data.get("messages", []) if isinstance(input_data, dict) else list(input_data or [])
        messages = list(messages)
        harness_result = None
        
        for _ in range(3):
            data_to_pass = {**input_data, "messages": messages} if isinstance(input_data, dict) else messages
            res = self.model.invoke(data_to_pass, config=config, **kwargs)
            harness_result = self._apply_harness(data_to_pass, res)
            
            if isinstance(harness_result, dict) and harness_result.get("linter_rejected"):
                from langchain_core.messages import ToolMessage, HumanMessage
                messages.append(harness_result["ai_message"])
                tc = harness_result.get("tool_call")
                if tc:
                    messages.append(ToolMessage(
                        tool_call_id=tc["id"],
                        name=tc["name"],
                        content=harness_result["feedback"]
                    ))
                else:
                    messages.append(HumanMessage(content=f"[SYSTEM NOTIFICATION]: {harness_result['feedback']}"))
                continue
            return harness_result
            
        return harness_result

    async def ainvoke(self, input_data, config=None, **kwargs) -> Any:
        messages = input_data.get("messages", []) if isinstance(input_data, dict) else list(input_data or [])
        messages = list(messages)
        harness_result = None
        
        for _ in range(3):
            data_to_pass = {**input_data, "messages": messages} if isinstance(input_data, dict) else messages
            res = await self.model.ainvoke(data_to_pass, config=config, **kwargs)
            harness_result = self._apply_harness(data_to_pass, res)
            
            if isinstance(harness_result, dict) and harness_result.get("linter_rejected"):
                from langchain_core.messages import ToolMessage, HumanMessage
                messages.append(harness_result["ai_message"])
                tc = harness_result.get("tool_call")
                if tc:
                    messages.append(ToolMessage(
                        tool_call_id=tc["id"],
                        name=tc["name"],
                        content=harness_result["feedback"]
                    ))
                else:
                    messages.append(HumanMessage(content=f"[SYSTEM NOTIFICATION]: {harness_result['feedback']}"))
                continue
            return harness_result
            
        return harness_result