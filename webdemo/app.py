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

from flask import Flask, jsonify, render_template, request, send_file

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
from src.pipeline.Router import build_router_input, get_router  # noqa: E402
from src.pipeline.SafeTooling import (  # noqa: E402
    RoleBasedPermissionGate,
    UserContext,
    PermissionAuditLogger,
    load_permission_config,
)
from src.pipeline.Utils import load_env  # noqa: E402
from webdemo import image_demo  # noqa: E402
from webdemo import safety_v0_review as review  # noqa: E402

load_env()  # make .env keys (GEMINI_API_KEY, OPENROUTER_API_KEY) visible to routers/verifier

app = Flask(__name__)

DEFAULT_PII_PIPELINE = "regex_recall"
DEFAULT_PI_DETECTOR = "rule_based_prompt_injection"
DEFAULT_ROUTER = "gemini_flash"

# One JSONL line per /api/analyze call, for the in-app Log view.
LOG_PATH = os.path.join(REPO_ROOT, "webdemo", "logs", "demo_requests.jsonl")
LOG_VIEW_LIMIT = 200

# Lazily built, cached singletons keyed by name.
_pii_pipelines = {}
_pi_detectors = {}
_anonymizer = None
_routers = {}

# Permission gate (loaded once at startup)
_permission_config = load_permission_config()
_permission_gate = RoleBasedPermissionGate(_permission_config.tool_permissions)
_permission_audit = PermissionAuditLogger()


def _parse_header_list(value, default=()):
    """Parse a comma-separated header value into a tuple of stripped tokens.

    Empty/missing values fall back to ``default`` (a tuple, not a string).
    """
    if value is None:
        return tuple(default)
    parts = tuple(p.strip() for p in value.split(",") if p.strip())
    return parts or tuple(default)


def resolve_user_from_headers(headers, anon_force_deny=False):
    """Build a ``UserContext`` from incoming request headers.

    Recognised headers (all optional):

    * ``X-User-ID``           -> user id (default ``"demo_user"``)
    * ``X-User-Roles``        -> comma-separated roles
    * ``X-User-Permissions``  -> comma-separated permissions

    Demo default: when no auth header is present the caller is treated as a
    trusted single-user demo (``roles=("user",)``). This keeps the local
    browser workflow functional without an auth layer in front of the demo.

    Production default: when ``anon_force_deny=True`` (or env
    ``WEBDEMO_ANON_FORCE_DENY=1``) the same header-less request resolves to
    ``UserContext.anonymous()`` instead, so the permission gate denies access
    to every tool that requires ``"user"`` or ``"admin"``. Flip this on once a
    real auth layer is bolted in front of the demo. The flag only flips the
    default — any client that supplies *any* of the three auth headers is
    honoured verbatim.
    """
    has_auth_header = any(
        key in headers
        for key in ("X-User-ID", "X-User-Roles", "X-User-Permissions")
    )
    if anon_force_deny and not has_auth_header:
        return UserContext.anonymous()
    user_id = headers.get("X-User-ID", "demo_user")
    roles = _parse_header_list(headers.get("X-User-Roles"), default=("user",))
    permissions = _parse_header_list(headers.get("X-User-Permissions"))
    return UserContext(user_id=user_id, roles=roles, permissions=permissions)


def get_current_user() -> UserContext:
    """Get current user from request context.

    Reads ``WEBDEMO_ANON_FORCE_DENY`` from the environment at request time so
    tests can flip the demo default without restarting the server. See
    ``resolve_user_from_headers`` for the full contract.
    """
    anon_force_deny = os.environ.get("WEBDEMO_ANON_FORCE_DENY", "").lower() in (
        "1", "true", "yes", "on",
    )
    return resolve_user_from_headers(request.headers, anon_force_deny=anon_force_deny)


def check_tool_permission(tool_name: str, user: UserContext = None):
    """Check if user has permission for tool, log audit, return 403 response
    tuple if denied, else True."""
    user = user or get_current_user()
    decision = _permission_gate.check_permission(tool_name, user)
    endpoint = request.endpoint if request.endpoint is not None else "unknown"
    _permission_audit.log_decision(decision, {"endpoint": endpoint})
    if not decision.allowed:
        return (
            jsonify(
                {
                    "error": f"Permission denied: {decision.reason}",
                    "permission_decision": decision.to_dict(),
                }
            ),
            403,
        )
    return True


