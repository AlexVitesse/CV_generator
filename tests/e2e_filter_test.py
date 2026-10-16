"""
Test E2E de calidad de adaptación de CV (NO es un test pytest unitario).

Mide el pipeline REAL contra el LLM (Ollama Cloud) para responder dos preguntas:
  1. ¿El CV adaptado PASA el filtro ATS?  (match_score >= UMBRAL y viable=True)
  2. ¿La adaptación MEJORA respecto al CV base?  (score_final >= score_base)

Para cada vacante mide 3 etapas del flujo real:
  A) BASE      -> CV con la selección de banco actual          -> analyze
  B) BANCO     -> IA selecciona mejores items del banco        -> analyze
  C) FINAL     -> se aplican las sugerencias sobre (B)         -> analyze

Uso:
    python3 tests/e2e_filter_test.py            # todas las vacantes
    python3 tests/e2e_filter_test.py --quick    # solo 1ª (smoke, menos tokens)

Requiere API key en .ai_config.json o env OLLAMA_API_KEY.
NO modifica banco_personal.json (trabaja sobre copia en memoria).
"""

import copy
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cvgen.ai_analyzer import analyze_vacancy, load_ai_config, select_from_bank
from cvgen.banco import apply_ai_selection, bank_to_active_cv, get_bank_manifest
from cvgen.helpers import sanitize_ai_result

# Umbral de "pasa filtro ATS". analyze.md: 70-84 = cubre todos los must-haves.
PASS_THRESHOLD = 70

# ──────────────────────────────────────────────────────────────────
# Vacantes de prueba (perfil del candidato: Backend & AI Engineer Python)
#   - match: deberían pasar el filtro tras adaptar
#   - stretch: límite (faltan años o un must) -> mide honestidad
#   - control: claramente fuera de perfil -> debería NO ser viable
# ──────────────────────────────────────────────────────────────────
VACANCIES = [
    {
        "id": "ai_rag_en",
        "kind": "match",
        "text": """AI Engineer — LLM / RAG Systems (Remote)
We are looking for an AI Engineer to build production RAG pipelines.
Must have: Python, FastAPI, LLM integration, vector databases (ChromaDB/Pinecone),
RAG architectures, REST API design. 2+ years of backend experience.
Nice to have: LangChain, prompt engineering, cloud deployment (AWS/Oracle Cloud),
CI/CD, Docker. English working proficiency required.""",
    },
    {
        "id": "backend_py_en",
        "kind": "match",
        "text": """Backend Engineer (Python)
Build and maintain scalable REST APIs. Must have: Python, FastAPI or Django,
SQL/PostgreSQL, REST API design, automated testing, 2+ years backend.
Nice to have: cloud (AWS/Oracle), Docker, CI/CD, microservices.""",
    },
    {
        "id": "senior_ai_5y",
        "kind": "stretch",
        "text": """Senior AI/ML Engineer (5+ years)
Lead design of ML/LLM systems at scale. Must have: 5+ years in ML/AI,
Python, Kubernetes, AWS, MLOps, distributed training, model deployment at scale.
Nice to have: LangChain, RAG, vector DBs.""",
    },
    {
        "id": "frontend_react",
        "kind": "control",
        "text": """Senior Frontend Engineer (React)
Must have: 5+ years React, TypeScript, Redux, CSS-in-JS, Webpack, Jest,
responsive design, accessibility. No backend work.""",
    },
]


def apply_all_suggestions(cv: dict, suggestions: dict) -> dict:
    """Aplica TODAS las sugerencias de la IA al CV (acepta todo).

    Réplica headless de ui/diff_viewer._apply_selected_changes, sin Streamlit.
    """
    cv = copy.deepcopy(cv)
    exps = cv.get("experiences", [])
    projs = cv.get("projects", [])

    if suggestions.get("summary"):
        cv["summary"] = suggestions["summary"]

    for exp_sug in suggestions.get("experiences", []):
        idx = exp_sug.get("index", 0)
        if 0 <= idx < len(exps):
            if exp_sug.get("title"):
                exps[idx]["title"] = exp_sug["title"]
            if exp_sug.get("bullets"):
                exps[idx]["bullets"] = exp_sug["bullets"]

    for proj_sug in suggestions.get("projects", []):
        idx = proj_sug.get("index", 0)
        if 0 <= idx < len(projs) and proj_sug.get("description"):
            projs[idx]["description"] = proj_sug["description"]

    if suggestions.get("skills"):
        raw = suggestions["skills"]
        line = " | ".join(raw) if isinstance(raw, list) else str(raw)
        new_skills = [{"text": line.strip()}]
        for sk in cv.get("skills", []):
            txt = sk.get("text", "")
            low = txt.lower()
            preserve = "cert" in low or "idioma" in low or "language" in low
            if preserve and txt.strip() not in line:
                new_skills.append(sk)
        cv["skills"] = new_skills

    return cv


