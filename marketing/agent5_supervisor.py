"""Marketing KORTEX — Agent 5 : Supervision.

Point d'entrée principal (`python marketing/agent5_supervisor.py`). Exécute les Agents 1 à 4 dans
l'ordre, avec retry 3x (backoff 2s/4s/8s) puis skip si l'étape échoue encore, et logge tout dans
`marketing/logs/supervisor.log`.

`--dry-run` : vérifie que toutes les clés requises sont présentes et que les APIs externes sont
JOIGNABLES, SANS jamais appeler un endpoint de génération de contenu ou de publication. À exécuter
et à faire valider avant toute publication réelle."""

import argparse
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from marketing import agent1_strategy, agent2_carousel, agent2_content, agent3_publisher, agent4_analytics
from marketing.config import (
    ANTHROPIC_API_KEY,
    FACEBOOK_PAGE_ID,
    GRAPH_API_BASE,
    INSTAGRAM_ACCOUNT_ID,
    KORTEX_SITE_URL,
    META_PAGE_ACCESS_TOKEN,
    PUBLICATIONS_LOG_FILE,
    REQUIRED_ENV_VARS,
    REQUEST_TIMEOUT_SECONDS,
    SUPERVISOR_LOG_FILE,
    TELEGRAM_API_BASE,
    TELEGRAM_CHANNEL,
    missing_env_vars,
)

_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 2


def _log(message: str) -> None:
    """Append une ligne horodatée à `marketing/logs/supervisor.log` ET l'imprime sur stdout —
    un seul run n'est jamais silencieux, même sans surveiller le fichier de log."""
    line = f"[{datetime.now(timezone.utc).isoformat()}] {message}"
    print(line)
    with SUPERVISOR_LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _run_step(step_name: str, func, *args, **kwargs):
    """Exécute `func(*args, **kwargs)` avec retry `_MAX_ATTEMPTS` fois (backoff exponentiel).
    Retourne `(True, résultat)` en cas de succès, `(False, None)` si toujours en échec après
    épuisement des tentatives — jamais d'exception qui remonte, l'appelant (`run_pipeline`) décide
    de sauter l'étape suivante en fonction du booléen."""
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            result = func(*args, **kwargs)
            _log(f"{step_name} : succès (tentative {attempt}/{_MAX_ATTEMPTS})")
            return True, result
        except Exception as exc:
            _log(f"{step_name} : échec tentative {attempt}/{_MAX_ATTEMPTS} — {exc}")
            if attempt < _MAX_ATTEMPTS:
                time.sleep(_RETRY_BACKOFF_SECONDS * attempt)
            else:
                _log(f"{step_name} : abandon après {_MAX_ATTEMPTS} tentatives\n{traceback.format_exc()}")
    return False, None


