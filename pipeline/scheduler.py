"""Pipeline — Module 3 : planificateur autonome (2 cours/jour, 12h d'écart minimum, multi-domaines).

Boucle de fond (`python pipeline/scheduler.py &`) : vérifie l'éligibilité (quota du jour, délai
minimum écoulé), choisit le meilleur sujet disponible via `domain_agent.get_top_topics`, lance
`run_pipeline.run_pipeline(..., interactive=False)` — SANS prompt de validation interactif (ce
processus n'a pas de terminal pour répondre à un `input()`) : chaque cours produit atterrit dans
`pending_validation.json`, à valider ensuite via `pipeline/validate.py` (Module 4).

Autonomie complète (feu vert tacite) : à chaque tour de boucle, `check_pending_for_tacit_approval`
balaie `pending_validation.json` et publie automatiquement (`pipeline/auto_publish.py`) tout cours
qui y est resté plus de `MAX_VALIDATION_HOURS` (défaut 2h) SANS rejet explicite (`validate.py
--slug ... non`, qui retire déjà l'entrée de cette file — rien de spécial à faire ici pour le cas
"rejeté", il n'y sera simplement plus). Aucune infrastructure d'envoi d'email n'existe dans ce
dépôt (vérifié : aucun SMTP/SendGrid/Resend nulle part) — et l'API Anthropic elle-même n'envoie pas
d'email — voir `_notify` : se contente donc du log (`pipeline/scheduler.log`), jamais un envoi réel
tant qu'un fournisseur d'email n'est pas explicitement choisi.

État persistant dans `scheduler_state.json` (quota du jour, horodatage du dernier cours,
pause/reprise) — configuration dans `scheduler_config.json` (voir `DEFAULT_CONFIG`)."""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.domain_agent import DOMAINS

PIPELINE_DIR = Path(__file__).resolve().parent
SCHEDULER_CONFIG_FILE = PIPELINE_DIR / "scheduler_config.json"
SCHEDULER_STATE_FILE = PIPELINE_DIR / "scheduler_state.json"
SCHEDULER_LOG_FILE = PIPELINE_DIR / "scheduler.log"

POLL_INTERVAL_SECONDS = 300  # fréquence de vérification d'éligibilité/feu-vert-tacite pendant l'attente

DEFAULT_CONFIG = {
    "MAX_COURSES_PER_DAY": 2,
    "MIN_HOURS_BETWEEN_COURSES": 12,
    "DOMAINS_ENABLED": list(DOMAINS),
    "AUTO_SELECT_TOPIC": True,
    "MAX_VALIDATION_HOURS": 2,
}


def load_config(path: Path | str | None = None) -> dict:
    path = Path(path) if path else SCHEDULER_CONFIG_FILE
    if not path.exists():
        return dict(DEFAULT_CONFIG)
    config = dict(DEFAULT_CONFIG)
    config.update(json.loads(path.read_text(encoding="utf-8")))
    return config


DEFAULT_STATE = {
    "paused": False,
    "last_course_at": None,
    "courses_today": {"date": None, "count": 0},
    "history": [],
}


def load_state(path: Path | str | None = None) -> dict:
    path = Path(path) if path else SCHEDULER_STATE_FILE
    if not path.exists():
        return json.loads(json.dumps(DEFAULT_STATE))  # copie profonde
    state = json.loads(json.dumps(DEFAULT_STATE))
    state.update(json.loads(path.read_text(encoding="utf-8")))
    return state


def save_state(state: dict, path: Path | str | None = None) -> None:
    path = Path(path) if path else SCHEDULER_STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _today_str() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def courses_produced_today(state: dict) -> int:
    if state["courses_today"].get("date") != _today_str():
        return 0
    return state["courses_today"].get("count", 0)


def record_course_started(state: dict) -> dict:
    """Incrémente le compteur du jour (remis à 0 si la date a changé depuis le dernier cours) et
    met à jour `last_course_at` — appelé APRÈS un lancement réussi de `run_pipeline`, jamais avant
    (un échec ne doit pas consommer le quota du jour)."""
    today = _today_str()
    count = courses_produced_today(state) + 1
    state["courses_today"] = {"date": today, "count": count}
    state["last_course_at"] = datetime.now(timezone.utc).isoformat()
    return state


def is_eligible_now(config: dict, state: dict) -> tuple[bool, str]:
    """Retourne `(eligible, raison)`. Deux garde-fous, dans l'ordre du cahier des charges : quota
    du jour, puis délai minimum depuis le dernier cours."""
    if state.get("paused"):
        return False, "en pause"

    if courses_produced_today(state) >= config["MAX_COURSES_PER_DAY"]:
        return False, f"quota du jour atteint ({config['MAX_COURSES_PER_DAY']} cours)"

    last_course_at = state.get("last_course_at")
    if last_course_at:
        elapsed = datetime.now(timezone.utc) - datetime.fromisoformat(last_course_at)
        min_delay = timedelta(hours=config["MIN_HOURS_BETWEEN_COURSES"])
        if elapsed < min_delay:
            return False, f"delai minimum non ecoule ({config['MIN_HOURS_BETWEEN_COURSES']}h entre deux cours)"

    return True, "eligible"


