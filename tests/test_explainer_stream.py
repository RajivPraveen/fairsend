"""Streaming answers: text reaches the page as it's written, and guardrails still hold."""

from fairsend import llm
from fairsend.explainer import answer
from fairsend.explainer.index import Chunk


class FakeIndex:
    def __init__(self):
        self.chunks = [Chunk(f"s{i}#0", f"s{i}", f"Source {i}", "CFPB", "https://example.org", "Section", "text")
                       for i in range(3)]

    def search(self, query, k=3):
        return [(c, 0.8) for c in self.chunks[:k]]


def fake_stream(pieces):
    def _stream(prompt, **kwargs):
        yield from pieces
    return _stream


def test_streams_text_and_renumbers_citations(monkeypatch):
    monkeypatch.setattr(llm, "stream", fake_stream(["The real rate ", "is the midpoint [3]. ", "It is fair [3][1]."]))
    seen = []
    a = answer.ask("What is the real exchange rate?", index=FakeIndex(), on_text=seen.append)
    assert seen and seen[-1].startswith("The real rate")
    assert a.status == "answered"
    assert a.text == "The real rate is the midpoint [1]. It is fair [1][2]."
    assert [c.source_id for c in a.citations] == ["s2", "s0"]


def test_not_in_sources_is_never_shown(monkeypatch):
    monkeypatch.setattr(llm, "stream", fake_stream(["NOT_IN", "_SOURCES and some trailing words here"]))
    seen = []
    a = answer.ask("What is the capital of France?", index=FakeIndex(), on_text=seen.append)
    assert a.status == "not_found"
    assert seen == []


def test_advice_is_declined_without_calling_the_model(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("model should not be called")
    monkeypatch.setattr(llm, "stream", boom)
    a = answer.ask("Should I wait until the rupee falls?", index=FakeIndex(), on_text=lambda t: None)
    assert a.status == "declined_advice"
