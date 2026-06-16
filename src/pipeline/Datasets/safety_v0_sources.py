"""Stable source names and path helpers for the `safety_v0` dataset build.

Single source of truth for:

- the canonical source slugs used everywhere (folder names, ``input_id``
  prefixes, work-queue references in ``DATA_PLAN.md``), and
- the on-disk layout under ``data/safety_v0/`` defined in the DATA_PLAN
  "Project Folder Structure" section.

Converters and the ``scripts/safety_v0/run_*.py`` stages import these helpers so
paths never get hardcoded at call sites. Change the layout here, not in the
scripts.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


# Repo root: this file is src/pipeline/Datasets/safety_v0_sources.py
REPO_ROOT = Path(__file__).resolve().parents[3]
DATASET_VERSION = "safety_v0"
DEFAULT_DATA_ROOT = REPO_ROOT / "data" / DATASET_VERSION


@dataclass(frozen=True)
class SafetySource:
    """One accepted/queued source in the safety_v0 build.

    - ``slug``: stable identifier used for folders and ``input_id`` prefixes.
    - ``name``: value written to ``row["source"]["name"]`` by default. For
      single-origin sources this is the upstream id (e.g. ``WebPII/webpii``);
      for aggregates it is the slug and the converter sets a per-row name.
    - ``decision``: the DATA_PLAN work-queue decision (accept/maybe/...).
    - ``has_images``: whether rows carry images (drives whether the OCR/redaction
      stages run for this source).
    """

    slug: str
    name: str
    decision: str
    has_images: bool


# Work-queue sources, in DATA_PLAN order. Slugs match the converter output
# folders documented in DATA_PLAN.md.
_SOURCES: List[SafetySource] = [
    SafetySource("existing_repo_pii", "existing_repo_pii", "accept", False),
    SafetySource("webpii", "WebPII/webpii", "accept", True),
    SafetySource("meddies_pii", "Meddies/meddies-pii", "maybe", False),
    SafetySource("local_vi_prompt_injection", "local_vi_prompt_injection", "accept", False),
    SafetySource("llmail_inject_challenge", "microsoft/llmail-inject-challenge", "accept", False),
    SafetySource("deepset_prompt_injections", "deepset/prompt-injections", "accept", False),
    SafetySource(
        "cyberseceval3_visual_prompt_injection",
        "facebook/cyberseceval3-visual-prompt-injection",
        "accept_after_inspection",
        True,
    ),
    SafetySource("vihsd_topic_safety", "uitnlp/vihsd", "accept", False),
    SafetySource("vlguard", "ys-zong/VLGuard", "accept_after_inspection", True),
    SafetySource("mm_safetybench", "PKU-Alignment/MM-SafetyBench", "accept_after_inspection", True),
    SafetySource("unsafebench", "yiting/UnsafeBench", "accept_after_inspection", True),
]

SOURCE_REGISTRY: Dict[str, SafetySource] = {s.slug: s for s in _SOURCES}


def list_source_slugs() -> List[str]:
    """Source slugs in DATA_PLAN work-queue order."""
    return [s.slug for s in _SOURCES]


def get_source(slug: str) -> SafetySource:
    try:
        return SOURCE_REGISTRY[slug]
    except KeyError as exc:
        available = ", ".join(list_source_slugs())
        raise ValueError(
            f"Unknown safety_v0 source {slug!r}. Available: {available}"
        ) from exc


def format_input_id(slug: str, index: int) -> str:
    """Canonical ``input_id`` such as ``safety_v0_webpii_000001`` (1-based)."""
    get_source(slug)  # validate slug
    return f"{DATASET_VERSION}_{slug}_{index:06d}"


# --- Path layout -------------------------------------------------------------
# Per-source subdirectories under data/safety_v0/. Each maps to a build stage.
_PER_SOURCE_KINDS = (
    "raw",
    "samples",
    "inspection",
    "converted",
    "rendered",
    "ocr",
    "redacted",
    "weak",
    "verified",
)
# Shared (not per-source) subdirectories.
_SHARED_KINDS = (
    "review/queue",
    "review/human_overrides",
    "review/api_labels",
    "final",
    "manifests",
)


def data_root(root: Optional[Path] = None) -> Path:
    return Path(root) if root is not None else DEFAULT_DATA_ROOT


def _ensure(path: Path, create: bool) -> Path:
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def source_dir(kind: str, slug: str, *, root: Optional[Path] = None, create: bool = False) -> Path:
    """Per-source directory, e.g. ``data/safety_v0/converted/<slug>/``."""
    if kind not in _PER_SOURCE_KINDS:
        raise ValueError(f"Unknown per-source kind {kind!r}. Allowed: {_PER_SOURCE_KINDS}")
    get_source(slug)
    return _ensure(data_root(root) / kind / slug, create)


def shared_dir(kind: str, *, root: Optional[Path] = None, create: bool = False) -> Path:
    """Shared directory, e.g. ``data/safety_v0/review/queue/`` or ``final/``."""
    if kind not in _SHARED_KINDS:
        raise ValueError(f"Unknown shared kind {kind!r}. Allowed: {_SHARED_KINDS}")
    return _ensure(data_root(root) / kind, create)


def converted_path(slug: str, *, root: Optional[Path] = None, create: bool = False) -> Path:
    """Canonical rows straight from the source converter (labels from source only)."""
    return source_dir("converted", slug, root=root, create=create) / "source_canonical.jsonl"


def ocr_path(slug: str, *, root: Optional[Path] = None, create: bool = False) -> Path:
    """Rows after the OCR stage: geometry.ocr_boxes + content.ocr_text filled in."""
    return source_dir("ocr", slug, root=root, create=create) / "ocr.jsonl"


def redacted_path(slug: str, *, root: Optional[Path] = None, create: bool = False) -> Path:
    """Rows after OCR-text PII detection + span-to-box redaction of the image."""
    return source_dir("redacted", slug, root=root, create=create) / "redacted.jsonl"


def redacted_images_dir(slug: str, *, root: Optional[Path] = None, create: bool = False) -> Path:
    """Where redacted image artifacts for a source are written."""
    return source_dir("redacted", slug, root=root, create=create) / "images"


def weak_path(slug: str, *, root: Optional[Path] = None, create: bool = False) -> Path:
    """Rows after OCR + PII/redaction + prompt-injection + weak visual/topic labels."""
    return source_dir("weak", slug, root=root, create=create) / "weak_labeled.jsonl"


def human_overrides_path(slug: str, *, root: Optional[Path] = None, create: bool = False) -> Path:
    """Human corrections written by the webdemo review tool, one file per source."""
    get_source(slug)
    return shared_dir("review/human_overrides", root=root, create=create) / f"{slug}.jsonl"


def review_queue_dir(*, root: Optional[Path] = None, create: bool = False) -> Path:
    return shared_dir("review/queue", root=root, create=create)


def api_labels_dir(*, root: Optional[Path] = None, create: bool = False) -> Path:
    return shared_dir("review/api_labels", root=root, create=create)


def final_dir(*, root: Optional[Path] = None, create: bool = False) -> Path:
    return shared_dir("final", root=root, create=create)


def manifests_dir(*, root: Optional[Path] = None, create: bool = False) -> Path:
    return shared_dir("manifests", root=root, create=create)
