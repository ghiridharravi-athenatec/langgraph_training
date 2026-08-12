'''Regression test for a real bug found via live smoke-testing: validate_json_schema's
event stores the parsed payload by reference, and both llm_invoke (retrieve.py) and
classify_intent (llm.py) used to attach their own guardrail_events list - which contains
that same schema event - back onto that same parsed dict, creating parsed -> guardrail_events
-> schema_event -> parsed, a cycle FastAPI's jsonable_encoder recurses into forever
(RecursionError) when serializing the /chat response. The unit test suite never caught
this because every other test monkeypatches classify_intent/llm_invoke entirely, bypassing
the exact code path with the bug.'''

import json
from unittest.mock import MagicMock

from app.utils.llm import IntentClassifier
from app.utils.retrieve import llm_invoke


def _fake_response(text, usage=None):
    response = MagicMock()
    response.text = text
    response.prompt_feedback = None
    response.candidates = []
    response.usage_metadata = usage
    return response


def test_llm_invoke_result_has_no_circular_reference(monkeypatch):
    fake = _fake_response('{"answer": "the sky is blue"}')
    monkeypatch.setattr("app.utils.retrieve.client.models.generate_content", lambda **kwargs: fake)

    result = llm_invoke("irrelevant prompt")

    # json.dumps recurses through the full structure exactly like FastAPI's
    # jsonable_encoder does - a lingering cycle raises RecursionError here too.
    json.dumps(result, default=str)
    assert result["answer"] == "the sky is blue"
    assert len(result["guardrail_events"]) == 2


def test_classify_intent_result_has_no_circular_reference(monkeypatch):
    fake = _fake_response('{"intent": "question", "confidence": 0.95, "is_prompt_injection": false, "injection_reason": ""}')
    classifier = IntentClassifier(api_key="test-key")
    monkeypatch.setattr(classifier.client.models, "generate_content", lambda **kwargs: fake)

    result = classifier.classify_intent("what is the warranty period on this product")

    json.dumps(result, default=str)
    assert result["intent"] == "question"
    assert len(result["guardrail_events"]) == 3
