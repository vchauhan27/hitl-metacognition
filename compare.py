import json, glob, os
from collections import Counter

def get_latest(f):
    lst = glob.glob(os.path.join(f, 'poc_summary_multi_*.json'))
    return max(lst, key=os.path.getmtime) if lst else None

for name, path in [('BEFORE (No Harness)', get_latest('evaluation/before-multi-turn-results')), ('AFTER (With Harness)', get_latest('evaluation/after-multi-turn-results'))]:
    if not path:
        print(f'{name}: not found')
        continue
    
    with open(path) as f:
        d = json.load(f)
        
    passed = sum(1 for r in d['runs'] if r.get('status') == 'pass')
    print(f'\n--- {name} ---')
    print(f"Total Pass Rate: {passed}/{len(d['runs'])}")
    
    c = Counter([r['failure_type'] + ' ' + r['status'] for r in d['runs']])
    for k in sorted(c.keys()):
        print(f'  {k}: {c[k]}')
        
    tr = d.get('trace_check', {}).get('aggregate', {})
    m = tr.get('missed_asks', 0)
    u = tr.get('unnecessary_asks', 0)
    print(f'Trace -> Missed Asks: {m}, Unnecessary Asks: {u}')
