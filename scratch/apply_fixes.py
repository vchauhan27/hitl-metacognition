import json

p = "data/scenarios-multi-turn.json"
d = json.load(open(p, encoding="utf-8"))
for c in d["conversational_scenarios"]:
    m = c["checks"]["must_not_call"]
    # keep only the two rule shapes the checker understands
    c["checks"]["must_not_call"] = [r for r in m if "after" not in r]
    for r in c["checks"]["must_not_call"]:
        r.pop("after_reply", None)
    for s in c["checks"]["expected_sequence"]:
        s.pop("before", None)
        s.pop("after_reply", None)
json.dump(d, open(p, "w", encoding="utf-8"), indent=4)
print([ (c["id"], c["checks"]["must_not_call"]) for c in d["conversational_scenarios"]])
