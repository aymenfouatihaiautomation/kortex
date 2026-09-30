"""Configuration partagée pour le Bloc 4 (publication LMS + landing page)."""

import os
from pathlib import Path

from dotenv import load_dotenv

from config import DATA_DIR

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_CURRICULUM_FILE = DATA_DIR / "bloc1_curriculum_20260726_122738.json"
DEFAULT_CONTENT_FILE = DATA_DIR / "bloc2_content_final.json"

# Choix explicite (2026-07-30) : chapter_1.mp4 (pilote v1), pas chapter_1_v2_preview.mp4.
# Le v2 preview a une narration/animation plus riche mais un timing volontairement APPROXIMATIF
# (documenté comme tel dans docs/BLOC3_VIDEO_PRODUCTION.md) — inadapté à un client final qui
# verrait des surlignages désynchronisés comme un bug. chapter_1.mp4 a une synchro exacte.
CHAPTER_1_VIDEO_FILE = DATA_DIR / "bloc3_video" / "chapter_1.mp4"

# LMS_STATE_DIR : en local, absent -> reste dans data/ (versionné avec le reste du projet). En
# déploiement (Render), pointé vers le disque persistant monté (ex. /var/data) — nécessaire car le
# système de fichiers d'un service Render est éphémère : sans ce disque, access_grants.json (accès
# payants accordés) serait perdu à chaque redéploiement/redémarrage. Voir docs/DEPLOYMENT.md.


def _resolve_lms_state_dir() -> Path:
    return Path(os.environ.get("LMS_STATE_DIR", DATA_DIR))


LMS_STATE_DIR = _resolve_lms_state_dir()
LMS_DATA_DIR = LMS_STATE_DIR / "bloc4_lms"
LMS_DATA_DIR.mkdir(parents=True, exist_ok=True)
ACCESS_STORE_FILE = LMS_DATA_DIR / "access_grants.json"

# MARKETING_IMAGES_DIR : visuels générés par marketing/agent2_content.py (voir
# marketing/agent3_publisher.py::upload_image_to_kortex), reçus via POST /api/upload-image et
# servis publiquement via GET /api/images/<filename> (app.py) — pour qu'Instagram puisse les
# télécharger, l'API Graph exige une URL publique, pas un fichier local. Réutilise LMS_STATE_DIR
# (même raison que LMS_DATA_DIR ci-dessus : disque persistant Render, sinon perdu à chaque
# redéploiement).
MARKETING_IMAGES_DIR = LMS_STATE_DIR / "marketing_images"
MARKETING_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# Authentifie POST /api/upload-image (voir app.py::upload_marketing_image) — DOIT avoir exactement
# la même valeur que MARKETING_UPLOAD_TOKEN dans marketing/.env (système marketing autonome,
# dépôt/processus séparé). Absent par défaut : la route refuse alors toute requête (fail-closed),
# jamais un accès public en clair par défaut.
MARKETING_UPLOAD_TOKEN = os.environ.get("MARKETING_UPLOAD_TOKEN", "")

# Le prix affiché n'est plus une constante ici : il est géré par `pricing_agent` (Phase 1 = prix de
# lancement, Phase 2 = ajustement à la demande) et lu dynamiquement via
# `pricing_agent.pricing_state.get_current_price_usd()` — toujours en dollars, cohérent avec Paddle.


def _resolve_flask_secret_key() -> str:
    key = os.environ.get("FLASK_SECRET_KEY")
    if key:
        return key
    if os.environ.get("RENDER"):
        # RENDER est positionnée automatiquement par Render sur tout service qui y tourne — sert
        # ici à détecter une vraie mise en ligne et à refuser de démarrer avec la clé de dev par
        # défaut (bien connue, donc un vrai risque de sécurité — falsification de session).
        raise RuntimeError(
            "FLASK_SECRET_KEY manquant en production (variable RENDER détectée) — défini une "
            "vraie valeur secrète dans les variables d'environnement Render avant de déployer."
        )
    return "dev-secret-key-not-for-production"


FLASK_SECRET_KEY = _resolve_flask_secret_key()

# Adresse affichée sur les pages légales (CGU/confidentialité/remboursement). Placeholder par
# défaut — à remplacer par une vraie adresse de contact (ou une boîte qui redirige vers la vraie)
# avant mise en ligne réelle.
LEGAL_CONTACT_EMAIL = os.environ.get("LEGAL_CONTACT_EMAIL", "contact@aymen-automation.site")
