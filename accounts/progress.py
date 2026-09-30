"""Suivi de progression par utilisateur : quels chapitres d'un cours ont été visités.

Nouvelle table (`ChapterProgress`, accounts/models.py) — n'ajoute aucune colonne à une table
existante, donc `accounts.db.init_db()` (create_all) la crée proprement même sur une base déjà en
production (voir le docstring d'accounts/models.py).

Comme le reste de accounts/service.py, chaque fonction ouvre et referme sa propre session
SQLAlchemy via `from accounts import db` puis `db.SessionLocal()` (pas
`from accounts.db import SessionLocal`) — c'est cette forme précise qui permet aux tests de
remplacer la base par une base temporaire isolée (voir accounts/db.py)."""

from accounts import db
from accounts.models import ChapterProgress
from accounts.security import normalize_email, utcnow
from sqlalchemy.exc import IntegrityError


def record_chapter_visit(email: str, course_slug: str, chapter_number: int) -> None:
    """Enregistre la visite d'un chapitre — idempotent : revisiter un chapitre déjà enregistré ne
    crée jamais de doublon. Vérifie d'abord l'existence (évite une écriture inutile la plupart du
    temps), et retombe sur la contrainte d'unicité en base en cas de course entre deux requêtes
    concurrentes du même utilisateur (deux onglets, double clic) — dans ce cas l'autre requête a
    déjà gagné, il n'y a rien de plus à faire."""
    email = normalize_email(email)
    with db.SessionLocal() as session:
        existing = (
            session.query(ChapterProgress)
            .filter(
                ChapterProgress.email == email,
                ChapterProgress.course_slug == course_slug,
                ChapterProgress.chapter_number == chapter_number,
            )
            .first()
        )
        if existing:
            return

        session.add(
            ChapterProgress(
                email=email, course_slug=course_slug, chapter_number=chapter_number, visited_at=utcnow()
            )
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()


def count_visited_chapters(email: str, course_slug: str) -> int:
    """Nombre de chapitres DISTINCTS visités par cet email pour ce cours (la contrainte d'unicité
    garantit qu'il n'y a jamais plus d'une ligne par chapitre, donc un simple COUNT suffit — pas
    besoin de DISTINCT)."""
    email = normalize_email(email)
    with db.SessionLocal() as session:
        return (
            session.query(ChapterProgress)
            .filter(ChapterProgress.email == email, ChapterProgress.course_slug == course_slug)
            .count()
        )


def is_course_complete(email: str, course_slug: str, total_chapters: int) -> bool:
    """Vrai si le nombre de chapitres visités par cet email pour ce cours est au moins égal à
    `total_chapters`. `total_chapters` doit TOUJOURS venir des données réelles du cours (ex.
    `len(course["chapters"])`) — jamais codé en dur ici, ce module ne connaît pas la structure
    d'un cours."""
    if total_chapters <= 0:
        return False
    return count_visited_chapters(email, course_slug) >= total_chapters
