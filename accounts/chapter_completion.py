"""Renforcement de l'attestation, PHASE 1 : fondation de complétion « forte » par chapitre —
distincte du suivi historique (`accounts/progress.py`, simple VISITE de page), volontairement
séparée pour ne rebrancher l'attestation sur ce nouveau critère qu'en Phase 3 (examen). Tant que
ce module n'est importé nulle part dans `accounts/certificate_routes.py`, l'attestation continue
de se baser sur `accounts.progress.is_course_complete` comme avant — voir son docstring.

Deux signaux distincts, dans deux tables neuves (`accounts/models.py`) :
- `ExerciseProgress` : participation à un item (QCM/question ouverte/exercice pratique) —
  répondu, jamais si c'est correct.
- `ChapterCompletion` : complétion EXPLICITE d'un chapitre (bouton « J'ai terminé ce chapitre »),
  autorisée seulement si tous les items du chapitre sont répondus — le contrôle est fait par
  l'appelant (`bloc4_publication/app.py::complete_chapter`) AVANT d'appeler `mark_chapter_complete`,
  jamais ici (même répartition des responsabilités que `accounts/certificates.py::issue_certificate`).

Même pattern que `accounts/progress.py` : `from accounts import db` puis `db.SessionLocal()` (pas
`from accounts.db import SessionLocal`), pour rester patchable par les tests."""

from accounts import db
from accounts.models import ChapterCompletion, ExerciseProgress
from accounts.security import normalize_email, utcnow
from sqlalchemy.exc import IntegrityError


def _mcq_item_type(exercise: dict) -> str:
    """Même condition que `bloc4_publication/templates/chapter.html` (`ex.type == "mcq" and
    ex.options`) : un exercice déclaré `mcq` mais sans `options` est en réalité rendu — et donc
    répondu — comme une question ouverte, jamais comme un QCM. Centralisé ici pour que le calcul
    du type réel ne diverge jamais entre le template et ce module."""
    return "mcq" if exercise.get("type") == "mcq" and exercise.get("options") else "short_answer"


