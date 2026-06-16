"""Flask demo server for the Vietnamese PII + prompt-injection guardrail pipeline.

Run from the repo root:

    python -m webdemo.app          # or: python webdemo/app.py

Then open http://127.0.0.1:5000

The two pipeline components are loaded lazily and cached, because the PII
pipeline pulls in Presidio/spaCy models that take a few seconds to warm up.
"""

import json
import os
import sys
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request

# Make the repo root importable when run as `python webdemo/app.py`.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from presidio_anonymizer import AnonymizerEngine  # noqa: E402

from src.pipeline.Pipelines import get_pipeline, list_pipeline_names  # noqa: E402
from src.pipeline.PromptInjection import (  # noqa: E402
    get_prompt_injection_detector,
    list_prompt_injection_detector_names,
)

app = Flask(__name__)

DEFAULT_PII_PIPELINE = "regex_recall"
DEFAULT_PI_DETECTOR = "rule_based_prompt_injection"

# One JSONL line per /api/analyze call, for the in-app Log view.
LOG_PATH = os.path.join(REPO_ROOT, "webdemo", "logs", "demo_requests.jsonl")
LOG_VIEW_LIMIT = 200

# Lazily built, cached singletons keyed by name.
_pii_pipelines = {}
_pi_detectors = {}
_anonymizer = None


def get_pii_pipeline(name):
    if name not in _pii_pipelines:
        _pii_pipelines[name] = get_pipeline(name, prediction_log_path=None)
    return _pii_pipelines[name]


def get_pi_detector(name):
    if name not in _pi_detectors:
        _pi_detectors[name] = get_prompt_injection_detector(name)
    return _pi_detectors[name]


def get_anonymizer():
    global _anonymizer
    if _anonymizer is None:
        _anonymizer = AnonymizerEngine()
    return _anonymizer


def dedupe_exact_spans(results):
    """Keep the highest-scoring recognizer result per (start, end) span."""
    best_by_span = {}
    for result in results:
        key = (result.start, result.end)
        existing = best_by_span.get(key)
        if existing is None or result.score > existing.score:
            best_by_span[key] = result
    return sorted(best_by_span.values(), key=lambda item: (item.start, item.end))


def run_pii(text, pipeline_name):
    pipeline = get_pii_pipeline(pipeline_name)
    results = dedupe_exact_spans(pipeline.predict(text))
    anonymized = get_anonymizer().anonymize(text=text, analyzer_results=results).text
    spans = [
        {
            "entity_type": r.entity_type,
            "start": r.start,
            "end": r.end,
            "score": round(float(r.score), 4),
            "text": text[r.start : r.end],
        }
        for r in results
    ]
    return {"pipeline": pipeline_name, "spans": spans, "anonymized": anonymized}


def run_prompt_injection(text, detector_name):
    detector = get_pi_detector(detector_name)
    result = detector.predict(text).to_dict()
    result["detector"] = detector_name
    return result


def append_log(record):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_log(limit=LOG_VIEW_LIMIT):
    if not os.path.exists(LOG_PATH):
        return []
    records = []
    with open(LOG_PATH, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    # Most recent first, capped.
    return list(reversed(records))[:limit]


def build_log_record(text, pi_result, pii_result):
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "text": text,
        "prompt_injection": {
            "detector": pi_result.get("detector"),
            "action": pi_result.get("action"),
            "score": pi_result.get("score"),
            "is_injection": pi_result.get("is_injection"),
            "categories": pi_result.get("categories", []),
            "matched_rules": pi_result.get("matched_rules", []),
        },
        "pii": {
            "pipeline": pii_result.get("pipeline"),
            "span_count": len(pii_result.get("spans", [])),
            "entity_types": sorted({s["entity_type"] for s in pii_result.get("spans", [])}),
            "anonymized": pii_result.get("anonymized"),
        },
    }


@app.route("/")
def index():
    return render_template(
        "index.html",
        pii_pipelines=list_pipeline_names(),
        pi_detectors=list_prompt_injection_detector_names(),
        default_pii_pipeline=DEFAULT_PII_PIPELINE,
        default_pi_detector=DEFAULT_PI_DETECTOR,
    )


@app.route("/api/pii", methods=["POST"])
def api_pii():
    payload = request.get_json(force=True, silent=True) or {}
    text = (payload.get("text") or "").strip()
    pipeline_name = payload.get("pipeline") or DEFAULT_PII_PIPELINE
    if not text:
        return jsonify({"error": "Empty input text."}), 400
    if pipeline_name not in list_pipeline_names():
        return jsonify({"error": f"Unknown pipeline {pipeline_name!r}."}), 400
    return jsonify(run_pii(text, pipeline_name))


@app.route("/api/prompt-injection", methods=["POST"])
def api_prompt_injection():
    payload = request.get_json(force=True, silent=True) or {}
    text = (payload.get("text") or "").strip()
    detector_name = payload.get("detector") or DEFAULT_PI_DETECTOR
    if not text:
        return jsonify({"error": "Empty input text."}), 400
    if detector_name not in list_prompt_injection_detector_names():
        return jsonify({"error": f"Unknown detector {detector_name!r}."}), 400
    return jsonify(run_prompt_injection(text, detector_name))


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    """Full guardrail: screen for injection first, then detect/mask PII."""
    payload = request.get_json(force=True, silent=True) or {}
    text = (payload.get("text") or "").strip()
    pipeline_name = payload.get("pipeline") or DEFAULT_PII_PIPELINE
    detector_name = payload.get("detector") or DEFAULT_PI_DETECTOR
    if not text:
        return jsonify({"error": "Empty input text."}), 400
    pi_result = run_prompt_injection(text, detector_name)
    pii_result = run_pii(text, pipeline_name)
    append_log(build_log_record(text, pi_result, pii_result))
    return jsonify({"prompt_injection": pi_result, "pii": pii_result})


@app.route("/api/log", methods=["GET"])
def api_log_list():
    return jsonify({"records": read_log()})


@app.route("/api/log", methods=["DELETE"])
def api_log_clear():
    if os.path.exists(LOG_PATH):
        os.remove(LOG_PATH)
    return jsonify({"cleared": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=True)
