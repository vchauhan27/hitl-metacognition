import json
import os

json_path = r'd:\hitl-metacognition\evaluation\before-single-turn-results\test_run_20261001_202145.json'
out_path = r'd:\hitl-metacognition\jev_full_summary.md'

try:
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
except FileNotFoundError:
    json_path = r'd:\hitl-metacognition\.deepeval\.latest_test_run.json'
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        if 'testRunData' in data:
            data = data['testRunData']

with open(out_path, 'w', encoding='utf-8') as out:
    out.write('# DeepEval Full JSON Summary\n\n')
    
    for idx, case in enumerate(data.get('testCases', [])):
        out.write(f'## Test Case {idx}\n')
        out.write(f"**Input:** `{case.get('input', '')}`\n\n")
        out.write(f"**Expected Action:** `{case.get('expectedOutput', '')}`\n\n")
        
        # Tools Called
        tools_called = case.get('toolsCalled', [])
        out.write('**Tools Called:**\n')
        if not tools_called:
            out.write('- *(None)*\n')
        else:
            for tc in tools_called:
                name = tc.get('name', 'Unknown')
                args = tc.get('inputParameters', {})
                tool_out = tc.get('output', '')
                # formatting output nicely
                tool_out_str = str(tool_out).replace('\n', ' ') if tool_out else ''
                out.write(f"- `{name}({json.dumps(args)})`\n")
                if tool_out_str:
                    out.write(f"  - *Output:* {tool_out_str}\n")
        out.write('\n')
        
        # Expected Tools
        expected_tools = case.get('expectedTools', [])
        if expected_tools:
            out.write('**Expected Tools:**\n')
            for et in expected_tools:
                out.write(f"- `{et.get('name', 'Unknown')}`\n")
            out.write('\n')

        out.write(f"**Actual Output:**\n> {case.get('actualOutput', '')}\n\n")
        
        out.write('**All Metrics (JevEval & DeepEval):**\n')
        for metric in case.get('metricsData', []):
            name = metric.get('name', 'Unknown')
            score = metric.get('score', 0)
            reason = metric.get('reason', '').strip()
            
            # Format reason block nicely
            if '\n' in reason:
                reason = f"\n  ```\n  {reason.replace(chr(10), chr(10) + '  ')}\n  ```"
            else:
                reason = f" - {reason}"
                
            out.write(f"- **{name}** (Score: {score}){reason}\n")
            
        out.write('\n---\n\n')

print(f'Successfully wrote comprehensive full summary to {out_path}')
