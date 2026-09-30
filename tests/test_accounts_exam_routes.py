"""Tests d'intégration de l'examen final (Phase 2, Étape 2) : gate serveur (accès + complétion
forte du cours), tirage/mélange réel via HTTP, notation, persistance de la tentative, et
has_passed_exam. Isolation accounts.db identique à test_accounts_certificate_routes.py.

La banque de questions est PATCHÉE (jamais le vrai exam_questions.json de production) — une
banque de 20 questions à réponse connue ("Bonne réponse" toujours à l'index 0), pour pouvoir
construire des soumissions 100% correctes ou 100% fausses de façon déterministe."""

import re
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from werkzeug.datastructures import MultiDict

from accounts.db import Base
from accounts.exam import has_passed_exam
from bloc4_publication.app import create_app
from bloc4_publication.content_loader import load_course

COURSE = load_course()
COURSE_SLUG = COURSE["slug"]

FAKE_BANK = [
    {
        "id": f"q{i}",
        "chapter": 1,
        "question": f"Question {i} ?",
        "options": ["Bonne réponse", "Mauvaise B", "Mauvaise C", "Mauvaise D"],
        "correct_index": 0,
        "explanation": f"Explication {i}.",
    }
    for i in range(1, 21)
]


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


@patch("bloc4_publication.app.request_correction")
def _complete_all_chapters(client, mock_correction):
    mock_correction.return_value = "ok"
    for chap in COURSE["chapters"]:
        number = chap["number"]
        for i, ex in enumerate(chap["comprehension_exercises"]):
            if ex["type"] == "mcq":
                client.post(f"/chapter/{number}/exercise/{i}/answer")
            else:
                client.post(f"/chapter/{number}/exercise/{i}/correct", json={"answer": "réponse"})
        client.post(f"/chapter/{number}/practical/correct", data={"answer": "solution"})
        client.post(f"/chapter/{number}/complete")


def _extract_question_ids(html: bytes) -> list[str]:
    return re.findall(rb'name="question_id" value="([^"]+)"', html)


# --- gate d'accès : GET -----------------------------------------------------------------------


def test_exam_redirects_to_landing_without_access(client):
    resp = client.get(f"/course/{COURSE_SLUG}/exam")
    assert resp.status_code == 302
    assert resp.headers["Location"] == f"/cours/{COURSE_SLUG}"


def test_exam_locked_with_access_but_course_incomplete(client):
    email = "incomplete@example.com"
    _grant_access_via_mock_checkout(client, email)

    resp = client.get(f"/course/{COURSE_SLUG}/exam")

    assert resp.status_code == 200
    assert "Termine d'abord tous les chapitres".encode() in resp.data


def test_exam_unknown_slug_is_404(client):
    email = "unknownslug@example.com"
    _grant_access_via_mock_checkout(client, email)
    resp = client.get("/course/un-autre-cours/exam")
    assert resp.status_code == 404


# --- robustesse : banque absente pour ce cours (jamais un 500) ---------------------------------


@patch("accounts.exam_routes.load_exam_questions")
def test_exam_get_shows_clean_message_when_bank_missing_even_if_course_complete(mock_load_bank, client):
    mock_load_bank.return_value = None
    email = "nobank1@example.com"
    _grant_access_via_mock_checkout(client, email)
    _complete_all_chapters(client)

    resp = client.get(f"/course/{COURSE_SLUG}/exam")

    assert resp.status_code == 200
    assert "Examen indisponible pour ce cours".encode() in resp.data


@patch("accounts.exam_routes.load_exam_questions")
def test_exam_post_shows_clean_message_when_bank_missing_even_if_course_complete(mock_load_bank, client):
    mock_load_bank.return_value = None
    email = "nobank2@example.com"
    _grant_access_via_mock_checkout(client, email)
    _complete_all_chapters(client)

    resp = client.post(f"/course/{COURSE_SLUG}/exam", data={})

    assert resp.status_code == 200
    assert "Examen indisponible pour ce cours".encode() in resp.data


@patch("accounts.exam_routes.load_exam_questions")
def test_exam_incomplete_course_message_takes_priority_over_missing_bank(mock_load_bank, client):
    # Cours pas terminé -> message "termine d'abord", jamais le message "indisponible", même si
    # la banque est aussi absente : l'apprenant doit d'abord savoir qu'il lui reste des chapitres.
    mock_load_bank.return_value = None
    email = "nobank3@example.com"
    _grant_access_via_mock_checkout(client, email)

    resp = client.get(f"/course/{COURSE_SLUG}/exam")

    assert resp.status_code == 200
    assert "Termine d'abord tous les chapitres".encode() in resp.data


