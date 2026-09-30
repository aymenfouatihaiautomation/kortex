"""Pipeline — Publication automatique après feu vert (`data/<slug>/READY_TO_PUBLISH`).

Enchaîne : création du produit + prix Paddle (API Paddle réelle) -> copie des fichiers du cours à
l'emplacement que le LMS peut servir -> mise à jour de l'index `data/published_courses.json` ->
redéploi Render (optionnel, dégrade proprement si non configuré).

Ne touche à AUCUN code de la plateforme LMS (`bloc4_publication`, `bloc5_payment`) : ce module
prépare les données/fichiers/API externes, il ne branche pas lui-même le multi-cours dans
`bloc4_publication/app.py` (voir le rapport d'inspection séparé sur ce point — changement de
plateforme distinct, hors périmètre de ce module)."""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from config import DATA_DIR

PADDLE_API_BASE = os.environ.get("PADDLE_API_BASE", "https://api.paddle.com")
RENDER_API_BASE = "https://api.render.com/v1"

PUBLISHED_COURSES_FILE = DATA_DIR / "published_courses.json"


class AutoPublishError(RuntimeError):
    """Levée quand une étape de publication échoue — jamais avalée silencieusement : créer un
    produit/prix Paddle ou publier un cours sont des actions réelles, une erreur doit remonter."""


def _check_ready_to_publish(slug: str) -> dict:
    path = DATA_DIR / slug / "READY_TO_PUBLISH"
    if not path.exists():
        raise AutoPublishError(f"data/{slug}/READY_TO_PUBLISH absent - publication refusee (cours non valide).")
    return json.loads(path.read_text(encoding="utf-8"))


def _paddle_api_key() -> str:
    key = os.environ.get("PADDLE_API_KEY")
    if not key:
        raise AutoPublishError("PADDLE_API_KEY manquant - impossible de creer le produit/prix Paddle.")
    return key


def create_paddle_product_and_price(title: str, price_usd: float) -> dict:
    """Crée un Product puis un Price Paddle (Billing v2, API réelle — jamais mock ici, contrairement
    à `bloc5_payment.paddle_client`, qui gère un mode démo pour le développement local ; ce module
    n'existe QUE pour le run réel de publication). Retourne `{"product_id", "price_id"}`. Lève
    `AutoPublishError` sur tout échec HTTP — jamais un price_id invalide silencieusement utilisé."""
    api_key = _paddle_api_key()
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    product_resp = requests.post(
        f"{PADDLE_API_BASE}/products",
        headers=headers,
        # "type" (catalogue Paddle "custom"/"standard", pas un type de contenu) — "digital" n'est pas
        # une valeur valide de l'API Paddle réelle (confirmé par un 400 en production, 2026-08-30) ;
        # "standard" est le bon choix pour un produit catalogue public à prix fixe (pas de tarif
        # négocié par client, cas de "custom").
        json={"name": title, "type": "standard", "tax_category": "standard"},
        timeout=30,
    )
    if product_resp.status_code >= 300:
        raise AutoPublishError(
            f"Echec creation produit Paddle ({product_resp.status_code}) : {product_resp.text[:500]}"
        )
    product_id = product_resp.json()["data"]["id"]

    price_resp = requests.post(
        f"{PADDLE_API_BASE}/prices",
        headers=headers,
        json={
            "product_id": product_id,
            "description": f"AI Edu Platform - {title}",
            "unit_price": {"amount": str(round(price_usd * 100)), "currency_code": "USD"},
        },
        timeout=30,
    )
    if price_resp.status_code >= 300:
        raise AutoPublishError(
            f"Echec creation prix Paddle ({price_resp.status_code}) : {price_resp.text[:500]}"
        )
    price_id = price_resp.json()["data"]["id"]

    return {"product_id": product_id, "price_id": price_id}


def save_paddle_info(slug: str, product_id: str, price_id: str) -> Path:
    path = DATA_DIR / slug / "paddle_info.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "product_id": product_id,
                "price_id": price_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def publish_course_files(slug: str) -> dict:
    """Copie `curriculum.json`/`final_content.json` (écrits par `run_pipeline.py` sous
    `data/<slug>/pipeline/`) vers `data/<slug>/curriculum.json` et `data/<slug>/content_final.json`
    — un emplacement stable, hors du sous-dossier `pipeline/` (artefacts intermédiaires), que
    `bloc4_publication.content_loader.load_course(curriculum_file=..., content_file=...)` peut
    lire directement (même mécanisme que `run_pipeline._stage_bloc7`, qui pointe déjà Bloc 7 vers
    des chemins explicites plutôt que les défauts figés de `bloc4_publication/config.py`)."""
    pipeline_dir = DATA_DIR / slug / "pipeline"
    curriculum_src = pipeline_dir / "curriculum.json"
    content_src = pipeline_dir / "final_content.json"
    if not curriculum_src.exists() or not content_src.exists():
        raise AutoPublishError(
            f"Fichiers de cours introuvables pour {slug!r} sous {pipeline_dir} - pipeline pas termine ?"
        )

    course_dir = DATA_DIR / slug
    curriculum_dst = course_dir / "curriculum.json"
    content_dst = course_dir / "content_final.json"
    shutil.copy2(curriculum_src, curriculum_dst)
    shutil.copy2(content_src, content_dst)
    return {"curriculum_file": curriculum_dst, "content_file": content_dst}


