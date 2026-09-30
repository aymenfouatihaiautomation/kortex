"""Schéma des comptes — Phase 1 (email + mot de passe) et Phase 2 (connexion Google, voir
accounts/oauth.py).

Pas de logique ici (hachage, validation, réconciliation) : voir `accounts/security.py` et
`accounts/service.py`.

Convention datetime : toutes les colonnes datetime de ce module sont des UTC NAIFS (pas de
`timezone=True`, pas de `tzinfo` sur les valeurs stockées) — voir `accounts/security.py::utcnow`
pour la raison (SQLite renvoie un datetime naïf même pour une colonne `timezone=True`, ce qui
casserait la comparaison avec un `datetime.now(timezone.utc)` aware sur ce backend). Rester
100% naïf-UTC des deux côtés (écriture ET comparaison) fonctionne de façon identique sur SQLite
et Postgres.

Schéma modifié pour la Phase 2 (voir accounts/service.py::get_or_create_google_user) : une base
locale déjà initialisée avant ce changement (`data/accounts.db`) ne rattrapera PAS ces colonnes
via `init_db()`/`create_all` (qui crée les tables manquantes, jamais les colonnes manquantes sur
une table déjà là) — supprimer ce fichier local et relancer `python -m accounts.db` si besoin."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from accounts.db import Base
from accounts.security import utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Email = clé d'identité (unique). Toujours stocké normalisé (strip + lower, voir
    # accounts.security.normalize_email) — c'est ce qui garantit que le futur webhook Paddle
    # (email du client, casse potentiellement différente) ET la connexion Google (email vérifié
    # par Google, voir accounts/oauth.py) rattachent l'achat/le compte au même utilisateur.
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    # Nullable depuis la Phase 2 : un compte créé via Google n'a pas de mot de passe (voir
    # accounts/service.py::get_or_create_google_user) — accounts/security.py::verify_password
    # n'est jamais appelée sur un password_hash NULL (accounts/service.py::authenticate_user le
    # court-circuite explicitement).
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Identifiant stable Google ("sub" du token OIDC) — optionnel, posé/mis à jour à la première
    # connexion Google d'un compte (qu'il ait été créé via mot de passe ou via Google). L'email
    # reste la clé de réconciliation ; `google_sub` est une liaison plus robuste en complément
    # (l'email Google peut en théorie être ré-attribué par le fournisseur, `sub` jamais).
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow, nullable=False)


class PasswordResetToken(Base):
    """Un jeton par demande de réinitialisation — les anciens jetons non utilisés restent
    simplement ignorés une fois expirés ou une fois le mot de passe changé (`used_at` posé),
    aucune invalidation croisée nécessaire à ce stade."""

    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)


class ChapterProgress(Base):
    """Une ligne = un chapitre visité par un email, pour un cours donné. Table NEUVE (voir le
    docstring du module) — ajoutée pour l'attestation de fin de cours, sans toucher `users` ni
    `password_reset_tokens`.

    Contrainte d'unicité sur (email, course_slug, chapter_number) : revisiter un chapitre déjà
    enregistré ne doit jamais créer un doublon — voir accounts/progress.py::record_chapter_visit,
    qui s'appuie sur cette contrainte pour être idempotent même en cas de double requête
    concurrente (deux onglets, double clic)."""

    __tablename__ = "chapter_progress"
    __table_args__ = (
        UniqueConstraint("email", "course_slug", "chapter_number", name="uq_chapter_progress_email_slug_chapter"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    course_slug: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False)
    visited_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow, nullable=False)


class Certificate(Base):
    """Une attestation émise. Table NEUVE, indépendante de `users` (pas de clé étrangère) : garde
    `email`, `course_slug`, `learner_name` et `course_title` en clair sur la ligne elle-même —
    l'attestation doit rester lisible et vérifiable telle qu'émise même si le compte est
    supprimé plus tard ou si le cours change de titre.

    `token` est la clé publique de vérification (URL `/certificate/<token>`, voir
    accounts/certificate_routes.py) — il ne doit JAMAIS permettre de retrouver l'email : la page
    de vérification publique n'affiche jamais `email`, seulement `learner_name`."""

    __tablename__ = "certificates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    course_slug: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    learner_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Dénormalisé volontairement (copié à l'émission, pas une référence vers le cours) : si le
    # titre du cours change plus tard, une attestation déjà émise doit rester fidèle à ce qu'elle
    # attestait au moment de l'émission.
    course_title: Mapped[str] = mapped_column(String(500), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow, nullable=False)