def get_router_cached(name):
    if name not in _routers:
        _routers[name] = get_router(name)
    return _routers[name]


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
    perm_result = check_tool_permission("pii_analyze")
    if perm_result is not True:
        return perm_result
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
    perm_result = check_tool_permission("prompt_injection_screen")
    if perm_result is not True:
        return perm_result
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
    perm_result = check_tool_permission("pii_analyze")
    if perm_result is not True:
        return perm_result
    perm_result = check_tool_permission("prompt_injection_screen")
    if perm_result is not True:
        return perm_result
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


@app.route("/api/analyze-image", methods=["POST"])
def api_analyze_image():
    """Full image guardrail mirroring the Annotate pipeline on an upload.

    Multipart form: ``image`` (file), optional ``text``, ``pipeline``,
    ``detector``. Runs OCR -> PII -> span/box mapping + redaction on the image,
    screens prompt injection over the typed text plus the OCR text, and detects
    PII on any typed text. The paid VLM router is left to a separate explicit
    call (see ``/api/demo/router``)."""
    perm_result = check_tool_permission("image_analyze")
    if perm_result is not True:
        return perm_result
    perm_result = check_tool_permission("prompt_injection_screen")
    if perm_result is not True:
        return perm_result
    file_storage = request.files.get("image")
    if file_storage is None or not file_storage.filename:
        return jsonify({"error": "No image uploaded."}), 400
    text = (request.form.get("text") or "").strip()
    pipeline_name = request.form.get("pipeline") or DEFAULT_PII_PIPELINE
    detector_name = request.form.get("detector") or DEFAULT_PI_DETECTOR
    if pipeline_name not in list_pipeline_names():
        return jsonify({"error": f"Unknown pipeline {pipeline_name!r}."}), 400
    if detector_name not in list_prompt_injection_detector_names():
        return jsonify({"error": f"Unknown detector {detector_name!r}."}), 400

    try:
        image_result = image_demo.process_image(
            file_storage, text, get_pii_pipeline(pipeline_name), pipeline_name
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # OCR/redaction failure -> surface, don't 500 blank
        return jsonify({"error": f"Image pipeline failed: {exc}"}), 500

    # Screen prompt injection over the combined surface (typed text + OCR text),
    # since an injection may live only in the image.
    screen_text = "\n".join(t for t in (text, image_result["ocr_text"]) if t.strip())
    pi_result = (
        run_prompt_injection(screen_text, detector_name)
        if screen_text.strip()
        else None
    )
    pii_result = run_pii(text, pipeline_name) if text else None
    return jsonify(
        {"prompt_injection": pi_result, "pii": pii_result, "image": image_result}
    )


@app.route("/api/demo/router", methods=["POST"])
def api_demo_router():
    """Run the shared VLM safety router on a previously analyzed demo image.

    PAID call, fired only by the explicit "Run safety router" button. Uses the
    cached row (redacted image + sanitized text) built by ``/api/analyze-image``.
    """
    perm_result = check_tool_permission("safety_router")
    if perm_result is not True:
        return perm_result
    payload = request.get_json(force=True, silent=True) or {}
    demo_id = payload.get("demo_id")
    router_name = payload.get("router") or DEFAULT_ROUTER
    row = image_demo.get_demo_row(demo_id)
    if row is None:
        return jsonify({"error": "Demo image expired — re-run analysis."}), 404
    try:
        router = get_router_cached(router_name)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    router_input = build_router_input(row)
    result = router.route(router_input)
    return jsonify(
        {
            "router": router_name,
            "result": result.to_dict(),
            "labels": result.to_labels(),
            "modalities": router_input.get("input_modalities", {}),
        }
    )


@app.route("/api/log", methods=["GET"])
def api_log_list():
    return jsonify({"records": read_log()})


@app.route("/api/log", methods=["DELETE"])
def api_log_clear():
    if os.path.exists(LOG_PATH):
        os.remove(LOG_PATH)
    return jsonify({"cleared": True})


@app.route("/api/permission-audit", methods=["GET"])
def api_permission_audit():
    """Admin-only view of the permission audit log.

    Gated behind the ``admin_config`` tool so a non-admin request is itself a
    denial recorded in the same audit log it tried to read. ``limit`` caps the
    number of most-recent records returned (default 200)."""
    gate = check_tool_permission("admin_config")
    if gate is not True:
        return gate
    try:
        limit = int(request.args.get("limit", 200))
    except (TypeError, ValueError):
        limit = 200
    return jsonify({"records": _permission_audit.read_recent(limit=limit)})


# ----------------------------- safety_v0 review -----------------------------
@app.route("/api/review/files", methods=["GET"])
def api_review_files():
    """Canonical safety_v0 JSONL files available to review."""
    perm_result = check_tool_permission("data_review")
    if perm_result is not True:
        return perm_result
    return jsonify({"files": review.list_canonical_files()})


@app.route("/api/review/rows", methods=["GET"])
def api_review_rows():
    """Rows for one file with human overrides applied, plus summary stats."""
    perm_result = check_tool_permission("data_review")
    if perm_result is not True:
        return perm_result
    rel_path = request.args.get("file") or ""
    data_file = review.resolve_data_file(rel_path)
    if data_file is None:
        return jsonify({"error": f"Unknown or unsafe file {rel_path!r}."}), 400
    rows, stats = review.load_rows(data_file)
    return jsonify({"file": rel_path, "rows": rows, "stats": stats})


@app.route("/api/review/save", methods=["POST"])
def api_review_save():
    """Append a human override (labels + review) for one row."""
    perm_result = check_tool_permission("data_review")
    if perm_result is not True:
        return perm_result
    payload = request.get_json(force=True, silent=True) or {}
    rel_path = payload.get("file") or ""
    input_id = payload.get("input_id")
    data_file = review.resolve_data_file(rel_path)
    if data_file is None:
        return jsonify({"error": f"Unknown or unsafe file {rel_path!r}."}), 400
    if not input_id:
        return jsonify({"error": "Missing input_id."}), 400
    try:
        record = review.save_override(
            data_file,
            input_id,
            payload.get("labels") or {},
            payload.get("review") or {},
            reviewer=payload.get("reviewer"),
            span_edits=payload.get("span_edits"),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"saved": True, "record": record})


