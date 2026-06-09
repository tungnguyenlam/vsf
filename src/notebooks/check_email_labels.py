"""Quick script to check if EMAIL labels exist in the dataset."""
import os, sys
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, project_root)

from datasets import load_dataset
from collections import Counter

from src.pipeline.Utils import load_hf_token

dataset = load_dataset("nguyenlamtung/pii-masking-95k-preencoded", token=load_hf_token())

for split_name in dataset:
    label_counter = Counter()
    for row in dataset[split_name]:
        for item in row["privacy_mask"]:
            label_counter[item["label"]] += 1
    
    print(f"\n=== {split_name} split ({len(dataset[split_name])} rows) ===")
    for label, count in sorted(label_counter.items()):
        print(f"  {label}: {count}")
    
    email_count = label_counter.get("EMAIL", 0)
    print(f"  >> EMAIL count: {email_count}")
