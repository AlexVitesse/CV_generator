"""Tests de translate.py — restauración de IDs y fallback por desajuste (V2-11)."""

from cvgen import translate
from cvgen.translate import _restore_ids_with_fallback


def test_restore_ids_matches_lengths(monkeypatch):
    monkeypatch.setattr(translate, "_translate_fallback", lambda t, s, tg: f"[T]{t}")

    data = [
        {"id": "exp_a", "company": "Alpha", "title": "Dev"},
        {"id": "exp_b", "company": "Bravo", "title": "Eng"},
    ]
    trans = [
        {"company": "Alpha-es", "title": "Dev-es"},
        {"company": "Bravo-es", "title": "Eng-es"},
    ]
    _restore_ids_with_fallback(data, trans, "en", "es")

    # Los IDs originales se restauran por posición.
    assert [t["id"] for t in trans] == ["exp_a", "exp_b"]


def test_restore_ids_fills_missing_with_fallback(monkeypatch):
    # El LLM devolvió MENOS items de los enviados: los faltantes se traducen
    # individualmente con el fallback, nunca se pierden en silencio.
    captured = []

    def fake_fallback(text, src, tgt):
        captured.append(text)
        return f"[T]{text}"

    monkeypatch.setattr(translate, "_translate_fallback", fake_fallback)

    data = [
        {"id": "exp_a", "company": "Alpha", "title": "Dev", "bullets": "did things"},
        {"id": "exp_b", "company": "Bravo", "title": "Eng", "bullets": "led team"},
    ]
    trans = [
        {"company": "Alpha-es", "title": "Dev-es", "bullets": "hizo cosas"},
    ]  # falta el segundo

    _restore_ids_with_fallback(data, trans, "en", "es")

    assert len(trans) == 2
    assert trans[1]["id"] == "exp_b"
    # El item faltante pasó por el fallback de traducción.
    assert trans[1]["company"] == "[T]Bravo"
    assert "Bravo" in captured and "led team" in captured


def test_restore_ids_no_loss_when_more_translated_than_source(monkeypatch):
    monkeypatch.setattr(translate, "_translate_fallback", lambda t, s, tg: t)
    data = [{"id": "exp_a", "company": "Alpha"}]
    trans = [{"company": "Alpha-es"}, {"company": "extra"}]
    # No debe romper aunque haya más traducidos que originales.
    _restore_ids_with_fallback(data, trans, "en", "es")
    assert trans[0]["id"] == "exp_a"
