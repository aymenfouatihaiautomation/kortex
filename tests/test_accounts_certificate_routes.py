"""Tests d'intégration de l'attestation de fin de cours (Phase 3, verrouillé) : gate serveur sur
les 3 conditions (accès payant + complétion FORTE de tous les chapitres + examen final réussi),
génération, page de vérification publique, bouton LinkedIn.

Isolation accounts.db identique à test_accounts_access_gate.py — voir son commentaire."""

import re
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from accounts.db import Base
from accounts.progress import count_visited_chapters
from bloc4_publication.app import create_app
from bloc4_publication.content_loader import load_course

COURSE = load_course()
COURSE_SLUG = COURSE["slug"]
TOTAL_CHAPTERS = len(COURSE["chapters"])


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
    # Complétion FORTE (Phase 1) : répond à tous les items de tous les chapitres puis valide
    # explicitement chacun via /chapter/<n>/complete — la simple visite de page ne suffit plus.
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


def _pass_the_exam(email):
    # Insertion directe d'une tentative réussie (accounts/exam.py), sans repasser par le tirage
    # aléatoire de /course/<slug>/exam — la mécanique de l'examen est déjà testée à part
    # (tests/test_accounts_exam_routes.py) ; ici on ne teste que le GATE de l'attestation.
    from accounts.exam import record_attempt

    record_attempt(email, COURSE_SLUG, score_percent=90, total=10, passed=True)


def _fail_the_exam(email):
    from accounts.exam import record_attempt

    record_attempt(email, COURSE_SLUG, score_percent=40, total=10, passed=False)


# --- PARTIE A : suivi de visite via /chapter/<n> (accounts/progress.py, inchangé) --------------
# Ne délivre plus d'attestation (voir PARTIE B) mais reste utilisé pour ce suivi léger.


def test_chapter_visit_by_a_buyer_is_recorded(client):
    email = "buyer1@example.com"
    _grant_access_via_mock_checkout(client, email)

    client.get("/chapter/1")

    assert count_visited_chapters(email, COURSE_SLUG) == 1


def test_revisiting_a_chapter_does_not_create_a_duplicate(client):
    email = "buyer2@example.com"
    _grant_access_via_mock_checkout(client, email)

    client.get("/chapter/1")
    client.get("/chapter/1")
    client.get("/chapter/1")

    assert count_visited_chapters(email, COURSE_SLUG) == 1


def test_visiting_a_chapter_without_access_records_nothing(client):
    resp = client.get("/chapter/1")
    assert resp.status_code == 302
    assert count_visited_chapters("", COURSE_SLUG) == 0


# --- PARTIE B : gate verrouillé (accès + complétion FORTE + examen réussi) ---------------------


def test_generate_certificate_redirects_to_landing_without_access(client):
    resp = client.get(f"/certificate/generate/{COURSE_SLUG}")
    assert resp.status_code == 302
    assert resp.headers["Location"] == f"/cours/{COURSE_SLUG}"


def test_generate_certificate_unknown_slug_is_404(client):
    resp = client.get("/certificate/generate/un-autre-cours")
    assert resp.status_code == 404


def test_generate_certificate_locked_when_chapters_incomplete(client):
    email = "incomplete@example.com"
    _grant_access_via_mock_checkout(client, email)
    client.get("/chapter/1")  # simple visite, ne compte plus pour rien ici

    resp = client.get(f"/certificate/generate/{COURSE_SLUG}")

    assert resp.status_code == 200
    assert "Pas encore accessible".encode() in resp.data
    assert "pdf" not in resp.headers.get("Content-Type", "").lower()


def test_generate_certificate_locked_when_chapters_complete_but_exam_never_taken(client):
    email = "noexam@example.com"
    _grant_access_via_mock_checkout(client, email)
    _complete_all_chapters(client)
    # Aucune tentative d'examen : toujours verrouillé malgré la complétion des chapitres.

    resp = client.get(f"/certificate/generate/{COURSE_SLUG}")

    assert resp.status_code == 200
    assert "Pas encore accessible".encode() in resp.data


def test_generate_certificate_locked_when_exam_failed_only(client):
    email = "examfailed@example.com"
    _grant_access_via_mock_checkout(client, email)
    _complete_all_chapters(client)
    _fail_the_exam(email)

    resp = client.get(f"/certificate/generate/{COURSE_SLUG}")

    assert resp.status_code == 200
    assert "Pas encore accessible".encode() in resp.data


def test_generate_certificate_post_also_refused_when_not_eligible(client):
    # Le refus est SERVEUR sur le POST aussi, pas seulement sur l'affichage du formulaire GET.
    email = "posteligible@example.com"
    _grant_access_via_mock_checkout(client, email)

    resp = client.post(f"/certificate/generate/{COURSE_SLUG}", data={"learner_name": "Peu importe"})

    assert resp.status_code == 200
    assert "Pas encore accessible".encode() in resp.data
    assert b"%PDF" not in resp.data


def test_generate_certificate_form_prefills_google_name_from_session(client):
    email = "googleuser@example.com"
    _grant_access_via_mock_checkout(client, email)
    _complete_all_chapters(client)
    _pass_the_exam(email)
    with client.session_transaction() as sess:
        sess["google_name"] = "Alice Dupont"

    resp = client.get(f"/certificate/generate/{COURSE_SLUG}")
    assert resp.status_code == 200
    assert b"Alice Dupont" in resp.data


