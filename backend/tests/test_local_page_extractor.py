"""Local VLM page extraction stays candidate-only and normalizes safe input."""
from __future__ import annotations

import json

from PIL import Image

from core.examdna.source_truth.consensus import _materialize, _settle
from document.models import ATU, ATUKind, Candidate, Document, Question
from document.verification import evaluate_gate
from providers.local.page import LocalVisionPageExtractor


class _Response:
    class _Choice:
        class _Message:
            content = json.dumps(
                {
                    "questions": [
                        {
                            "label": "1",
                            "body": "△ABC에서 AB=AC일 때 ∠A의 크기는?",
                            "choices": ["① 40°", "② 50°"],
                            "points": 3,
                            "bbox": {"xmin": 50, "ymin": 100, "xmax": 950, "ymax": 450},
                        },
                        {"label": "2-1", "body": "과정을 서술하시오.", "choices": []},
                    ]
                },
                ensure_ascii=False,
            )

        message = _Message()

    choices = [_Choice()]


class _Completions:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return _Response()


class _Client:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": _Completions()})()


def test_local_page_extractor_returns_structured_candidate(tmp_path, monkeypatch):
    image = tmp_path / "시험지.jpg"
    Image.new("RGB", (200, 100), "white").save(image)
    client = _Client()
    monkeypatch.setenv("LOCAL_LLM_CACHE", "0")

    candidate = LocalVisionPageExtractor(client=client).extract_page(image)[0]

    assert candidate.provider == "local-vision-page:local-large"
    assert candidate.meta["candidate_only"] is True
    assert [item["label"] for item in candidate.value] == ["1", "2-1"]
    assert candidate.value[0]["bbox"]["xmax"] == 950.0
    assert candidate.value[0]["choices"] == ["40°", "50°"]
    assert candidate.value[1]["choices"] == []
    assert client.chat.completions.kwargs["extra_body"] == {"think": False}
    assert client.chat.completions.kwargs["messages"][0]["content"][1]["image_url"]["url"].startswith(
        "data:image/jpeg;base64,"
    )


def test_local_page_extractor_rejects_invalid_question_payload(tmp_path, monkeypatch):
    image = tmp_path / "p.png"
    Image.new("RGB", (20, 20), "white").save(image)
    monkeypatch.setenv("LOCAL_LLM_CACHE", "0")

    class BadClient(_Client):
        class _BadCompletions:
            def create(self, **kwargs):
                return type(
                    "R",
                    (),
                    {"choices": [type("C", (), {"message": type("M", (), {"content": '{"questions":[{"label":"1","body":"","bbox":{"xmin":-1}}]}'} )()})()]},
                )()

        def __init__(self):
            self.chat = type("Chat", (), {"completions": self._BadCompletions()})()

    candidate = LocalVisionPageExtractor(client=BadClient()).extract_page(image)[0]
    assert candidate.value == []
    assert candidate.confidence == 0.0


def test_single_source_candidate_is_visible_as_draft_but_never_passes_gate():
    question = Question(number=1, label="1")
    question.atus.append(
        ATU(
            kind=ATUKind.TEXT_TOKEN,
            field="body",
            candidates=[Candidate(provider="local-vision-page:local-large", value="복원 초안", confidence=0.9)],
        )
    )
    _settle(question.atus[0])
    doc = Document(tenant_id="t", questions=[question])

    _materialize(doc)

    assert [span.text for span in question.body] == ["복원 초안"]
    assert question.atus[0].status.value == "UNVERIFIED"
    assert evaluate_gate(doc).passed is False
