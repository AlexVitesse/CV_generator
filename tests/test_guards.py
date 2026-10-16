"""Tests de los guards anti-fabricación: métricas (#1), tier de skills (#2),
reconciliación de viabilidad (#3). Cubren los casos reales vistos en logs/."""

from cvgen.metrics_guard import extract_metrics, find_fabricated_metrics, resolve_target_index
from cvgen.helpers import (
    sanitize_ai_result,
    _enforce_skill_tiers,
    _demote_missing_keyword_skills,
    _reconcile_score_with_coverage,
    _resolve_patch_index,
    _fix_stuck_words,
    camel_terms_in,
    detect_vacancy_language,
    apply_chat_patch,
)
from cvgen.ai_analyzer import _reintegrate_lost_evidence, _drop_projects_duplicating_experience
from cvgen.translate import _restore_ids_with_fallback


# ── #1 — extract_metrics ─────────────────────────────────────────

def test_extract_metrics_captures_pct_and_thousands():
    mets = {m["key"] for m in extract_metrics("logró 99.5% sobre 1,200 solicitudes diarias")}
    assert "995" in mets and "1200" in mets


def test_extract_metrics_ignores_lone_small_digits():
    # "3 fases" / "4 servicios" son conteos estructurales, no métricas de impacto.
    keys = {m["key"] for m in extract_metrics("entregó 4 servicios en 3 fases")}
    assert keys == set()


def test_extract_metrics_keeps_single_digit_percent():
    mets = extract_metrics("precisión de ±1%")
    assert any(m["key"] == "1" and m["is_pct"] for m in mets)


# ── #1 — find_fabricated_metrics ─────────────────────────────────

_CV = {
    "summary": "AI Engineer",
    "experiences": [
        {"company": "ZAPI", "title": "Founder",
         "bullets": "Construyó agente con 89% en benchmark y 99% de uptime."},
        {"company": "Cóndor", "title": "Backend",
         "bullets": "APIs en FastAPI procesando 1,200+ solicitudes diarias."},
    ],
    "projects": [
        {"name": "ZAPI", "description": "SaaS con ~15,000 líneas de código."},
    ],
    "skills": [],
}


def test_detects_transplanted_metric_across_items():
    # La métrica 1,200/día es de Cóndor (index 1); aquí aparece bajo ZAPI (index 0).
    suggestions = {"experiences": [
        {"index": 0, "title": "Founder",
         "bullets": "Construyó plataforma procesando 1,200 solicitudes diarias."},
    ]}
    offenders = find_fabricated_metrics(suggestions, _CV)
    assert any(o["metric"].startswith("1,200") and o["index"] == 0 for o in offenders)


def test_detects_invented_percentage():
    suggestions = {"experiences": [
        {"index": 1, "title": "Backend",
         "bullets": "Implementó pruebas reduciendo regresiones en 30%."},
    ]}
    offenders = find_fabricated_metrics(suggestions, _CV)
    assert any(o["metric"] == "30%" for o in offenders)


def test_real_metric_in_same_item_is_clean():
    suggestions = {"experiences": [
        {"index": 0, "title": "Founder",
         "bullets": "Construyó agente con 89% en benchmark."},
    ]}
    assert find_fabricated_metrics(suggestions, _CV) == []


def test_summary_metric_checked_against_whole_cv():
    suggestions = {"summary": "AI Engineer con 5,000 despliegues."}  # 5000 no está en el CV
    offenders = find_fabricated_metrics(suggestions, _CV)
    assert any(o["kind"] == "summary" for o in offenders)


# ── #2 — tier de skills ──────────────────────────────────────────

def test_inferred_skill_goes_to_lowest_tier():
    original = ["Dominio avanzado: Python | Dominio intermedio: SQL | Familiaridad: Make"]
    # La IA mete "Docker" (nueva, inferida) en avanzado → debe bajar a familiaridad.
    suggested = "Dominio avanzado: Python, Docker | Dominio intermedio: SQL | Familiaridad: Make"
    out = _enforce_skill_tiers(suggested, original)
    assert "Docker" in out.split("Familiaridad:")[1]
    assert "Docker" not in out.split("|")[0]  # ya no en avanzado