@app.route("/api/review/export-overrides", methods=["GET"])
def api_review_export_overrides():
    """Export the human overrides file for a given dataset."""
    perm_result = check_tool_permission("export_data")
    if perm_result is not True:
        return perm_result
    rel_path = request.args.get("file") or ""
    data_file = review.resolve_data_file(rel_path)
    if data_file is None:
        return jsonify({"error": f"Unknown or unsafe file {rel_path!r}."}), 400
    override_path = review._layer_path_for(data_file.path, "human_overrides")
    if not os.path.exists(override_path):
        return jsonify({"error": "No overrides found."}), 404
    return send_file(override_path, as_attachment=True, download_name=os.path.basename(override_path))


@app.route("/api/review/recompute", methods=["POST"])
def api_review_recompute():
    """Re-derive box mappings + a redacted preview for one row from its current
    spans + unsaved span edits. Writes no labels/overrides; preview only."""
    perm_result = check_tool_permission("data_review")
    if perm_result is not True:
        return perm_result
    payload = request.get_json(force=True, silent=True) or {}
    rel_path = payload.get("file") or ""
    input_id = payload.get("input_id")
    data_file = review.resolve_data_file(rel_path)
    if data_file is None:
        return jsonify({"error": f"Unknown or unsafe file {rel_path!r}."}), 400
    if not input_id:
        return jsonify({"error": "Missing input_id."}), 400
    try:
        result = review.recompute_row(data_file, input_id, payload.get("span_edits"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(result)


@app.route("/api/review/run-router", methods=["POST"])
def api_review_run_router():
    """Explicitly run the shared VLM safety router on one row (PAID call).

    Fired only by the "Run router" button — never on load. Returns the validated
    router decision (action + risk flags) so the reviewer can inspect it and, if
    they choose, copy it into the label form. It does NOT write any labels.
    """
    perm_result = check_tool_permission("safety_router")
    if perm_result is not True:
        return perm_result
    payload = request.get_json(force=True, silent=True) or {}
    rel_path = payload.get("file") or ""
    input_id = payload.get("input_id")
    router_name = payload.get("router") or DEFAULT_ROUTER
    data_file = review.resolve_data_file(rel_path)
    if data_file is None:
        return jsonify({"error": f"Unknown or unsafe file {rel_path!r}."}), 400
    if not input_id:
        return jsonify({"error": "Missing input_id."}), 400
    row = review.get_row(data_file, input_id)
    if row is None:
        return jsonify({"error": f"Row {input_id!r} not found."}), 404
    try:
        router = get_router_cached(router_name)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    router_input = build_router_input(row)
    result = router.route(router_input)
    return jsonify({
        "router": router_name,
        "result": result.to_dict(),
        "labels": result.to_labels(),
        "modalities": router_input.get("input_modalities", {}),
    })


@app.route("/api/review/image", methods=["GET"])
def api_review_image():
    """Serve an image referenced by a row, constrained to the data root."""
    image_path = review.resolve_image(request.args.get("path"))
    if image_path is None:
        return jsonify({"error": "Image not found."}), 404
    return send_file(image_path)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=True)
