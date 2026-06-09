"""Re-upload the locally-cached pii-masking-95k-preencoded dataset to a personal HF account.

Source: the original HF snapshot still present in the local hub cache
(README.md + splits_95k_preencoded/{train,validation,test}.jsonl).
"""
import os
from pathlib import Path

from huggingface_hub import HfApi

# --- load .env ---
ENV = {}
for line in Path(".env").read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    ENV[k] = v.strip().strip('"').strip("'")

USERNAME = ENV["HF_USERNAME"]
TOKEN = ENV["HF_TOKEN"]
REPO_ID = f"{USERNAME}/pii-masking-95k-preencoded"

SNAPSHOT = Path.home() / (
    ".cache/huggingface/hub/"
    "datasets--NAMANDREWLV--pii-masking-95k-preencoded/"
    "snapshots/fe50d5bf5857f4212db206d0aefe95d5ebc880e2"
)

assert SNAPSHOT.is_dir(), f"snapshot not found: {SNAPSHOT}"
assert (SNAPSHOT / "README.md").is_file()
assert (SNAPSHOT / "splits_95k_preencoded" / "train.jsonl").is_file()

api = HfApi(token=TOKEN)

print(f"Whoami: {api.whoami()['name']}")
print(f"Creating dataset repo: {REPO_ID}")
api.create_repo(repo_id=REPO_ID, repo_type="dataset", exist_ok=True, private=False)

print(f"Uploading folder {SNAPSHOT} ...")
api.upload_folder(
    repo_id=REPO_ID,
    repo_type="dataset",
    folder_path=str(SNAPSHOT),
    allow_patterns=["README.md", "splits_95k_preencoded/*.jsonl"],
    commit_message="Re-upload pii-masking-95k-preencoded from local cache",
)
print(f"DONE -> https://huggingface.co/datasets/{REPO_ID}")
