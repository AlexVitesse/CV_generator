"""
Banco de Habilidades y Proyectos — módulo core.

Gestiona un archivo maestro (banco_personal.json) con TODOS los items
del candidato. Permite activar/desactivar items por vacante sin perder datos.
"""

import json
import logging
import os
import re
import shutil
import uuid
from datetime import datetime
from cvgen import DATA_DIR

logger = logging.getLogger("banco")
_load_warning: str = ""  # populated by load_banco on corruption


def get_load_warning() -> str:
    return _load_warning


BANCO_FILENAME = "banco_personal.json"


def _banco_path() -> str:
    return os.path.join(DATA_DIR, BANCO_FILENAME)


def generate_bank_id(prefix: str = "item") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _split_bullets(bullets_text: str) -> list[str]:
    """Divide el string de bullets del CV en líneas no vacías."""
    return [b.strip() for b in (bullets_text or "").split("\n") if b.strip()]


# ═══════════════════════════════════════════════════════════════
# FILE I/O
# ═══════════════════════════════════════════════════════════════

def load_banco() -> dict:
    """Carga banco_personal.json. Retorna dict vacío si no existe.
    Si el archivo está corrupto, intenta recuperar desde el .bak."""
    global _load_warning
    path = _banco_path()
    if not os.path.exists(path):
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        bak_path = path + ".bak"
        if os.path.exists(bak_path):
            try:
                with open(bak_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                _load_warning = "banco_personal.json estaba corrupto. Se recuperó la copia de seguridad (.bak)."
                logger.warning("banco corrupto, recuperado de .bak")
                return data
            except (json.JSONDecodeError, IOError):
                pass
        _load_warning = "banco_personal.json está corrupto y no se pudo recuperar. Se usará un banco vacío."
        logger.error("banco corrupto y sin .bak válido")
        return {}


def save_banco(banco: dict) -> None:
    """Guarda banco a disco con escritura atómica y backup.

    Escribe a un .tmp primero, luego renombra atómicamente,
    y conserva el archivo previo como .bak.
    """
    if "_meta" not in banco:
        banco["_meta"] = {"version": 1}
    banco["_meta"]["last_modified"] = datetime.now().isoformat(timespec="seconds")

    path = _banco_path()
    tmp_path = path + ".tmp"
    bak_path = path + ".bak"

    # Escribir a .tmp
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(banco, f, ensure_ascii=False, indent=2)

    # Conservar copia de seguridad del archivo previo
    if os.path.exists(path):
        shutil.copy2(path, bak_path)

    # Renombrar atómicamente
    os.replace(tmp_path, path)


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

_MONTHS = {m: i for i, names in enumerate([
    ("jan", "ene"), ("feb",), ("mar",), ("apr", "abr"), ("may",), ("jun",),
    ("jul",), ("aug", "ago"), ("sep", "set"), ("oct",), ("nov",), ("dec", "dic"),
], start=1) for m in names}
_CURRENT = ("present", "actualidad", "presente", "current", "actual")


def _parse_date(text: str) -> tuple[int, int]:
    """(año, mes) de "Abril 2026", "May 2024" o "2026" (mes 0 si no hay). (0, 0) si no hay año."""
    low = text.lower()
    year = re.search(r"(19|20)\d{2}", low)
    month = next((n for k, n in _MONTHS.items() if re.search(rf"\b{k}", low)), 0)
    return (int(year.group()), month) if year else (0, 0)


def _date_sort_key(dates: str) -> tuple:
    """Clave para ordenar experiencias: (es_actual, fin, inicio). Acepta "–", "—" o "-"."""
    parts = re.split(r"\s+[–—-]\s+", str(dates or ""), maxsplit=1)
    start = _parse_date(parts[0])
    end_txt = parts[1] if len(parts) > 1 else parts[0]
    current = any(w in end_txt.lower() for w in _CURRENT)
    return (current, (9999, 12) if current else _parse_date(end_txt), start)


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
    # Orden cronológico inverso (convención de CV): puestos actuales primero, luego por
    # fecha de fin. Antes seguía el orden del banco y un contrato ya terminado (DCM)
    # quedaba encima del puesto actual y más fuerte (Condor).
    cv["experiences"].sort(key=lambda e: _date_sort_key(e["dates"]), reverse=True)

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

    # Certifications: activas por defecto (como educación) — siempre relevantes.
    cv["certifications"] = []
    for cert in banco.get("certifications", []):
        if not cert.get("active", True):
            continue
        cv["certifications"].append({
            "id": cert["id"],
            "text": cert.get("text", ""),
            "credential_id": cert.get("credential_id", ""),
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
            "text": f"{exp.get('company', '')} — {exp.get('title', '')} ({exp.get('dates', '')})",
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

    # Las certificaciones también compiten por el espacio de la página: si no entran
    # al manifiesto, se imprimen TODAS en toda vacante (6-7 líneas fijas) y obligan
    # al PDF a encoger la fuente para caber.
    for cert in banco.get("certifications", []):
        manifest.append({
            "id": cert["id"], "type": "certification",
            "text": cert.get("text", "")[:150],
            "tags": ["certs"],
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

    # Educación: SIEMPRE activa (el prompt la pide completa en todas las vacantes).
    for edu in banco.get("education", []):
        edu["active"] = True

    # Certificaciones: solo si el modelo eligió al menos una (fail-open: un modelo que
    # las ignore deja el comportamiento anterior de imprimirlas todas).
    certs = banco.get("certifications", [])
    if any(c["id"] in selected for c in certs):
        for c in certs:
            c["active"] = c["id"] in selected

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

    # ── Experiences: emparejar por id (no por posición) ──
    # El CV solo trae los items activos, pero el banco es el master set: los
    # items sin match en el CV se conservan; los del CV sin match se agregan.
    bank_exps_by_id = {e["id"]: e for e in banco.get("experiences", []) if "id" in e}
    for cv_exp in cv.get("experiences", []):
        bank_exp = bank_exps_by_id.get(cv_exp.get("id"))
        cv_bullet_lines = _split_bullets(cv_exp.get("bullets", ""))

        if bank_exp is None:
            # Experiencia nueva (reordenada/creada en Manual): agregar al banco.
            banco.setdefault("experiences", []).append({
                "id": cv_exp.get("id") or generate_bank_id("exp"),
                "company": cv_exp.get("company", ""),
                "title": cv_exp.get("title", ""),
                "location": cv_exp.get("location", ""),
                "dates": cv_exp.get("dates", ""),
                "active": True,
                "bullets": [
                    {"id": generate_bank_id("bul"), "text": txt, "tags": [], "active": True}
                    for txt in cv_bullet_lines
                ],
            })
            continue

        bank_exp["company"] = cv_exp.get("company", bank_exp["company"])
        bank_exp["title"] = cv_exp.get("title", bank_exp["title"])
        bank_exp["location"] = cv_exp.get("location", bank_exp["location"])
        bank_exp["dates"] = cv_exp.get("dates", bank_exp["dates"])

        # Bullets: el CV los aplana a string y pierden su id, así que dentro de
        # la experiencia (ya emparejada por id) se sincronizan por posición
        # sobre los bullets activos. Los extra del CV se agregan como nuevos.
        active_bullets = [b for b in bank_exp.get("bullets", []) if b.get("active", True)]
        for j, bank_bul in enumerate(active_bullets):
            if j < len(cv_bullet_lines):
                bank_bul["text"] = cv_bullet_lines[j]
        if len(cv_bullet_lines) > len(active_bullets):
            for new_text in cv_bullet_lines[len(active_bullets):]:
                bank_exp["bullets"].append({
                    "id": generate_bank_id("bul"),
                    "text": new_text,
                    "tags": [],
                    "active": True,
                })

    # ── Projects: emparejar por id ──
    bank_projs_by_id = {p["id"]: p for p in banco.get("projects", []) if "id" in p}
    for cv_proj in cv.get("projects", []):
        bank_proj = bank_projs_by_id.get(cv_proj.get("id"))
        if bank_proj is None:
            banco.setdefault("projects", []).append({
                "id": cv_proj.get("id") or generate_bank_id("proj"),
                "name": cv_proj.get("name", ""),
                "url": cv_proj.get("url", ""),
                "description": cv_proj.get("description", ""),
                "tags": [],
                "active": True,
            })
            continue
        bank_proj["name"] = cv_proj.get("name", bank_proj["name"])
        bank_proj["url"] = cv_proj.get("url", bank_proj["url"])
        bank_proj["description"] = cv_proj.get("description", bank_proj["description"])

    # ── Skills: emparejar por id ──
    bank_skills_by_id = {s["id"]: s for s in banco.get("skills", []) if "id" in s}
    for cv_sk in cv.get("skills", []):
        bank_sk = bank_skills_by_id.get(cv_sk.get("id"))
        if bank_sk is None:
            banco.setdefault("skills", []).append({
                "id": cv_sk.get("id") or generate_bank_id("sk"),
                "text": cv_sk.get("text", ""),
                "tags": [],
                "active": True,
            })
            continue
        bank_sk["text"] = cv_sk.get("text", bank_sk["text"])

    # ── Education: emparejar por id ──
    bank_edus_by_id = {e["id"]: e for e in banco.get("education", []) if "id" in e}
    for cv_edu in cv.get("education", []):
        bank_edu = bank_edus_by_id.get(cv_edu.get("id"))
        if bank_edu is None:
            banco.setdefault("education", []).append({
                "id": cv_edu.get("id") or generate_bank_id("edu"),
                "institution": cv_edu.get("institution", ""),
                "degree": cv_edu.get("degree", ""),
                "details": cv_edu.get("details", ""),
                "location": cv_edu.get("location", ""),
                "date": cv_edu.get("date", ""),
                "active": True,
            })
            continue
        bank_edu["institution"] = cv_edu.get("institution", bank_edu["institution"])
        bank_edu["degree"] = cv_edu.get("degree", bank_edu["degree"])
        bank_edu["details"] = cv_edu.get("details", bank_edu["details"])
        bank_edu["location"] = cv_edu.get("location", bank_edu["location"])
        bank_edu["date"] = cv_edu.get("date", bank_edu["date"])

    # ── Certifications: emparejar por id ──
    bank_certs_by_id = {c["id"]: c for c in banco.get("certifications", []) if "id" in c}
    for cv_cert in cv.get("certifications", []):
        bank_cert = bank_certs_by_id.get(cv_cert.get("id"))
        if bank_cert is None:
            banco.setdefault("certifications", []).append({
                "id": cv_cert.get("id") or generate_bank_id("cert"),
                "text": cv_cert.get("text", ""),
                "credential_id": cv_cert.get("credential_id", ""),
                "active": True,
            })
            continue
        bank_cert["text"] = cv_cert.get("text", bank_cert["text"])
        bank_cert["credential_id"] = cv_cert.get("credential_id", bank_cert.get("credential_id", ""))


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
