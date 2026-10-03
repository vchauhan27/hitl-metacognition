import json, glob
for f in glob.glob('evaluation/after-single-turn-results/test_run_*.json'):
    data = json.load(open(f, encoding='utf-8'))
    for tc in data.get('testCases', []):
        if 'slot_01_twin' in tc.get('name', ''):
            print(f"--- {tc.get('name')} ---")
            print("Output:", tc.get('actualOutput'))
            print("Tools:", tc.get('toolsCalled'))
