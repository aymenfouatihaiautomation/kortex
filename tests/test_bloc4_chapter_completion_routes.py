"""Tests d'intégration du renforcement de l'attestation, PHASE 1 : routes de participation
(/chapter/<n>/exercise/<i>/answer, hooks dans /correct et /practical/correct) et de complétion
explicite (/chapter/<n>/progress, /chapter/<n>/complete).

Isolation accounts.db identique à test_accounts_certificate_routes.py."""

import re
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from accounts.chapter_completion import is_chapter_marked_complete, is_course_complete
from accounts.db import Base
from bloc4_publication.app import create_app
from bloc4_publication.content_loader import load_course

COURSE = load_course()
COURSE_SLUG = COURSE["slug"]
CHAPTER_1 = COURSE["chapters"][0]
# Vérifié par inspection (voir le rapport) : ['mcq', 'mcq', 'mcq', 'short_answer', 'mcq', 'mcq'].
MCQ_INDEXES = [i for i, ex in enumerate(CHAPTER_1["comprehension_exercises"]) if ex["type"] == "mcq"]
SHORT_ANSWER_INDEXES = [i for i, ex in enumerate(CHAPTER_1["comprehension_exercises"]) if ex["type"] == "short_answer"]
TOTAL_ITEMS_CHAPTER_1 = len(CHAPTER_1["comprehension_exercises"]) + 1


@pytest.fixture
def client(tmp_path):
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'accounts_test.db'}", connect_args={"check_same_thread": False}
    )
    from accounts import models  # noqa: F401

    Base.metadata.create_all(bind=test_engine)
    test_session_local = sessionmaker(bind=test_engine, expire_on_commit=False)

    with (
        patch("accounts.db.engine", test_engine),
        patch("accounts.db.SessionLocal", test_session_local),
        patch("bloc4_publication.config.ACCESS_STORE_FILE", tmp_path / "access.json"),
        patch("pricing_agent.config.PRICING_STATE_FILE", tmp_path / "pricing_state.json"),
        patch("pricing_agent.config.SALES_LOG_FILE", tmp_path / "sales_log.json"),
    ):
        app = create_app()
        app.config.update(TESTING=True)
        with app.test_client() as test_client:
            yield test_client


def _grant_access_via_mock_checkout(client, email):
    start = client.get(f"/checkout/start?email={email}")
    mock_checkout_path = start.headers["Location"]
    transaction_id = mock_checkout_path.split("/checkout/mock/")[1].split("?")[0]
    complete = client.post(f"/checkout/mock/{transaction_id}/complete", data={"email": email})
    match = re.search(rb'href="([^"]*/access/[^"]+)"', complete.data)
    access_url = match.group(1).decode()
    client.get(access_url)


def _answer_all_of_chapter_1(client, request_correction_mock):
    request_correction_mock.return_value = "Bonne réponse, bravo."
    for i in MCQ_INDEXES:
        r = client.post(f"/chapter/1/exercise/{i}/answer")
        assert r.status_code == 200
    for i in SHORT_ANSWER_INDEXES:
        r = client.post(f"/chapter/1/exercise/{i}/correct", json={"answer": "ma réponse détaillée"})
        assert r.status_code == 200
    r = client.post("/chapter/1/practical/correct", data={"answer": "ma solution complète"})
    assert r.status_code == 200


# --- /chapter/<n>/exercise/<i>/answer (participation QCM) --------------------------------------


def test_answer_mcq_requires_access(client):
    resp = client.post(f"/chapter/1/exercise/{MCQ_INDEXES[0]}/answer")
    assert resp.status_code == 403


def test_answer_mcq_records_participation_and_returns_progress(client):
    email = "mcq1@example.com"
    _grant_access_via_mock_checkout(client, email)

    resp = client.post(f"/chapter/1/exercise/{MCQ_INDEXES[0]}/answer")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["answered_count"] == 1
    assert data["total_items"] == TOTAL_ITEMS_CHAPTER_1
    assert data["ready"] is False


