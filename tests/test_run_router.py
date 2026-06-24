"""Tests for the batch safety-router stage + fallback queue (no network)."""

import importlib.util
from pathlib import Path

from src.pipeline.Router.output import RouterResult

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = PROJECT_ROOT / "scripts" / "safety_v0" / "run_router.py"
    spec = importlib.util.spec_from_file_location("run_router", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeRouter:
    """Returns a queued list of RouterResults, one per route() call."""

    def __init__(self, results):
        self._results = list(results)
        self.calls = 0

    def route(self, router_input):
        r = self._results[self.calls % len(self._results)]
        self.calls += 1
        return r


def test_api_label_record_provenance_and_status():
    mod = _load()
    safe = RouterResult("safe", {"pii_visible": False, "prompt_injection": False,
                                 "sexual": False, "violence": False, "blood_gore": False,
                                 "political": False, "religious": False}, valid=True)
    rec = mod.api_label_record("safety_v0_x_000001", safe, "gemini_flash")
    assert rec["labels"]["action"] == "safe"
    assert rec["label_source"]["action"] == "api"
    assert rec["label_source"]["pii_visible"] == "api"
    assert rec["review"]["status"] == "unreviewed"  # safe -> not queued for review

    unsure = RouterResult("unsure", {}, valid=False, error="bad json")
    rec2 = mod.api_label_record("safety_v0_x_000002", unsure, "gemini_flash")
    assert rec2["review"]["status"] == "needs_review"
    assert rec2["labels"]["action"] == "unsure"
    assert rec2["label_source"]["sexual"] is None  # unknown stays unsourced


def test_route_rows_queues_only_unsure_and_invalid():
    mod = _load()
    flags = {f: False for f in ["pii_visible", "prompt_injection", "sexual", "violence",
                                "blood_gore", "political", "religious"]}
    results = [
        RouterResult("safe", flags, valid=True),
        RouterResult("reject", flags, valid=True),
        RouterResult("unsure", {}, valid=False, error="x"),
    ]
    rows = [{"input_id": f"id{i}"} for i in range(3)]
    router = FakeRouter(results)

    out = list(mod.route_rows(rows, router, "gemini_flash", "src.jsonl"))
    assert len(out) == 3
    queued = [q for _, q, _ in out if q is not None]
    assert len(queued) == 1 and queued[0]["reason"] == "router_unsure"


def test_route_rows_respects_limit():
    mod = _load()
    flags = {f: False for f in ["pii_visible", "prompt_injection", "sexual", "violence",
                                "blood_gore", "political", "religious"]}
    rows = [{"input_id": f"id{i}"} for i in range(10)]
    router = FakeRouter([RouterResult("safe", flags, valid=True)])
    out = list(mod.route_rows(rows, router, "gemini_flash", "s", limit=3))
    assert len(out) == 3 and router.calls == 3