def test_missing_keyword_skill_demoted():
    suggested = "Core skills: Python | Working knowledge: Next.js | Exposure to: Make"
    out = _demote_missing_keyword_skills(suggested, ["Next.js (solid experience)"])
    assert "Next.js" in out.split("Exposure to:")[1]
    assert "Working knowledge: Next.js" not in out  # ya no en working knowledge


# ── #3 — reconciliación de viabilidad ────────────────────────────

def test_high_score_forces_viable_true():
    res = sanitize_ai_result({"match_score": 78, "viable": False, "suggestions": {}})
    assert res["viable"] is True


def test_low_score_forces_viable_false():
    res = sanitize_ai_result({"match_score": 35, "viable": True, "suggestions": {}})
    assert res["viable"] is False


def test_mid_score_respects_model_judgment():
    res = sanitize_ai_result({"match_score": 60, "viable": True, "suggestions": {}})
    assert res["viable"] is True
    res2 = sanitize_ai_result({"match_score": 58, "viable": False, "suggestions": {}})
    assert res2["viable"] is False


# ── Bug A — anti-misatribución de experiencias/proyectos ─────────

_EXPS = [
    {"id": "exp_dcm", "company": "DCM Moguls", "title": "AI Engineer",
     "bullets": "Contribuyó commits a codebase multi-tenant; cumplimiento CASA Tier 2 OWASP; framework red-team de agentes Mastra."},
    {"id": "exp_zapi", "company": "ZAPI", "title": "Founder",
     "bullets": "Plataforma SaaS multi-tenant WhatsApp con agente ReAct, Gemini Vision, React Tailwind, 4 servicios Docker, Whisper."},
    {"id": "exp_condor", "company": "Ingeniería Cóndor", "title": "Backend",
     "bullets": "Arquitectura IoT ESP32 MQTT Firebase; APIs FastAPI y C# en Oracle Cloud; RAG manufactura LangChain ChromaDB; CI/CD en RunPod."},
]


def test_resolve_by_id_beats_model_index():
    # El modelo numera index=0 (DCM) pero el id apunta a Cóndor → gana el id.
    sug = {"id": "exp_condor", "index": 0, "title": "Backend",
           "bullets": "Diseñó arquitectura IoT con ESP32 y MQTT."}
    assert resolve_target_index(sug, _EXPS, kind="experience") == 2


def test_resolve_by_content_when_id_missing():
    # Sin id; el contenido (FastAPI/Oracle Cloud/RunPod) es de Cóndor aunque diga index=0.
    sug = {"index": 0, "title": "AI Engineer Jr.",
           "bullets": "Diseñó y desplegó APIs REST con FastAPI en Oracle Cloud, desplegado en RunPod."}
    assert resolve_target_index(sug, _EXPS, kind="experience") == 2


def test_resolve_discards_when_ambiguous():
    # Contenido genérico sin señal discriminante de ninguna empresa → None (descartar).
    sug = {"title": "Engineer", "bullets": "Trabajó en varias tareas mejorando resultados generales."}
    assert resolve_target_index(sug, _EXPS, kind="experience") is None


def test_resolve_unknown_id_falls_back_to_content():
    # id inexistente → cae a contenido; los tokens de DCM resuelven a index 0.
    sug = {"id": "exp_nope", "title": "AI Engineer",
           "bullets": "Cumplimiento CASA Tier 2 OWASP y framework red-team de agentes Mastra."}
    assert resolve_target_index(sug, _EXPS, kind="experience") == 0


def test_metrics_guard_uses_model_intent_not_content():
    # Guard de métricas: el modelo dice index=0 (DCM) pero mete contenido+cifra de Cóndor.
    # Debe detectar el trasplante (fallback="index"), no auto-justificarlo por contenido.
    cv = {"experiences": _EXPS, "projects": [], "summary": "", "skills": []}
    sugs = {"experiences": [
        {"index": 0, "title": "AI Engineer",
         "bullets": "APIs FastAPI en Oracle Cloud procesando 1,200 solicitudes diarias."},
    ]}
    offenders = find_fabricated_metrics(sugs, cv)
    assert any(o["metric"].startswith("1,200") and o["index"] == 0 for o in offenders)