def run_pipeline(demo: bool = False) -> dict:
    """Exécute les Agents 0 à 4 dans l'ordre. Si l'Agent 0, 1, 2 ou 3 échoue définitivement (voir
    `_run_step`), les étapes suivantes sont sautées (chaque étape dépend de la sortie de la
    précédente) ; l'Agent 4 (analytics) est best-effort et ne fait jamais échouer le run global."""
    if not demo:
        from datetime import date
        import json as _json
        if PUBLICATIONS_LOG_FILE.exists():
            pubs = _json.loads(
                PUBLICATIONS_LOG_FILE.read_text(encoding="utf-8")
            ).get("publications", [])
            today = date.today().isoformat()
            already_today = any(
                p.get("statut") == "success" and
                p.get("timestamp", "").startswith(today)
                for p in pubs
            )
            if already_today:
                _log(f"Already published today ({today}) — skipping.")
                return {"status": "skipped", "reason": "already_published_today"}

    _log("=== Run supervisor démarré ===")

    from marketing import agent0_director

    # Agent 0 décide le plan du jour
    ok, director_plan = _run_step(
        "Agent 0 (director)", agent0_director.decide, demo=demo
    )
    if not ok:
        _log("Run arrêté : Agent 0 a échoué.")
        return {"status": "failed", "failed_at": "agent0"}

    # Pour chaque post décidé par l'Agent 0
    posts = director_plan.get("posts", [{}])
    _log(f"Agent 0 : {director_plan.get('director_note', '')}")
    _log(f"Agent 0 : {len(posts)} post(s) planifié(s) aujourd'hui")

    # Prend le premier post pour ce run
    # (si 2 posts prévus, le scheduler relancera à 14h)
    today_post = posts[0]

    # Passe la décision à l'Agent 1
    strategy_input = {
        "domain": today_post["domain"],
        "visual_style": today_post["visual_style"],
        "format": today_post["format"],
        "angle": today_post["angle"],
        "fal_model": today_post["fal_model"],
        "prompt_style": today_post["prompt_style"],
        "cta_link": today_post["cta_link"],
    }

    ok, strategy = _run_step(
        "Agent 1 (stratégie)",
        agent1_strategy.decide_daily_topic,
        demo=demo,
        director_input=strategy_input,
    )
    if not ok:
        _log("Run arrêté : Agent 1 a échoué définitivement.")
        return {"status": "failed", "failed_at": "agent1"}

    # Le format carrousel/image simple vient de strategy_input (décision brute de l'Agent 0), PAS
    # de strategy["format"] : agent1_strategy.py écrase toujours ce champ avec un label
    # tip/hook/fact/cta dérivé de l'angle (voir ANGLE_FORMAT_LABELS), donc strategy["format"] ne
    # vaut jamais "carousel" — vérifié en lisant decide_daily_topic avant d'écrire cette branche.
    is_carousel = strategy_input.get("format") == "carousel"

    if is_carousel:
        ok, content = _run_step("Agent 2 (carrousel)", agent2_carousel.generate_carousel, strategy, demo=demo)
    else:
        ok, content = _run_step("Agent 2 (contenu)", agent2_content.create_content, strategy, demo=demo)
    if not ok:
        _log("Run arrêté : Agent 2 a échoué définitivement.")
        return {"status": "failed", "failed_at": "agent2", "strategy": strategy}

    if demo:
        _log("Mode démo : Agent 3 (publication réelle) sauté.")
        publish_results = {"skipped": "mode démo"}
    elif is_carousel:
        caption = content["ig_caption"] + "\n\n" + " ".join(f"#{h}" for h in content["ig_hashtags"])
        ok, publish_result = _run_step(
            "Agent 3 (publication carrousel)",
            agent3_publisher.publish_instagram_carousel,
            content["image_paths"],
            caption,
            domain=strategy_input.get("domain", ""),
            visual_style=strategy_input.get("visual_style", ""),
        )
        if not ok:
            _log("Agent 3 (carrousel) a échoué définitivement — Agent 4 sauté (rien à analyser).")
            return {"status": "failed", "failed_at": "agent3", "strategy": strategy, "content": content}
        publish_results = {"instagram_carousel": {"status": "success", **publish_result}}
        _log(f"  -> instagram_carousel : succès (post_id={publish_result.get('post_id')})")
    else:
        ok, publish_results = _run_step(
            "Agent 3 (publication)",
            agent3_publisher.publish_all,
            content,
            domain=strategy_input.get("domain", ""),
            visual_style=strategy_input.get("visual_style", ""),
        )
        if not ok:
            _log("Agent 3 a échoué définitivement — Agent 4 sauté (rien à analyser).")
            return {"status": "failed", "failed_at": "agent3", "strategy": strategy, "content": content}
        for channel, result in publish_results.items():
            if result.get("status") == "success":
                _log(f"  -> {channel} : succès (post_id={result.get('post_id')})")
            elif result.get("status") == "skipped":
                _log(f"  -> {channel} : sauté ({result.get('reason')})")
            else:
                _log(f"  -> {channel} : échec ({result.get('error')})")

    if demo:
        _log("Mode démo : Agent 4 (analytics réelles) sauté.")
        report = {"skipped": "mode démo"}
    else:
        publications = []
        if PUBLICATIONS_LOG_FILE.exists():
            import json

            publications = json.loads(PUBLICATIONS_LOG_FILE.read_text(encoding="utf-8")).get("publications", [])
        ok, report = _run_step("Agent 4 (analytics)", agent4_analytics.build_daily_report, publications)
        if not ok:
            _log("Agent 4 a échoué définitivement (non bloquant, publication déjà faite).")
            report = {"status": "failed"}

    _log("=== Run supervisor terminé ===")
    return {
        "status": "success",
        "strategy": strategy,
        "content": content,
        "publish_results": publish_results,
        "report": report,
    }