def test_answer_mcq_is_idempotent(client):
    email = "mcq2@example.com"
    _grant_access_via_mock_checkout(client, email)

    client.post(f"/chapter/1/exercise/{MCQ_INDEXES[0]}/answer")
    resp = client.post(f"/chapter/1/exercise/{MCQ_INDEXES[0]}/answer")

    assert resp.get_json()["answered_count"] == 1


def test_answer_endpoint_rejects_a_short_answer_index(client):
    email = "mcq3@example.com"
    _grant_access_via_mock_checkout(client, email)

    resp = client.post(f"/chapter/1/exercise/{SHORT_ANSWER_INDEXES[0]}/answer")
    assert resp.status_code == 400


def test_answer_endpoint_404_on_out_of_range_index(client):
    email = "mcq4@example.com"
    _grant_access_via_mock_checkout(client, email)

    resp = client.post("/chapter/1/exercise/999/answer")
    assert resp.status_code == 404


# --- hooks de participation dans /correct et /practical/correct ---------------------------------


@patch("bloc4_publication.app.request_correction")
def test_short_answer_correction_records_participation(mock_correction, client):
    mock_correction.return_value = "Bonne réponse."
    email = "open1@example.com"
    _grant_access_via_mock_checkout(client, email)
    index = SHORT_ANSWER_INDEXES[0]

    client.post(f"/chapter/1/exercise/{index}/correct", json={"answer": "ma réponse"})

    progress = client.get("/chapter/1/progress").get_json()
    assert progress["answered_count"] == 1


@patch("bloc4_publication.app.request_correction")
def test_short_answer_participation_recorded_even_if_llm_call_fails(mock_correction, client):
    from common.llm_client import LLMCallError

    mock_correction.side_effect = LLMCallError("boom")
    email = "open2@example.com"
    _grant_access_via_mock_checkout(client, email)
    index = SHORT_ANSWER_INDEXES[0]

    resp = client.post(f"/chapter/1/exercise/{index}/correct", json={"answer": "ma réponse"})
    assert resp.status_code == 502  # le correcteur échoue...

    progress = client.get("/chapter/1/progress").get_json()
    assert progress["answered_count"] == 1  # ...mais la participation est bien enregistrée


def test_short_answer_correction_does_not_record_an_empty_answer(client):
    email = "open3@example.com"
    _grant_access_via_mock_checkout(client, email)
    index = SHORT_ANSWER_INDEXES[0]

    resp = client.post(f"/chapter/1/exercise/{index}/correct", json={"answer": "   "})
    assert resp.status_code == 400

    progress = client.get("/chapter/1/progress").get_json()
    assert progress["answered_count"] == 0


@patch("bloc4_publication.app.request_correction")
def test_practical_correction_records_participation(mock_correction, client):
    mock_correction.return_value = "Bon travail."
    email = "practical1@example.com"
    _grant_access_via_mock_checkout(client, email)

    client.post("/chapter/1/practical/correct", data={"answer": "ma solution"})

    progress = client.get("/chapter/1/progress").get_json()
    assert progress["answered_count"] == 1


# --- /chapter/<n>/progress ------------------------------------------------------------------------


def test_progress_endpoint_requires_access(client):
    resp = client.get("/chapter/1/progress")
    assert resp.status_code == 403


def test_progress_endpoint_lists_missing_items(client):
    email = "progress1@example.com"
    _grant_access_via_mock_checkout(client, email)
    client.post(f"/chapter/1/exercise/{MCQ_INDEXES[0]}/answer")

    progress = client.get("/chapter/1/progress").get_json()
    assert progress["ready"] is False
    assert len(progress["missing"]) == TOTAL_ITEMS_CHAPTER_1 - 1
    assert progress["chapter_marked_complete"] is False


# --- /chapter/<n>/complete ------------------------------------------------------------------------


def test_complete_chapter_requires_access(client):
    resp = client.post("/chapter/1/complete")
    assert resp.status_code == 403