def load_published_courses() -> list[dict]:
    if not PUBLISHED_COURSES_FILE.exists():
        return []
    return json.loads(PUBLISHED_COURSES_FILE.read_text(encoding="utf-8")).get("courses", [])


def add_published_course(entry: dict) -> None:
    """Ajoute (ou remplace, si ce slug est déjà publié) une entrée dans l'index. Ce fichier est LU
    par le LMS pour le catalogue multi-cours — voir le rapport d'inspection séparé sur le point 4
    (le LMS ne le fait pas encore aujourd'hui, changement de plateforme distinct)."""
    courses = [c for c in load_published_courses() if c.get("slug") != entry.get("slug")]
    courses.append(entry)
    PUBLISHED_COURSES_FILE.parent.mkdir(parents=True, exist_ok=True)
    PUBLISHED_COURSES_FILE.write_text(
        json.dumps({"courses": courses}, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def trigger_render_redeploy() -> dict | None:
    """Déclenche un redéploi Render si `RENDER_API_KEY`/`RENDER_SERVICE_ID` sont définis — dégrade
    proprement (retourne `None`, log) si absents, JAMAIS une exception : le redéploi est un bonus,
    pas une condition de succès de la publication (le cours reste publié dans l'index même sans
    redéploiement immédiat — le prochain déploiement naturel le servira)."""
    api_key = os.environ.get("RENDER_API_KEY")
    service_id = os.environ.get("RENDER_SERVICE_ID")
    if not api_key or not service_id:
        print("[auto_publish] RENDER_API_KEY/RENDER_SERVICE_ID absent - redeploi Render ignore.")
        return None

    response = requests.post(
        f"{RENDER_API_BASE}/services/{service_id}/deploys",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={},
        timeout=30,
    )
    if response.status_code >= 300:
        print(f"[auto_publish] Echec declenchement redeploi Render ({response.status_code}) : {response.text[:300]}")
        return None
    return response.json()


def auto_publish(slug: str, title: str, domain: str, price_usd: float | None = None) -> dict:
    """Enchaîne création Paddle -> copie fichiers -> mise à jour de l'index -> redéploi Render.
    Vérifie elle-même `data/<slug>/READY_TO_PUBLISH` (refuse de publier un cours non validé, même
    appelée directement hors du flux normal `scheduler.py`/`validate.py`) — le prix utilisé est
    celui de ce marqueur si `price_usd` n'est pas fourni explicitement (une seule source de vérité
    pour le prix validé, pas un second paramètre qui pourrait diverger)."""
    marker = _check_ready_to_publish(slug)
    if price_usd is None:
        price_usd = marker.get("price_usd")
    if price_usd is None:
        raise AutoPublishError(f"Aucun prix disponible pour {slug!r} (ni parametre, ni READY_TO_PUBLISH).")

    paddle_info = create_paddle_product_and_price(title, price_usd)
    paddle_info_path = save_paddle_info(slug, paddle_info["product_id"], paddle_info["price_id"])

    files = publish_course_files(slug)

    entry = {
        "slug": slug,
        "title": title,
        "domain": domain,
        # "paddle_price_id" (pas "price_id") : nom attendu par content_loader.load_published_courses
        # et par le catalogue de bloc4_publication/app.py.
        "paddle_price_id": paddle_info["price_id"],
        "price_usd": price_usd,
        # Chemins relatifs (pas str(files[...]), qui donnerait un chemin Windows absolu en local,
        # invalide une fois lu par _load_json() sur Render/Linux) — le cwd du process (gunicorn
        # comme les scripts locaux) est toujours la racine du dépôt, d'où "data/<slug>/..." fiable
        # dans les deux environnements.
        "curriculum_file": f"data/{slug}/curriculum.json",
        "content_file": f"data/{slug}/content_final.json",
        "published_at": datetime.now(timezone.utc).isoformat(),
    }
    add_published_course(entry)

    render_result = trigger_render_redeploy()

    return {
        "slug": slug,
        "paddle": paddle_info,
        "paddle_info_path": str(paddle_info_path),
        "published_courses_file": str(PUBLISHED_COURSES_FILE),
        "render_deploy_triggered": render_result is not None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline — Publication automatique après feu vert")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--price", type=float, default=None)
    args = parser.parse_args()

    try:
        result = auto_publish(args.slug, args.title, args.domain, price_usd=args.price)
    except AutoPublishError as exc:
        print(f"Erreur : {exc}")
        raise SystemExit(1) from exc

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
