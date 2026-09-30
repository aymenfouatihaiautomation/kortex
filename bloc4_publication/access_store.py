"""Bloc 4 — Octroi d'accès simple au LMS après paiement confirmé (Bloc 5).

Registre "qui a payé QUEL cours" — indépendant du système de comptes (`accounts/`, connexion par
mot de passe) : `has_access(email, slug)` répond uniquement à "cet email a-t-il acheté CE cours ?",
jamais "cet email a-t-il un compte/un mot de passe ?". C'est ce découplage qui permet la
réconciliation Paddle : que l'email vienne d'un jeton d'accès (`/access/<token>`, achat direct sans
compte) ou d'une connexion par mot de passe (`accounts/routes.py`), le même
`has_access(session["email"], slug)` fait foi pour déverrouiller le contenu payant de CE cours
précis (voir bloc4_publication/app.py et bloc6_chatbot/course_routes.py).

Multi-cours (Changement 4, Étape A) : `grant_access`/`has_access` exigent désormais un `slug` —
un achat du cours A ne doit JAMAIS donner accès au cours B. FALLBACK CRITIQUE pour la
compatibilité : les grants enregistrés AVANT ce changement (access_grants.json existant, un seul
cours à l'époque) n'ont pas de champ "slug" — `has_access`/`resolve_token` traitent une entrée
sans "slug" comme un achat de `SLUG_COURS_1`, JAMAIS comme "aucun cours" : aucun client déjà
payant ne doit perdre l'accès à cause de cette migration de schéma.

Emails toujours normalisés (strip + lower, voir `_normalize_email`) avant stockage ET avant
comparaison : Paddle et l'utilisateur au clavier peuvent taper une casse différente pour le même
email, la correspondance doit rester insensible à la casse.

Stockage JSON simple (pas de base de données)."""

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path

from bloc4_publication import config as _config

# Slug du cours 1 — seul cours existant avant le Changement 4 (multi-cours). Fallback pour les
# grants enregistrés avant l'ajout du champ "slug" (voir has_access/resolve_token) : sans ce
# fallback, un client qui a payé avant ce changement perdrait l'accès dès que has_access
# commencerait à filtrer par slug.
SLUG_COURS_1 = "agents-ia-en-production-gerer-les-erreurs-evaluer-et-deployer-sans-risque"


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _load(store_path: Path) -> dict:
    if not store_path.exists():
        return {}
    with store_path.open(encoding="utf-8") as f:
        return json.load(f)


def _save(store_path: Path, data: dict) -> None:
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _entry_slug(entry: dict) -> str:
    """Slug effectif d'un grant enregistré — `SLUG_COURS_1` si absent (grant antérieur au
    Changement 4, voir docstring du module)."""
    return entry.get("slug") or SLUG_COURS_1


def grant_access(email: str, slug: str, store_path: Path | None = None) -> str:
    """Enregistre l'accès de `email` (normalisé) au cours `slug` et retourne un token d'accès
    unique. `slug` est obligatoire : un jeton n'est plus valable "pour le cours" au singulier,
    mais pour UN cours précis (Changement 4, multi-cours)."""
    store_path = store_path or _config.ACCESS_STORE_FILE
    data = _load(store_path)
    token = secrets.token_urlsafe(24)
    data[token] = {
        "email": _normalize_email(email),
        "slug": slug,
        "granted_at": datetime.now(timezone.utc).isoformat(),
    }
    _save(store_path, data)
    return token


def resolve_token(token: str, store_path: Path | None = None) -> tuple[str, str] | None:
    """Retourne `(email, slug)` associé à ce jeton d'accès, ou `None` s'il est invalide. Un grant
    antérieur au Changement 4 (sans "slug" enregistré) résout sur `SLUG_COURS_1` — voir
    `_entry_slug`."""
    store_path = store_path or _config.ACCESS_STORE_FILE
    entry = _load(store_path).get(token)
    if entry is None:
        return None
    return entry["email"], _entry_slug(entry)


def has_access(email: str, slug: str, store_path: Path | None = None) -> bool:
    """Cet email (comparé normalisé) a-t-il acheté LE cours `slug` précisément — peu importe
    d'où vient `email` (jeton d'accès ou compte connecté). Un grant antérieur au Changement 4
    (sans "slug" enregistré, un seul cours existant à l'époque) compte comme un achat de
    `SLUG_COURS_1`, jamais comme "aucun cours" — voir `_entry_slug` et le docstring du module."""
    store_path = store_path or _config.ACCESS_STORE_FILE
    normalized = _normalize_email(email)
    return any(
        entry["email"] == normalized and _entry_slug(entry) == slug
        for entry in _load(store_path).values()
    )
