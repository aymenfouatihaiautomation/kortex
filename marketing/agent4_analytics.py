"""Marketing KORTEX — Agent 4 : Analytics.

Récupère les statistiques des publications du jour sur les 3 canaux, consolide dans
`marketing/analytics/daily_report.json`, calcule le taux d'engagement / meilleur contenu / meilleur
canal, et met à jour l'historique `marketing/strategy/performance_history.json`."""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from marketing.config import (
    DAILY_REPORT_FILE,
    GRAPH_API_BASE,
    PERFORMANCE_HISTORY_FILE,
    TELEGRAM_API_BASE,
    MarketingAPIError,
    append_json_list,
    http_request_with_retry,
)


def get_facebook_insights(post_id: str) -> dict:
    """`GET /{POST_ID}/insights?metric=post_impressions,post_impressions_unique,post_clicks` —
    retourne `{impressions, reach, clicks}`. Métriques renommées ici pour homogénéité avec
    Instagram (le brief demandait `impressions,reach,clicks`, noms internes Graph API réels
    utilisés dans la requête)."""
    from marketing.config import META_PAGE_ACCESS_TOKEN

    url = f"{GRAPH_API_BASE}/{post_id}/insights"
    params = {
        "metric": "post_impressions,post_impressions_unique,post_clicks",
        "access_token": META_PAGE_ACCESS_TOKEN,
    }
    response = http_request_with_retry("GET", url, params=params)
    if response.status_code >= 400:
        raise MarketingAPIError(f"Facebook insights a échoué : HTTP {response.status_code} {response.text[:300]}")
    values = {item["name"]: item["values"][0]["value"] for item in response.json().get("data", [])}
    return {
        "impressions": values.get("post_impressions", 0),
        "reach": values.get("post_impressions_unique", 0),
        "clicks": values.get("post_clicks", 0),
    }


def get_instagram_insights(media_id: str) -> dict:
    """`GET /{MEDIA_ID}/insights?metric=impressions,reach,likes` — retourne
    `{impressions, reach, likes}`."""
    from marketing.config import META_PAGE_ACCESS_TOKEN

    url = f"{GRAPH_API_BASE}/{media_id}/insights"
    params = {"metric": "impressions,reach,likes", "access_token": META_PAGE_ACCESS_TOKEN}
    response = http_request_with_retry("GET", url, params=params)
    if response.status_code >= 400:
        raise MarketingAPIError(f"Instagram insights a échoué : HTTP {response.status_code} {response.text[:300]}")
    values = {item["name"]: item["values"][0]["value"] for item in response.json().get("data", [])}
    return {
        "impressions": values.get("impressions", 0),
        "reach": values.get("reach", 0),
        "likes": values.get("likes", 0),
    }


def get_telegram_stats() -> dict:
    """`GET /getChat` — le Bot API n'expose pas de stats de vues par message, seulement des
    infos sur le canal (dont `member_count` via un appel séparé `getChatMemberCount`) — c'est la
    limite documentée de l'API pour un canal, pas une omission de cette implémentation."""
    from marketing.config import TELEGRAM_CHANNEL

    chat_response = http_request_with_retry("GET", f"{TELEGRAM_API_BASE}/getChat", params={"chat_id": TELEGRAM_CHANNEL})
    if chat_response.status_code >= 400:
        raise MarketingAPIError(f"Telegram getChat a échoué : HTTP {chat_response.status_code} {chat_response.text[:300]}")

    count_response = http_request_with_retry(
        "GET", f"{TELEGRAM_API_BASE}/getChatMemberCount", params={"chat_id": TELEGRAM_CHANNEL}
    )
    member_count = count_response.json().get("result", 0) if count_response.status_code < 400 else 0
    return {"member_count": member_count}


def _engagement_rate(stats: dict) -> float:
    """(likes/clicks + reach) / impressions, en % — 0 si impressions=0 (évite une division par
    zéro plutôt que de lever une exception pour un canal qui n'a pas encore d'impressions)."""
    impressions = stats.get("impressions", 0)
    if not impressions:
        return 0.0
    interactions = stats.get("clicks", 0) + stats.get("likes", 0)
    return round((interactions + stats.get("reach", 0)) / impressions * 100, 2)


def build_daily_report(publications: list[dict]) -> dict:
    """Consolide les stats des publications réussies du jour (voir
    `marketing/logs/publications.json`) en un rapport `{date, channels: {...}, best_channel,
    best_content}`. `publications` : liste d'entrées `{canal, statut, post_id}` du log du jour."""
    today = datetime.now(timezone.utc).date().isoformat()
    publications = [
        p for p in publications
        if p.get("timestamp", "").startswith(today)
    ]

    channels: dict[str, dict] = {}
    for pub in publications:
        if pub.get("statut") != "success" or not pub.get("post_id"):
            continue
        canal, post_id = pub["canal"], pub["post_id"]
        try:
            if canal == "facebook":
                stats = get_facebook_insights(post_id)
            elif canal in ("instagram", "instagram_carousel"):
                # Un carrousel publié est un media Instagram comme un autre côté Graph API — même
                # endpoint d'insights, même structure de réponse (voir
                # agent3_publisher.py::publish_instagram_carousel, qui loggue sous ce canal distinct
                # pour la traçabilité, sans que ça change la façon de lire ses stats).
                stats = get_instagram_insights(post_id)
            elif canal == "telegram":
                stats = get_telegram_stats()
            else:
                continue
        except MarketingAPIError as exc:
            stats = {"error": str(exc)}
        stats["engagement_rate"] = _engagement_rate(stats) if "error" not in stats else 0.0
        channels[canal] = stats

    # visual_style du jour : pris sur la première publication du jour qui en a un (choisi par
    # agent0_director.py, loggué par agent3_publisher.py::_log_publication) — utilisé par
    # agent0_director.py::_build_context_summary pour calculer l'engagement moyen par style.
    visual_style = next((p.get("visual_style") for p in publications if p.get("visual_style")), None)

    best_channel = max(channels, key=lambda c: channels[c].get("engagement_rate", 0.0), default=None)
    report = {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "channels": channels,
        "best_channel": best_channel,
        "visual_style": visual_style,
    }
    DAILY_REPORT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    append_json_list(PERFORMANCE_HISTORY_FILE, report, "history")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Marketing KORTEX — Agent 4 : Analytics")
    parser.add_argument(
        "--publications-json",
        type=str,
        default="",
        help="JSON liste des publications du jour (défaut : lit marketing/logs/publications.json en entier)",
    )
    args = parser.parse_args()

    if args.publications_json:
        publications = json.loads(args.publications_json)
    else:
        from marketing.config import PUBLICATIONS_LOG_FILE

        if not PUBLICATIONS_LOG_FILE.exists():
            raise SystemExit("Aucune publication trouvée dans marketing/logs/publications.json")
        publications = json.loads(PUBLICATIONS_LOG_FILE.read_text(encoding="utf-8")).get("publications", [])

    report = build_daily_report(publications)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
