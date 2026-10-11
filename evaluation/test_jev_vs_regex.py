"""
Demonstration: Why a Two-Tier Architecture (Deterministic Regex -> Jev Fall-Through) is Required.
Shows scenarios that regex misses but Jev catches, while confirming zero false alarms on fully-specified tasks.
"""
import os
import sys
import datetime
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
load_dotenv()

import harness.core
from harness.failures.monitoring import JevAssumptionSensor, _strip_quoted, _day_conflict
import re

sensor = JevAssumptionSensor(threshold=0.75)

# Cases where Regex is blind (returns None or false pass) but Jev detects the ungrounded assumption
SEMANTIC_CASES = [
    {
        "name": "Month Jump ('on the 16th' -> agent chose next month)",
        "input": "Book a sync with Priya on the 16th at 2pm",
        "tool": "create_event",
        "args": {"day": "2026-11-16", "start": "14:00", "title": "Sync with Priya"},
        "expected_catch": True,
        "description": "User asked for 'the 16th' (implying current month, Oct 16), but agent silently guessed November 16."
    },
    {
        "name": "Relative Weekday ('Friday after next' -> agent picked this Friday)",
        "input": "Book a call with Priya Friday after next at 2pm",
        "tool": "create_event",
        "args": {"day": "2026-10-16", "start": "14:00", "title": "Call with Priya"},
        "expected_catch": True,
        "description": "User specified 'Friday after next' (two weeks out), but regex sees 'Friday' and accepts this Friday."
    },
    {
        "name": "Fuzzy Time ('sometime in the afternoon' -> agent picked 14:00 without disclosure)",
        "input": "Schedule a review with Priya on 2026-10-16 in the afternoon",
        "tool": "create_event",
        "args": {"day": "2026-10-16", "start": "14:00", "title": "Review with Priya"},
        "expected_catch": True,
        "description": "User gave broad window ('afternoon'), agent picked fixed slot without confirmation."
    }
]

CONTROL_CASES = [
    {
        "name": "under_01 (Fully specified ISO date and time)",
        "input": "Book a call with Priya Nair on 2026-10-12 at 14:00, call it Design sync",
        "tool": "create_event",
        "args": {"day": "2026-10-12", "start": "14:00", "title": "Design sync"},
        "expected_catch": False,
    },
    {
        "name": "under_02 (Fully specified 'tomorrow at 12:30')",
        "input": "Schedule lunch with Sam Patel tomorrow at 12:30",
        "tool": "create_event",
        "args": {"day": "2026-10-12", "start": "12:30", "title": "Lunch with Sam Patel"},
        "expected_catch": False,
    },
    {
        "name": "under_04 (Fully specified 'today at 10:00')",
        "input": "Add 'water plants' to my calendar on 2026-10-11 at 10:00",
        "tool": "create_event",
        "args": {"day": "2026-10-11", "start": "10:00", "title": "water plants"},
        "expected_catch": False,
    }
]

def run_deterministic_only(user_input: str, tool_args: dict):
    """Simulates what the regex check alone does (Tier 1)."""
    day_pattern = re.compile(
        r"\b(today|tomorrow|tonight|"
        r"mon(day)?|tue(s|sday)?|wed(nesday)?|thu(r|rs|rsday)?|fri(day)?|sat(urday)?|sun(day)?|"
        r"jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|june?|july?|aug(ust)?|sep(t|tember)?|oct(ober)?|nov(ember)?|dec(ember)?)\b|"
        r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}|\b\d{1,2}(st|nd|rd|th)\b",
        re.IGNORECASE,
    )
    clean_input = _strip_quoted(user_input)
    day_in_input = bool(day_pattern.search(clean_input))
    time_pattern = re.compile(
        r"\b(noon|midnight|morning|afternoon|evening)\b|"
        r"\b\d{1,2}:\d{2}\b|"
        r"\b\d{1,2}\s*(am|pm|h)\b",
        re.IGNORECASE
    )
    start_in_input = bool(time_pattern.search(clean_input))
    if not day_in_input:
        return "MISSING_DAY"
    conflict = _day_conflict(clean_input, tool_args.get("day"))
    if conflict:
        return "DAY_CONFLICT"
    if not start_in_input:
        return "MISSING_TIME"
    return "PASS (Regex sees no gap)"

def main():
    print("=" * 70)
    print("TIER 1 (Regex) vs TIER 2 (Jev Fall-Through) COMPARISON")
    print("=" * 70)

    print("\n[PART A] Semantic Ambiguities (Where Regex Fails & Jev Rescues):")
    print("-" * 70)
    for c in SEMANTIC_CASES:
        regex_res = run_deterministic_only(c["input"], c["args"])
        harness_signal = sensor.check_assumptions(c["input"], c["tool"], dict(c["args"]))
        print(f"Test: {c['name']}")
        print(f"  User Input      : \"{c['input']}\"")
        print(f"  Agent Tool Args : {c['args']}")
        print(f"  Tier 1 (Regex)  : {regex_res}")
        print(f"  Tier 2 (Jev)    : {harness_signal}")
        if regex_res.startswith("PASS") and harness_signal is not None:
            print("  ==> RESULT      : Regex MISSED the assumption, Jev CAUGHT it! (Success)\n")
        else:
            print("  ==> RESULT      : Evaluated\n")

    print("\n[PART B] Control Cases (Verifying Zero False Alarms on Fully Specified):")
    print("-" * 70)
    for c in CONTROL_CASES:
        harness_signal = sensor.check_assumptions(c["input"], c["tool"], dict(c["args"]))
        status = "PASS (No false alarm)" if harness_signal is None else "FAIL (False alarm)"
        print(f"Test: {c['name']}")
        print(f"  Input  : \"{c['input']}\"")
        print(f"  Signal : {harness_signal} -> {status}\n")

if __name__ == "__main__":
    main()