# ── Bug A — chat patch anclado por id ────────────────────────────

def test_chat_patch_resolves_by_target_id():
    data = {"experiences": [dict(e) for e in _EXPS]}
    # target_index=0 (DCM) sería erróneo; target_id manda → Cóndor.
    patch = {"field": "experience_title", "target_id": "exp_condor",
             "target_index": 0, "action": "replace", "content": "Backend & AI Engineer"}
    apply_chat_patch(data, patch)
    assert data["experiences"][2]["title"] == "Backend & AI Engineer"
    assert data["experiences"][0]["title"] == "AI Engineer"  # DCM intacto


def test_chat_patch_falls_back_to_index_without_id():
    data = {"experiences": [dict(e) for e in _EXPS]}
    patch = {"field": "experience_title", "target_index": 1,
             "action": "replace", "content": "Fundador"}
    apply_chat_patch(data, patch)
    assert data["experiences"][1]["title"] == "Fundador"


# ── Bug B — guard score ↔ cobertura (anti imán-35) ───────────────

def test_score_floor_high_coverage():
    # 18/21 = 0.857 ≥ 0.85 → piso 70 (el 35-imán sube).
    assert _reconcile_score_with_coverage(35, ["k"] * 18, ["m"] * 3) == 70


def test_score_floor_mid_coverage_user_case():
    # Caso real del usuario: 16 match / 5 miss = 0.762 → piso 60.
    assert _reconcile_score_with_coverage(35, ["k"] * 16, ["m"] * 5) == 60


def test_score_floor_never_lowers():
    # Cobertura baja (2/10) no debe bajar un score alto: el guard solo sube.
    assert _reconcile_score_with_coverage(90, ["k"] * 2, ["m"] * 8) == 90


def test_score_unchanged_without_keywords():
    assert _reconcile_score_with_coverage(35, [], []) == 35


def test_sanitize_applies_score_floor():
    res = sanitize_ai_result({
        "match_score": 35, "viable": True,
        "matching_keywords": ["k"] * 16, "missing_keywords": ["m"] * 5,
        "suggestions": {},
    })
    assert res["match_score"] == 60


# ── Bug C — preservar evidencia en select_from_bank ──────────────

_MANIFEST = [
    {"id": "b1", "type": "bullet", "text": "Construyó automated testing suites con pytest", "tags": []},
    {"id": "b2", "type": "bullet", "text": "Diseñó APIs REST en FastAPI", "tags": []},
    {"id": "b3", "type": "bullet", "text": "Implementó CI/CD con Docker", "tags": ["docker"]},
]


def test_reintegrates_dropped_protected_keyword():
    # Selección dejó fuera la única evidencia de "automated testing" → se re-agrega b1.
    out = _reintegrate_lost_evidence(_MANIFEST, ["b2"], ["automated testing"])
    assert "b1" in out and out[0] == "b2"  # preserva orden original + reintegra


def test_no_reintegration_when_covered():
    out = _reintegrate_lost_evidence(_MANIFEST, ["b2", "b1"], ["automated testing"])
    assert out == ["b2", "b1"]


def test_no_reintegration_without_protected():
    assert _reintegrate_lost_evidence(_MANIFEST, ["b2"], None) == ["b2"]


# ── Bug A — translate re-alinea por id (no por posición) ─────────

def test_translate_realigns_by_id_when_reordered():
    data = [{"id": "x", "company": "DCM"}, {"id": "y", "company": "Cóndor"}]
    # El LLM devolvió las experiencias REORDENADAS (y antes que x).
    trans = [{"id": "y", "company": "Cóndor-tr"}, {"id": "x", "company": "DCM-tr"}]
    _restore_ids_with_fallback(data, trans, "es", "en")
    # Tras re-alinear, la posición 0 debe ser la de id x (DCM), no la de y.
    assert trans[0]["id"] == "x" and trans[0]["company"] == "DCM-tr"
    assert trans[1]["id"] == "y" and trans[1]["company"] == "Cóndor-tr"


