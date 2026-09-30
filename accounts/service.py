"""Logique métier des comptes : inscription, connexion, réinitialisation de mot de passe.

Chaque fonction ouvre et referme sa propre session SQLAlchemy — pas de session partagée entre
requêtes, cohérent avec le style du reste du projet (ex. `bloc4_publication/access_store.py`
ouvre/referme son fichier JSON à chaque appel). Import `from accounts import db` (pas
`from accounts.db import SessionLocal`) : voir accounts/db.py pour pourquoi cette forme précise
est nécessaire pour que les tests puissent isoler la base."""

import secrets
from datetime import timedelta

from accounts import db
from accounts.models import PasswordResetToken, User
from accounts.security import (
    ValidationError,
    hash_password,
    normalize_email,
    utcnow,
    validate_email_format,
    validate_password_strength,
    verify_password,
)

RESET_TOKEN_TTL = timedelta(hours=1)


class EmailAlreadyRegisteredError(ValueError):
    """Levée à l'inscription si l'email est déjà associé à un compte."""


def register_user(email: str, password: str) -> User:
    email = normalize_email(email)
    validate_email_format(email)
    validate_password_strength(password)

    with db.SessionLocal() as session:
        existing = session.query(User).filter(User.email == email).first()
        if existing:
            raise EmailAlreadyRegisteredError("Un compte existe déjà avec cet email.")

        user = User(email=email, password_hash=hash_password(password))
        session.add(user)
        session.commit()
        session.refresh(user)
        return user


def account_exists(email: str) -> bool:
    """Vrai si un compte existe déjà pour cet email. Utilisée par `accounts/routes.py::register`
    (GET) pour rediriger vers `/login` plutôt que d'afficher le formulaire d'inscription à
    quelqu'un qui a déjà un compte — en particulier le client qui vient de payer via l'overlay
    Paddle.js et atterrit sur `/register?email=...` (voir bloc4_publication/templates/landing.html).

    N'introduit pas une nouvelle fuite d'information : POST /register révèle déjà "cet email a
    un compte" via `EmailAlreadyRegisteredError` — ceci ne fait que surfacer la même information
    plus tôt (avant de faire saisir un mot de passe pour rien), jamais une exposition nouvelle."""
    email = normalize_email(email)
    with db.SessionLocal() as session:
        return session.query(User).filter(User.email == email).first() is not None


def authenticate_user(email: str, password: str) -> User | None:
    """Retourne le `User` si l'email et le mot de passe correspondent, sinon `None`.

    L'appelant (route Flask) DOIT afficher le même message d'erreur générique dans les deux cas
    (email inconnu / mauvais mot de passe) — cette fonction ne distingue pas les deux cas dans sa
    valeur de retour précisément pour empêcher l'énumération de comptes en amont.

    Un compte créé via Google (`password_hash` NULL, voir `get_or_create_google_user`) échoue ici
    exactement comme un mauvais mot de passe — jamais d'appel à `verify_password` avec un hash
    absent (ça lèverait une exception côté werkzeug, pas un simple échec)."""
    email = normalize_email(email)
    if not password:
        return None

    with db.SessionLocal() as session:
        user = session.query(User).filter(User.email == email).first()
        if not user or not user.password_hash or not verify_password(password, user.password_hash):
            return None
        return user


def get_or_create_google_user(email: str, google_sub: str | None = None) -> User:
    """Réconciliation par email vérifié (voir accounts/oauth.py — Google ne fournit cet email que
    si `email_verified` est vrai, vérifié par l'appelant avant d'arriver ici).

    Si un compte existe déjà pour cet email — créé via mot de passe OU via une connexion Google
    précédente — s'y connecte, ne crée JAMAIS de doublon. Sinon crée un compte sans mot de passe
    (`password_hash` NULL : connexion Google uniquement, à moins que l'utilisateur ne passe plus
    tard par "mot de passe oublié" pour s'en définir un). `google_sub` (l'identifiant stable
    Google) est posé/mis à jour pour une liaison plus robuste que l'email seul, mais l'email
    reste la clé de réconciliation effective."""
    email = normalize_email(email)

    with db.SessionLocal() as session:
        user = session.query(User).filter(User.email == email).first()
        if user:
            if google_sub and user.google_sub != google_sub:
                user.google_sub = google_sub
                session.commit()
                session.refresh(user)
            return user

        user = User(email=email, password_hash=None, google_sub=google_sub)
        session.add(user)
        session.commit()
        session.refresh(user)
        return user


def request_password_reset(email: str) -> str | None:
    """Si un compte existe pour cet email, crée un jeton de réinitialisation et le retourne —
    sinon retourne `None`. L'appelant doit afficher le MÊME message de succès dans les deux cas
    (ne jamais révéler si un email est inscrit)."""
    email = normalize_email(email)

    with db.SessionLocal() as session:
        user = session.query(User).filter(User.email == email).first()
        if not user:
            return None

        token = secrets.token_urlsafe(32)
        now = utcnow()
        session.add(
            PasswordResetToken(user_id=user.id, token=token, created_at=now, expires_at=now + RESET_TOKEN_TTL)
        )
        session.commit()
        return token


def resolve_reset_token(token: str) -> User | None:
    """Retourne le `User` associé à ce jeton s'il est valide (existe, non expiré, non utilisé),
    sinon `None`."""
    with db.SessionLocal() as session:
        entry = session.query(PasswordResetToken).filter(PasswordResetToken.token == token).first()
        if not entry or entry.used_at is not None or entry.expires_at < utcnow():
            return None
        return session.query(User).filter(User.id == entry.user_id).first()


def reset_password(token: str, new_password: str) -> bool:
    """Applique `new_password` si le jeton est valide et le marque utilisé. Retourne False (sans
    lever) si le jeton est invalide/expiré/déjà utilisé — l'appelant affiche une erreur générique.
    Lève `ValidationError` si `new_password` ne respecte pas la longueur minimale."""
    validate_password_strength(new_password)

    with db.SessionLocal() as session:
        entry = session.query(PasswordResetToken).filter(PasswordResetToken.token == token).first()
        if not entry or entry.used_at is not None or entry.expires_at < utcnow():
            return False

        user = session.query(User).filter(User.id == entry.user_id).first()
        if not user:
            return False

        user.password_hash = hash_password(new_password)
        entry.used_at = utcnow()
        session.commit()
        return True
