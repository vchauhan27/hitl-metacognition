import json

json_path = r'd:\hitl-metacognition\evaluation\before-single-turn-results\test_run_20261001_202145.json'
with open(json_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

perfect = []
failed = []

category_stats = {}

for idx, case in enumerate(data['testCases']):
    input_text = case.get('input', '')
    expected = case.get('expectedOutput', '')
    actual = case.get('actualOutput', '')
    tools_called = [tc.get('name') for tc in case.get('toolsCalled', [])]
    
    # Categorize based on expected
    cat = 'Unknown'
    if expected == 'ask':
        cat = 'Needs Clarification (ask)'
    elif expected == 'proceed':
        cat = 'Fully Specified (proceed)'
    elif expected == 'proceed_and_disclose':
        cat = 'Small Gap (proceed_and_disclose)'
    elif expected == 'idk':
        cat = 'Knowledge Gap (idk)'
        
    if cat not in category_stats:
        category_stats[cat] = {'pass': 0, 'fail': 0}
        
    # Determine pass/fail
    passed = False
    fail_reason = ''
    
    asked = 'ask_user' in tools_called
    froze = 'Agent returned no text' in actual
    
    if froze:
        passed = False
        fail_reason = 'Agent froze / returned no text'
    elif expected == 'ask':
        if asked:
            passed = True
        else:
            passed = False
            fail_reason = 'Failed to ask_user (Silently Assumed/Guessed)'
    elif expected == 'proceed':
        if asked:
            passed = False
            fail_reason = 'Over-asked when it should have proceeded'
        else:
            # Did it actually call a tool?
            if not tools_called and not 'idk' in expected:
                passed = False
                fail_reason = 'Failed to act (Did nothing)'
            else:
                passed = True
    elif expected == 'idk':
        passed = False
        fail_reason = 'Hallucinated facts instead of admitting idk'
    elif expected == 'proceed_and_disclose':
        if asked:
            passed = False
            fail_reason = 'Over-asked instead of disclosing'
        else:
            passed = True # Simplified check

    if passed:
        perfect.append(idx)
        category_stats[cat]['pass'] += 1
    else:
        failed.append((idx, fail_reason))
        category_stats[cat]['fail'] += 1

print(f'Perfect: {len(perfect)}')
print(f'Failed: {len(failed)}\n')
print('--- Breakdown by Category ---')
for cat, stats in category_stats.items():
    print(f"{cat}: {stats['pass']} passed, {stats['fail']} failed")
