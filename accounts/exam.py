"""Examen final de cours — persistance des tentatives uniquement (voir accounts/exam_grading.py
pour le tirage/la notation, accounts/exam_routes.py pour les routes Flask).

Nouvelle table (`ExamAttempt`, accounts/models.py) — aucune migration sur une table existante.

Même pattern que accounts/progress.py et accounts/chapter_completion.py : `from accounts import
db` puis `db.SessionLocal()` (pas `from accounts.db import SessionLocal`), pour rester patchable
par les tests."""

from accounts import db
from accounts.models import ExamAttempt
from accounts.security import normalize_email, utcnow


def record_attempt(email: str, course_slug: str, score_percent: int, total: int, passed: bool) -> ExamAttempt:
    """Enregistre une NOUVELLE tentative — jamais un upsert : réessais illimités, chaque tentative
    (réussie ou non) crée sa propre ligne. `passed` est fourni par l'appelant
    (accounts/exam_grading.py::grade_submission, déjà déterminé selon PASS_THRESHOLD_PERCENT) —
    ce module ne connaît pas le seuil de réussite, il persiste seulement ce qu'on lui donne."""
    email = normalize_email(email)
    with db.SessionLocal() as session:
        attempt = ExamAttempt(
            email=email,
            course_slug=course_slug,
            score=score_percent,
            total=total,
            passed=passed,
            taken_at=utcnow(),
        )
        session.add(attempt)
        session.commit()
        session.refresh(attempt)
        return attempt


def has_passed_exam(email: str, course_slug: str) -> bool:
    """Vrai si cet email a AU MOINS une tentative réussie pour ce cours, peu importe le nombre
    d'échecs avant ou après. Utilisée par la Phase 3 (pas ici) pour le gate de l'attestation —
    voir le garde-fou explicite : cette étape ne rebranche PAS l'attestation dessus."""
    email = normalize_email(email)
    with db.SessionLocal() as session:
        return (
            session.query(ExamAttempt)
            .filter(
                ExamAttempt.email == email,
                ExamAttempt.course_slug == course_slug,
                ExamAttempt.passed.is_(True),
            )
            .first()
            is not None
        )