@patch("accounts.exam_routes.load_exam_questions")
def test_exam_take_renders_ten_questions_when_course_complete(mock_load_bank, client):
    mock_load_bank.return_value = FAKE_BANK
    email = "eligible1@example.com"
    _grant_access_via_mock_checkout(client, email)
    _complete_all_chapters(client)

    resp = client.get(f"/course/{COURSE_SLUG}/exam")

    assert resp.status_code == 200
    assert len(_extract_question_ids(resp.data)) == 10


@patch("accounts.exam_routes.load_exam_questions")
def test_exam_options_are_shuffled_but_same_set_of_texts(mock_load_bank, client):
    mock_load_bank.return_value = FAKE_BANK
    email = "eligible2@example.com"
    _grant_access_via_mock_checkout(client, email)
    _complete_all_chapters(client)

    resp = client.get(f"/course/{COURSE_SLUG}/exam")
    # Les 4 options d'une question donnée doivent toutes apparaître, quel que soit leur ordre.
    for expected in ("Bonne réponse", "Mauvaise B", "Mauvaise C", "Mauvaise D"):
        assert expected.encode() in resp.data


@patch("accounts.exam_routes.load_exam_questions")
def test_retrying_draws_a_different_random_set(mock_load_bank, client):
    mock_load_bank.return_value = FAKE_BANK
    email = "eligible3@example.com"
    _grant_access_via_mock_checkout(client, email)
    _complete_all_chapters(client)

    seen_sets = set()
    for _ in range(8):
        resp = client.get(f"/course/{COURSE_SLUG}/exam")
        seen_sets.add(tuple(sorted(_extract_question_ids(resp.data))))
    # Banque de 20, tirage de 10 : la probabilité que les 8 tirages soient tous identiques est
    # négligeable — au moins deux tirages distincts confirment un vrai tirage aléatoire.
    assert len(seen_sets) > 1


# --- gate d'accès : POST ------------------------------------------------------------------------


def test_exam_submit_requires_access(client):
    resp = client.post(f"/course/{COURSE_SLUG}/exam", data={})
    assert resp.status_code == 302


def test_exam_submit_locked_when_course_incomplete(client):
    email = "incomplete2@example.com"
    _grant_access_via_mock_checkout(client, email)

    resp = client.post(f"/course/{COURSE_SLUG}/exam", data={})

    assert resp.status_code == 200
    assert "Termine d'abord tous les chapitres".encode() in resp.data


# --- notation + persistance ---------------------------------------------------------------------


@patch("accounts.exam_routes.load_exam_questions")
def test_all_correct_answers_pass_and_are_recorded(mock_load_bank, client):
    mock_load_bank.return_value = FAKE_BANK
    email = "success1@example.com"
    _grant_access_via_mock_checkout(client, email)
    _complete_all_chapters(client)

    take_resp = client.get(f"/course/{COURSE_SLUG}/exam")
    question_ids = [qid.decode() for qid in _extract_question_ids(take_resp.data)]

    form_data = [("question_id", qid) for qid in question_ids]
    form_data += [(f"answer_{qid}", "Bonne réponse") for qid in question_ids]

    result_resp = client.post(f"/course/{COURSE_SLUG}/exam", data=MultiDict(form_data))

    assert result_resp.status_code == 200
    assert b"100" in result_resp.data
    assert "Examen réussi".encode() in result_resp.data
    assert has_passed_exam(email, COURSE_SLUG) is True


@patch("accounts.exam_routes.load_exam_questions")
def test_all_wrong_answers_fail_and_show_explanations(mock_load_bank, client):
    mock_load_bank.return_value = FAKE_BANK
    email = "fail1@example.com"
    _grant_access_via_mock_checkout(client, email)
    _complete_all_chapters(client)

    take_resp = client.get(f"/course/{COURSE_SLUG}/exam")
    question_ids = [qid.decode() for qid in _extract_question_ids(take_resp.data)]

    form_data = [("question_id", qid) for qid in question_ids]
    form_data += [(f"answer_{qid}", "Mauvaise B") for qid in question_ids]

    result_resp = client.post(f"/course/{COURSE_SLUG}/exam", data=MultiDict(form_data))

    assert result_resp.status_code == 200
    assert "Examen non réussi".encode() in result_resp.data
    assert any(f"Explication {i}.".encode() in result_resp.data for i in range(1, 21))
    assert "Bonne réponse".encode() in result_resp.data  # la bonne réponse est révélée sur la page de résultat
    assert has_passed_exam(email, COURSE_SLUG) is False


