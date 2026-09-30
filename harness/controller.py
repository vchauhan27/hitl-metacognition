from harness.monitor import Signals

def decide(s: Signals) -> str:
    if s.no_support:
        return "IDK"
    if s.permission_needed:
        return "ASK"
    if s.missing or s.ambiguous_referent:
        return "ASK" if s.costly else "PROCEED_AND_DISCLOSE"
    if s.vague:
        return "ASK" if s.costly else "PROCEED_AND_DISCLOSE"
    if s.stale_memory:
        return "ASK"
    return "PROCEED"
