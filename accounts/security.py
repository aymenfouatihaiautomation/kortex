"""Validation d'entrée, hachage des mots de passe, et l'horloge naïve-UTC partagée par ce module.

Hachage via `werkzeug.security` (PBKDF2, salé, itéré) — déjà une dépendance de Flask, aucun
nouveau paquet nécessaire. `password_hash` est un simple champ texte : passer à Argon2
(`argon2-cffi`) plus tard ne demanderait de changer que `hash_password`/`verify_password`
ci-dessous, pas le schéma ni les appelants."""

import re
from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 8


class ValidationError(ValueError):
    """Levée quand l'email ou le mot de passe fourni ne respecte pas les règles de base."""


def utcnow() -> datetime:
    """UTC naïf (sans tzinfo) — voir accounts/models.py pour la raison : SQLite renvoie un
    datetime naïf même pour une colonne déclarée `timezone=True`, ce qui casserait la
    comparaison avec un datetime aware. Rester naïf des deux côtés (écriture ET comparaison,
    voir accounts/service.py) fonctionne à l'identique sur SQLite et Postgres."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalize_email(email: str) -> str:
    """strip + lower — condition pour que l'accès posé à l'achat (`access_store.grant_access`,
    lui aussi normalisé) et l'email de connexion se rejoignent quelle que soit la casse tapée
    par l'utilisateur (voir bloc4_publication/access_store.py)."""
    return (email or "").strip().lower()


def validate_email_format(email: str) -> None:
    if not EMAIL_RE.match(email):
        raise ValidationError("Adresse email invalide.")


def validate_password_strength(password: str) -> None:
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(f"Le mot de passe doit contenir au moins {MIN_PASSWORD_LENGTH} caractères.")


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return check_password_hash(password_hash, password)
