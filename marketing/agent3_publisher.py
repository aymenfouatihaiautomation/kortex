"""Marketing KORTEX — Agent 3 : Publication.

Publie le contenu de l'Agent 2 sur Facebook, Instagram et Telegram, logge chaque publication dans
`marketing/logs/publications.json`, et fournit `refresh_long_lived_token()` pour renouveler le
token Meta courte durée (~1h-2h) en token longue durée (~60 jours).

Hébergement de l'image pour Instagram : depuis qu'Agent 2 génère le visuel localement avec Pillow
(plus de Pollinations.ai), il n'y a plus d'URL publique toute faite à donner à l'API Instagram
(qui exige une URL — elle re-télécharge l'image côté serveur Meta). `upload_image_to_kortex`
héberge donc le fichier local sur le site KORTEX lui-même (POST /api/upload-image, voir
bloc4_publication/app.py::upload_marketing_image), qui le sert ensuite via GET /api/images/<nom>
sur le disque persistant Render.

Écart vs le brief initial, VÉRIFIÉ avant implémentation (voir tests directs dans la session) :
tmpfiles.org (`upload_to_tmpfiles`, implémentée ci-dessous pour rester fidèle au brief) renvoie une
URL qui sert une page HTML d'atterrissage, PAS l'image brute (confirmé par `curl -I`, y compris sur
la variante `/dl/{id}/{filename}` qui redirige vers la même page HTML) — inutilisable comme
`image_url` Instagram. Conservée en fallback documenté seulement, jamais appelée par
`publish_instagram`."""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from marketing.config import (
    ENV_FILE,
    FACEBOOK_PAGE_ID,
    GRAPH_API_BASE,
    INSTAGRAM_ACCOUNT_ID,
    KORTEX_SITE_URL,
    MARKETING_UPLOAD_TOKEN,
    META_APP_ID,
    META_APP_SECRET,
    META_PAGE_ACCESS_TOKEN,
    PUBLICATIONS_LOG_FILE,
    REQUEST_TIMEOUT_SECONDS,
    TELEGRAM_API_BASE,
    TELEGRAM_CHANNEL,
    TMPFILES_UPLOAD_URL,
    MarketingAPIError,
    append_json_list,
    http_request_with_retry,
)


def _log_publication(
    canal: str,
    statut: str,
    post_id: str | None,
    detail: str = "",
    domain: str = "",
    visual_style: str = "",
) -> None:
    """Ajoute une entrée à `marketing/logs/publications.json` — appelé pour CHAQUE canal, succès
    ou échec, jamais seulement les succès (on veut voir les échecs dans le log). `domain`/
    `visual_style` (choisis par agent0_director.py) sont inclus dans CHAQUE entrée — pas seulement
    les succès — pour qu'agent4_analytics.py::build_daily_report puisse les retrouver même si
    certains canaux ont échoué."""
    append_json_list(
        PUBLICATIONS_LOG_FILE,
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "canal": canal,
            "statut": statut,
            "post_id": post_id,
            "detail": detail,
            "domain": domain,
            "visual_style": visual_style,
        },
        "publications",
    )


def publish_facebook(message: str, domain: str = "", visual_style: str = "") -> dict:
    """`POST /{PAGE_ID}/feed` — publie un post texte sur la Page Facebook. Retourne
    `{"post_id": "..."}`. Logge le résultat (succès ou échec) avant de retourner/lever."""
    url = f"{GRAPH_API_BASE}/{FACEBOOK_PAGE_ID}/feed"
    try:
        response = http_request_with_retry(
            "POST", url, data={"message": message, "access_token": META_PAGE_ACCESS_TOKEN}
        )
        if response.status_code >= 400:
            raise MarketingAPIError(f"Facebook feed a échoué : HTTP {response.status_code} {response.text[:300]}")
        post_id = response.json().get("id")
        _log_publication("facebook", "success", post_id, domain=domain, visual_style=visual_style)
        return {"post_id": post_id}
    except MarketingAPIError as exc:
        _log_publication("facebook", "failed", None, str(exc), domain=domain, visual_style=visual_style)
        raise