class ChapterCompletion(Base):
    """Complétion EXPLICITE d'un chapitre (bouton « J'ai terminé ce chapitre »), distincte de la
    simple VISITE (`ChapterProgress`, posée automatiquement à l'ouverture de `/chapter/<n>`).
    Table NEUVE — aucune colonne ajoutée à une table existante, `create_all()` la crée sans
    migration.

    Ne suffit pas à elle seule à dire qu'un chapitre est complet : voir
    `accounts/chapter_completion.py::is_chapter_complete`, qui combine cette marque explicite avec
    le fait que tous les items du chapitre ont été répondus (`ExerciseProgress`) — le contrôle
    serveur (pas seulement un bouton désactivé côté client) refuse de poser cette marque tant que
    ce n'est pas le cas, voir `bloc4_publication/app.py::complete_chapter`."""

    __tablename__ = "chapter_completions"
    __table_args__ = (
        UniqueConstraint(
            "email", "course_slug", "chapter_number", name="uq_chapter_completions_email_slug_chapter"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    course_slug: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow, nullable=False)


class ExerciseProgress(Base):
    """Participation à un item d'exercice (QCM, question ouverte, exercice pratique) d'un
    chapitre — enregistre seulement qu'il a été RÉPONDU/soumis, jamais si c'est correct (la
    justesse reste éphémère, gérée par `bloc4_publication/exercise_correction.py`, jamais
    persistée ici ni ailleurs).

    `item_type` + `item_index` identifient l'item de façon stable : les QCM et questions ouvertes
    d'un même chapitre partagent le même espace d'index (leur position dans
    `comprehension_exercises`), et l'exercice pratique est toujours `item_type="practical"`,
    `item_index=0` — au même index que le premier exercice de compréhension. `item_type` est donc
    nécessaire pour lever cette ambiguïté.

    Table NEUVE, indépendante de `chapter_progress` (simple visite de page) et de
    `chapter_completions` (complétion explicite)."""

    __tablename__ = "exercise_progress"
    __table_args__ = (
        UniqueConstraint(
            "email", "course_slug", "chapter_number", "item_type", "item_index",
            name="uq_exercise_progress_item",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    course_slug: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False)
    item_type: Mapped[str] = mapped_column(String(32), nullable=False)
    item_index: Mapped[int] = mapped_column(Integer, nullable=False)
    answered_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow, nullable=False)


class ExamAttempt(Base):
    """Une tentative d'examen final (Phase 2, Étape 2). Table NEUVE — aucune colonne ajoutée à une
    table existante, `create_all()` la crée sans migration.

    Réessais ILLIMITÉS (voir accounts/exam_routes.py) : chaque tentative crée une NOUVELLE ligne,
    jamais un UPSERT sur une ligne existante — `accounts/exam.py::has_passed_exam` cherche
    seulement s'IL EXISTE au moins une ligne `passed=True`, peu importe le nombre d'échecs avant
    ou après. `score`/`total` sont dénormalisés (pas recalculés depuis les réponses détaillées,
    qui ne sont jamais persistées ici — voir accounts/exam_grading.py, 100% déterministe et
    recalculé à chaque tentative depuis la banque de questions, jamais depuis cette table)."""

    __tablename__ = "exam_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    course_slug: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    taken_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow, nullable=False)
