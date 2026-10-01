import json
import glob

def analyze(file_path):
    d = json.load(open(file_path))
    print(f'\n--- {file_path} ---')
    print(f"Passed: {d.get('testPassed', 0)} / {d.get('testPassed', 0) + d.get('testFailed', 0)}")
    
    if 'metricsScores' in d:
        for metric in d['metricsScores']:
            scores = metric['scores']
            avg = sum(scores) / len(scores) if scores else 0
            print(f"  {metric['metric']}: Pass {metric['passes']}/{metric['passes']+metric['fails']} | Avg Score: {avg:.2f}")

for file in glob.glob('evaluation/before-multi-turn-results/*.json'): analyze(file)
for file in glob.glob('evaluation/after-multi-turn-results/*.json'): analyze(file)
