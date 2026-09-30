"""Tests unitaires du renforcement de l'attestation, PHASE 1 (accounts/chapter_completion.py) :
participation par item (QCM/question ouverte/exercice pratique) et complétion explicite de
chapitre.

Base SQLite temporaire isolée par test — même pattern que test_accounts_service.py."""

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from accounts.chapter_completion import (
    answered_item_keys,
    count_answered_items,
    is_chapter_complete,
    is_chapter_marked_complete,
    is_course_complete,
    mark_chapter_complete,
    missing_item_labels,
    record_item_answered,
)
from accounts.db import Base

SLUG = "cours-ia"

CHAPTER_1 = {
    "number": 1,
    "comprehension_exercises": [
        {"type": "mcq", "options": ["A", "B"]},
        {"type": "short_answer"},
        {"type": "mcq", "options": ["A", "B"]},
    ],
}

CHAPTER_2 = {
    "number": 2,
    "comprehension_exercises": [
        {"type": "short_answer"},
        {"type": "short_answer"},
    ],
}


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


def _answer_all_of_chapter_1(email):
    record_item_answered(email, SLUG, 1, "mcq", 0)
    record_item_answered(email, SLUG, 1, "short_answer", 1)
    record_item_answered(email, SLUG, 1, "mcq", 2)
    record_item_answered(email, SLUG, 1, "practical", 0)


def _answer_all_of_chapter_2(email):
    record_item_answered(email, SLUG, 2, "short_answer", 0)
    record_item_answered(email, SLUG, 2, "short_answer", 1)
    record_item_answered(email, SLUG, 2, "practical", 0)


# --- record_item_answered / count_answered_items ------------------------------------------------


def test_record_item_answered_is_counted(isolated_db):
    record_item_answered("alice@example.com", SLUG, 1, "mcq", 0)
    assert count_answered_items("alice@example.com", SLUG, 1) == 1


def test_record_item_answered_is_idempotent(isolated_db):
    record_item_answered("alice@example.com", SLUG, 1, "mcq", 0)
    record_item_answered("alice@example.com", SLUG, 1, "mcq", 0)
    record_item_answered("alice@example.com", SLUG, 1, "mcq", 0)

    assert count_answered_items("alice@example.com", SLUG, 1) == 1


def test_same_index_different_type_are_counted_separately(isolated_db):
    # L'exercice pratique est toujours item_index=0, comme le premier exercice de compréhension —
    # item_type est ce qui lève l'ambiguïté (voir le docstring du module).
    record_item_answered("alice@example.com", SLUG, 1, "mcq", 0)
    record_item_answered("alice@example.com", SLUG, 1, "practical", 0)

    assert count_answered_items("alice@example.com", SLUG, 1) == 2
    assert answered_item_keys("alice@example.com", SLUG, 1) == {("mcq", 0), ("practical", 0)}


def test_record_item_answered_normalizes_email(isolated_db):
    record_item_answered("Alice@Example.com", SLUG, 1, "mcq", 0)
    record_item_answered("alice@example.com", SLUG, 1, "mcq", 0)

    assert count_answered_items("alice@example.com", SLUG, 1) == 1


def test_distinct_chapters_are_counted_separately(isolated_db):
    record_item_answered("alice@example.com", SLUG, 1, "mcq", 0)
    record_item_answered("alice@example.com", SLUG, 2, "mcq", 0)

    assert count_answered_items("alice@example.com", SLUG, 1) == 1
    assert count_answered_items("alice@example.com", SLUG, 2) == 1


# --- missing_item_labels -------------------------------------------------------------------------


def test_missing_item_labels_lists_everything_when_nothing_answered(isolated_db):
    missing = missing_item_labels("alice@example.com", SLUG, CHAPTER_1)
    assert missing == ["Question 1", "Question 2", "Question 3", "Exercice pratique"]


def test_missing_item_labels_excludes_answered_items(isolated_db):
    record_item_answered("alice@example.com", SLUG, 1, "mcq", 0)
    record_item_answered("alice@example.com", SLUG, 1, "practical", 0)

    missing = missing_item_labels("alice@example.com", SLUG, CHAPTER_1)
    assert missing == ["Question 2", "Question 3"]


def test_missing_item_labels_empty_when_everything_answered(isolated_db):
    _answer_all_of_chapter_1("alice@example.com")
    assert missing_item_labels("alice@example.com", SLUG, CHAPTER_1) == []


# --- mark_chapter_complete / is_chapter_marked_complete ------------------------------------------


def test_chapter_not_marked_complete_by_default(isolated_db):
    assert is_chapter_marked_complete("alice@example.com", SLUG, 1) is False


def test_mark_chapter_complete_is_idempotent(isolated_db):
    mark_chapter_complete("alice@example.com", SLUG, 1)
    mark_chapter_complete("alice@example.com", SLUG, 1)

    assert is_chapter_marked_complete("alice@example.com", SLUG, 1) is True


# --- is_chapter_complete --------------------------------------------------------------------------


def test_is_chapter_complete_false_when_not_marked_even_if_all_answered(isolated_db):
    _answer_all_of_chapter_1("alice@example.com")
    # Tout répondu, mais le bouton "J'ai terminé ce chapitre" n'a jamais été cliqué.
    assert is_chapter_complete("alice@example.com", SLUG, 1, total_items=4) is False


def test_is_chapter_complete_false_when_marked_but_not_all_answered(isolated_db):
    record_item_answered("alice@example.com", SLUG, 1, "mcq", 0)
    mark_chapter_complete("alice@example.com", SLUG, 1)

    assert is_chapter_complete("alice@example.com", SLUG, 1, total_items=4) is False


def test_is_chapter_complete_true_when_marked_and_all_answered(isolated_db):
    _answer_all_of_chapter_1("alice@example.com")
    mark_chapter_complete("alice@example.com", SLUG, 1)

    assert is_chapter_complete("alice@example.com", SLUG, 1, total_items=4) is True


def test_is_chapter_complete_false_for_total_items_zero(isolated_db):
    mark_chapter_complete("alice@example.com", SLUG, 1)
    assert is_chapter_complete("alice@example.com", SLUG, 1, total_items=0) is False


# --- is_course_complete ---------------------------------------------------------------------------


def test_is_course_complete_false_when_no_chapter_done(isolated_db):
    assert is_course_complete("alice@example.com", SLUG, [CHAPTER_1, CHAPTER_2]) is False


def test_is_course_complete_false_when_only_some_chapters_done(isolated_db):
    _answer_all_of_chapter_1("alice@example.com")
    mark_chapter_complete("alice@example.com", SLUG, 1)
    # Chapitre 2 jamais touché.

    assert is_course_complete("alice@example.com", SLUG, [CHAPTER_1, CHAPTER_2]) is False


def test_is_course_complete_true_when_all_chapters_done_with_different_item_counts(isolated_db):
    # CHAPTER_1 a 3 exercices de compréhension, CHAPTER_2 en a 2 : le total par chapitre ne doit
    # jamais être une constante partagée.
    _answer_all_of_chapter_1("alice@example.com")
    mark_chapter_complete("alice@example.com", SLUG, 1)
    _answer_all_of_chapter_2("alice@example.com")
    mark_chapter_complete("alice@example.com", SLUG, 2)

    assert is_course_complete("alice@example.com", SLUG, [CHAPTER_1, CHAPTER_2]) is True


def test_is_course_complete_false_for_empty_chapter_list(isolated_db):
    assert is_course_complete("alice@example.com", SLUG, []) is False
