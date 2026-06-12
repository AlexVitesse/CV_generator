"""Tests de llm_client.py (V2-07): parsing tolerante y call_ollama con retry."""

import json

import pytest

import llm_client
from llm_client import _parse_json_response, call_ollama, LLMError


# ── _parse_json_response ─────────────────────────────────────────

def test_parse_plain_json():
    assert _parse_json_response('{"a": 1}') == {"a": 1}


def test_parse_with_markdown_fences():
    raw = '```json\n{"a": 1, "b": 2}\n```'
    assert _parse_json_response(raw) == {"a": 1, "b": 2}


def test_parse_with_surrounding_text():
    raw = 'Claro, aquí tienes:\n{"score": 80}\nEspero que ayude.'
    assert _parse_json_response(raw) == {"score": 80}


def test_parse_empty_raises():
    with pytest.raises(json.JSONDecodeError):
        _parse_json_response("")


def test_parse_garbage_raises():
    with pytest.raises(json.JSONDecodeError):
        _parse_json_response("no hay json aquí")


# ── call_ollama (httpx mockeado) ─────────────────────────────────

class _FakeResponse:
    def __init__(self, payload, status_code=200, raise_exc=None):
        self._payload = payload
        self.status_code = status_code
        self._raise_exc = raise_exc

    def raise_for_status(self):
        if self._raise_exc:
            raise self._raise_exc

    def json(self):
        return self._payload


def _patch_post(monkeypatch, responses):
    """Encola respuestas/excepciones; cada POST consume la siguiente."""
    calls = {"n": 0}

    def fake_post(url, **kwargs):
        i = calls["n"]
        calls["n"] += 1
        item = responses[min(i, len(responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(llm_client.httpx, "post", fake_post)
    # backoff sin dormir
    monkeypatch.setattr(llm_client.time, "sleep", lambda *_: None)
    return calls


def test_call_ollama_success(monkeypatch):
    _patch_post(monkeypatch, [
        _FakeResponse({"message": {"content": "  hola  "}}),
    ])
    out = call_ollama([{"role": "user", "content": "hi"}], model="m", api_key="k")
    assert out == "hola"


def test_call_ollama_retries_then_succeeds(monkeypatch):
    err = llm_client.httpx.HTTPError("boom")
    calls = _patch_post(monkeypatch, [
        err,
        _FakeResponse({"message": {"content": "ok"}}),
    ])
    out = call_ollama([{"role": "user", "content": "hi"}], model="m", api_key="k")
    assert out == "ok"
    assert calls["n"] == 2  # falló una vez, reintentó


def test_call_ollama_empty_content_raises_after_retries(monkeypatch):
    calls = _patch_post(monkeypatch, [
        _FakeResponse({"message": {"content": "   "}}),
    ])
    with pytest.raises(LLMError):
        call_ollama([{"role": "user", "content": "hi"}], model="m", api_key="k", retries=2)
    assert calls["n"] == 2  # agotó los reintentos


def test_call_ollama_missing_message_key_is_safe(monkeypatch):
    # Ollama devuelve un shape de error inesperado: no debe lanzar KeyError.
    _patch_post(monkeypatch, [
        _FakeResponse({"error": "model not found"}),
    ])
    with pytest.raises(LLMError):
        call_ollama([{"role": "user", "content": "hi"}], model="m", api_key="k", retries=1)


def test_call_ollama_requires_api_key(monkeypatch):
    with pytest.raises(ValueError):
        call_ollama([{"role": "user", "content": "hi"}], model="m", api_key="")


def test_call_ollama_json_mode_sets_format(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(kwargs["json"])
        return _FakeResponse({"message": {"content": "{}"}})

    monkeypatch.setattr(llm_client.httpx, "post", fake_post)
    call_ollama([{"role": "user", "content": "hi"}], model="m", api_key="k", json_mode=True)
    assert captured.get("format") == "json"