def score(cv, vacancy_text, api_key, model):
    """Analiza un CV y devuelve (result, elapsed_s). Aplica sanitize como en la app."""
    t = time.time()
    res = analyze_vacancy(cv, vacancy_text, api_key, model)
    res = sanitize_ai_result(res, cv)
    return res, time.time() - t


def run_vacancy(vac, banco, api_key, model):
    print(f"\n{'='*70}\n  VACANTE: {vac['id']}  [{vac['kind']}]\n{'='*70}")

    # A) BASE — selección de banco actual
    base_cv = bank_to_active_cv(banco)
    base, dt = score(base_cv, vac["text"], api_key, model)
    print(f"  A) BASE   score={base['match_score']:>3}  viable={base['viable']!s:>5}  ({dt:.0f}s)")

    # B) BANCO — IA selecciona mejores items
    banco_copy = copy.deepcopy(banco)
    try:
        ids = select_from_bank(get_bank_manifest(banco_copy), vac["text"], api_key, model)
        banco_copy = apply_ai_selection(banco_copy, ids)
        bank_cv = bank_to_active_cv(banco_copy)
        bnk, dt = score(bank_cv, vac["text"], api_key, model)
        print(f"  B) BANCO  score={bnk['match_score']:>3}  viable={bnk['viable']!s:>5}  ({dt:.0f}s)  ids={len(ids)}")
    except Exception as e:
        print(f"  B) BANCO  ERROR: {type(e).__name__}: {str(e)[:120]}")
        bank_cv, bnk = base_cv, base

    # C) FINAL — aplicar sugerencias sobre (B)
    final_cv = apply_all_suggestions(bank_cv, bnk.get("suggestions", {}))
    fin, dt = score(final_cv, vac["text"], api_key, model)
    print(f"  C) FINAL  score={fin['match_score']:>3}  viable={fin['viable']!s:>5}  ({dt:.0f}s)")

    miss = fin.get("missing_keywords", [])
    print(f"     matching={len(fin.get('matching_keywords', []))}  missing={miss}")

    passed = fin["match_score"] >= PASS_THRESHOLD and fin["viable"]
    improved = fin["match_score"] >= base["match_score"]
    return {
        "id": vac["id"], "kind": vac["kind"],
        "base": base["match_score"], "bank": bnk["match_score"], "final": fin["match_score"],
        "viable": fin["viable"], "passed": passed, "improved": improved,
    }


def main():
    quick = "--quick" in sys.argv
    cfg = load_ai_config()
    api_key, model = cfg.get("api_key"), cfg.get("model")
    if not api_key:
        print("ERROR: falta API key (.ai_config.json o OLLAMA_API_KEY)")
        sys.exit(2)

    banco = json.load(open("data/banco_personal.json", encoding="utf-8"))
    vacs = VACANCIES[:1] if quick else VACANCIES

    print(f"Modelo: {model} | umbral pasa-filtro: {PASS_THRESHOLD} | vacantes: {len(vacs)}")
    t0 = time.time()
    rows = [run_vacancy(v, banco, api_key, model) for v in vacs]

    # ── Reporte final ──
    print(f"\n{'='*70}\n  RESUMEN  ({time.time()-t0:.0f}s total)\n{'='*70}")
    print(f"  {'vacante':<16}{'tipo':<9}{'base':>5}{'banco':>6}{'final':>6}  {'Δ':>4}  resultado")
    print(f"  {'-'*64}")
    for r in rows:
        delta = r["final"] - r["base"]
        verdict = "✅ PASA" if r["passed"] else ("· honesto-no" if r["kind"] == "control" else "❌ NO pasa")
        print(f"  {r['id']:<16}{r['kind']:<9}{r['base']:>5}{r['bank']:>6}{r['final']:>6}  {delta:>+4}  {verdict}")

    # ── Verificación de criterios ──
    matches = [r for r in rows if r["kind"] in ("match",)]
    control = [r for r in rows if r["kind"] == "control"]
    print(f"\n  Criterios:")
    ok_pass = all(r["passed"] for r in matches) if matches else True
    ok_impr = all(r["improved"] for r in matches) if matches else True
    ok_ctrl = all(not r["viable"] for r in control) if control else True
    print(f"    [{'OK' if ok_pass else 'X'}] vacantes 'match' pasan filtro (>= {PASS_THRESHOLD} y viable)")
    print(f"    [{'OK' if ok_impr else 'X'}] adaptación no empeora el score (final >= base)")
    print(f"    [{'OK' if ok_ctrl else 'X'}] control fuera de perfil NO es viable (honestidad)")

    sys.exit(0 if (ok_pass and ok_impr and ok_ctrl) else 1)


if __name__ == "__main__":
    main()