def next_eligible_at(config: dict, state: dict) -> datetime | None:
    """`None` si éligible dès maintenant ; sinon l'horodatage (UTC) à partir duquel ce sera le cas
    — minuit UTC du lendemain si le quota du jour est atteint, sinon `last_course_at +
    MIN_HOURS_BETWEEN_COURSES`."""
    eligible, reason = is_eligible_now(config, state)
    if eligible:
        return None
    if reason.startswith("quota"):
        tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
        return datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=timezone.utc)
    if reason.startswith("delai"):
        last_course_at = datetime.fromisoformat(state["last_course_at"])
        return last_course_at + timedelta(hours=config["MIN_HOURS_BETWEEN_COURSES"])
    return None  # "en pause" : indéterminé, dépend d'une action humaine (--resume)


def get_status(config: dict | None = None, state: dict | None = None) -> dict:
    config = config or load_config()
    state = state or load_state()
    eligible, reason = is_eligible_now(config, state)
    next_at = next_eligible_at(config, state)
    return {
        "paused": state.get("paused", False),
        "courses_today": courses_produced_today(state),
        "max_courses_per_day": config["MAX_COURSES_PER_DAY"],
        "last_course_at": state.get("last_course_at"),
        "eligible_now": eligible,
        "reason": reason,
        "next_eligible_at": next_at.isoformat() if next_at else None,
        "domains_enabled": config["DOMAINS_ENABLED"],
    }


def _log(message: str) -> None:
    line = f"[{datetime.now(timezone.utc).isoformat()}] {message}"
    print(line)
    SCHEDULER_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with SCHEDULER_LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _notify(subject: str, body: str) -> None:
    """Notifie l'opérateur d'un événement important (publication automatique, échec...). Aucune
    infrastructure d'envoi d'email n'existe dans ce dépôt (vérifié : aucun SMTP/SendGrid/Resend
    nulle part) — et l'API Anthropic elle-même n'envoie pas d'email, donc "via l'API Anthropic"
    n'est pas une option réelle sans en choisir une explicitement. Se contente donc du log
    (toujours), en mentionnant l'adresse destinataire si `RENDER_NOTIFY_EMAIL` est définie, pour
    qu'un humain qui lit `pipeline/scheduler.log` voie le message même sans envoi réel. Brancher
    un vrai envoi (SMTP/API email) tiendrait dans cette seule fonction, à remplacer plus tard."""
    notify_email = os.environ.get("RENDER_NOTIFY_EMAIL")
    if notify_email:
        _log(f"NOTIFICATION (destinataire {notify_email}, aucun envoi email reel configure) : {subject} - {body}")
    else:
        _log(f"NOTIFICATION (log uniquement, RENDER_NOTIFY_EMAIL non definie) : {subject} - {body}")


def pick_next_topic(config: dict, demo: bool = False) -> dict | None:
    from pipeline.domain_agent import get_top_topics

    topics = get_top_topics(domains=config["DOMAINS_ENABLED"], top_n=1, demo=demo)
    return topics[0] if topics else None


def check_pending_for_tacit_approval(config: dict | None = None, now: datetime | None = None) -> list[dict]:
    """Publie automatiquement tout cours resté dans `pending_validation.json` plus de
    `MAX_VALIDATION_HOURS` sans rejet explicite ("feu vert tacite" — voir docstring du module). Un
    rejet via `pipeline/validate.py --slug ... non` retire déjà l'entrée de cette file avant que ce
    balayage ne s'exécute : rien de spécial à faire ici pour ce cas, l'entrée n'y sera simplement
    plus. Retourne la liste des issues (`{"slug", "status": "published"|"failed"|"skipped_no_report"}`)
    pour les tests/l'audit."""
    from pipeline.auto_publish import AutoPublishError, auto_publish
    from pipeline.run_pipeline import REPORTS_DIR, apply_validation_decision, load_pending_validation, remove_pending_validation

    config = config or load_config()
    now = now or datetime.now(timezone.utc)
    max_hours = config.get("MAX_VALIDATION_HOURS", DEFAULT_CONFIG["MAX_VALIDATION_HOURS"])

    outcomes: list[dict] = []
    for entry in load_pending_validation():
        added_at = datetime.fromisoformat(entry["added_at"])
        elapsed_hours = (now - added_at).total_seconds() / 3600
        if elapsed_hours < max_hours:
            continue

        slug = entry["slug"]
        report_path = REPORTS_DIR / f"{slug}_report.json"
        if not report_path.exists():
            _log(f"Rapport introuvable pour {slug} - impossible de publier automatiquement, laisse en attente.")
            outcomes.append({"slug": slug, "status": "skipped_no_report"})
            continue

        report = json.loads(report_path.read_text(encoding="utf-8"))
        price_usd = report.get("prix_suggere_usd")
        title = report.get("titre") or entry.get("topic")

        apply_validation_decision(slug, "oui", price_usd=price_usd)
        remove_pending_validation(slug)

        try:
            auto_publish(slug, title=title, domain=entry["domain"], price_usd=price_usd)
        except AutoPublishError as exc:
            _log(f"Echec publication automatique de {slug} : {exc}")
            _notify("Echec de publication automatique", f"{slug} : {exc}")
            outcomes.append({"slug": slug, "status": "failed"})
            continue

        _log(f"Cours {slug} publie automatiquement (feu vert tacite, {max_hours}h ecoulees sans reponse).")
        _notify("Cours publie automatiquement", f"{slug} publie apres {max_hours}h sans reponse (feu vert tacite).")
        outcomes.append({"slug": slug, "status": "published"})

    return outcomes


