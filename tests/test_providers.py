"""Tests del dispatcher multi-proveedor (Ollama / OpenAI / Anthropic / Gemini).

Mockean httpx.post para verificar que cada backend construye la request correcta
y extrae bien la respuesta, sin tocar la red.
"""

import pytest

import llm_client
from llm_client import call_llm, LLMError, _split_system


class _Resp:
    def __init__(self, code=200, data=None, text=""):
        self.status_code = code
        self._d = data or {}
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise llm_client.httpx.HTTPStatusError("err", request=None, response=self)

    def json(self):
        return self._d


@pytest.fixture
def capture(monkeypatch):
    """Captura el último cuerpo enviado y devuelve respuestas canónicas por proveedor."""
    seen = {"bodies": [], "url": None, "headers": None}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen["url"] = url
        seen["headers"] = headers
        seen["bodies"].append(json)
        if "openai" in url:
            return _Resp(200, {"choices": [{"message": {"content": "OAI"}}]})
        if "anthropic" in url:
            return _Resp(200, {"stop_reason": "end_turn", "content": [{"type": "text", "text": "ANT"}]})
        if "generativelanguage" in url:
            return _Resp(200, {"candidates": [{"content": {"parts": [{"text": "GEM"}]}}]})
        return _Resp(200, {"message": {"content": "OLL"}})

    monkeypatch.setattr(llm_client.httpx, "post", fake_post)
    return seen


_MSGS = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
_OPTS = {"temperature": 0, "top_p": 0.9, "seed": 42}


def test_split_system():
    system, rest = _split_system(_MSGS)
    assert system == "sys"
    assert rest == [{"role": "user", "content": "hi"}]


def test_ollama_payload(capture):
    out = call_llm(_MSGS, provider="ollama", model="m", api_key="k", json_mode=True, options=_OPTS)
    assert out == "OLL"
    body = capture["bodies"][-1]
    assert body["format"] == "json" and body["options"] == _OPTS


def test_openai_payload(capture):
    out = call_llm(_MSGS, provider="openai", model="m", api_key="k", json_mode=True, options=_OPTS)
    assert out == "OAI"
    body = capture["bodies"][-1]
    assert body["response_format"] == {"type": "json_object"}
    assert body["temperature"] == 0 and body["top_p"] == 0.9


def test_anthropic_payload_no_temperature(capture):
    # Anthropic separa el system y NUNCA recibe temperature (Opus 4.8 da 400).
    out = call_llm(_MSGS, provider="anthropic", model="claude-opus-4-8", api_key="k",
                   json_mode=True, options=_OPTS)
    assert out == "ANT"
    body = capture["bodies"][-1]
    assert "temperature" not in body
    assert body["max_tokens"] == 16000
    assert [m["role"] for m in body["messages"]] == ["user"]
    assert "JSON" in body["system"]
    assert capture["headers"]["x-api-key"] == "k"


def test_gemini_payload(capture):
    out = call_llm(_MSGS, provider="gemini", model="gemini-2.5-flash", api_key="k",
                   json_mode=True, options=_OPTS)
    assert out == "GEM"
    body = capture["bodies"][-1]
    assert body["systemInstruction"]["parts"][0]["text"] == "sys"
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    # maxOutputTokens y thinking apagado: evita el cuelgue / respuesta vacía de Flash.
    assert body["generationConfig"]["maxOutputTokens"] == llm_client._MAX_OUTPUT_TOKENS
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}
    assert body["generationConfig"]["seed"] == 42  # determinismo del scorer
    assert body["contents"][0]["role"] == "user"


def test_gemini_drops_thinking_on_400(monkeypatch):
    # Si el endpoint no admite thinkingConfig (400), reintenta una vez sin él.
    bodies = []

    def fake_post(url, headers=None, json=None, timeout=None):
        bodies.append(json)
        if "thinkingConfig" in json["generationConfig"]:
            return _Resp(400, text="Unknown name 'thinkingConfig'")
        return _Resp(200, {"candidates": [{"content": {"parts": [{"text": "GEM"}]}}]})

    monkeypatch.setattr(llm_client.httpx, "post", fake_post)
    out = call_llm(_MSGS, provider="gemini", model="gemini-2.5-flash", api_key="k", json_mode=True)
    assert out == "GEM"
    assert len(bodies) == 2 and "thinkingConfig" not in bodies[1]["generationConfig"]