def publish_instagram(caption: str, image_url: str, domain: str = "", visual_style: str = "") -> dict:
    """Flux Instagram Business en 2 étapes : `POST /{IG_ID}/media` (crée le conteneur média à
    partir de `image_url`) puis `POST /{IG_ID}/media_publish` (publie le conteneur). `image_url`
    doit servir des octets image bruts en GET — utiliser `upload_image_to_kortex()`, PAS
    `upload_to_tmpfiles()` (voir note en tête de fichier)."""
    try:
        media_url = f"{GRAPH_API_BASE}/{INSTAGRAM_ACCOUNT_ID}/media"
        media_response = http_request_with_retry(
            "POST",
            media_url,
            data={"image_url": image_url, "caption": caption, "access_token": META_PAGE_ACCESS_TOKEN},
        )
        if media_response.status_code >= 400:
            raise MarketingAPIError(
                f"Instagram media a échoué : HTTP {media_response.status_code} {media_response.text[:300]}"
            )
        creation_id = media_response.json().get("id")

        publish_url = f"{GRAPH_API_BASE}/{INSTAGRAM_ACCOUNT_ID}/media_publish"
        publish_response = http_request_with_retry(
            "POST", publish_url, data={"creation_id": creation_id, "access_token": META_PAGE_ACCESS_TOKEN}
        )
        if publish_response.status_code >= 400:
            raise MarketingAPIError(
                f"Instagram media_publish a échoué : HTTP {publish_response.status_code} "
                f"{publish_response.text[:300]}"
            )
        media_id = publish_response.json().get("id")
        _log_publication("instagram", "success", media_id, domain=domain, visual_style=visual_style)
        return {"post_id": media_id}
    except MarketingAPIError as exc:
        _log_publication("instagram", "failed", None, str(exc), domain=domain, visual_style=visual_style)
        raise


def publish_telegram(text: str, domain: str = "", visual_style: str = "") -> dict:
    """`POST /bot{TOKEN}/sendMessage` — publie un message Markdown sur le canal Telegram."""
    url = f"{TELEGRAM_API_BASE}/sendMessage"
    try:
        response = http_request_with_retry(
            "POST", url, data={"chat_id": TELEGRAM_CHANNEL, "text": text, "parse_mode": "Markdown"}
        )
        if response.status_code >= 400:
            raise MarketingAPIError(f"Telegram sendMessage a échoué : HTTP {response.status_code} {response.text[:300]}")
        message_id = response.json().get("result", {}).get("message_id")
        _log_publication(
            "telegram", "success", str(message_id) if message_id else None, domain=domain, visual_style=visual_style
        )
        return {"post_id": str(message_id) if message_id else None}
    except MarketingAPIError as exc:
        _log_publication("telegram", "failed", None, str(exc), domain=domain, visual_style=visual_style)
        raise


def publish_instagram_carousel(
    image_paths: list[str], caption: str, domain: str = "", visual_style: str = ""
) -> dict:
    """Publie un carrousel Instagram (voir agent2_carousel.py::generate_carousel, toujours 5
    slides) en 3 étapes Graph API :
    1. Héberge chaque image locale sur le site KORTEX (`upload_image_to_kortex`), puis crée un
       conteneur média par slide avec `is_carousel_item=true` (`POST /{IG_ID}/media`) — pas encore
       publié à ce stade, seulement les items individuels.
    2. Crée le conteneur carrousel parent (`media_type=CAROUSEL`, `children=<creation_id des slides>`).
    3. Publie le conteneur carrousel (`POST /{IG_ID}/media_publish`), comme pour une image simple.

    Loggue sous le canal `"instagram_carousel"` (distinct de `"instagram"`) — pas encore lu par
    agent4_analytics.py::build_daily_report, qui ne reconnaît que facebook/instagram/telegram."""
    try:
        item_ids = []
        for image_path in image_paths:
            image_url = upload_image_to_kortex(image_path)
            item_url = f"{GRAPH_API_BASE}/{INSTAGRAM_ACCOUNT_ID}/media"
            item_response = http_request_with_retry(
                "POST",
                item_url,
                data={"image_url": image_url, "is_carousel_item": "true", "access_token": META_PAGE_ACCESS_TOKEN},
            )
            if item_response.status_code >= 400:
                raise MarketingAPIError(
                    f"Instagram carousel item a échoué : HTTP {item_response.status_code} {item_response.text[:300]}"
                )
            item_ids.append(item_response.json()["id"])

        carousel_url = f"{GRAPH_API_BASE}/{INSTAGRAM_ACCOUNT_ID}/media"
        carousel_response = http_request_with_retry(
            "POST",
            carousel_url,
            data={
                "media_type": "CAROUSEL",
                "children": ",".join(item_ids),
                "caption": caption,
                "access_token": META_PAGE_ACCESS_TOKEN,
            },
        )
        if carousel_response.status_code >= 400:
            raise MarketingAPIError(
                f"Instagram carousel container a échoué : HTTP {carousel_response.status_code} "
                f"{carousel_response.text[:300]}"
            )
        creation_id = carousel_response.json()["id"]

        publish_url = f"{GRAPH_API_BASE}/{INSTAGRAM_ACCOUNT_ID}/media_publish"
        publish_response = http_request_with_retry(
            "POST", publish_url, data={"creation_id": creation_id, "access_token": META_PAGE_ACCESS_TOKEN}
        )
        if publish_response.status_code >= 400:
            raise MarketingAPIError(
                f"Instagram carousel media_publish a échoué : HTTP {publish_response.status_code} "
                f"{publish_response.text[:300]}"
            )
        media_id = publish_response.json().get("id")
        _log_publication("instagram_carousel", "success", media_id, domain=domain, visual_style=visual_style)
        return {"post_id": media_id}
    except MarketingAPIError as exc:
        _log_publication("instagram_carousel", "failed", None, str(exc), domain=domain, visual_style=visual_style)
        raise