def test_generate_certificate_rejects_empty_name(client):
    email = "buyer3@example.com"
    _grant_access_via_mock_checkout(client, email)
    _complete_all_chapters(client)
    _pass_the_exam(email)

    resp = client.post(f"/certificate/generate/{COURSE_SLUG}", data={"learner_name": "   "})
    assert resp.status_code == 400
    assert "pdf" not in resp.headers.get("Content-Type", "").lower()


def test_generate_certificate_succeeds_and_redirects_to_verify_page(client):
    email = "graduate@example.com"
    _grant_access_via_mock_checkout(client, email)
    _complete_all_chapters(client)
    _pass_the_exam(email)

    resp = client.post(f"/certificate/generate/{COURSE_SLUG}", data={"learner_name": "Jean Dupont"})

    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("/certificate/")
    assert "/generate/" not in resp.headers["Location"]

    verify_resp = client.get(resp.headers["Location"])
    assert verify_resp.status_code == 200
    assert b"Jean Dupont" in verify_resp.data
    assert b"%PDF" not in verify_resp.data  # page HTML, pas le flux binaire du PDF


def test_certificate_is_actually_issued_in_db_with_correct_data(client):
    email = "graduate2@example.com"
    _grant_access_via_mock_checkout(client, email)
    _complete_all_chapters(client)
    _pass_the_exam(email)

    client.post(f"/certificate/generate/{COURSE_SLUG}", data={"learner_name": "Jean Dupont"})

    from accounts import db
    from accounts.models import Certificate

    with db.SessionLocal() as session:
        certificate = session.query(Certificate).filter(Certificate.email == email).first()

    assert certificate is not None
    assert certificate.learner_name == "Jean Dupont"
    assert certificate.course_title == COURSE["title"]
    assert certificate.course_slug == COURSE_SLUG


# --- page de vérification publique (sans session) -----------------------------------------------


def _issue_a_certificate(client):
    email = "verified@example.com"
    _grant_access_via_mock_checkout(client, email)
    _complete_all_chapters(client)
    _pass_the_exam(email)
    client.post(f"/certificate/generate/{COURSE_SLUG}", data={"learner_name": "Marie Curie"})

    from accounts import db
    from accounts.models import Certificate

    with db.SessionLocal() as session:
        certificate = session.query(Certificate).filter(Certificate.email == email).first()
        return certificate.token, email


def test_verify_page_is_public_and_shows_certificate_details(client):
    token, _email = _issue_a_certificate(client)

    with client.session_transaction() as sess:
        sess.clear()  # aucune session requise pour la vérification

    resp = client.get(f"/certificate/{token}")
    assert resp.status_code == 200
    assert b"Marie Curie" in resp.data
    assert COURSE["title"].encode() in resp.data


def test_verify_page_never_exposes_the_email(client):
    token, email = _issue_a_certificate(client)

    resp = client.get(f"/certificate/{token}")
    assert email.encode() not in resp.data


def test_verify_unknown_token_is_a_clean_404(client):
    resp = client.get("/certificate/does-not-exist")
    assert resp.status_code == 404


def test_download_pdf_is_public_and_returns_a_pdf(client):
    token, _email = _issue_a_certificate(client)

    with client.session_transaction() as sess:
        sess.clear()

    resp = client.get(f"/certificate/{token}/pdf")
    assert resp.status_code == 200
    assert resp.headers["Content-Type"] == "application/pdf"
    assert resp.data.startswith(b"%PDF")


# --- bouton LinkedIn, bien visible sur la page affichée après génération ------------------------


def test_verify_page_linkedin_button_has_expected_parameters(client):
    token, _email = _issue_a_certificate(client)

    resp = client.get(f"/certificate/{token}")
    match = re.search(rb'href="(https://www\.linkedin\.com/profile/add\?[^"]+)"', resp.data)
    assert match is not None
    linkedin_url = match.group(1).decode().replace("&amp;", "&")

    query = parse_qs(urlparse(linkedin_url).query)
    assert query["startTask"] == ["CERTIFICATION_NAME"]
    assert query["name"] == [COURSE["title"]]
    assert query["organizationName"] == ["AI Edu Platform"]
    assert query["certId"] == [token]
    assert query["certUrl"] == [f"http://localhost/certificate/{token}"]


def test_verify_page_linkedin_button_is_prominently_displayed(client):
    token, _email = _issue_a_certificate(client)

    resp = client.get(f"/certificate/{token}")
    assert "Partager sur LinkedIn".encode() in resp.data
    assert b"btn-linkedin" in resp.data


def test_generate_success_page_shows_linkedin_button_immediately(client):
    # Le bouton doit être visible SUR LA PAGE affichée juste après la génération (pas seulement
    # en revenant plus tard sur l'URL de vérification) — voir le garde-fou explicite.
    email = "sharenow@example.com"
    _grant_access_via_mock_checkout(client, email)
    _complete_all_chapters(client)
    _pass_the_exam(email)

    generate_resp = client.post(f"/certificate/generate/{COURSE_SLUG}", data={"learner_name": "Nadia Belkacem"})
    result_page = client.get(generate_resp.headers["Location"])

    assert "Partager sur LinkedIn".encode() in result_page.data
    assert "Nadia Belkacem".encode() in result_page.data