def test_translate_omitted_middle_item_no_misattribution():
    # El LLM omitió el item INTERMEDIO (B). No debe correr la lista y meter C bajo B.
    data = [{"id": "a", "company": "A"}, {"id": "b", "company": ""},
            {"id": "c", "company": "C"}]
    trans = [{"id": "a", "company": "A-tr"}, {"id": "c", "company": "C-tr"}]
    _restore_ids_with_fallback(data, trans, "es", "en")
    assert trans[0]["id"] == "a" and trans[0]["company"] == "A-tr"
    assert trans[1]["id"] == "b"                       # hueco de B rellenado en SU posición
    assert trans[2]["id"] == "c" and trans[2]["company"] == "C-tr"


# ── #2 — guards de tier corren sobre el array (una línea por tier) ──

def test_skill_tiers_enforced_on_array_form():
    # El prompt nuevo devuelve skills como ARRAY (una línea por tier). El guard debe
    # regresar Rust (originalmente 'Familiaridad') al tier bajo aunque la IA la promovió.
    cv = {"skills": [{"text": "Dominio avanzado: Python"},
                     {"text": "Familiaridad: Rust"}]}
    result = {"missing_keywords": [], "suggestions": {"skills": [
        "Core skills: Python, Rust", "Working knowledge: Docker", "Exposure to: Bash",
    ]}}
    lines = sanitize_ai_result(result, cv)["suggestions"]["skills"]
    assert len(lines) > 1 and not any(" | " in l for l in lines)  # una línea por tier
    assert lines[0].startswith("Core skills:") and "Rust" not in lines[0]
    assert "Rust" in next(l for l in lines if l.startswith("Exposure to:"))  # degradada


# ── #9 — evidencia protegida por palabra completa (no substring) ──

def test_java_not_covered_by_javascript():
    manifest = [{"id": "j1", "text": "Backend en Java con Spring Boot"},
                {"id": "j2", "text": "Frontend en JavaScript y React"}]
    # Solo j2 (JavaScript) seleccionado: "Java" NO está cubierto → se reintegra j1.
    out = _reintegrate_lost_evidence(manifest, ["j2"], ["Java"])
    assert "j1" in out


# ── Reintegración: bullet sin su experiencia no se renderiza; summary no se pisa ──

def test_reintegrated_bullet_brings_its_parent_experience():
    manifest = [{"id": "exp_dcm", "type": "experience", "text": "DCM — Engineer (Contractor)"},
                {"id": "bul_dcm", "type": "bullet", "parent": "exp_dcm", "text": "Built features in Mastra"},
                {"id": "exp_z", "type": "experience", "text": "ZAPI — Founder"}]
    out = _reintegrate_lost_evidence(manifest, ["exp_z"], ["Mastra"])
    assert "bul_dcm" in out and "exp_dcm" in out  # sin el padre, el bullet no sale en el PDF


def test_reintegration_never_readds_a_summary():
    manifest = [{"id": "sum_a", "type": "summary", "text": "Backend: experto en Rust"},
                {"id": "sk_a", "type": "skill", "text": "Rust, Go, Python"},
                {"id": "sum_b", "type": "summary", "text": "AI: agentes"}]
    out = _reintegrate_lost_evidence(manifest, ["sum_b"], ["Rust"])
    assert "sum_a" not in out and "sk_a" in out  # el summary elegido no se pisa


# ── Dedup proyecto ↔ experiencia (ZAPI salía dos veces) ──

def test_project_duplicating_selected_experience_is_dropped():
    manifest = [{"id": "exp_z", "type": "experience", "text": "ZAPI (Own Project) — AI Engineer (2026)"},
                {"id": "proj_z", "type": "project", "text": "ZAPI — WhatsApp Sales SaaS: multi-tenant"},
                {"id": "proj_rag", "type": "project", "text": "RAG Assistant: ChromaDB y BM25"}]
    out = _drop_projects_duplicating_experience(manifest, ["exp_z", "proj_z", "proj_rag"])
    assert out == ["exp_z", "proj_rag"]


