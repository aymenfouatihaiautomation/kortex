"""Attestations de fin de cours — persistance uniquement (voir accounts/certificate_pdf.py pour
la génération du PDF, accounts/certificate_routes.py pour les routes Flask et le contrôle
d'éligibilité).

Nouvelle table (`Certificate`, accounts/models.py) — aucune migration sur une table existante.

`token` est la clé publique de vérification (URL `/certificate/<token>`) — cette fonction ne
retourne jamais l'email dans un contexte destiné à une page publique ; c'est à l'appelant de ne
jamais exposer `.email` (voir accounts/certificate_routes.py::verify, qui ne passe que
`learner_name`/`course_title`/`issued_at`/`token` au template)."""

import secrets

from accounts import db
from accounts.models import Certificate
from accounts.security import normalize_email, utcnow


def issue_certificate(email: str, course_slug: str, course_title: str, learner_name: str) -> Certificate:
    """Crée une nouvelle attestation et retourne la ligne créée (avec son `token`).

    Ne revérifie PAS l'éligibilité (achat + cours terminé) — c'est la responsabilité de
    l'appelant (accounts/certificate_routes.py::generate), qui doit refuser AVANT d'appeler cette
    fonction. `learner_name` est pris tel que fourni par l'appelant, juste débarrassé des espaces
    superflus."""
    email = normalize_email(email)
    token = secrets.token_urlsafe(24)

    with db.SessionLocal() as session:
        certificate = Certificate(
            token=token,
            email=email,
            course_slug=course_slug,
            learner_name=learner_name.strip(),
            course_title=course_title,
            issued_at=utcnow(),
        )
        session.add(certificate)
        session.commit()
        session.refresh(certificate)
        return certificate


def get_certificate_by_token(token: str) -> Certificate | None:
    """Retourne l'attestation associée à ce jeton, ou None s'il est inconnu — l'appelant doit
    répondre 404 dans ce cas (voir accounts/certificate_routes.py), jamais une page vide."""
    with db.SessionLocal() as session:
        return session.query(Certificate).filter(Certificate.token == token).first()
