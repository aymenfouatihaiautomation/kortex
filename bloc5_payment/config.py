"""Configuration Bloc 5 (Paddle). Bascule automatiquement en mode mock si les identifiants réels
sont absents — ne bloque jamais le développement en attendant la vraie clé (même logique que
ElevenLabs au Bloc 3 : le mode réel est signalé explicitement, jamais silencieux)."""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

PADDLE_API_KEY = os.environ.get("PADDLE_API_KEY")
# .strip() : un espace/retour-à-la-ligne parasite de copier-coller (fin de valeur collée dans
# Render, .env avec \n final, etc.) produit un HMAC systématiquement différent malgré une clé
# visuellement correcte — bug réel diagnostiqué (403 webhook malgré un secret "correct").
PADDLE_WEBHOOK_SECRET = os.environ.get("PADDLE_WEBHOOK_SECRET", "").strip()

# PADDLE_CLIENT_TOKEN : jeton "client-side" (Paddle dashboard -> Developer Tools ->
# Authentication) — PAS un secret au sens API key (conçu par Paddle pour être exposé dans le
# HTML/JS servi au navigateur), mais gardé en variable d'env comme le reste : spécifique au
# compte, jamais en dur dans le code. Sert UNIQUEMENT à `Paddle.Initialize` côté client pour
# ouvrir l'overlay Paddle.js — n'autorise aucun appel API serveur (ça reste PADDLE_API_KEY).
PADDLE_CLIENT_TOKEN = os.environ.get("PADDLE_CLIENT_TOKEN")

# PADDLE_PRICE_ID : fallback statique utilisé UNIQUEMENT si le pricing agent (`pricing_agent/`) n'a
# pas encore de prix actif enregistré (avant que la Phase 1 ait été appliquée). Une fois
# `launch_pricing.apply_launch_price()` exécuté, c'est `pricing_state.json` qui fait foi.
PADDLE_PRICE_ID = os.environ.get("PADDLE_PRICE_ID")

# PADDLE_PRODUCT_ID : requis pour créer un nouveau Price Paddle (les Price sont immuables une fois
# créés côté Paddle Billing — changer le prix crée un NOUVEAU Price rattaché au même Product, ce
# n'est jamais une modification en place). Utilisé par `paddle_client.sync_price_to_paddle`.
PADDLE_PRODUCT_ID = os.environ.get("PADDLE_PRODUCT_ID")

# Sandbox par défaut : Paddle sépare complètement compte test (sandbox-api.paddle.com) et compte
# réel (api.paddle.com), avec des clés/identifiants distincts — pas un simple flag sur la même API.
PADDLE_API_BASE = os.environ.get("PADDLE_API_BASE", "https://sandbox-api.paddle.com")


def is_mock_mode() -> bool:
    """Mode mock = pas de compte Paddle réel (clé API absente). Indépendant du prix actif — le
    pricing agent gère séparément quel price_id est utilisé une fois un compte réel disponible."""
    return not PADDLE_API_KEY


def paddle_overlay_enabled() -> bool:
    """L'overlay Paddle.js (checkout côté client, requis par Paddle Billing — voir
    bloc4_publication/templates/landing.html) n'est proposé QUE si `PADDLE_CLIENT_TOKEN` est
    configuré. Volontairement DÉCOUPLÉ de `is_mock_mode()` (qui teste `PADDLE_API_KEY`, une
    clé différente pour un usage différent — appels API serveur, pas l'overlay) : même
    principe que `accounts/oauth.py::google_oauth_enabled` — pas de bouton/script sans sa
    configuration complète, jamais une moitié de configuration silencieusement cassée."""
    return bool(PADDLE_CLIENT_TOKEN)