# ── Clamp de la re-eval tras adaptar (anti-caída artificial del score) ──

from cvgen.helpers import clamp_reeval_score


def test_clamp_floors_score_when_matches_preserved():
    # Caso real: pre-adapt 78, re-eval cae a 48 pero conservó todos los matches.
    prev = {"match_score": 78, "matching_keywords": ["Python", "FastAPI", "Docker", "AWS"]}
    new = {"match_score": 48, "matching_keywords": ["python", "fastapi", "docker", "aws", "redis"]}
    out = clamp_reeval_score(new, prev)
    assert out["match_score"] == 78  # el piso pre-adapt aplica (case-insensitive)


def test_clamp_respects_legitimate_drop():
    # Si la adaptación SÍ perdió evidencia matcheada (<85%), la caída es legítima.
    prev = {"match_score": 78, "matching_keywords": ["Python", "FastAPI", "Docker", "AWS"]}
    new = {"match_score": 48, "matching_keywords": ["python"]}  # perdió 3/4
    assert clamp_reeval_score(new, prev)["match_score"] == 48


def test_clamp_never_lowers():
    prev = {"match_score": 60, "matching_keywords": ["Python"]}
    new = {"match_score": 90, "matching_keywords": ["python"]}
    assert clamp_reeval_score(new, prev)["match_score"] == 90


def test_clamp_noop_without_prev():
    new = {"match_score": 48, "matching_keywords": ["python"]}
    assert clamp_reeval_score(new, None)["match_score"] == 48


# ── Piso de cobertura: exige muestra mínima (miss_kw=0 no regala un 70) ──

def test_coverage_floor_needs_minimum_sample():
    # Caso real de los logs: el modelo devuelve pocos keywords y 0 faltantes.
    # cobertura 1.0 sobre 2 keywords NO debe subir el score a 70.
    assert _reconcile_score_with_coverage(35, ["python", "sql"], []) == 35


def test_coverage_floor_applies_with_enough_keywords():
    kws = ["python", "fastapi", "docker", "aws", "sql", "git"]
    assert _reconcile_score_with_coverage(35, kws, []) == 70


# ── CamelCase: los términos del propio CV se protegen solos ──

def test_camel_terms_from_cv_are_not_split():
    cv = {"summary": "", "experiences": [{"bullets": "Construyó MuseTalk y LangGraph"}]}
    terms = camel_terms_in(cv)
    assert {"MuseTalk", "LangGraph"} <= set(terms)
    out = _fix_stuck_words("Ingeniero de MuseTalk y LangGraph", terms)
    assert "Muse Talk" not in out and "Lang Graph" not in out


def test_stuck_words_still_split_when_unknown():
    assert _fix_stuck_words("EngineerBackend") == "Engineer Backend"


# ── Idioma: acentos/¿¡ ganan al conteo de marcadores en inglés ──

def test_spanish_vacancy_with_english_boilerplate():
    txt = ("About the team and our requirements: buscamos un ingeniero con "
           "experiencia en programación, diseño de aplicaciones y gestión técnica.")
    assert detect_vacancy_language(txt) == "es"


def test_english_vacancy_still_detected():
    txt = "About the team: you will work with our engineers and develop new features."
    assert detect_vacancy_language(txt) == "en"


# ── merge_skill_line: reusa el id (no ensucia el banco en cada guardado) ──

def test_merge_skill_line_reuses_id_and_keeps_languages():
    from cvgen.ui.diff_viewer import merge_skill_line
    old = [{"id": "sk_tech", "text": "Core skills: Python"},
           {"id": "sk_lang", "text": "Languages: Spanish, English"}]
    out = merge_skill_line(old, "Core skills: Python, Go")
    assert out[0]["id"] == "sk_tech"          # mismo id → merge_cv_to_bank actualiza
    assert out[1]["id"] == "sk_lang"          # la línea de idiomas sobrevive


# ── Revisión 14-oct-2026 ──