def _check_reachable(name: str, method: str, url: str, **kwargs) -> dict:
    """Vérifie qu'une URL répond (n'importe quel code HTTP compte comme "joignable" — un 400/401
    prouve que le serveur répond, contrairement à un timeout/DNS-error). Utilisé UNIQUEMENT par
    `run_dry_run`, jamais pour un vrai appel métier."""
    import requests

    try:
        response = requests.request(method, url, timeout=REQUEST_TIMEOUT_SECONDS, **kwargs)
        return {"name": name, "reachable": True, "http_status": response.status_code}
    except requests.exceptions.RequestException as exc:
        return {"name": name, "reachable": False, "error": str(exc)}


def run_dry_run() -> dict:
    """Vérifie (1) que toutes les variables d'environnement requises sont présentes et (2) que les
    APIs externes sont joignables — SANS jamais appeler un endpoint de génération de contenu ou de
    publication (aucun `messages.create`, aucun `/feed`, aucun `/media`, aucun `sendMessage`,
    aucune génération Pollinations). Retourne un rapport détaillé, exit code 1 si un check échoue."""
    report: dict = {"missing_env_vars": missing_env_vars(REQUIRED_ENV_VARS), "checks": []}

    report["checks"].append(
        _check_reachable("Anthropic API", "GET", "https://api.anthropic.com", headers={})
    )

    if FACEBOOK_PAGE_ID and META_PAGE_ACCESS_TOKEN:
        report["checks"].append(
            _check_reachable(
                "Meta Graph API (lecture Page)",
                "GET",
                f"{GRAPH_API_BASE}/{FACEBOOK_PAGE_ID}",
                params={"access_token": META_PAGE_ACCESS_TOKEN, "fields": "id"},
            )
        )
    else:
        report["checks"].append({"name": "Meta Graph API (lecture Page)", "reachable": False, "error": "FACEBOOK_PAGE_ID ou META_PAGE_ACCESS_TOKEN manquant"})

    if INSTAGRAM_ACCOUNT_ID and META_PAGE_ACCESS_TOKEN:
        report["checks"].append(
            _check_reachable(
                "Meta Graph API (lecture compte Instagram)",
                "GET",
                f"{GRAPH_API_BASE}/{INSTAGRAM_ACCOUNT_ID}",
                params={"access_token": META_PAGE_ACCESS_TOKEN, "fields": "id"},
            )
        )
    else:
        report["checks"].append({"name": "Meta Graph API (lecture compte Instagram)", "reachable": False, "error": "INSTAGRAM_ACCOUNT_ID ou META_PAGE_ACCESS_TOKEN manquant"})

    if TELEGRAM_API_BASE:
        report["checks"].append(
            _check_reachable("Telegram Bot API (getMe)", "GET", f"{TELEGRAM_API_BASE}/getMe")
        )
    else:
        report["checks"].append({"name": "Telegram Bot API (getMe)", "reachable": False, "error": "TELEGRAM_BOT_TOKEN manquant"})

    # Le visuel est désormais généré localement (Pillow, aucun réseau) puis hébergé sur le site
    # KORTEX lui-même (voir agent3_publisher.py::upload_image_to_kortex) — c'est donc la
    # joignabilité du site KORTEX, pas d'un service d'image externe, qui conditionne la publication
    # Instagram.
    report["checks"].append(_check_reachable("Site KORTEX (hébergement image)", "GET", KORTEX_SITE_URL))

    all_env_present = not report["missing_env_vars"]
    all_reachable = all(c.get("reachable") for c in report["checks"])
    report["status"] = "ok" if (all_env_present and all_reachable) else "failed"
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Marketing KORTEX — Agent 5 : Supervision")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Vérifie clés + joignabilité des APIs, SANS rien publier ni générer",
    )
    parser.add_argument("--demo", action="store_true", help="Run complet en mode démo (stubs, aucun appel réseau)")
    args = parser.parse_args()

    if args.dry_run:
        import json

        report = run_dry_run()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(0 if report["status"] == "ok" else 1)

    result = run_pipeline(demo=args.demo)
    if result["status"] != "success":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