def run_once(config: dict, state: dict, demo: bool = False) -> dict:
    """Choisit le meilleur sujet disponible et lance `run_pipeline` (mode non-interactif : le
    cours produit part en 'attente', voir `pending_validation.json`). Retourne le résultat de
    `run_pipeline.run_pipeline` (ou `{"status": "no_topic"}` s'il ne reste aucun sujet non
    produit dans les domaines actifs)."""
    from pipeline.run_pipeline import run_pipeline

    topic = pick_next_topic(config, demo=demo)
    if topic is None:
        _log("Aucun sujet disponible (tous deja produits dans les domaines actifs).")
        return {"status": "no_topic"}

    _log(f"Lancement pipeline : [{topic['domain']}] {topic['topic']} (score {topic['score_total']}/30)")
    result = run_pipeline(
        topic=topic["topic"],
        domain=topic["domain"],
        price_usd=topic["suggested_price_usd"],
        gap_reason=topic.get("justification", ""),
        dry_run=demo,
        interactive=False,
    )
    _log(f"Pipeline termine : slug={result['slug']} statut={result['status']}")

    # `demo=True` (--demo / --dry-run) ne doit JAMAIS consommer le quota/délai réels : sinon un
    # test gratuit bloquerait le prochain run réel jusqu'à MIN_HOURS_BETWEEN_COURSES plus tard —
    # bug réel constaté (un --once --demo a bloqué le --once réel suivant pendant 12h).
    if result["status"] == "completed" and not demo:
        record_course_started(state)
        save_state(state)

    return result


def main_loop(demo: bool = False) -> None:
    _log("Scheduler demarre.")
    while True:
        state = load_state()
        config = load_config()
        eligible, reason = is_eligible_now(config, state)

        if eligible:
            run_once(config, state, demo=demo)
        else:
            _log(f"Non eligible pour l'instant ({reason}).")

        check_pending_for_tacit_approval(config)

        time.sleep(POLL_INTERVAL_SECONDS)


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline — Planificateur (2 cours/jour, multi-domaines)")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--next", action="store_true", help="Sujet qui serait produit ensuite (sans lancer le pipeline)")
    parser.add_argument("--pause", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--once", action="store_true", help="Une seule iteration puis quitte (au lieu de la boucle infinie)")
    parser.add_argument(
        "--check-pending", action="store_true",
        help="Balaie pending_validation.json et publie ce qui a depasse MAX_VALIDATION_HOURS, sans lancer de nouveau cours",
    )
    parser.add_argument("--demo", action="store_true", help="Mode demo pour --next/--once (aucun appel reseau/cout)")
    args = parser.parse_args()

    if args.status:
        status = get_status()
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return

    if args.next:
        config = load_config()
        topic = pick_next_topic(config, demo=args.demo)
        print(json.dumps(topic, ensure_ascii=False, indent=2) if topic else "Aucun sujet disponible.")
        return

    if args.pause:
        state = load_state()
        state["paused"] = True
        save_state(state)
        print("Scheduler mis en pause.")
        return

    if args.resume:
        state = load_state()
        state["paused"] = False
        save_state(state)
        print("Scheduler relance.")
        return

    if args.check_pending:
        outcomes = check_pending_for_tacit_approval()
        print(json.dumps(outcomes, ensure_ascii=False, indent=2))
        return

    if args.once:
        state = load_state()
        config = load_config()
        eligible, reason = is_eligible_now(config, state)
        if not eligible:
            print(f"Non eligible ({reason}).")
            return
        result = run_once(config, state, demo=args.demo)
        print(json.dumps(result.get("report", result), ensure_ascii=False, indent=2, default=str))
        return

    main_loop(demo=args.demo)


if __name__ == "__main__":
    main()