def record_item_answered(email: str, course_slug: str, chapter_number: int, item_type: str, item_index: int) -> None:
    """Enregistre qu'un item a été répondu/soumis — idempotent, jamais si c'est correct (voir le
    docstring du module). Même logique anti-doublon que
    `accounts/progress.py::record_chapter_visit` (vérification puis retombée sur la contrainte
    d'unicité en cas de course concurrente entre deux requêtes du même utilisateur)."""
    email = normalize_email(email)
    with db.SessionLocal() as session:
        existing = (
            session.query(ExerciseProgress)
            .filter(
                ExerciseProgress.email == email,
                ExerciseProgress.course_slug == course_slug,
                ExerciseProgress.chapter_number == chapter_number,
                ExerciseProgress.item_type == item_type,
                ExerciseProgress.item_index == item_index,
            )
            .first()
        )
        if existing:
            return

        session.add(
            ExerciseProgress(
                email=email,
                course_slug=course_slug,
                chapter_number=chapter_number,
                item_type=item_type,
                item_index=item_index,
                answered_at=utcnow(),
            )
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()


def answered_item_keys(email: str, course_slug: str, chapter_number: int) -> set[tuple[str, int]]:
    """Ensemble des (item_type, item_index) déjà répondus pour ce chapitre — utilisé pour calculer
    ce qu'il reste à faire (voir `missing_item_labels`)."""
    email = normalize_email(email)
    with db.SessionLocal() as session:
        rows = (
            session.query(ExerciseProgress.item_type, ExerciseProgress.item_index)
            .filter(
                ExerciseProgress.email == email,
                ExerciseProgress.course_slug == course_slug,
                ExerciseProgress.chapter_number == chapter_number,
            )
            .all()
        )
        return {(row[0], row[1]) for row in rows}


def count_answered_items(email: str, course_slug: str, chapter_number: int) -> int:
    """Nombre d'items DISTINCTS répondus pour ce chapitre (la contrainte d'unicité garantit qu'il
    n'y a jamais plus d'une ligne par item)."""
    return len(answered_item_keys(email, course_slug, chapter_number))


def missing_item_labels(email: str, course_slug: str, chapter: dict) -> list[str]:
    """Libellés lisibles des items pas encore répondus pour ce chapitre — utilisé par
    `bloc4_publication/app.py` pour indiquer à l'apprenant ce qu'il reste à faire avant que le
    bouton « J'ai terminé ce chapitre » ne s'active. `chapter` doit être un chapitre réel
    (`bloc4_publication.content_loader.get_chapter`) — jamais une structure codée en dur ici."""
    answered = answered_item_keys(email, course_slug, chapter["number"])
    missing = []
    for index, exercise in enumerate(chapter["comprehension_exercises"]):
        if (_mcq_item_type(exercise), index) not in answered:
            missing.append(f"Question {index + 1}")
    if ("practical", 0) not in answered:
        missing.append("Exercice pratique")
    return missing


def mark_chapter_complete(email: str, course_slug: str, chapter_number: int) -> None:
    """Enregistre la complétion EXPLICITE d'un chapitre — idempotent. N'IMPOSE PAS elle-même le
    contrôle « tout répondu » : c'est la responsabilité de l'appelant, qui doit refuser AVANT
    d'appeler cette fonction (voir le docstring du module)."""
    email = normalize_email(email)
    with db.SessionLocal() as session:
        existing = (
            session.query(ChapterCompletion)
            .filter(
                ChapterCompletion.email == email,
                ChapterCompletion.course_slug == course_slug,
                ChapterCompletion.chapter_number == chapter_number,
            )
            .first()
        )
        if existing:
            return

        session.add(
            ChapterCompletion(
                email=email, course_slug=course_slug, chapter_number=chapter_number, completed_at=utcnow()
            )
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()


def is_chapter_marked_complete(email: str, course_slug: str, chapter_number: int) -> bool:
    email = normalize_email(email)
    with db.SessionLocal() as session:
        return (
            session.query(ChapterCompletion)
            .filter(
                ChapterCompletion.email == email,
                ChapterCompletion.course_slug == course_slug,
                ChapterCompletion.chapter_number == chapter_number,
            )
            .first()
            is not None
        )


def is_chapter_complete(email: str, course_slug: str, chapter_number: int, total_items: int) -> bool:
    """Vrai si le chapitre est À LA FOIS marqué terminé explicitement ET si tous ses items ont été
    répondus. `total_items` doit TOUJOURS venir de la structure réelle du chapitre (nombre
    d'exercices de compréhension + 1 exercice pratique) — jamais codé en dur ici, ce module ne
    connaît pas la structure d'un chapitre (même convention que
    `accounts/progress.py::is_course_complete`)."""
    if total_items <= 0:
        return False
    return is_chapter_marked_complete(email, course_slug, chapter_number) and count_answered_items(
        email, course_slug, chapter_number
    ) >= total_items


def is_course_complete(email: str, course_slug: str, chapters: list[dict]) -> bool:
    """Vrai si TOUS les chapitres du cours sont complets (voir `is_chapter_complete`). `chapters`
    doit être `course["chapters"]` (`bloc4_publication.content_loader.load_course`) — chaque
    chapitre fournit son propre nombre d'items (`len(comprehension_exercises) + 1` exercice
    pratique), jamais une constante partagée entre chapitres.

    NE PAS confondre avec `accounts.progress.is_course_complete` (critère historique, basé sur la
    simple visite de page) : ce module est volontairement séparé, l'attestation continue
    d'utiliser l'ancien critère jusqu'à la Phase 3 — voir le docstring du module."""
    if not chapters:
        return False
    return all(
        is_chapter_complete(email, course_slug, chapter["number"], len(chapter["comprehension_exercises"]) + 1)
        for chapter in chapters
    )
