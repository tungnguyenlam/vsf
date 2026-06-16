import subprocess
import json
import os

pipelines = [
    "regex_only",
    "regex_recall",
    "underthesea_ner",
    "underthesea_regex",
    "underthesea_regex_recall"
]

results = {}

os.makedirs("results", exist_ok=True)

for pipeline in pipelines:
    print(f"Evaluating {pipeline}...")
    cmd = [
        "python", "scripts/evaluate_pipeline.py",
        "--pipeline", pipeline,
        "--split", "validation",
        "--limit", "500",
        "--no-log"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    # The output is a JSON string printed to stdout
    try:
        # Find the json part in the output
        start_idx = result.stdout.find("{")
        end_idx = result.stdout.rfind("}") + 1
        if start_idx != -1 and end_idx != -1:
            json_str = result.stdout[start_idx:end_idx]
            data = json.loads(json_str)
            results[pipeline] = data
        else:
            print(f"Error parsing json for {pipeline}")
            print(result.stdout)
            print(result.stderr)
    except Exception as e:
        print(f"Failed to process {pipeline}: {e}")

with open("results/metrics.json", "w") as f:
    json.dump(results, f, indent=2)

print("Metrics saved to results/metrics.json")
