"""Configuration du pricing agent — Phase 1 (prix de lancement) + Phase 2 (ajustement à la demande).

Les constantes business ci-dessous sont des décisions produit explicites de l'utilisateur, PAS des
valeurs générées par un LLM (même principe que `LEVEL`/`PREREQUISITES` au Bloc 1 ou `RUNNING_EXAMPLE`
au Bloc 2) : la recherche web (`research.py`) fournit le contexte marché et le raisonnement, jamais
le chiffre final.
"""

import os
from pathlib import Path

from config import DATA_DIR

# Phase 1 — prix de lancement. Décision initiale : $5 (floor Paddle strict). Reconsidéré par
# l'utilisateur le 2026-07-30 après la recherche marché réelle (celle-ci suggérait $10-30, compte
# tenu du catalogue vidéo incomplet à 1/7 chapitres) — $15 retenu : nettement meilleure marge que $5
# (frais Paddle ≈8.3% du prix contre 15%) tout en restant prudent tant que la vidéo n'est pas complète.
LAUNCH_PRICE_USD = 15.00
PADDLE_FEE_PCT = 0.05
PADDLE_FEE_FIXED_USD = 0.50

# Phase 2 — ajustement selon la demande.
DEMAND_INCREASE_PCT = 0.15
SALES_THRESHOLD_PER_WINDOW = 10  # exemple donné par l'utilisateur ("ex. par semaine"), ajustable
REVIEW_WINDOW_DAYS = 7
PRICE_CEILING_USD = 79.00  # plafond dur — jamais dépassé sans nouvelle validation explicite

# LMS_STATE_DIR : même mécanisme que bloc4_publication/config.py — en local, reste dans data/ ; en
# déploiement (Render), pointé vers le disque persistant monté, pour ne jamais perdre
# pricing_state.json/sales_log.json (prix actif, historique des ventes) à chaque redéploiement.


def _resolve_lms_state_dir() -> Path:
    return Path(os.environ.get("LMS_STATE_DIR", DATA_DIR))


LMS_STATE_DIR = _resolve_lms_state_dir()
PRICING_DIR = LMS_STATE_DIR / "pricing"
PRICING_DIR.mkdir(parents=True, exist_ok=True)
PRICING_STATE_FILE = PRICING_DIR / "pricing_state.json"
SALES_LOG_FILE = PRICING_DIR / "sales_log.json"