def test_gemini_empty_parts_reports_finish_reason(monkeypatch):
    # Candidato sin parts (p.ej. MAX_TOKENS) → error claro con el finishReason.
    monkeypatch.setattr(llm_client.httpx, "post", lambda *a, **k: _Resp(
        200, {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": []}}]}))
    with pytest.raises(LLMError, match="MAX_TOKENS"):
        call_llm([{"role": "user", "content": "hi"}], provider="gemini",
                 model="gemini-2.5-flash", api_key="k", retries=1)


def test_gemini_prompt_block_reported(monkeypatch):
    monkeypatch.setattr(llm_client.httpx, "post", lambda *a, **k: _Resp(
        200, {"promptFeedback": {"blockReason": "SAFETY"}}))
    with pytest.raises(LLMError, match="blockReason=SAFETY"):
        call_llm([{"role": "user", "content": "hi"}], provider="gemini",
                 model="gemini-2.5-flash", api_key="k", retries=1)


def test_openai_strips_sampling_on_400(monkeypatch):
    # Modelos de razonamiento (gpt-5.x) rechazan temperature≠default → reintento sin sampling.
    bodies = []

    def fake_post(url, headers=None, json=None, timeout=None):
        bodies.append(json)
        if "temperature" in json:
            return _Resp(400, text="unsupported value: temperature")
        return _Resp(200, {"choices": [{"message": {"content": "OK"}}]})

    monkeypatch.setattr(llm_client.httpx, "post", fake_post)
    out = call_llm([{"role": "user", "content": "hi"}], provider="openai",
                   model="gpt-5.1", api_key="k", options={"temperature": 0})
    assert out == "OK"
    assert len(bodies) == 2 and "temperature" not in bodies[1]


def test_anthropic_refusal_raises(monkeypatch):
    monkeypatch.setattr(llm_client.httpx, "post",
                        lambda *a, **k: _Resp(200, {"stop_reason": "refusal", "content": []}))
    with pytest.raises(LLMError):
        call_llm([{"role": "user", "content": "hi"}], provider="anthropic",
                 model="claude-opus-4-8", api_key="k")


def test_unknown_provider_raises():
    with pytest.raises(ValueError):
        call_llm([{"role": "user", "content": "hi"}], provider="cohere", model="m", api_key="k")


def test_missing_api_key_raises():
    with pytest.raises(ValueError):
        call_llm([{"role": "user", "content": "hi"}], provider="openai", model="m", api_key="")


def test_groq_is_default_and_openai_compatible(capture):
    out = call_llm(_MSGS, provider=None, model="m", api_key="k", json_mode=True, options=_OPTS)
    assert out == "OAI"  # Groq responde con el shape de OpenAI
    assert capture["url"] == llm_client.GROQ_URL
    assert capture["bodies"][-1]["response_format"] == {"type": "json_object"}


def test_legacy_config_stays_on_ollama(tmp_path, monkeypatch):
    import ai_analyzer
    cfg = tmp_path / "cfg.json"
    cfg.write_text('{"api_key": "old", "model": "gpt-oss:120b-cloud"}', encoding="utf-8")
    monkeypatch.setattr(ai_analyzer, "_config_path", lambda: str(cfg))
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    out = ai_analyzer.load_ai_config()
    assert out["provider"] == "ollama" and out["api_key"] == "old"
    cfg.unlink()
    assert ai_analyzer.load_ai_config()["provider"] == "groq"  # instalación nueva


def test_default_model_is_in_options():
    for p in llm_client.PROVIDERS:
        assert llm_client.DEFAULT_MODELS[p] in llm_client.MODEL_OPTIONS[p]
