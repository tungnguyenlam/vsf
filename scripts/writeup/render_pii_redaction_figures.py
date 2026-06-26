"""Render the 4 PII redaction figures for the writeup as clean matplotlib schematics.

The previous version of these figures was 4 webdemo screenshots. Those were
information-dense but visually noisy (browser chrome, label chips, save button,
router rail, etc.). This script replaces them with 4 schematics that keep the
exact same payload (real row IDs, real spans, real box coordinates) but lay it
out as textbook-style figures.

Figures:
  1. pii-redaction-pipeline.png        -> text-row "Detect" stage
  2. pii-redaction-pipeline-2.png      -> text-row "Review" stage (sanitized + span table)
  3. pii-redaction-image-1.png         -> image-row "Detect" stage (image + 9 numbered boxes)
  4. pii-redaction-image-3.png         -> image-row "Redact" stage (redacted image + box->OCR map)

Usage:
    python scripts/writeup/render_pii_redaction_figures.py

Reads:
    data/safety_v0/converted/existing_repo_pii/source_canonical.jsonl
    data/safety_v0/ocr/webpii/ocr.jsonl
    data/safety_v0/converted/webpii/images/safety_v0_webpii_000001.png
    data/safety_v0/redacted/webpii/images/safety_v0_webpii_000001_redacted.png

Writes:
    writeup/images/pii-redaction-pipeline.png
    writeup/images/pii-redaction-pipeline-2.png
    writeup/images/pii-redaction-image-1.png
    writeup/images/pii-redaction-image-3.png
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
TXT_SRC = REPO / "data/safety_v0/converted/existing_repo_pii/source_canonical.jsonl"
IMG_SRC = REPO / "data/safety_v0/ocr/webpii/ocr.jsonl"
IMG_ORIG = REPO / "data/safety_v0/converted/webpii/images/safety_v0_webpii_000001.png"
IMG_REDACTED = REPO / "data/safety_v0/redacted/webpii/images/safety_v0_webpii_000001_redacted.png"
OUT = REPO / "writeup/images"

ENTITY_COLORS = {
    "PERSON": "#ffd6a5",
    "LOCATION": "#d0bfff",
    "ORGANIZATION": "#fcc2d7",
    "PHONE_NUMBER": "#b9f6ca",
    "MISC": "#fff3bf",
    "MEDICAL": "#a5d8ff",
    "NRP": "#c0c0c0",
    "CREDENTIAL": "#ffadad",
    "URL": "#bdb2ff",
    "IP_ADDRESS": "#9bf6ff",
    "BANK_ACCOUNT": "#ffc6ff",
    "ID": "#fdffb6",
    "DATE_TIME": "#e0e0e0",
}

# Reasonable defaults that look good in typst at 100% width on A4.
FIGSIZE_WIDE = (18.0, 9.0)
FIGSIZE_TALL = (18.0, 10.0)
DPI = 300
FONT = "Liberation Sans"
MONO = "Liberation Mono"
# Coordinate space is the figsize in inches. All positions in the figure
# functions are in this space. Sizes and font sizes are also in this space.
# We also bump font sizes by S_FONT so the text scales with the larger figure.
S_FONT = 1.30


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_first(path: Path) -> dict:
    with path.open() as f:
        return json.loads(f.readline())


def find_text_row() -> dict:
    """Find the text row whose gold spans match what the original screenshot showed
    (MEDICAL+NRP+CREDENTIAL+URL+IP_ADDRESS — the existing_repo_pii_000006 row)."""
    with TXT_SRC.open() as f:
        for line in f:
            d = json.loads(line)
            spans = d.get("detections", {}).get("pii_spans", [])
            types = {s["entity_type"] for s in spans}
            if {"MEDICAL", "NRP", "CREDENTIAL", "URL", "IP_ADDRESS"}.issubset(types):
                return d
    raise RuntimeError("could not find the reference text row")


def stage_header(ax, n: int, label: str, title: str, width: float = 18.0, height: float = 9.0) -> None:
    """Top strip with a circled step number and the stage title."""
    ax.set_xlim(0, width)
    ax.set_ylim(0, height)
    ax.axis("off")
    circle = plt.Circle((0.55, height - 0.65), 0.42, color="#1a5fb4", zorder=3)
    ax.add_patch(circle)
    ax.text(0.55, height - 0.65, str(n), ha="center", va="center", color="white",
            fontsize=23.4, fontweight="bold", zorder=4)
    ax.text(1.20, height - 0.58, label, ha="left", va="center",
            fontsize=20.8, fontweight="bold", color="#1a1a1a")
    ax.text(1.20, height - 1.05, title, ha="left", va="center",
            fontsize=15.6, color="#5a5a5a", style="italic")


def soft_box(ax, x, y, w, h, fc="#f4f6fa", ec="#cdd5e0", lw=0.7) -> FancyBboxPatch:
    box = FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08",
        facecolor=fc, edgecolor=ec, linewidth=lw, zorder=1,
    )
    ax.add_patch(box)
    return box


def entity_chip(ax, x, y, text: str, entity: str) -> float:
    color = ENTITY_COLORS.get(entity, "#e8e8e8")
    pad = 0.08
    width = 0.16 * len(text) + 0.20
    chip = FancyBboxPatch(
        (x, y), width, 0.32, boxstyle="round,pad=0.01,rounding_size=0.04",
        facecolor=color, edgecolor="#888", linewidth=0.4, zorder=2,
    )
    ax.add_patch(chip)
    ax.text(x + 0.05, y + 0.16, text, ha="left", va="center",
            fontsize=11.1, family=MONO, zorder=3)
    return width + 0.04


# ---------------------------------------------------------------------------
# Figure 1 — Text-row "Detect" stage
# ---------------------------------------------------------------------------


def figure1_text_detect(row: dict) -> None:
    text = row["content"]["input_text"]
    spans = row["detections"]["pii_spans"]

    fig, ax = plt.subplots(figsize=FIGSIZE_WIDE, dpi=DPI)
    fig.patch.set_facecolor("white")
    stage_header(
        ax, 1, "Detect  (text-only row)",
        f"pii_masking_95k / train / {row['input_id']} — {len(spans)} spans via source_gold",
    )

    # Source chip strip
    ax.text(0.55, 7.50, "source: ", fontsize=11.7, color="#5a5a5a", ha="right", va="center")
    chips_x = 0.70
    for label, fill in (
        ("pii_masking_95k", "#dde7ff"),
        ("image: false", "#eef2f7"),
        ("text: true", "#eef2f7"),
        ("ocr: false", "#eef2f7"),
    ):
        w = 0.18 * len(label) + 0.40
        ax.add_patch(FancyBboxPatch(
            (chips_x, 7.20), w, 0.50,
            boxstyle="round,pad=0.01,rounding_size=0.05",
            facecolor=fill, edgecolor="#9aa3b2", linewidth=0.5,
        ))
        ax.text(chips_x + w / 2, 7.45, label, ha="center", va="center",
                fontsize=11.1, color="#1a1a1a")
        chips_x += w + 0.10

    # Annotated text box (the input text with each PII span highlighted)
    box_x, box_y, box_w, box_h = 0.55, 2.60, 16.90, 4.10
    soft_box(ax, box_x, box_y, box_w, box_h, fc="#fafafa", ec="#cdd5e0")
    ax.text(box_x + 0.25, box_y + box_h - 0.40,
            "Input text with detected PII spans highlighted",
            fontsize=11.7, color="#5a5a5a", style="italic")

    # Render text in a monospace column. We word-wrap the text and record the
    # line/column of every character so we can draw highlight rectangles on the
    # correct (line, col) pair.
    mono_advance = 0.140
    base_x = box_x + 0.30
    base_y = box_y + box_h - 0.85
    line_h = 0.42
    max_chars = int((box_w - 0.60) / mono_advance)
    char_to_pos: list[tuple[int, int]] = []
    col = 0
    line_no = 0
    wrapped_lines: list[str] = []
    cur_line = ""
    for ch in text:
        if ch == "\n":
            wrapped_lines.append(cur_line)
            cur_line = ""
            line_no += 1
            col = 0
            char_to_pos.append((line_no, -1))
            continue
        if col >= max_chars and ch == " ":
            wrapped_lines.append(cur_line)
            cur_line = ""
            line_no += 1
            col = 0
            char_to_pos.append((line_no, -1))
            continue
        if col >= max_chars:
            wrapped_lines.append(cur_line)
            cur_line = ""
            line_no += 1
            col = 0
        cur_line += ch
        char_to_pos.append((line_no, col))
        col += 1
    wrapped_lines.append(cur_line)

    text_height = 0.30
    for i, line in enumerate(wrapped_lines):
        ax.text(base_x, base_y - i * line_h, line, ha="left", va="top",
                family=MONO, fontsize=11.7, color="#1a1a1a")

    for s in spans:
        ent = s["entity_type"]
        if ent not in ENTITY_COLORS:
            continue
        rows = set()
        for i in range(s["start"], s["end"]):
            ln, c = char_to_pos[i]
            if c < 0:
                continue
            rows.add(ln)
        for ln in rows:
            cols = [char_to_pos[i][1] for i in range(s["start"], s["end"])
                    if char_to_pos[i][0] == ln and char_to_pos[i][1] >= 0]
            if not cols:
                continue
            c0, c1 = min(cols), max(cols) + 1
            x = base_x + c0 * mono_advance - 0.02
            y = base_y - ln * line_h - text_height
            w = (c1 - c0) * mono_advance + 0.04
            ax.add_patch(Rectangle(
                (x, y), w, text_height,
                facecolor=ENTITY_COLORS[ent], edgecolor="none",
                alpha=0.55, zorder=5,
            ))

    # Span annotation strip below the text (one chip per span, wrapped)
    ax.text(0.55, 2.20, "Detected spans", fontsize=12.3, fontweight="bold",
            color="#1a1a1a")
    ax.text(0.55, 1.90,
            "each chip = (entity, span text, char offsets); sorted by entity type then start",
            fontsize=10.7, color="#5a5a5a", style="italic")
    sorted_spans = sorted(spans, key=lambda s: (s["entity_type"], s["start"]))
    cur_x = 0.55
    cur_y = 1.30
    max_x = 17.40
    for s in sorted_spans:
        short = s["text"] if len(s["text"]) < 28 else s["text"][:25] + "…"
        chip_text = f"{s['entity_type']}  '{short}'  {s['start']}-{s['end']}"
        width = 0.115 * len(chip_text) + 0.40
        if cur_x + width > max_x:
            cur_x = 0.55
            cur_y -= 0.58
        ax.add_patch(FancyBboxPatch(
            (cur_x, cur_y), width, 0.45,
            boxstyle="round,pad=0.01,rounding_size=0.05",
            facecolor=ENTITY_COLORS.get(s["entity_type"], "#e8e8e8"),
            edgecolor="#888", linewidth=0.4,
        ))
        ax.text(cur_x + 0.10, cur_y + 0.22, chip_text, ha="left", va="center",
                family=MONO, fontsize=9.9, color="#1a1a1a")
        cur_x += width + 0.08

    fig.tight_layout(pad=0.5)
    out = OUT / "pii-redaction-pipeline.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"wrote {out}")


# ---------------------------------------------------------------------------
# Figure 2 — Text-row "Review" stage
# ---------------------------------------------------------------------------


def figure2_text_review(row: dict) -> None:
    text = row["content"]["input_text"]
    spans = sorted(row["detections"]["pii_spans"], key=lambda s: s["start"], reverse=True)
    sanitized = text
    for s in spans:
        sanitized = sanitized[: s["start"]] + f"<{s['entity_type']}>" + sanitized[s["end"]:]

    fig, (ax_text, ax_table) = plt.subplots(
        2, 1, figsize=FIGSIZE_WIDE, dpi=DPI,
        gridspec_kw={"height_ratios": [1.15, 1.0]},
    )
    fig.patch.set_facecolor("white")

    # --- top: sanitized text ---
    stage_header(
        ax_text, 2, "Review  (text-only row)",
        "live 'Sanitized' preview with <ENTITY> substitutions; reviewer confirms before save",
    )
    soft_box(ax_text, 0.55, 1.20, 16.90, 6.40, fc="#f4f7fb", ec="#cdd5e0")
    ax_text.text(0.85, 7.20, "Sanitized (live)", fontsize=11.7, color="#5a5a5a", style="italic")
    # Build sanitized text with [ENTITY] markers (so it's still readable as plain text)
    cursor = 0
    pieces: list[tuple[str, str | None]] = []
    i = 0
    while i < len(sanitized):
        if sanitized[i] == "<":
            end = sanitized.find(">", i)
            if end == -1:
                pieces.append((sanitized[cursor:], None))
                break
            if cursor < i:
                pieces.append((sanitized[cursor:i], None))
            pieces.append((sanitized[i + 1 : end], sanitized[i + 1 : end]))
            i = end + 1
            cursor = i
        else:
            i += 1
    if cursor < len(sanitized):
        pieces.append((sanitized[cursor:], None))
    line = "".join(
        f"[{p[0]}]" if p[1] is not None else p[0] for p in pieces
    )
    ax_text.text(0.85, 5.80, line, ha="left", va="top", family=MONO,
                 fontsize=11.4, wrap=True, color="#1a1a1a")
    used = sorted({s["entity_type"] for s in spans})
    cur_x = 0.85
    cur_y = 1.85
    ax_text.text(0.85, 2.40, "Legend", fontsize=11.7, color="#5a5a5a", style="italic")
    for ent in used:
        chip_text = f"<{ent}>"
        w = 0.21 * len(chip_text) + 0.40
        ax_text.add_patch(FancyBboxPatch(
            (cur_x, cur_y), w, 0.42,
            boxstyle="round,pad=0.01,rounding_size=0.05",
            facecolor=ENTITY_COLORS.get(ent, "#e8e8e8"),
            edgecolor="#888", linewidth=0.4,
        ))
        ax_text.text(cur_x + 0.10, cur_y + 0.21, chip_text, ha="left", va="center",
                     family=MONO, fontsize=11.1)
        cur_x += w + 0.12
        if cur_x > 16.0:
            cur_x = 0.85
            cur_y = 1.30

    # --- bottom: span table ---
    ax_table.axis("off")
    ax_table.set_xlim(0, 17.5)
    ax_table.set_ylim(0, 5)
    ax_table.text(0.55, 4.65, "PII spans table  (per-span record on save)",
                  fontsize=13.0, fontweight="bold", color="#1a1a1a")
    ax_table.text(0.55, 4.35, "stored alongside sanitized text in human_overrides/<source>.jsonl",
                  fontsize=11.1, color="#5a5a5a", style="italic")

    cols = [
        ("#", 0.7),
        ("TYPE", 1.9),
        ("TEXT", 7.5),
        ("SPAN", 1.7),
        ("FROM", 2.7),
    ]
    col_x = [0.55]
    for _, w in cols:
        col_x.append(col_x[-1] + w)
    header_y = 3.85
    ax_table.add_patch(Rectangle((0.55, header_y - 0.05), sum(c[1] for c in cols), 0.55,
                                 facecolor="#eef2f7", edgecolor="#cdd5e0", linewidth=0.5))
    for (label, _), x in zip(cols, col_x[:-1]):
        ax_table.text(x + 0.12, header_y + 0.22, label, ha="left", va="center",
                      fontsize=11.7, fontweight="bold", color="#1a1a1a")

    row_y = header_y - 0.45
    for i, s in enumerate(sorted(spans, key=lambda x: x["start"]), start=1):
        if i % 2 == 0:
            ax_table.add_patch(Rectangle(
                (0.55, row_y - 0.05), sum(c[1] for c in cols), 0.50,
                facecolor="#fafbfd", edgecolor="none",
            ))
        ax_table.text(col_x[0] + 0.12, row_y + 0.18, str(i),
                      ha="left", va="center", fontsize=11.1, family=MONO)
        ax_table.add_patch(FancyBboxPatch(
            (col_x[1] + 0.10, row_y + 0.05), 1.75, 0.40,
            boxstyle="round,pad=0.01,rounding_size=0.05",
            facecolor=ENTITY_COLORS.get(s["entity_type"], "#e8e8e8"),
            edgecolor="#888", linewidth=0.4,
        ))
        ax_table.text(col_x[1] + 0.20, row_y + 0.25, s["entity_type"],
                      ha="left", va="center", family=MONO, fontsize=10.8)
        ax_table.text(col_x[2] + 0.12, row_y + 0.18,
                      s["text"] if len(s["text"]) < 95 else s["text"][:92] + "…",
                      ha="left", va="center", family=MONO, fontsize=10.8)
        ax_table.text(col_x[3] + 0.12, row_y + 0.18,
                      f"{s['start']}-{s['end']}",
                      ha="left", va="center", family=MONO, fontsize=10.8)
        ax_table.text(col_x[4] + 0.12, row_y + 0.18,
                      s.get("detector", "source_gold"),
                      ha="left", va="center", family=MONO, fontsize=10.8, color="#5a5a5a")
        row_y -= 0.50

    fig.tight_layout(pad=0.5)
    out = OUT / "pii-redaction-pipeline-2.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"wrote {out}")


# ---------------------------------------------------------------------------
# Figure 3 — Image-row "Detect" stage
# ---------------------------------------------------------------------------


def figure3_image_detect(row: dict) -> None:
    detections = row["detections"]["pii_spans"]
    image = Image.open(IMG_ORIG)
    W, H = image.size  # 1280 x 895

    fig, ax = plt.subplots(figsize=FIGSIZE_WIDE, dpi=DPI)
    fig.patch.set_facecolor("white")
    stage_header(
        ax, 3, "Detect  (image row)",
        f"WebPII/webpii / test / {row['input_id']} — 9 PII regions, OCR-aligned",
    )

    # Source chip strip
    ax.text(0.55, 7.50, "source: ", fontsize=11.7, color="#5a5a5a", ha="right", va="center")
    chips_x = 0.70
    for label, fill in (
        ("WebPII/webpii", "#dde7ff"),
        ("image: true", "#eef2f7"),
        ("text: false", "#eef2f7"),
        ("ocr: true", "#eef2f7"),
    ):
        w = 0.18 * len(label) + 0.40
        ax.add_patch(FancyBboxPatch(
            (chips_x, 7.20), w, 0.50,
            boxstyle="round,pad=0.01,rounding_size=0.05",
            facecolor=fill, edgecolor="#9aa3b2", linewidth=0.5,
        ))
        ax.text(chips_x + w / 2, 7.45, label, ha="center", va="center",
                fontsize=11.1, color="#1a1a1a")
        chips_x += w + 0.10

    # Image with detection boxes
    img_x, img_y, img_w, img_h = 0.55, 0.8, 10.50, 6.10
    ax.add_patch(Rectangle((img_x, img_y), img_w, img_h,
                           facecolor="white", edgecolor="#cdd5e0", linewidth=0.6,
                           zorder=1))
    ax.imshow(image, extent=[img_x, img_x + img_w, img_y, img_y + img_h], zorder=2)

    sx = img_w / W
    sy = img_h / H
    spb = row["geometry"]["source_pii_boxes"]
    spb_map = {b["box_id"]: b for b in spb}
    for idx, s in enumerate(detections, start=1):
        if not s.get("box_ids"):
            continue
        src_box_id = s.get("source_box_id")
        b = spb_map.get(src_box_id) if src_box_id else None
        if b is None:
            continue
        x1, y1, x2, y2 = b["box"]
        rx = img_x + x1 * sx
        ry = img_y + (H - y2) * sy
        rw = (x2 - x1) * sx
        rh = (y2 - y1) * sy
        color = ENTITY_COLORS.get(s["entity_type"], "#1a5fb4")
        ax.add_patch(Rectangle(
            (rx, ry), rw, rh,
            facecolor=color, edgecolor="#1a1a1a",
            linewidth=1.2, alpha=0.40, zorder=3,
        ))
        ax.add_patch(FancyBboxPatch(
            (rx, ry + rh - 0.30), 0.40, 0.30,
            boxstyle="round,pad=0.005,rounding_size=0.04",
            facecolor="#1a5fb4", edgecolor="#1a1a1a", linewidth=0.5, zorder=4,
        ))
        ax.text(rx + 0.20, ry + rh - 0.15, str(idx), ha="center", va="center",
                color="white", fontsize=11.7, fontweight="bold", zorder=5)

    # Right rail
    rail_x = 11.50
    rail_y = 6.50
    ax.text(rail_x, rail_y, f"PII regions  ({len(detections)} detected)",
            fontsize=13.0, fontweight="bold", color="#1a1a1a")
    ax.text(rail_x, rail_y - 0.30, "rows numbered to match the boxes on the left",
            fontsize=10.7, color="#5a5a5a", style="italic")
    cur_y = rail_y - 0.80
    for idx, s in enumerate(detections, start=1):
        ax.add_patch(FancyBboxPatch(
            (rail_x, cur_y - 0.07), 0.40, 0.40,
            boxstyle="round,pad=0.005,rounding_size=0.04",
            facecolor="#1a5fb4", edgecolor="#1a1a1a", linewidth=0.5,
        ))
        ax.text(rail_x + 0.20, cur_y + 0.13, str(idx), ha="center", va="center",
                color="white", fontsize=11.7, fontweight="bold")
        ent = s["entity_type"]
        w = 0.21 * len(ent) + 0.40
        ax.add_patch(FancyBboxPatch(
            (rail_x + 0.55, cur_y - 0.07), w, 0.40,
            boxstyle="round,pad=0.005,rounding_size=0.04",
            facecolor=ENTITY_COLORS.get(ent, "#e8e8e8"),
            edgecolor="#888", linewidth=0.4,
        ))
        ax.text(rail_x + 0.65, cur_y + 0.13, ent, ha="left", va="center",
                family=MONO, fontsize=10.7)
        ax.text(rail_x + 0.55 + w + 0.10, cur_y + 0.13,
                f"{s['text']}",
                ha="left", va="center", family=MONO, fontsize=10.7, color="#1a1a1a")
        ax.text(rail_x + 0.55 + w + 0.10, cur_y - 0.18,
                "ocr: " + ", ".join(s.get("box_ids", [])),
                ha="left", va="center", family=MONO, fontsize=9.8, color="#5a5a5a")
        cur_y -= 0.62

    fig.tight_layout(pad=0.5)
    out = OUT / "pii-redaction-image-1.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"wrote {out}")


# ---------------------------------------------------------------------------
# Figure 4 — Image-row "Redact" stage
# ---------------------------------------------------------------------------


def figure4_image_redact(row: dict) -> None:
    detections = row["detections"]["pii_spans"]
    image = Image.open(IMG_REDACTED)
    W, H = image.size

    fig, ax = plt.subplots(figsize=FIGSIZE_WIDE, dpi=DPI)
    fig.patch.set_facecolor("white")
    stage_header(
        ax, 4, "Redact  (image row)",
        f"redacted image — 9 PII regions replaced by blurred blocks; OCR text and span table preserved",
    )

    # Status chip
    ax.add_patch(FancyBboxPatch(
        (0.55, 7.20), 7.0, 0.50,
        boxstyle="round,pad=0.01,rounding_size=0.05",
        facecolor="#e6f4ea", edgecolor="#7fc99a", linewidth=0.5,
    ))
    ax.text(0.75, 7.45, "Redacted image  ·  PII regions masked",
            ha="left", va="center", fontsize=12.3, color="#1a5a3a", fontweight="bold")
    ax.text(0.55, 6.80, "released payload = sanitized bytes + audit metadata (span table + box→OCR map below)",
            fontsize=11.1, color="#5a5a5a", style="italic")

    # Redacted image
    img_x, img_y, img_w, img_h = 0.55, 0.8, 10.50, 5.80
    ax.add_patch(Rectangle((img_x, img_y), img_w, img_h,
                           facecolor="white", edgecolor="#cdd5e0", linewidth=0.6,
                           zorder=1))
    ax.imshow(image, extent=[img_x, img_x + img_w, img_y, img_y + img_h], zorder=2)

    # Right rail: box -> OCR mapping
    rail_x = 11.50
    rail_y = 6.50
    ax.text(rail_x, rail_y, "Box ↔ OCR mapping", fontsize=13.0, fontweight="bold",
            color="#1a1a1a")
    ax.text(rail_x, rail_y - 0.30, "each detection is traceable to its source OCR box",
            fontsize=10.7, color="#5a5a5a", style="italic")

    headers = [("#", 0.40), ("TYPE", 1.55), ("TEXT", 2.85), ("OCR BOX IDS", 1.55)]
    cur_x = rail_x
    header_y = rail_y - 0.80
    for label, w in headers:
        ax.add_patch(Rectangle(
            (cur_x, header_y - 0.07), w, 0.40,
            facecolor="#eef2f7", edgecolor="#cdd5e0", linewidth=0.4,
        ))
        ax.text(cur_x + 0.08, header_y + 0.13, label, ha="left", va="center",
                fontsize=10.7, fontweight="bold", color="#1a1a1a")
        cur_x += w

    cur_y = header_y - 0.55
    for i, s in enumerate(detections, start=1):
        if i % 2 == 0:
            cur_x = rail_x
            ax.add_patch(Rectangle(
                (cur_x, cur_y - 0.07),
                sum(w for _, w in headers), 0.46,
                facecolor="#fafbfd", edgecolor="none",
            ))
        cur_x = rail_x
        ax.text(cur_x + 0.13, cur_y + 0.13, str(i), ha="left", va="center",
                family=MONO, fontsize=10.4, fontweight="bold")
        cur_x += headers[0][1]
        ent = s["entity_type"]
        ax.add_patch(FancyBboxPatch(
            (cur_x + 0.06, cur_y - 0.02), 1.45, 0.40,
            boxstyle="round,pad=0.005,rounding_size=0.04",
            facecolor=ENTITY_COLORS.get(ent, "#e8e8e8"),
            edgecolor="#888", linewidth=0.4,
        ))
        ax.text(cur_x + 0.13, cur_y + 0.18, ent, ha="left", va="center",
                family=MONO, fontsize=10.0)
        cur_x += headers[1][1]
        t = s["text"] if len(s["text"]) < 38 else s["text"][:35] + "…"
        ax.text(cur_x + 0.08, cur_y + 0.13, t, ha="left", va="center",
                family=MONO, fontsize=10.0, color="#1a1a1a")
        cur_x += headers[2][1]
        ax.text(cur_x + 0.08, cur_y + 0.13,
                ", ".join(s.get("box_ids", [])),
                ha="left", va="center", family=MONO, fontsize=10.0, color="#5a5a5a")
        cur_y -= 0.50

    fig.tight_layout(pad=0.5)
    out = OUT / "pii-redaction-image-3.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"wrote {out}")


# ---------------------------------------------------------------------------


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    text_row = find_text_row()
    img_row = load_first(IMG_SRC)
    print(f"text row: {text_row['input_id']}  ({len(text_row['detections']['pii_spans'])} spans)")
    print(f"img row:  {img_row['input_id']}  ({len(img_row['detections']['pii_spans'])} spans)")
    figure1_text_detect(text_row)
    figure2_text_review(text_row)
    figure3_image_detect(img_row)
    figure4_image_redact(img_row)


if __name__ == "__main__":
    main()