@patch("bloc4_publication.app.request_correction")
def test_complete_chapter_rejected_while_items_remain_unanswered(mock_correction, client):
    mock_correction.return_value = "ok"
    email = "complete1@example.com"
    _grant_access_via_mock_checkout(client, email)
    client.post(f"/chapter/1/exercise/{MCQ_INDEXES[0]}/answer")  # un seul item répondu

    resp = client.post("/chapter/1/complete")
    assert resp.status_code == 400
    assert resp.get_json()["missing"]
    assert is_chapter_marked_complete(email, COURSE_SLUG, 1) is False


@patch("bloc4_publication.app.request_correction")
def test_complete_chapter_succeeds_once_everything_is_answered(mock_correction, client):
    email = "complete2@example.com"
    _grant_access_via_mock_checkout(client, email)
    _answer_all_of_chapter_1(client, mock_correction)

    resp = client.post("/chapter/1/complete")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["chapter_marked_complete"] is True
    assert is_chapter_marked_complete(email, COURSE_SLUG, 1) is True


@patch("bloc4_publication.app.request_correction")
def test_complete_chapter_is_idempotent(mock_correction, client):
    email = "complete3@example.com"
    _grant_access_via_mock_checkout(client, email)
    _answer_all_of_chapter_1(client, mock_correction)

    first = client.post("/chapter/1/complete")
    second = client.post("/chapter/1/complete")

    assert first.status_code == 200
    assert second.status_code == 200


# --- /chapter/<n> (page) : la bannière de complétion reflète l'état ------------------------------


def test_chapter_page_shows_disabled_button_before_completion(client):
    email = "page1@example.com"
    _grant_access_via_mock_checkout(client, email)

    resp = client.get("/chapter/1")
    assert resp.status_code == 200
    assert "J'ai terminé ce chapitre".encode() in resp.data
    assert b"disabled" in resp.data


@patch("bloc4_publication.app.request_correction")
def test_chapter_page_shows_done_message_after_completion(mock_correction, client):
    email = "page2@example.com"
    _grant_access_via_mock_checkout(client, email)
    _answer_all_of_chapter_1(client, mock_correction)
    client.post("/chapter/1/complete")

    resp = client.get("/chapter/1")
    assert "Chapitre marqué comme terminé".encode() in resp.data


# --- is_course_complete (accounts/chapter_completion.py) via un parcours réel bout-en-bout ------


@patch("bloc4_publication.app.request_correction")
def test_is_course_complete_true_only_after_every_chapter_is_marked_complete(mock_correction, client):
    mock_correction.return_value = "ok"
    email = "fullcourse@example.com"
    _grant_access_via_mock_checkout(client, email)

    chapters = COURSE["chapters"]
    for chap in chapters[:-1]:
        number = chap["number"]
        for i, ex in enumerate(chap["comprehension_exercises"]):
            if ex["type"] == "mcq":
                client.post(f"/chapter/{number}/exercise/{i}/answer")
            else:
                client.post(f"/chapter/{number}/exercise/{i}/correct", json={"answer": "réponse"})
        client.post(f"/chapter/{number}/practical/correct", data={"answer": "solution"})
        client.post(f"/chapter/{number}/complete")

    # Dernier chapitre pas encore traité -> le cours n'est pas complet.
    assert is_course_complete(email, COURSE_SLUG, chapters) is False

    last = chapters[-1]
    number = last["number"]
    for i, ex in enumerate(last["comprehension_exercises"]):
        if ex["type"] == "mcq":
            client.post(f"/chapter/{number}/exercise/{i}/answer")
        else:
            client.post(f"/chapter/{number}/exercise/{i}/correct", json={"answer": "réponse"})
    client.post(f"/chapter/{number}/practical/correct", data={"answer": "solution"})
    client.post(f"/chapter/{number}/complete")

    assert is_course_complete(email, COURSE_SLUG, chapters) is True
