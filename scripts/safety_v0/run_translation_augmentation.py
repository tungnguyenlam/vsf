"""EN->VI translation augmentation for whole-text-labelled rows.

For each eligible source row this writes a translated *twin* row, so one labelled
sample becomes two. This is how we grow scarce Vietnamese prompt-injection / topic
data from English sources: translation preserves a *whole-text* label (the whole
string is or is not an attack) even though it would destroy PII character spans.

Scope and guards (matches the design decision: PI + topic only, never PII):

- Rows carrying ``detections.pii_spans`` are PII data; translation breaks their
  offsets, so a twin is NEVER produced for them (the original passes through).
- Only rows whose detected language differs from the target are translated, so
  Vietnamese rows are left alone (we do not translate VI->EN; English is not a
  project goal).
- The twin's labels are *inherited from a translated text*, so the provenance of
  the content-bearing axes (``prompt_injection``, ``political``, ``religious``)
  is marked ``<orig>_translated`` instead of pretending to be pristine gold. A
  source-gold whole-text injection span is regenerated over the translated text
  as ``source_gold_translated``.
- An ``augmentation`` block records the backend, model, and ``source_input_id``
  so every twin is traceable to its original and the pair can be kept in the
  same split downstream.

Translations are cached on disk (keyed by model + langs + text hash) so reruns
never re-pay. The translator backend/model are config flips.

Cost discipline: paid Gemini calls. Smoke-test with ``--limit`` first.

    python scripts/safety_v0/run_translation_augmentation.py \
        --slug deepset_prompt_injections --limit 20
    # data/safety_v0/converted/<slug>/source_canonical.jsonl
    #   -> data/safety_v0/augmented/<slug>/augmented.jsonl   (originals + twins)
"""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline.Datasets.language import detect_language  # noqa: E402
from src.pipeline.Datasets.safety_v0_schema import (  # noqa: E402
    new_prompt_injection_span,
    validate_row,
)
from src.pipeline.Datasets.safety_v0_sources import (  # noqa: E402
    augmented_path,
    converted_path,
    shared_dir,
)
from src.pipeline.Translation import get_translator  # noqa: E402
from src.pipeline.Utils import load_env  # noqa: E402

# Label axes whose value depends on the text content and is therefore carried
# (not invented) by a faithful translation. Their provenance gets a
# "_translated" suffix on the twin; modality assumptions (pii_visible, sexual,
# violence, blood_gore for a text PI source) are language-independent and kept.
_TRANSLATED_AXES = ("prompt_injection", "political", "religious")


