"""
Cost controller — routage des appels LLM par tâche pour limiter les coûts.

Stratégie : curriculum / content / quality_control passent par Gemini (gratuit)
tant que le quota gratuit journalier n'est pas épuisé, puis basculent sur
Claude Haiku (peu coûteux) en secours. exam_questions / domain_search passent
directement par Haiku (le volume d'appels de Bloc 7 dépasse largement le quota
gratuit de Gemini, voir note ci-dessous).

Note vérifiée en conditions réelles (2026-08-28 puis 2026-08-30) : le quota
gratuit réel de gemini-3.6-flash sur ce projet Google Cloud est de 20
requêtes/JOUR (erreur 429, quotaId
"GenerateRequestsPerDayPerProjectPerModel-FreeTier", quotaValue "20") — pas
1500/jour comme supposé initialement. GEMINI_DAILY_LIMIT reflète ce vrai
chiffre pour que le fallback Haiku se déclenche AVANT que Google ne bloque,
plutôt qu'après.
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

COST_LOG_PATH = Path(__file__).parent / "cost_log.json"

GEMINI_MODEL = "gemini-3.6-flash"
HAIKU_MODEL = "claude-haiku-4-5"

GEMINI_DAILY_LIMIT = 20
MAX_BUDGET_PER_COURSE_USD = 0.10

HAIKU_COST_PER_CALL = {
    "exam_questions": 0.002,
    "domain_search": 0.001,
    "curriculum": 0.003,
    "content": 0.004,
    "quality_control": 0.002,
}

TASK_MODEL = {
    "curriculum": ("gemini", True),
    "content": ("gemini", True),
    "quality_control": ("gemini", True),
    "exam_questions": ("haiku", False),
    "domain_search": ("haiku", False),
}


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load_log() -> dict:
    if not COST_LOG_PATH.exists():
        return {"calls": []}
    try:
        return json.loads(COST_LOG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"calls": []}


def _save_log(log: dict) -> None:
    COST_LOG_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def _gemini_quota() -> dict:
    log = _load_log()
    today = _today_str()
    used = sum(
        1 for c in log["calls"]
        if c["date"] == today and c["model"] == GEMINI_MODEL
    )
    return {"used": used, "date": today}


def choose_model(task: str) -> tuple[str, bool]:
    """Retourne (model_name, use_gemini) pour une tâche donnée."""
    model_type, use_gemini = TASK_MODEL.get(task, ("gemini", True))
    if use_gemini:
        q = _gemini_quota()
        if q["used"] >= GEMINI_DAILY_LIMIT:
            print(f"[cost] Quota Gemini épuisé ({q['used']}/{GEMINI_DAILY_LIMIT} aujourd'hui) → Haiku")
            return HAIKU_MODEL, False
        return GEMINI_MODEL, True
    return HAIKU_MODEL, False


def record_call(task: str, model: str) -> None:
    log = _load_log()
    log["calls"].append({
        "date": _today_str(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task": task,
        "model": model,
    })
    _save_log(log)


def check_budget(course_slug: str) -> None:
    """Lève une erreur si le coût estimé du jour dépasse le budget max par cours.

    Note : ce contrôle est actuellement calculé sur le total des appels du jour
    (tous cours confondus), pas filtré par course_slug — aucun call_llm_api()
    ne tague encore ses appels par cours. Cette fonction n'est pas branchée
    dans le pipeline pour le moment (voir README de l'étape correspondante) ;
    elle est fournie prête à l'emploi pour un futur branchement.
    """
    log = _load_log()
    today = _today_str()
    today_cost = sum(
        HAIKU_COST_PER_CALL.get(c["task"], 0.0)
        for c in log["calls"]
        if c["date"] == today and c["model"] == HAIKU_MODEL
    )
    if today_cost > MAX_BUDGET_PER_COURSE_USD:
        raise RuntimeError(
            f"Budget dépassé pour '{course_slug}' : ${today_cost:.4f} > ${MAX_BUDGET_PER_COURSE_USD:.2f}"
        )


if __name__ == "__main__":
    q = _gemini_quota()
    print(f"Quota Gemini aujourd'hui : {q['used']}/{GEMINI_DAILY_LIMIT}")
    print()
    for task in TASK_MODEL:
        model, use_gemini = choose_model(task)
        cost = 0.0 if use_gemini else HAIKU_COST_PER_CALL.get(task, 0.0)
        print(f"  {task:<18} -> {model:<20} (~${cost:.4f}/appel)")
