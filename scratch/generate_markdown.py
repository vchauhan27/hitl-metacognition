import json
import os
import glob

def generate_markdown_for_json(json_path, out_path):
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    if 'testRunData' in data:
        data = data['testRunData']

    with open(out_path, 'w', encoding='utf-8') as out:
        base_name = os.path.basename(json_path)
        out.write(f'# DeepEval Full JSON Summary for {base_name}\n\n')
        
        for idx, case in enumerate(data.get('testCases', [])):
            out.write(f'## Test Case {idx}\n')
            out.write(f"**Input:** `{case.get('input', '')}`\n\n")
            out.write(f"**Expected Action:** `{case.get('expectedOutput', '')}`\n\n")
            out.write(f"**Success:** `{case.get('success', False)}`\n")
            out.write(f"**Flaky:** `{case.get('flaky', False)}`\n")
            out.write(f"**Evaluation Cost:** `{case.get('evaluationCost', 0.0)}`\n\n")
            
            # Retrieval Context
            ret_ctx = case.get('retrievalContext', [])
            out.write('**Retrieval Context:**\n')
            if ret_ctx:
                for ctx in ret_ctx:
                    out.write(f"- `{ctx}`\n")
            else:
                out.write('- *(None)*\n')
            out.write('\n')
            
            # Tools Called
            tools_called = case.get('toolsCalled', [])
            out.write('**Tools Called:**\n')
            if not tools_called:
                out.write('- *(None)*\n')
            else:
                for tc in tools_called:
                    name = tc.get('name', 'Unknown')
                    tc_type = tc.get('type', 'Unknown')
                    args = tc.get('inputParameters', {})
                    tool_out = tc.get('output', '')
                    # formatting output nicely
                    tool_out_str = str(tool_out).replace('\n', ' ') if tool_out else ''
                    out.write(f"- `{name}` (Type: `{tc_type}`) with args: `{json.dumps(args)}`\n")
                    if tool_out_str:
                        out.write(f"  - *Output:* {tool_out_str}\n")
            out.write('\n')
            
            # Expected Tools
            expected_tools = case.get('expectedTools', [])
            if expected_tools:
                out.write('**Expected Tools:**\n')
                for et in expected_tools:
                    et_name = et.get('name', 'Unknown')
                    et_type = et.get('type', 'Unknown')
                    out.write(f"- `{et_name}` (Type: `{et_type}`)\n")
                out.write('\n')

            out.write(f"**Actual Output:**\n> {case.get('actualOutput', '')}\n\n")
            
            out.write('**All Metrics (JevEval & DeepEval):**\n')
            for metric in case.get('metricsData', []):
                name = metric.get('name', 'Unknown')
                score = metric.get('score', 0)
                reason = metric.get('reason', '').strip()
                metric_cost = metric.get('evaluationCost', 0.0)
                
                # Format reason block nicely
                if '\n' in reason:
                    reason = f"\n  ```\n  {reason.replace(chr(10), chr(10) + '  ')}\n  ```"
                else:
                    reason = f" - {reason}"
                    
                out.write(f"- **{name}** (Score: {score}, Cost: {metric_cost}){reason}\n")
                
            out.write('\n---\n\n')

        for idx, case in enumerate(data.get('conversationalTestCases', [])):
            out.write(f"## {case.get('name', f'Conversational Test Case {idx}')}\n")
            out.write(f"**Success:** `{case.get('success', False)}`\n")
            out.write(f"**Flaky:** `{case.get('flaky', False)}`\n\n")
            
            # Print turns
            out.write('**Turns:**\n')
            for turn in case.get('turns', []):
                role = turn.get('role', '')
                content = turn.get('content', '')
                out.write(f"**{role.capitalize()}**: {content}\n")
                
                # Retrieval Context
                ret_ctx = turn.get('retrievalContext', [])
                if ret_ctx:
                    out.write('\n  *Retrieval Context:*\n')
                    for ctx in ret_ctx:
                        out.write(f"  - `{ctx}`\n")
                
                # Tools Called
                tools_called = turn.get('toolsCalled', [])
                if tools_called:
                    out.write('\n  *Tools Called:*\n')
                    for tc in tools_called:
                        name = tc.get('name', 'Unknown')
                        tc_type = tc.get('type', 'Unknown')
                        args = tc.get('inputParameters', {})
                        tool_out = tc.get('output', '')
                        tool_out_str = str(tool_out).replace('\n', ' ') if tool_out else ''
                        out.write(f"  - `{name}` (Type: `{tc_type}`) with args: `{json.dumps(args)}`\n")
                        if tool_out_str:
                            out.write(f"    - *Output:* {tool_out_str}\n")
                out.write('\n')
            
            out.write('**All Metrics (JevEval & DeepEval):**\n')
            for metric in case.get('metricsData', []):
                name = metric.get('name', 'Unknown')
                score = metric.get('score', 0)
                reason = metric.get('reason', '').strip()
                metric_cost = metric.get('evaluationCost', 0.0)
                
                # Format reason block nicely
                if '\n' in reason:
                    reason = f"\n  ```\n  {reason.replace(chr(10), chr(10) + '  ')}\n  ```"
                else:
                    reason = f" - {reason}"
                    
                out.write(f"- **{name}** (Score: {score}, Cost: {metric_cost}){reason}\n")
                
            out.write('\n---\n\n')

    print(f'Successfully wrote comprehensive full summary to {out_path}')

def main():
    target_dirs = [
        r'd:\hitl-metacognition\evaluation\before-single-turn-results',
        r'd:\hitl-metacognition\evaluation\before-multi-turn-results',
        r'd:\hitl-metacognition\evaluation\after-single-turn-results',
        r'd:\hitl-metacognition\evaluation\after-multi-turn-results'
    ]
    
    for target_dir in target_dirs:
        if not os.path.exists(target_dir):
            print(f"Directory not found: {target_dir}")
            continue
            
        json_files = glob.glob(os.path.join(target_dir, '*.json'))
        for json_path in json_files:
            base_name = os.path.splitext(os.path.basename(json_path))[0]
            out_path = os.path.join(target_dir, f"{base_name}.md")
            generate_markdown_for_json(json_path, out_path)

if __name__ == '__main__':
    main()
