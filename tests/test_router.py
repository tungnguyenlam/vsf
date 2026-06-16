"""Tests for the VLM safety router (no network; fake OpenAI-compatible client)."""

from types import SimpleNamespace

import pytest

from src.pipeline.Datasets.safety_v0_schema import new_ocr_box, new_pii_span, new_row
from src.pipeline.Router import (
    GeminiVlmRouter,
    build_router_input,
    get_router,
    list_router_names,
    parse_router_output,
)
from src.pipeline.Router.output import extract_json


class FakeClient:
    """Minimal stand-in for an OpenAI client: returns a canned message content."""

    def __init__(self, content):
        self._content = content
        self.calls = []

        outer = self

        class _Completions:
            def create(self, **kwargs):
                outer.calls.append(kwargs)
                msg = SimpleNamespace(content=outer._content)
                return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

        self.chat = SimpleNamespace(completions=_Completions())


VALID = (
    '{"action": "reject", "pii_visible": false, "prompt_injection": true, '
    '"sexual": false, "violence": false, "blood_gore": false, '
    '"political": false, "religious": false}'
)


# --- output parsing ----------------------------------------------------------
def test_parse_valid():
    r = parse_router_output(VALID)
    assert r.valid and r.action == "reject"
    assert r.flags["prompt_injection"] is True
    labels = r.to_labels()
    assert labels["action"] == "reject" and labels["pii_visible"] is False


def test_parse_bad_action_routes_unsure():
    r = parse_router_output('{"action": "allow", "pii_visible": false, '
                            '"prompt_injection": false, "sexual": false, "violence": false, '
                            '"blood_gore": false, "political": false, "religious": false}')
    assert not r.valid and r.action == "unsure"


def test_parse_missing_flag_routes_unsure_but_keeps_present():
    r = parse_router_output('{"action": "safe", "prompt_injection": true}')
    assert not r.valid and r.action == "unsure"
    assert r.flags["prompt_injection"] is True  # present bool kept for audit
    assert r.to_labels()["sexual"] is None  # unknown stays None


def test_parse_garbage_routes_unsure():
    r = parse_router_output("the model refused to answer")
    assert not r.valid and r.action == "unsure" and r.flags == {}


def test_extract_json_from_fence():
    obj = extract_json("```json\n{\"action\": \"safe\"}\n```")
    assert obj == {"action": "safe"}


# --- input building ----------------------------------------------------------
def test_build_router_input_prefers_redacted_and_summarizes():
    row = new_row("safety_v0_demo_000001", "demo/webpii", has_image=True, has_ocr=True,
                  original_image_path="data/x/orig.png",
                  redacted_image_path="data/x/red.png",
                  ocr_text="raw", sanitized_ocr_text="So dien thoai <PHONE_NUMBER>")
    row["geometry"]["ocr_boxes"] = [new_ocr_box("box_0001", "x", 0, 1, [0, 0, 1, 1])]
    row["detections"]["pii_spans"] = [
        new_pii_span("pii_0001", "PHONE_NUMBER", 14, 24, "0987654321", 0.9, ["box_0001"])
    ]
    ri = build_router_input(row)
    assert ri["image_path"] == "data/x/red.png" and ri["image_is_redacted"] is True
    assert ri["ocr_text"] == "So dien thoai <PHONE_NUMBER>"  # sanitized preferred
    assert ri["presidio_spans"][0]["entity_type"] == "PHONE_NUMBER"
    assert ri["input_modalities"]["presidio_metadata"] is True


def test_build_router_input_text_only():
    row = new_row("safety_v0_demo_000002", "demo", has_text=True,
                  input_text="x", sanitized_text="hello")
    ri = build_router_input(row)
    assert ri["image_path"] is None
    assert ri["input_modalities"]["image"] is False
    assert ri["input_text"] == "hello"


# --- router backend with fake client ----------------------------------------
def test_router_valid_response():
    router = GeminiVlmRouter(client=FakeClient(VALID))
    result = router.route(build_router_input(
        new_row("safety_v0_demo_000003", "demo", has_text=True, sanitized_text="hi")
    ))
    assert result.valid and result.action == "reject"


def test_router_malformed_response_unsure():
    router = GeminiVlmRouter(client=FakeClient("sorry, no JSON here"))
    result = router.route_row(
        new_row("safety_v0_demo_000004", "demo", has_text=True, sanitized_text="hi")
    )
    assert not result.valid and result.action == "unsure"


def test_router_api_error_unsure():
    class Boom:
        def __init__(self):
            self.chat = SimpleNamespace(completions=self)

        def create(self, **kwargs):
            raise RuntimeError("network down")

    router = GeminiVlmRouter(client=Boom())
    result = router.route({"input_id": "x", "input_modalities": {}})
    assert not result.valid and result.action == "unsure" and "network down" in result.error


def test_router_sends_image_when_present(tmp_path):
    from PIL import Image
    img = tmp_path / "red.png"
    Image.new("RGB", (10, 10), "white").save(img)

    fake = FakeClient(VALID)
    router = GeminiVlmRouter(client=fake)
    router.route({"input_id": "x", "image_path": str(img), "image_is_redacted": True,
                  "input_text": "", "ocr_text": "", "presidio_spans": [],
                  "redaction_metadata": [], "input_modalities": {"image": True}})
    content = fake.calls[0]["messages"][1]["content"]
    assert any(part.get("type") == "image_url" for part in content)


def test_registry():
    assert "gemini_flash" in list_router_names()
    assert isinstance(get_router("gemini_flash", api_key="x"), GeminiVlmRouter)
    with pytest.raises(ValueError):
        get_router("nope")