def upload_to_tmpfiles(image_path: str) -> str:
    """`POST https://tmpfiles.org/api/v1/upload` — implémentée telle que spécifiée dans le brief,
    pour disponibilité/complétude API. ATTENTION (vérifié directement) : l'URL renvoyée sert une
    page HTML d'atterrissage, pas l'image brute — NE PAS utiliser cette fonction comme source de
    `image_url` pour `publish_instagram` (voir note en tête de fichier). Conservée en fallback
    documenté seulement."""
    with open(image_path, "rb") as f:
        response = http_request_with_retry("POST", TMPFILES_UPLOAD_URL, files={"file": f})
    if response.status_code >= 400:
        raise MarketingAPIError(f"tmpfiles.org upload a échoué : HTTP {response.status_code} {response.text[:300]}")
    return response.json()["data"]["url"]


def upload_image_to_kortex(image_path: str) -> str:
    """Envoie le visuel PNG local (généré par agent2_content.py::generate_image_card) vers
    `POST {KORTEX_SITE_URL}/api/upload-image` sur le site KORTEX lui-même — voir
    bloc4_publication/app.py::upload_marketing_image, qui le sauvegarde sur le disque persistant
    Render et le sert via `GET /api/images/<nom>`. Authentifié par MARKETING_UPLOAD_TOKEN (en-tête
    Authorization: Bearer ...) — cette valeur doit être IDENTIQUE des deux côtés (marketing/.env et
    le .env du site KORTEX, deux déploiements séparés). Retourne l'URL publique de l'image."""
    if not MARKETING_UPLOAD_TOKEN:
        raise MarketingAPIError("MARKETING_UPLOAD_TOKEN manquant dans marketing/.env")

    path = Path(image_path)
    with path.open("rb") as f:
        response = http_request_with_retry(
            "POST",
            f"{KORTEX_SITE_URL}/api/upload-image",
            files={"file": (path.name, f, "image/png")},
            headers={"Authorization": f"Bearer {MARKETING_UPLOAD_TOKEN}"},
        )
    if response.status_code >= 400:
        raise MarketingAPIError(f"Upload image KORTEX a échoué : HTTP {response.status_code} {response.text[:300]}")
    return response.json()["url"]