from cvgen.ai_analyzer import _covers


def test_covers_symbol_keywords():
    assert _covers("c++", "python, c++ y go")
    assert _covers(".net", "c#, .net core")
    assert _covers("c#", "c#, .net core")
    assert not _covers("java", "javascript")


def test_reintegrated_project_survives_dedup(monkeypatch):
    from cvgen import ai_analyzer
    manifest = [{"id": "exp_z", "type": "experience", "text": "ZAPI (Own Project) — AI Engineer (2026)"},
                {"id": "proj_z", "type": "project", "text": "ZAPI — SaaS: multi-tenant", "tags": ["kafka"]}]
    monkeypatch.setattr(ai_analyzer, "_call_validated",
                        lambda *a, **k: {"selected_ids": ["exp_z"], "reasoning": ""})
    out = ai_analyzer.select_from_bank(manifest, "vacante", "k", "m", protected_keywords=["kafka"])
    assert "proj_z" in out  # única evidencia de un keyword protegido: no se descarta


def test_translation_mangled_id_does_not_duplicate(monkeypatch):
    from cvgen import translate
    monkeypatch.setattr(translate, "_translate_fallback", lambda t, s, g: t + "[fb]")
    data = [{"id": "exp_a", "title": "Ingeniero"}, {"id": "exp_b", "title": "Dev"}]
    trans = [{"id": "exp-a", "title": "Engineer"}, {"id": "exp_b", "title": "Dev"}]
    _restore_ids_with_fallback(data, trans, "es", "en")
    assert [t["id"] for t in trans] == ["exp_a", "exp_b"]
    assert trans[0]["title"] == "Engineer"


def test_list_bullets_are_joined():
    from cvgen.ai_analyzer import _normalize_suggestion_text
    parsed = {"suggestions": {"experiences": [{"id": "e", "bullets": ["Hizo A", {"text": "Hizo B"}]}],
                              "projects": [{"id": "p", "description": ["Desc"]}]}}
    _normalize_suggestion_text(parsed)
    assert parsed["suggestions"]["experiences"][0]["bullets"] == "Hizo A\nHizo B"
    assert parsed["suggestions"]["projects"][0]["description"] == "Desc"


def test_reintegrated_experience_still_dedups_project(monkeypatch):
    # Caso real: la reintegración re-agrega la EXPERIENCIA ZAPI; el proyecto ZAPI que
    # eligió el modelo debe caer (antes salían los dos).
    from cvgen import ai_analyzer
    manifest = [{"id": "exp_z", "type": "experience", "text": "ZAPI (Own Project) — AI Engineer (2026)"},
                {"id": "bul_z", "type": "bullet", "parent": "exp_z", "text": "Deployed pgvector services"},
                {"id": "proj_z", "type": "project", "text": "ZAPI — SaaS: multi-tenant"}]
    monkeypatch.setattr(ai_analyzer, "_call_validated",
                        lambda *a, **k: {"selected_ids": ["proj_z"], "reasoning": ""})
    out = ai_analyzer.select_from_bank(manifest, "vacante", "k", "m", protected_keywords=["pgvector"])
    assert "exp_z" in out and "proj_z" not in out


def test_parse_json_tolerates_raw_newline_in_string():
    from cvgen.llm_client import _parse_json_response
    assert _parse_json_response('{"a": "linea1\nlinea2"}') == {"a": "linea1\nlinea2"}


def test_real_job_title_is_restored():
    cv = {"experiences": [{"id": "exp_c", "title": "Python Backend Engineer"}]}
    result = {"suggestions": {"experiences": [
        {"id": "exp_c", "title": "Python Data & Systems Engineer", "bullets": "Built APIs"}]}}
    out = sanitize_ai_result(result, cv)["suggestions"]["experiences"][0]
    assert out["title"] == "Python Backend Engineer"


