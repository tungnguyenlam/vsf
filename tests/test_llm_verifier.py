import json
from types import SimpleNamespace

import pytest
from presidio_analyzer import RecognizerResult

from src.pipeline.Verifiers.LLMVerifier import LLMVerifier


class FakeCompletions:
    def __init__(self, response=None, error=None):
        self.response = response or {"drop": [], "relabel": []}
        self.error = error
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if self.error:
            raise self.error
        content = json.dumps(self.response)
        message = SimpleNamespace(content=content)
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice])


class FakeClient:
    def __init__(self, completions):
        self.chat = SimpleNamespace(completions=completions)


def make_result(entity_type="ID"):
    return RecognizerResult(entity_type=entity_type, start=4, end=10, score=0.7)


def test_default_provider_requires_supported_parameters():
    completions = FakeCompletions()
    verifier = LLMVerifier(client=FakeClient(completions))

    verifier.verify("Mã 123456", [make_result()])

    request = completions.requests[0]
    assert request["extra_body"]["provider"] == {"require_parameters": True}
    assert request["response_format"]["type"] == "json_schema"
    assert request["response_format"]["json_schema"]["strict"] is True
    assert request["max_tokens"] == 1024


def test_explicit_provider_pin_is_passed_through():
    completions = FakeCompletions()
    provider = LLMVerifier.pin_provider("novita")
    verifier = LLMVerifier(client=FakeClient(completions), provider=provider)

    verifier.verify("Mã 123456", [make_result()])

    assert completions.requests[0]["extra_body"]["provider"] == {
        "order": ["novita"],
        "allow_fallbacks": False,
    }


def test_verify_applies_sparse_drop_and_relabel_corrections():
    completions = FakeCompletions(
        {
            "drop": [1],
            "relabel": [{"id": 0, "entity_type": "BANK_ACCOUNT"}],
        }
    )
    verifier = LLMVerifier(client=FakeClient(completions))
    results = [make_result("ID"), make_result("ID")]

    adjudicated = verifier.verify("STK 123456 và mã đơn 778899", results)

    assert len(adjudicated) == 1
    assert adjudicated[0].entity_type == "BANK_ACCOUNT"


def test_verify_keeps_unmentioned_candidates_unchanged():
    completions = FakeCompletions({"drop": [], "relabel": []})
    verifier = LLMVerifier(client=FakeClient(completions))
    results = [make_result("ID"), make_result("PHONE_NUMBER")]

    adjudicated = verifier.verify("Mã 123456 và sđt 098765", results)

    assert adjudicated == results
    assert [r.entity_type for r in adjudicated] == ["ID", "PHONE_NUMBER"]


def test_verify_falls_back_to_noop_by_default_on_error():
    completions = FakeCompletions(error=RuntimeError("routing failed"))
    verifier = LLMVerifier(client=FakeClient(completions))
    results = [make_result()]

    assert verifier.verify("Mã 123456", results) is results


def test_verify_raises_on_error_in_strict_mode():
    completions = FakeCompletions(error=RuntimeError("routing failed"))
    verifier = LLMVerifier(client=FakeClient(completions), raise_on_error=True)

    with pytest.raises(RuntimeError, match="routing failed"):
        verifier.verify("Mã 123456", [make_result()])
