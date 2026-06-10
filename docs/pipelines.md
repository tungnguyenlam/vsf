# Pipelines

Pipeline classes are model definitions. Keep them visually separate from registry,
evaluation, and analyzer infrastructure.

## Layout

```text
src/pipeline/Pipelines/
  Models/
    BaselinePresidioPipeline.py
    RegexOnlyPipeline.py
    HybridRegexPipeline.py
    __init__.py
  base.py
  registry.py
  evaluation.py
  variants.py
```

Responsibilities:

| Path | Responsibility |
|------|----------------|
| `Models/<ClassName>.py` | One pipeline model class per file. Filename should match the class name. |
| `Models/__init__.py` | Re-export model classes for concise imports. |
| `base.py` | Shared `VietnamesePipeline` base behavior. |
| `registry.py` | Maps stable registry keys to model classes. |
| `evaluation.py` | OOP evaluation runner and CLI argument definitions. |
| `variants.py` | Compatibility re-export only. Do not add model logic here. |

Current registry keys:

| Key | Class | File |
|-----|-------|------|
| `baseline_presidio` | `BaselinePresidioPipeline` | `Models/BaselinePresidioPipeline.py` |
| `regex_only` | `RegexOnlyPipeline` | `Models/RegexOnlyPipeline.py` |
| `regex_recall` | `RegexRecallPipeline` | `Models/RegexRecallPipeline.py` |
| `underthesea_ner` | `UndertheseaNerPipeline` | `Models/UndertheseaNerPipeline.py` |
| `underthesea_regex` | `UndertheseaRegexPipeline` | `Models/UndertheseaRegexPipeline.py` |
| `underthesea_regex_recall` | `UndertheseaRegexRecallPipeline` | `Models/UndertheseaRegexPipeline.py` |
| `hybrid_regex` | `HybridRegexPipeline` | `Models/HybridRegexPipeline.py` |

## Adding a Pipeline

1. Add a new class file under `src/pipeline/Pipelines/Models/`.
2. Name the file exactly like the class, for example `MyExperimentPipeline.py`.
3. Subclass `VietnamesePipeline` unless there is a clear reason to use `PIIPipeline` directly.
4. Keep model/provider/recognizer choices explicit in the constructor.
5. Export the class from `Models/__init__.py`.
6. Register a stable snake_case key in `registry.py`.
7. Add or update focused tests in `tests/test_pipeline_registry_and_evaluation.py`.

Minimal pattern:

```python
from src.pipeline.Pipelines.base import VietnamesePipeline
from src.pipeline.Recognizers.CustomPatternRecognizer import CustomPatternRecognizer


class MyExperimentPipeline(VietnamesePipeline):
    def __init__(self, **kwargs):
        super().__init__(
            recognizers=[CustomPatternRecognizer()],
            pipeline_name="my_experiment",
            **kwargs,
        )
```

## Evaluation Runner

The script entrypoint is:

```bash
PYTHONPATH=. python3 scripts/evaluate_pipeline.py --pipeline regex_only --split train_val --limit 50
```

For LLM verifier runs:

```bash
PYTHONPATH=. python3 scripts/evaluate_pipeline.py --pipeline regex_only --split train_val --limit 50 --verify
```

Use `train_val` for routine inspection and rule iteration. It is a deterministic
10% holdout partition derived from the train split (`random_state=42`), disjoint
from `train_main`. Keep the dataset's `test` split untouched until final reporting.

`scripts/evaluate_pipeline.py` is intentionally thin. The actual runner lives in
`src/pipeline/Pipelines/evaluation.py`:

- `PipelineEvaluationConfig`
- `PipelineEvaluationRunner`

Programmatic usage:

```python
from src.pipeline.Pipelines.evaluation import (
    PipelineEvaluationConfig,
    PipelineEvaluationRunner,
)

config = PipelineEvaluationConfig(
    pipeline="regex_only",
    split="train_val",
    limit=50,
    verify=False,
)
result = PipelineEvaluationRunner(config).run()
```

The runner loads local `.env` values before dataset and verifier setup, so `HF_TOKEN`
and `OPENROUTER_API_KEY` can live in `.env` for CLI runs.

## Prediction Logs

By default, evaluation writes logs under:

```text
output/predictions/<run_id>/predictions.jsonl
output/predictions/<run_id>/predictions.readable.json
```

Use `--no-log` to disable logging, or `--log-path` to choose an explicit JSONL path.
Raw `source_text` is not logged unless `--include-source-text` is passed.

## Verifier Output

The LLM verifier is a post-Analyzer correction pass, not the primary detector. It receives
candidate spans already found by Presidio recognizers and returns sparse corrections:

```json
{
  "drop": [1],
  "relabel": [{"id": 0, "entity_type": "BANK_ACCOUNT"}]
}
```

Unmentioned candidates are kept unchanged. The verifier does not add missing spans.
