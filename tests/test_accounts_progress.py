"""Tests unitaires du suivi de progression (accounts/progress.py).

Base SQLite temporaire isolée par test — même pattern que test_accounts_service.py (patch
`accounts.db.engine`/`accounts.db.SessionLocal`, jamais le fichier accounts.db réel)."""

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from accounts.db import Base
from accounts.progress import count_visited_chapters, is_course_complete, record_chapter_visit


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


def test_record_chapter_visit_is_counted(isolated_db):
    record_chapter_visit("alice@example.com", "cours-ia", 1)
    assert count_visited_chapters("alice@example.com", "cours-ia") == 1


def test_record_chapter_visit_is_idempotent(isolated_db):
    record_chapter_visit("alice@example.com", "cours-ia", 1)
    record_chapter_visit("alice@example.com", "cours-ia", 1)
    record_chapter_visit("alice@example.com", "cours-ia", 1)

    assert count_visited_chapters("alice@example.com", "cours-ia") == 1


def test_record_chapter_visit_normalizes_email(isolated_db):
    record_chapter_visit("Alice@Example.com", "cours-ia", 1)
    record_chapter_visit("alice@example.com", "cours-ia", 1)

    assert count_visited_chapters("alice@example.com", "cours-ia") == 1


def test_distinct_chapters_and_courses_are_counted_separately(isolated_db):
    record_chapter_visit("alice@example.com", "cours-ia", 1)
    record_chapter_visit("alice@example.com", "cours-ia", 2)
    record_chapter_visit("alice@example.com", "autre-cours", 1)
    record_chapter_visit("bob@example.com", "cours-ia", 1)

    assert count_visited_chapters("alice@example.com", "cours-ia") == 2
    assert count_visited_chapters("alice@example.com", "autre-cours") == 1
    assert count_visited_chapters("bob@example.com", "cours-ia") == 1


def test_is_course_complete_false_when_no_visit(isolated_db):
    assert is_course_complete("alice@example.com", "cours-ia", total_chapters=3) is False


def test_is_course_complete_false_when_partially_visited(isolated_db):
    record_chapter_visit("alice@example.com", "cours-ia", 1)
    record_chapter_visit("alice@example.com", "cours-ia", 2)

    assert is_course_complete("alice@example.com", "cours-ia", total_chapters=3) is False


def test_is_course_complete_true_when_all_chapters_visited(isolated_db):
    record_chapter_visit("alice@example.com", "cours-ia", 1)
    record_chapter_visit("alice@example.com", "cours-ia", 2)
    record_chapter_visit("alice@example.com", "cours-ia", 3)

    assert is_course_complete("alice@example.com", "cours-ia", total_chapters=3) is True


def test_is_course_complete_false_for_total_chapters_zero(isolated_db):
    assert is_course_complete("alice@example.com", "cours-ia", total_chapters=0) is False
