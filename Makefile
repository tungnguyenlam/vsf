# Reproduce and verify the Vietnamese safety tooling numbers cited in the
# writeup. Targets run from a clean clone with PYTHONPATH=. and the on-disk
# data/translation cache in place; none spend LLM budget.
#
# Quick checks:
#     make help
#     make reproduce-pi     # re-runs every PI eval number in the writeup
#     make test-pi          # pins the PI writeup tables
#     make test-pii         # runs the PII pipeline tests (fast, no model download)
#     make smoke-pii        # runs regex_only on 5 rows (real HF data, ~1s)
#     make -k all

PYTHON ?= python
PYTEST ?= pytest

PI_REPRODUCER = scripts/safety_v0/run_heldout_evaluation.py
PI_TEST = tests/test_prompt_injection_evaluation.py
PII_TEST = tests/test_pipeline_registry_and_evaluation.py
PII_SMOKE_LIMIT ?= 5
PII_SMOKE_OUT ?= output/evaluations/smoke_pii/metrics.json

.PHONY: help reproduce-pi test-pi sweep-pi test-pii smoke-pii test all

help:
	@echo "Targets:"
	@echo "  reproduce-pi  Run the unified PI reproducer (writes 4 JSONs under output/safety_v0/)."
	@echo "  test-pi       Run the test that pins the writeup tables to the PI reproducer."
	@echo "  sweep-pi      Run only the threshold-sweep helper (for quick checks)."
	@echo "  test-pii      Run the PII pipeline + registry + evaluation tests (no HF download)."
	@echo "  smoke-pii     Run regex_only on a 5-row HF sample to smoke-test the pipeline end-to-end."
	@echo "  test          Run the full test suite."
	@echo "  all           reproduce-pi then test-pi then test-pii then smoke-pii (no full suite)."

reproduce-pi:
	PYTHONPATH=. $(PYTHON) $(PI_REPRODUCER)

test-pi:
	PYTHONPATH=. $(PYTEST) $(PI_TEST) -v

sweep-pi:
	PYTHONPATH=. $(PYTHON) scripts/safety_v0/sweep_pi_vi_nb_threshold.py

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

all: reproduce-pi test-pi test-pii smoke-pii
