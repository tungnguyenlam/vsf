# Reproduce and verify the Vietnamese safety tooling numbers cited in the
# writeup. Targets run from a clean clone with PYTHONPATH=. and the on-disk
# data/translation cache in place; none spend LLM budget.
#
# Quick checks:
#     make help
#     make reproduce-pi     # re-runs every PI eval number in the writeup
#     make test-pi          # pins the PI writeup tables
#     make reproduce-pii    # re-runs the pinned regex_recall on 500 val input_ids
#     make test-pii         # runs the PII pipeline tests (fast, no model download)
#     make smoke-pii        # runs regex_only on 5 rows (real HF data, ~1s)
#     make -k all

PYTHON ?= python
PYTEST ?= pytest

PI_REPRODUCER = scripts/safety_v0/run_heldout_evaluation.py
PI_TEST = tests/test_prompt_injection_evaluation.py
PII_TEST = tests/test_pipeline_registry_and_evaluation.py
PII_REPRO_PIPELINE ?= regex_recall
PII_REPRO_MANIFEST ?= data/sample_ids/pii_masking_95k__validation__writeup_pin_500.json
PII_REPRO_OUT ?= output/evaluations/pinned_pii/regex_recall.json
PII_SMOKE_LIMIT ?= 5
PII_SMOKE_OUT ?= output/evaluations/smoke_pii/metrics.json

.PHONY: help reproduce-pi test-pi sweep-pi reproduce-pii test-pii smoke-pii test all

help:
	@echo "Targets:"
	@echo "  reproduce-pi   Run the unified PI reproducer (writes 4 JSONs under output/safety_v0/)."
	@echo "  test-pi        Run the test that pins the writeup tables to the PI reproducer."
	@echo "  sweep-pi       Run only the threshold-sweep helper (for quick checks)."
	@echo "  reproduce-pii  Re-run regex_recall on the pinned 500-row val input_id manifest."
	@echo "  test-pii       Run the PII pipeline + registry + evaluation tests (no HF download)."
	@echo "  smoke-pii      Run regex_only on a 5-row HF sample to smoke-test the pipeline end-to-end."
	@echo "  test           Run the full test suite."
	@echo "  all            reproduce-pi then test-pi then reproduce-pii then test-pii then smoke-pii."

reproduce-pi:
	PYTHONPATH=. $(PYTHON) $(PI_REPRODUCER)

test-pi:
	PYTHONPATH=. $(PYTEST) $(PI_TEST) -v

sweep-pi:
	PYTHONPATH=. $(PYTHON) scripts/safety_v0/sweep_pi_vi_nb_threshold.py

reproduce-pii:
	@mkdir -p $(dir $(PII_REPRO_OUT))
	PYTHONPATH=. $(PYTHON) scripts/evaluate_pipeline.py \
		--pipeline $(PII_REPRO_PIPELINE) --split val \
		--input-ids-file $(PII_REPRO_MANIFEST) --no-log \
		--log-path /tmp/pinned_pii_predictions.jsonl \
		> $(PII_REPRO_OUT)
	@echo "Wrote $(PII_REPRO_OUT)"

test-pii:
	PYTHONPATH=. $(PYTEST) $(PII_TEST) -v

smoke-pii:
	@mkdir -p $(dir $(PII_SMOKE_OUT))
	PYTHONPATH=. $(PYTHON) scripts/evaluate_pipeline.py \
		--pipeline regex_only --split train --limit $(PII_SMOKE_LIMIT) --no-log \
		--log-path /tmp/smoke_pii_predictions.jsonl \
		> $(PII_SMOKE_OUT)
	@echo "Wrote $(PII_SMOKE_OUT)"

test:
	PYTHONPATH=. $(PYTEST)

all: reproduce-pi test-pi reproduce-pii test-pii smoke-pii
