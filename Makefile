# Reproduce and verify the Vietnamese safety tooling numbers cited in the
# writeup. Targets run from a clean clone with PYTHONPATH=. and the on-disk
# data/translation cache in place; none spend LLM budget.
#
# Quick check:
#     make reproduce-pi
#     make test-pi
#     make -k all

PYTHON ?= python
PYTEST ?= pytest

PI_REPRODUCER = scripts/safety_v0/run_heldout_evaluation.py
PI_TEST = tests/test_prompt_injection_evaluation.py

.PHONY: help reproduce-pi test-pi test sweep-pi

help:
	@echo "Targets:"
	@echo "  reproduce-pi  Run the unified PI reproducer (writes 4 JSONs under output/safety_v0/)."
	@echo "  test-pi       Run the test that pins the writeup tables to the reproducer."
	@echo "  sweep-pi      Run only the threshold-sweep helper (for quick checks)."
	@echo "  test          Run the full test suite."
	@echo "  all           reproduce-pi then test-pi (no full suite)."

reproduce-pi:
	PYTHONPATH=. $(PYTHON) $(PI_REPRODUCER)

test-pi:
	PYTHONPATH=. $(PYTEST) $(PI_TEST) -v

sweep-pi:
	PYTHONPATH=. $(PYTHON) scripts/safety_v0/sweep_pi_vi_nb_threshold.py

test:
	PYTHONPATH=. $(PYTEST)

all: reproduce-pi test-pi