def test_merge_skill_line_one_entry_per_tier():
    from cvgen.ui.diff_viewer import merge_skill_line
    old = [{"id": "sk1", "text": "Core skills: Python"}, {"id": "sk2", "text": "Exposure to: Go"},
           {"id": "sk_lang", "text": "Languages: Spanish"}]
    out = merge_skill_line(old, "Core skills: Python\nWorking knowledge: SQL\nExposure to: Go")
    assert [s["text"] for s in out[:3]] == ["Core skills: Python", "Working knowledge: SQL", "Exposure to: Go"]
    assert out[0]["id"] == "sk1" and out[1]["id"] == "sk2"   # reusa ids en orden
    assert out[-1]["id"] == "sk_lang"
    legacy = merge_skill_line(old, "Core skills: Python | Exposure to: Go")
    assert len(legacy) == 3                                    # formato viejo también se separa


def test_dropped_core_skills_are_restored():
    cv = {"skills": [{"text": "Dominio avanzado: Python, FastAPI, Oracle Cloud"},
                     {"text": "Dominio intermedio: React"}]}
    result = {"missing_keywords": [], "suggestions": {"skills": [
        "Core skills: Python, SQL", "Exposure to: Oracle Cloud Infrastructure"]}}
    lines = sanitize_ai_result(result, cv)["suggestions"]["skills"]
    core = next(l for l in lines if l.startswith("Core skills:"))
    assert "FastAPI" in core                                # re-agregada a su tier
    assert sum("Oracle Cloud" in l for l in lines) == 1      # "Oracle Cloud Infrastructure" ya la cubría
    assert not any("React" in l for l in lines)             # intermedias no se re-agregan


def test_has_foreign_text_detects_mixed_bank():
    from cvgen.helpers import has_foreign_text
    en = {"summary": "Engineer with experience in Python",
          "experiences": [{"bullets": "Built APIs with FastAPI\nTrained five engineers in SQL"}]}
    assert not has_foreign_text(en, "en")
    en["projects"] = [{"description": "Desarrolló bot de trading con lógica propia para Telegram"}]
    assert has_foreign_text(en, "en")


def test_demoted_skill_returns_to_original_tier():
    cv = {"skills": [{"text": "Dominio avanzado: Python, FastAPI"}, {"text": "Familiaridad: Bash"}]}
    result = {"missing_keywords": [], "suggestions": {"skills": [
        "Core skills: Python", "Working knowledge: FastAPI", "Exposure to: Bash"]}}
    lines = sanitize_ai_result(result, cv)["suggestions"]["skills"]
    assert "FastAPI" in next(l for l in lines if l.startswith("Core skills:"))


def test_title_not_applied_to_other_company():
    # Caso real: sugerencia con id de ZAPI (no seleccionada) resuelta por contenido
    # hacia Condor → no debe ponerle a Condor el título de ZAPI.
    from cvgen.ui.diff_viewer import _collect_suggestion_changes
    d = {"experiences": [{"id": "exp_condor", "title": "Python Backend Engineer",
                          "bullets": "Developed RAG pipelines using LangChain"}]}
    sugg = {"experiences": [{"id": "exp_zapi", "title": "AI Engineer – Founder",
                             "bullets": "Developed RAG pipelines using LangChain and ChromaDB"}]}
    changes, _ = _collect_suggestion_changes(d, sugg)
    assert not any(c["kind"] == "exp_title" for c in changes)


def test_evidenced_untiered_skill_goes_to_working_not_exposure():
    cv = {"skills": [{"text": "Dominio avanzado: Python"},
                     {"text": "AI/ML: LLMs, OpenAI API, hybrid RAG"}],
          "experiences": [{"bullets": "Developed RAG pipelines using LangChain\nBuilt RESTful APIs"}]}
    result = {"missing_keywords": [], "suggestions": {"skills": [
        "Core skills: Python, OpenAI API",                  # inflado: sin tier → no Core
        "Working knowledge: Docker",
        "Exposure to: RAG Pipelines, REST APIs, Figma APIs"]}}
    lines = sanitize_ai_result(result, cv)["suggestions"]["skills"]
    working = next(l for l in lines if l.startswith("Working knowledge:"))
    exposure = next(l for l in lines if l.startswith("Exposure to:"))
    assert "OpenAI API" in working and "RAG Pipelines" in working and "REST APIs" in working
    assert "Figma APIs" in exposure                         # sin evidencia: tier más bajo


