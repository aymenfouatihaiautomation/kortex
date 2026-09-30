"""Tests unitaires de la persistance des tentatives d'examen (accounts/exam.py).

Base SQLite temporaire isolée par test — même pattern que test_accounts_service.py."""

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from accounts.db import Base
from accounts.exam import has_passed_exam, record_attempt

SLUG = "cours-ia"


@pytest.fixture
def isolated_db(tmp_path):
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'accounts_test.db'}", connect_args={"check_same_thread": False}
    )
    from accounts import models  # noqa: F401 — enregistre les tables sur Base.metadata

    Base.metadata.create_all(bind=test_engine)
    test_session_local = sessionmaker(bind=test_engine, expire_on_commit=False)

    with patch("accounts.db.engine", test_engine), patch("accounts.db.SessionLocal", test_session_local):
        yield


def test_record_attempt_creates_a_row(isolated_db):
    attempt = record_attempt("alice@example.com", SLUG, score_percent=80, total=10, passed=True)

    assert attempt.email == "alice@example.com"
    assert attempt.course_slug == SLUG
    assert attempt.score == 80
    assert attempt.total == 10
    assert attempt.passed is True
    assert attempt.taken_at is not None


def test_record_attempt_normalizes_email(isolated_db):
    record_attempt("Alice@Example.com", SLUG, score_percent=80, total=10, passed=True)
    assert has_passed_exam("alice@example.com", SLUG) is True


def test_record_attempt_never_upserts_always_creates_new_rows(isolated_db):
    # Réessais illimités : deux tentatives échouées puis une réussie doivent laisser 3 lignes.
    record_attempt("alice@example.com", SLUG, score_percent=40, total=10, passed=False)
    record_attempt("alice@example.com", SLUG, score_percent=60, total=10, passed=False)
    record_attempt("alice@example.com", SLUG, score_percent=90, total=10, passed=True)

    from accounts import db
    from accounts.models import ExamAttempt

    with db.SessionLocal() as session:
        count = session.query(ExamAttempt).filter(ExamAttempt.email == "alice@example.com").count()
    assert count == 3


def test_has_passed_exam_false_with_no_attempts(isolated_db):
    assert has_passed_exam("alice@example.com", SLUG) is False


def test_has_passed_exam_false_when_only_failed_attempts(isolated_db):
    record_attempt("alice@example.com", SLUG, score_percent=50, total=10, passed=False)
    record_attempt("alice@example.com", SLUG, score_percent=60, total=10, passed=False)

    assert has_passed_exam("alice@example.com", SLUG) is False


def test_has_passed_exam_true_after_at_least_one_success_even_with_prior_failures(isolated_db):
    record_attempt("alice@example.com", SLUG, score_percent=50, total=10, passed=False)
    record_attempt("alice@example.com", SLUG, score_percent=80, total=10, passed=True)
    record_attempt("alice@example.com", SLUG, score_percent=30, total=10, passed=False)  # après coup, sans effet

    assert has_passed_exam("alice@example.com", SLUG) is True


def test_has_passed_exam_is_scoped_per_course(isolated_db):
    record_attempt("alice@example.com", "cours-a", score_percent=90, total=10, passed=True)

    assert has_passed_exam("alice@example.com", "cours-a") is True
    assert has_passed_exam("alice@example.com", "cours-b") is False


def test_has_passed_exam_is_scoped_per_email(isolated_db):
    record_attempt("alice@example.com", SLUG, score_percent=90, total=10, passed=True)

    assert has_passed_exam("alice@example.com", SLUG) is True
    assert has_passed_exam("bob@example.com", SLUG) is False