def refresh_long_lived_token() -> dict:
    """`GET /oauth/access_token?grant_type=fb_exchange_token` — échange le token Page courte durée
    contre un token longue durée (~60 jours), et l'écrit dans `marketing/.env`
    (clé `META_PAGE_ACCESS_TOKEN`). Endpoint/paramètres vérifiés contre la doc officielle Meta
    (developers.facebook.com/docs/facebook-login/guides/access-tokens/get-long-lived)."""
    url = f"{GRAPH_API_BASE}/oauth/access_token"
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": META_APP_ID,
        "client_secret": META_APP_SECRET,
        "fb_exchange_token": META_PAGE_ACCESS_TOKEN,
    }
    response = http_request_with_retry("GET", url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    if response.status_code >= 400:
        raise MarketingAPIError(f"Refresh token Meta a échoué : HTTP {response.status_code} {response.text[:300]}")

    payload = response.json()
    new_token = payload["access_token"]
    _write_env_var("META_PAGE_ACCESS_TOKEN", new_token)
    return payload


def _write_env_var(key: str, value: str) -> None:
    """Met à jour (ou ajoute) une variable dans `marketing/.env` sans toucher aux autres lignes —
    utilisé uniquement par `refresh_long_lived_token()` pour persister le nouveau token."""
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    prefix = f"{key}="
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = f"{prefix}{value}"
            break
    else:
        lines.append(f"{prefix}{value}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def publish_all(content: dict, domain: str = "", visual_style: str = "") -> dict:
    """Publie sur les 3 canaux INDÉPENDAMMENT — l'échec d'un canal ne doit jamais empêcher les
    deux autres d'être tentés (Facebook/Instagram/Telegram n'ont aucune dépendance entre eux côté
    API). Chaque canal est isolé dans son propre try/except ; `publish_facebook`/
    `publish_instagram`/`publish_telegram` loggent déjà l'échec dans publications.json avant de
    lever, ce bloc se contente de convertir cette exception en résultat structuré au lieu de la
    laisser remonter et couper les canaux suivants.

    `domain`/`visual_style` (choisis par agent0_director.py, transmis par agent5_supervisor.py)
    sont propagés à chaque canal pour être loggués dans publications.json — c'est ce
    qu'agent4_analytics.py::build_daily_report lit ensuite pour que l'historique de l'Agent 0 soit
    réellement exploitable (voir _build_context_summary dans agent0_director.py).

    `content["image_path"]` étant un chemin LOCAL (voir agent2_content.py::generate_image_card),
    on l'héberge d'abord sur le site KORTEX via `upload_image_to_kortex()` pour obtenir une URL
    publique avant d'appeler `publish_instagram()` — l'API Instagram exige une URL, jamais un
    fichier local.

    Retourne toujours les 3 clés `facebook`/`instagram`/`telegram`, chacune
    `{"status": "success", "post_id": ...}`, `{"status": "error", "error": "..."}` ou (Instagram
    uniquement, si aucune image n'a été générée) `{"status": "skipped", "reason": "..."}`."""
    results: dict = {}

    try:
        results["facebook"] = {
            "status": "success",
            **publish_facebook(content["fb_text"], domain=domain, visual_style=visual_style),
        }
    except Exception as exc:
        results["facebook"] = {"status": "error", "error": str(exc)}

    try:
        if content.get("image_path"):
            image_url = upload_image_to_kortex(content["image_path"])
            caption = content["ig_caption"] + "\n\n" + " ".join(f"#{h}" for h in content["ig_hashtags"])
            results["instagram"] = {
                "status": "success",
                **publish_instagram(caption, image_url, domain=domain, visual_style=visual_style),
            }
        else:
            results["instagram"] = {"status": "skipped", "reason": "aucune image locale disponible"}
    except Exception as exc:
        results["instagram"] = {"status": "error", "error": str(exc)}

    try:
        results["telegram"] = {
            "status": "success",
            **publish_telegram(content["tg_text"], domain=domain, visual_style=visual_style),
        }
    except Exception as exc:
        results["telegram"] = {"status": "error", "error": str(exc)}

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Marketing KORTEX — Agent 3 : Publication")
    parser.add_argument("--refresh-token", action="store_true", help="Renouvelle le token Meta longue durée")
    parser.add_argument("--content-json", type=str, default="", help="JSON du contenu de l'Agent 2 à publier")
    args = parser.parse_args()

    if args.refresh_token:
        payload = refresh_long_lived_token()
        print(json.dumps({"expires_in": payload.get("expires_in")}, ensure_ascii=False, indent=2))
        return

    if not args.content_json:
        raise SystemExit("--content-json est requis (ou utilise --refresh-token)")

    content = json.loads(args.content_json)
    results = publish_all(content)
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