def test_thin_reintegrated_experience_gets_second_bullet():
    from cvgen.ai_analyzer import _pad_thin_experiences
    manifest = [{"id": "exp_z", "type": "experience", "text": "ZAPI — Founder"},
                {"id": "b_hook", "type": "bullet", "parent": "exp_z", "text": "MercadoPago webhooks"},
                {"id": "b_agent", "type": "bullet", "parent": "exp_z", "text": "AI agents on LangChain with Gemini Vision"},
                {"id": "b_menu", "type": "bullet", "parent": "exp_z", "text": "React menu with TailwindCSS"}]
    out = _pad_thin_experiences(manifest, ["exp_z", "b_hook"], ["webhooks", "LangChain", "Gemini"])
    assert "b_agent" in out and "b_menu" not in out
    # Sin keywords cubiertos no se agrega nada (no rellena por rellenar).
    assert _pad_thin_experiences(manifest, ["exp_z", "b_hook"], ["Kubernetes"]) == ["exp_z", "b_hook"]


def test_pad_skips_twin_bullet_with_same_text():
    # Caso real: el banco tenía bul_ai_dev_tools con el MISMO texto que bul_de51254e y ZAPI salió
    # con la línea de Docker repetida.
    from cvgen.ai_analyzer import _pad_thin_experiences
    manifest = [{"id": "exp_z", "type": "experience", "text": "ZAPI"},
                {"id": "b_dock", "type": "bullet", "parent": "exp_z", "text": "Deployed Docker with pgvector"},
                {"id": "b_twin", "type": "bullet", "parent": "exp_z", "text": "Deployed Docker with pgvector "},
                {"id": "b_agent", "type": "bullet", "parent": "exp_z", "text": "LangChain agents"}]
    out = _pad_thin_experiences(manifest, ["exp_z", "b_dock"], ["Docker", "LangChain"])
    assert "b_twin" not in out and "b_agent" in out


def test_experience_suggested_by_analysis_survives_selection(monkeypatch):
    # Vacante fintech: el análisis sugirió DCM, la selección lo tiró y la sugerencia se perdió.
    from cvgen import ai_analyzer
    monkeypatch.setattr(ai_analyzer, "_call_validated", lambda *a, **k: {"selected_ids": ["exp_a", "b_a1", "b_a2"]})
    manifest = [{"id": "exp_a", "type": "experience", "text": "Condor"},
                {"id": "b_a1", "type": "bullet", "parent": "exp_a", "text": "FastAPI"},
                {"id": "b_a2", "type": "bullet", "parent": "exp_a", "text": "CI/CD"},
                {"id": "exp_d", "type": "experience", "text": "DCM"},
                {"id": "b_d1", "type": "bullet", "parent": "exp_d", "text": "idempotency and rollbacks"},
                {"id": "b_d2", "type": "bullet", "parent": "exp_d", "text": "AES-256-GCM security"},
                {"id": "b_d3", "type": "bullet", "parent": "exp_d", "text": "team work"}]
    out = ai_analyzer.select_from_bank(manifest, "vacante", "k", "m",
                                       protected_keywords=["idempotency", "AES-256-GCM"],
                                       required_ids=["exp_d", "exp_inexistente"])
    assert "exp_d" in out and {"b_d1", "b_d2"} <= set(out) and "b_d3" not in out
    assert "exp_inexistente" not in out


def test_summary_claim_without_body_evidence_is_flagged():
    from cvgen.ui.diff_viewer import unsupported_summary_claims
    d = {"experiences": [{"title": "Backend", "bullets": "Built FastAPI APIs with webhooks"}],
         "projects": [], "skills": [{"text": "Core: Python, Docker"}], "certifications": []}
    s = "Backend engineer with Python, webhooks and idempotency; multi-agent architectures."
    assert unsupported_summary_claims(s, d, ["Python", "webhooks", "idempotency", "multi-agent", "Kafka"]) \
        == ["idempotency", "multi-agent"]