@patch("accounts.exam_routes.load_exam_questions")
def test_attempt_is_persisted_even_on_failure(mock_load_bank, client):
    mock_load_bank.return_value = FAKE_BANK
    email = "recorded1@example.com"
    _grant_access_via_mock_checkout(client, email)
    _complete_all_chapters(client)

    take_resp = client.get(f"/course/{COURSE_SLUG}/exam")
    question_ids = [qid.decode() for qid in _extract_question_ids(take_resp.data)]
    form_data = [("question_id", qid) for qid in question_ids]
    form_data += [(f"answer_{qid}", "Mauvaise B") for qid in question_ids]
    client.post(f"/course/{COURSE_SLUG}/exam", data=MultiDict(form_data))

    from accounts import db
    from accounts.models import ExamAttempt

    with db.SessionLocal() as session:
        attempts = session.query(ExamAttempt).filter(ExamAttempt.email == email).all()
    assert len(attempts) == 1
    assert attempts[0].passed is False
    assert attempts[0].total == 10
    assert attempts[0].score == 0


@patch("accounts.exam_routes.load_exam_questions")
def test_unlimited_retries_each_create_a_new_attempt_row(mock_load_bank, client):
    mock_load_bank.return_value = FAKE_BANK
    email = "retry1@example.com"
    _grant_access_via_mock_checkout(client, email)
    _complete_all_chapters(client)

    for _ in range(3):
        take_resp = client.get(f"/course/{COURSE_SLUG}/exam")
        question_ids = [qid.decode() for qid in _extract_question_ids(take_resp.data)]
        form_data = [("question_id", qid) for qid in question_ids]
        form_data += [(f"answer_{qid}", "Mauvaise B") for qid in question_ids]
        client.post(f"/course/{COURSE_SLUG}/exam", data=MultiDict(form_data))

    from accounts import db
    from accounts.models import ExamAttempt

    with db.SessionLocal() as session:
        count = session.query(ExamAttempt).filter(ExamAttempt.email == email).count()
    assert count == 3


# --- lien conditionnel sur le tableau de bord ---------------------------------------------------


def test_exam_link_absent_from_dashboard_before_completion(client):
    email = "dashboard1@example.com"
    _grant_access_via_mock_checkout(client, email)

    resp = client.get("/course")

    assert "Passer l'examen final".encode() not in resp.data


@patch("bloc4_publication.app.exam_bank_available")
def test_exam_link_absent_from_dashboard_when_bank_missing_even_if_complete(mock_bank_available, client):
    # Le lien du tableau de bord dépend de bloc4_publication.app.exam_bank_available (vérifie la
    # présence du fichier), PAS de accounts.exam_routes.load_exam_questions (utilisé par les
    # routes /course/<slug>/exam elles-mêmes) — d'où le patch sur le bon module ici.
    mock_bank_available.return_value = False
    email = "dashboard3@example.com"
    _grant_access_via_mock_checkout(client, email)
    _complete_all_chapters(client)

    resp = client.get("/course")

    assert "Passer l'examen final".encode() not in resp.data


@patch("accounts.exam_routes.load_exam_questions")
def test_exam_link_present_on_dashboard_after_completion(mock_load_bank, client):
    mock_load_bank.return_value = FAKE_BANK
    email = "dashboard2@example.com"
    _grant_access_via_mock_checkout(client, email)
    _complete_all_chapters(client)

    resp = client.get("/course")

    assert "Passer l'examen final".encode() in resp.data


# --- Phase 3 : point d'entrée de l'examen en fin de dernier chapitre ----------------------------


def test_exam_entry_point_appears_on_last_chapter_when_course_complete(client):
    email = "lastchapter1@example.com"
    _grant_access_via_mock_checkout(client, email)
    _complete_all_chapters(client)

    last_chapter_number = COURSE["chapters"][-1]["number"]
    resp = client.get(f"/chapter/{last_chapter_number}")

    assert resp.status_code == 200
    assert "Passer l'examen final".encode() in resp.data


def test_exam_entry_point_absent_from_last_chapter_before_completion(client):
    email = "lastchapter2@example.com"
    _grant_access_via_mock_checkout(client, email)

    last_chapter_number = COURSE["chapters"][-1]["number"]
    resp = client.get(f"/chapter/{last_chapter_number}")

    assert resp.status_code == 200
    assert "Passer l'examen final".encode() not in resp.data


def test_exam_entry_point_never_appears_on_non_final_chapters(client):
    email = "notlast1@example.com"
    _grant_access_via_mock_checkout(client, email)
    _complete_all_chapters(client)

    resp = client.get("/chapter/1")  # le cours a plusieurs chapitres, jamais le dernier ici

    assert resp.status_code == 200
    assert "Passer l'examen final".encode() not in resp.data


@patch("bloc4_publication.app.exam_bank_available")
def test_exam_entry_point_absent_from_last_chapter_when_bank_missing(mock_bank_available, client):
    mock_bank_available.return_value = False
    email = "lastchapter3@example.com"
    _grant_access_via_mock_checkout(client, email)
    _complete_all_chapters(client)

    last_chapter_number = COURSE["chapters"][-1]["number"]
    resp = client.get(f"/chapter/{last_chapter_number}")

    assert "Passer l'examen final".encode() not in resp.data