def _cache_key(model: str, source_lang: str, target_lang: str, text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"{model}|{source_lang}|{target_lang}|{digest}"


def load_cache(path: Path) -> Dict[str, str]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_cache(path: Path, cache: Dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make_twin(
    row: Dict[str, Any],
    *,
    input_text_vi: str,
    ocr_text_vi: str,
    model: str,
    backend: str,
    source_lang: str,
    target_lang: str,
) -> Dict[str, Any]:
    """Build the translated twin of a row (deep-copied, then mutated)."""
    twin = json.loads(json.dumps(row))  # cheap deep copy of JSON-only data
    twin["input_id"] = f"{row['input_id']}_{target_lang}"

    content = twin.setdefault("content", {})
    content["input_text"] = input_text_vi
    # No PII on translation-eligible rows, so sanitized == input.
    content["sanitized_text"] = input_text_vi
    if ocr_text_vi or content.get("ocr_text"):
        content["ocr_text"] = ocr_text_vi
        content["sanitized_ocr_text"] = ocr_text_vi

    # Regenerate the source-gold whole-text injection span over the translated
    # text; drop spans tied to the original text's offsets.
    spans = twin.get("detections", {}).get("prompt_injection_spans") or []
    gold = [s for s in spans if str(s.get("detector", "")).startswith("source_gold")]
    new_spans: List[Dict[str, Any]] = []
    if gold and input_text_vi.strip():
        attack_type = gold[0].get("attack_type", "prompt_injection")
        new_spans.append(
            new_prompt_injection_span(
                "pi_0001",
                attack_type,
                0,
                len(input_text_vi),
                input_text_vi,
                score=gold[0].get("score"),
                box_ids=[],
                detector="source_gold_translated",
            )
        )
    twin["detections"]["prompt_injection_spans"] = new_spans

    # Mark provenance of the content-bearing axes as translated (only where known).
    label_source = twin.setdefault("label_source", {})
    labels = twin.get("labels", {})
    for axis in _TRANSLATED_AXES:
        if labels.get(axis) is not None and label_source.get(axis):
            base = str(label_source[axis])
            if not base.endswith("_translated"):
                label_source[axis] = f"{base}_translated"

    twin["augmentation"] = {
        "type": "translation",
        "direction": f"{source_lang}2{target_lang}",
        "backend": backend,
        "model": model,
        "source_input_id": row["input_id"],
    }
    twin.setdefault("review", {})["status"] = "unreviewed"
    return twin


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser(description="EN->VI translation augmentation over canonical rows.")
    parser.add_argument("--slug", help="Source slug for default input/output paths.")
    parser.add_argument("--input", help="Input JSONL (overrides --slug default).")
    parser.add_argument("--output", help="Output JSONL (overrides --slug default).")
    parser.add_argument("--backend", default="gemini", help="Translator backend name.")
    parser.add_argument("--model", default=None, help="Model override for the backend.")
    parser.add_argument("--source-lang", default="en")
    parser.add_argument("--target-lang", default="vi")
    parser.add_argument(
        "--include-originals",
        dest="include_originals",
        action="store_true",
        default=True,
        help="Write the original rows alongside the twins (default).",
    )
    parser.add_argument(
        "--twins-only",
        dest="include_originals",
        action="store_false",
        help="Write only the translated twins.",
    )
    parser.add_argument("--cache", help="Translation cache JSON (defaults under manifests/).")
    parser.add_argument("--limit", type=int, default=None, help="Max rows to read (smoke test).")
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.0,
        help="Seconds to sleep after each new (uncached) call; pace under free-tier RPM caps.",
    )
    args = parser.parse_args()

    if args.input:
        in_path = Path(args.input)
    elif args.slug:
        in_path = converted_path(args.slug)
    else:
        parser.error("provide --input or --slug")
    if args.output:
        out_path = Path(args.output)
    elif args.slug:
        out_path = augmented_path(args.slug, create=True)
    else:
        parser.error("provide --output or --slug")
    if not in_path.exists():
        print(f"Input not found: {in_path}", file=sys.stderr)
        return 1

    translator_kwargs = {"model": args.model} if args.model else {}
    translator = get_translator(args.backend, **translator_kwargs)
    model_name = getattr(translator, "model", args.backend)

    cache_path = Path(args.cache) if args.cache else (
        shared_dir("manifests", create=True) / "translation_cache.json"
    )
    cache = load_cache(cache_path)

    def translate(text: str) -> str:
        if not text or not text.strip():
            return text
        key = _cache_key(model_name, args.source_lang, args.target_lang, text)
        if key in cache:
            return cache[key]
        out = translator.translate(text, source_lang=args.source_lang, target_lang=args.target_lang)
        cache[key] = out
        if args.sleep:
            time.sleep(args.sleep)
        return out

    rows: List[Dict[str, Any]] = []
    with open(in_path, encoding="utf-8") as src:
        for line in src:
            line = line.strip()
            if not line:
                continue
            if args.limit is not None and len(rows) >= args.limit:
                break
            rows.append(json.loads(line))

    total = twins = skipped_pii = skipped_lang = invalid = new_calls = failed = 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(out_path, "w", encoding="utf-8") as dst:
            for row in rows:
                total += 1
                if args.include_originals:
                    dst.write(json.dumps(row, ensure_ascii=False) + "\n")

                # Guard: never translate PII-span data.
                if row.get("detections", {}).get("pii_spans"):
                    skipped_pii += 1
                    continue
                # Gate: skip rows already in the target language.
                in_text = row.get("content", {}).get("input_text") or ""
                if detect_language(in_text) == args.target_lang:
                    skipped_lang += 1
                    continue

                before = len(cache)
                try:
                    in_vi = translate(in_text)
                    ocr_vi = translate(row.get("content", {}).get("ocr_text") or "")
                except Exception as exc:  # noqa: BLE001 - one bad row must not kill the run
                    failed += 1
                    print(f"  translate failed {row['input_id']}: {exc}", file=sys.stderr)
                    save_cache(cache_path, cache)  # keep whatever succeeded
                    continue
                new_calls += len(cache) - before
                if len(cache) - before:  # flush periodically to protect budget
                    if new_calls % 25 == 0:
                        save_cache(cache_path, cache)

                twin = make_twin(
                    row,
                    input_text_vi=in_vi,
                    ocr_text_vi=ocr_vi,
                    model=model_name,
                    backend=args.backend,
                    source_lang=args.source_lang,
                    target_lang=args.target_lang,
                )
                errors = validate_row(twin)
                if errors:
                    invalid += 1
                    print(f"  invalid {twin.get('input_id')}: {errors[0]}", file=sys.stderr)
                    continue
                dst.write(json.dumps(twin, ensure_ascii=False) + "\n")
                twins += 1
    finally:
        save_cache(cache_path, cache)

    print(
        f"Translation augmentation: {total} rows -> {twins} twins "
        f"({skipped_pii} skipped (pii), {skipped_lang} skipped (already target), "
        f"{failed} failed (transient), {invalid} invalid, "
        f"{new_calls} new translations) -> {out_path}"
    )
    return 1 if invalid else 0


if __name__ == "__main__":
    raise SystemExit(main())
