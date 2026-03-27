"""
Banco de Habilidades y Proyectos — módulo core.

Gestiona un archivo maestro (banco_personal.json) con TODOS los items
del candidato. Permite activar/desactivar items por vacante sin perder datos.
"""

import json
import os
import uuid
from datetime import datetime


BANCO_FILENAME = "banco_personal.json"


def _banco_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), BANCO_FILENAME)


def generate_bank_id(prefix: str = "item") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ═══════════════════════════════════════════════════════════════
# FILE I/O
# ═══════════════════════════════════════════════════════════════

def load_banco() -> dict:
    """Carga banco_personal.json. Retorna dict vacío si no existe."""
    path = _banco_path()
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_banco(banco: dict) -> None:
    """Guarda banco a disco con timestamp actualizado."""
    if "_meta" not in banco:
        banco["_meta"] = {"version": 1}
    banco["_meta"]["last_modified"] = datetime.now().isoformat(timespec="seconds")
    with open(_banco_path(), "w", encoding="utf-8") as f:
        json.dump(banco, f, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════
# MIGRACIÓN DESDE config_personal.json
# ═══════════════════════════════════════════════════════════════

def migrate_from_config(config_path: str) -> dict:
    """Convierte config_personal.json al formato banco.

    Separa bullets en objetos individuales con IDs,
    agrega active=true a todo, envuelve summary en array summaries.
    """
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    banco = {
        "_meta": {"version": 1},
        "name": cfg.get("name", ""),
        "location": cfg.get("location", ""),
        "linkedin": cfg.get("linkedin", ""),
        "github": cfg.get("github", ""),
        "phone": cfg.get("phone", ""),
        "email": cfg.get("email", ""),
    }

    # ── Summaries ──
    summary_text = cfg.get("summary", "")
    banco["summaries"] = []
    if summary_text:
        banco["summaries"].append({
            "id": generate_bank_id("sum"),
            "label": "Principal",
            "text": summary_text,
            "active": True,
        })

    # ── Experiences con bullets individuales ──
    banco["experiences"] = []
    for exp in cfg.get("experiences", []):
        bullets_text = exp.get("bullets", "")
        bullet_lines = [b.strip() for b in bullets_text.split("\n") if b.strip()]
        bullet_objects = []
        for line in bullet_lines:
            bullet_objects.append({
                "id": generate_bank_id("bul"),
                "text": line,
                "tags": [],
                "active": True,
            })
        banco["experiences"].append({
            "id": exp.get("id", generate_bank_id("exp")),
            "company": exp.get("company", ""),
            "title": exp.get("title", ""),
            "location": exp.get("location", ""),
            "dates": exp.get("dates", ""),
            "active": True,
            "bullets": bullet_objects,
        })

    # ── Projects ──
    banco["projects"] = []
    for proj in cfg.get("projects", []):
        banco["projects"].append({
            "id": proj.get("id", generate_bank_id("proj")),
            "name": proj.get("name", ""),
            "url": proj.get("url", ""),
            "description": proj.get("description", ""),
            "tags": [],
            "active": True,
        })

    # ── Education ──
    banco["education"] = []
    for edu in cfg.get("education", []):
        banco["education"].append({
            "id": edu.get("id", generate_bank_id("edu")),
            "institution": edu.get("institution", ""),
            "degree": edu.get("degree", ""),
            "details": edu.get("details", ""),
            "location": edu.get("location", ""),
            "date": edu.get("date", ""),
            "active": True,
        })

    # ── Skills ──
    banco["skills"] = []
    for sk in cfg.get("skills", []):
        banco["skills"].append({
            "id": sk.get("id", generate_bank_id("sk")),
            "text": sk.get("text", ""),
            "tags": [],
            "active": True,
        })

    return banco


# ═══════════════════════════════════════════════════════════════
# FILTRADO: BANCO → CV ACTIVO
# ═══════════════════════════════════════════════════════════════

def bank_to_active_cv(banco: dict) -> dict:
    """Filtra items con active=true y retorna dict compatible con el pipeline.

    El dict resultante tiene la misma estructura que config_personal.json:
    bullets son strings separados por \\n, summary es string plano, etc.
    """
    cv = {
        "name": banco.get("name", ""),
        "location": banco.get("location", ""),
        "linkedin": banco.get("linkedin", ""),
        "github": banco.get("github", ""),
        "phone": banco.get("phone", ""),
        "email": banco.get("email", ""),
    }

    # Summary: primer summary activo
    summaries = banco.get("summaries", [])
    active_sums = [s for s in summaries if s.get("active", True)]
    cv["summary"] = active_sums[0]["text"] if active_sums else ""

    # Experiences: solo activas, bullets activos unidos con \n
    cv["experiences"] = []
    for exp in banco.get("experiences", []):
        if not exp.get("active", True):
            continue
        active_bullets = [
            b["text"] for b in exp.get("bullets", [])
            if b.get("active", True)
        ]
        cv["experiences"].append({
            "id": exp["id"],
            "company": exp.get("company", ""),
            "title": exp.get("title", ""),
            "location": exp.get("location", ""),
            "dates": exp.get("dates", ""),
            "bullets": "\n".join(active_bullets),
        })

    # Projects: solo activos
    cv["projects"] = []
    for proj in banco.get("projects", []):
        if not proj.get("active", True):
            continue
        cv["projects"].append({
            "id": proj["id"],
            "name": proj.get("name", ""),
            "url": proj.get("url", ""),
            "description": proj.get("description", ""),
        })

    # Education: solo activas
    cv["education"] = []
    for edu in banco.get("education", []):
        if not edu.get("active", True):
            continue
        cv["education"].append({
            "id": edu["id"],
            "institution": edu.get("institution", ""),
            "degree": edu.get("degree", ""),
            "details": edu.get("details", ""),
            "location": edu.get("location", ""),
            "date": edu.get("date", ""),
        })

    # Skills: solo activas
    cv["skills"] = []
    for sk in banco.get("skills", []):
        if not sk.get("active", True):
            continue
        cv["skills"].append({"id": sk["id"], "text": sk.get("text", "")})

    return cv


# ═══════════════════════════════════════════════════════════════
# MANIFEST PARA IA
# ═══════════════════════════════════════════════════════════════

def get_bank_manifest(banco: dict) -> list[dict]:
    """Genera lista compacta de items para que la IA seleccione.

    Formato: [{"id": "bul_001", "type": "bullet", "parent": "exp_001",
               "text": "...", "tags": [...]}]
    """
    manifest = []

    for s in banco.get("summaries", []):
        manifest.append({
            "id": s["id"], "type": "summary",
            "text": s.get("label", "") + ": " + s["text"][:120],
            "tags": [],
        })

    for exp in banco.get("experiences", []):
        manifest.append({
            "id": exp["id"], "type": "experience",
            "text": f"{exp.get('company', '')} — {exp.get('title', '')}",
            "tags": [],
        })
        for bul in exp.get("bullets", []):
            manifest.append({
                "id": bul["id"], "type": "bullet", "parent": exp["id"],
                "text": bul["text"][:120],
                "tags": bul.get("tags", []),
            })

    for proj in banco.get("projects", []):
        manifest.append({
            "id": proj["id"], "type": "project",
            "text": proj.get("name", "") + ": " + proj.get("description", "")[:100],
            "tags": proj.get("tags", []),
        })

    for edu in banco.get("education", []):
        manifest.append({
            "id": edu["id"], "type": "education",
            "text": f"{edu.get('institution', '')} — {edu.get('degree', '')}",
            "tags": [],
        })

    for sk in banco.get("skills", []):
        manifest.append({
            "id": sk["id"], "type": "skill",
            "text": sk["text"][:150],
            "tags": sk.get("tags", []),
        })

    return manifest


# ═══════════════════════════════════════════════════════════════
# SELECCIÓN DE IA
# ═══════════════════════════════════════════════════════════════

def apply_ai_selection(banco: dict, selected_ids: list[str]) -> dict:
    """Activa items en selected_ids, desactiva el resto.

    Educación siempre queda activa por defecto.
    Si un experience ID está en selected_ids, se activa la experiencia
    (pero solo los bullets que también estén en la lista).
    """
    selected = set(selected_ids)

    for s in banco.get("summaries", []):
        s["active"] = s["id"] in selected

    for exp in banco.get("experiences", []):
        exp["active"] = exp["id"] in selected
        for bul in exp.get("bullets", []):
            bul["active"] = bul["id"] in selected

    for proj in banco.get("projects", []):
        proj["active"] = proj["id"] in selected

    # Educación: activa por defecto si no se especifica
    for edu in banco.get("education", []):
        edu["active"] = edu["id"] in selected if edu["id"] in selected else True

    for sk in banco.get("skills", []):
        sk["active"] = sk["id"] in selected

    return banco


# ═══════════════════════════════════════════════════════════════
# TOGGLE MANUAL
# ═══════════════════════════════════════════════════════════════

def toggle_item(banco: dict, item_id: str, active: bool) -> None:
    """Cambia el estado active de un item por su ID."""
    for section in ("summaries", "experiences", "projects", "education", "skills"):
        for item in banco.get(section, []):
            if item.get("id") == item_id:
                item["active"] = active
                return
            # Buscar en bullets anidados
            if section == "experiences":
                for bul in item.get("bullets", []):
                    if bul.get("id") == item_id:
                        bul["active"] = active
                        return


# ═══════════════════════════════════════════════════════════════
# MERGE: CV → BANCO (save-back)
# ═══════════════════════════════════════════════════════════════

def merge_cv_to_bank(cv: dict, banco: dict) -> None:
    """Actualiza los items activos del banco con el texto editado del CV.

    Sincroniza: summary, experience titles, bullets, project descriptions,
    skill texts. Solo toca items que ya están activos en el banco.
    """
    # ── Contact info ──
    for field in ("name", "location", "linkedin", "github", "phone", "email"):
        if field in cv:
            banco[field] = cv[field]

    # ── Summary → primer summary activo ──
    active_sums = [s for s in banco.get("summaries", []) if s.get("active", True)]
    if active_sums and cv.get("summary"):
        active_sums[0]["text"] = cv["summary"]

    # ── Experiences ──
    active_exps = [e for e in banco.get("experiences", []) if e.get("active", True)]
    cv_exps = cv.get("experiences", [])
    for i, bank_exp in enumerate(active_exps):
        if i >= len(cv_exps):
            break
        cv_exp = cv_exps[i]
        bank_exp["company"] = cv_exp.get("company", bank_exp["company"])
        bank_exp["title"] = cv_exp.get("title", bank_exp["title"])
        bank_exp["location"] = cv_exp.get("location", bank_exp["location"])
        bank_exp["dates"] = cv_exp.get("dates", bank_exp["dates"])

        # Sincronizar bullets: el CV tiene string, el banco tiene objetos
        cv_bullet_lines = [
            b.strip() for b in cv_exp.get("bullets", "").split("\n") if b.strip()
        ]
        active_bullets = [b for b in bank_exp.get("bullets", []) if b.get("active", True)]

        # Actualizar bullets existentes
        for j, bank_bul in enumerate(active_bullets):
            if j < len(cv_bullet_lines):
                bank_bul["text"] = cv_bullet_lines[j]

        # Si el CV tiene más bullets que el banco (nuevos del AI), agregarlos
        if len(cv_bullet_lines) > len(active_bullets):
            for new_text in cv_bullet_lines[len(active_bullets):]:
                bank_exp["bullets"].append({
                    "id": generate_bank_id("bul"),
                    "text": new_text,
                    "tags": [],
                    "active": True,
                })

    # ── Projects ──
    active_projs = [p for p in banco.get("projects", []) if p.get("active", True)]
    cv_projs = cv.get("projects", [])
    for i, bank_proj in enumerate(active_projs):
        if i >= len(cv_projs):
            break
        cv_proj = cv_projs[i]
        bank_proj["name"] = cv_proj.get("name", bank_proj["name"])
        bank_proj["url"] = cv_proj.get("url", bank_proj["url"])
        bank_proj["description"] = cv_proj.get("description", bank_proj["description"])

    # Si el CV tiene más projects, agregar al banco
    if len(cv_projs) > len(active_projs):
        for new_proj in cv_projs[len(active_projs):]:
            banco["projects"].append({
                "id": generate_bank_id("proj"),
                "name": new_proj.get("name", ""),
                "url": new_proj.get("url", ""),
                "description": new_proj.get("description", ""),
                "tags": [],
                "active": True,
            })

    # ── Skills ──
    active_skills = [s for s in banco.get("skills", []) if s.get("active", True)]
    cv_skills = cv.get("skills", [])
    for i, bank_sk in enumerate(active_skills):
        if i < len(cv_skills):
            bank_sk["text"] = cv_skills[i].get("text", bank_sk["text"])

    if len(cv_skills) > len(active_skills):
        for new_sk in cv_skills[len(active_skills):]:
            banco["skills"].append({
                "id": generate_bank_id("sk"),
                "text": new_sk.get("text", ""),
                "tags": [],
                "active": True,
            })

    # ── Education ──
    active_edus = [e for e in banco.get("education", []) if e.get("active", True)]
    cv_edus = cv.get("education", [])
    for i, bank_edu in enumerate(active_edus):
        if i < len(cv_edus):
            cv_edu = cv_edus[i]
            bank_edu["institution"] = cv_edu.get("institution", bank_edu["institution"])
            bank_edu["degree"] = cv_edu.get("degree", bank_edu["degree"])
            bank_edu["details"] = cv_edu.get("details", bank_edu["details"])
            bank_edu["location"] = cv_edu.get("location", bank_edu["location"])
            bank_edu["date"] = cv_edu.get("date", bank_edu["date"])


# ═══════════════════════════════════════════════════════════════
# UTILIDADES
# ═══════════════════════════════════════════════════════════════

def count_bank_items(banco: dict) -> tuple[int, int]:
    """Retorna (total, activos) contando todos los items toggleables."""
    total = 0
    active = 0
    for section in ("summaries", "projects", "education", "skills"):
        for item in banco.get(section, []):
            total += 1
            if item.get("active", True):
                active += 1
    for exp in banco.get("experiences", []):
        total += 1
        if exp.get("active", True):
            active += 1
        for bul in exp.get("bullets", []):
            total += 1
            if bul.get("active", True):
                active += 1
    return total, active


def toggle_all(banco: dict, active: bool) -> None:
    """Activa o desactiva TODOS los items del banco."""
    for section in ("summaries", "projects", "education", "skills"):
        for item in banco.get(section, []):
            item["active"] = active
    for exp in banco.get("experiences", []):
        exp["active"] = active
        for bul in exp.get("bullets", []):
            bul["active"] = active
