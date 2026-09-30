"""Tests multi-cours pour bloc4_publication/app.py (Changement 4, Étapes C et D) : catalogue
dynamique, course_landing par slug inconnu/connu, course_home avec 0/1/2 cours achetés,
checkout_start avec/sans slug, webhook Paddle multi-cours — SANS jamais changer le comportement
du cours 1 seul (voir test_bloc4_app.py pour ces garanties, non dupliquées ici)."""

import json
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from accounts.db import Base
from bloc4_publication.access_store import SLUG_COURS_1, grant_access
from bloc4_publication.config import DEFAULT_CONTENT_FILE, DEFAULT_CURRICULUM_FILE

SECOND_COURSE_SLUG = "excel-avance-pour-managers"
SECOND_COURSE_TITLE = "Excel avancé pour managers"

SECOND_CURRICULUM = {
    "title": SECOND_COURSE_TITLE,
    "niche": "Excel avancé",
    "level": "intermédiaire",
    "prerequisites": "Bases d'Excel.",
    "source_topic": {"title": SECOND_COURSE_TITLE, "gap_reason": "Demande réelle observée."},
    "chapters": [
        {
            "number": 1,
            "title": "Tableaux croisés dynamiques",
            "learning_objectives": ["obj1", "obj2"],
            "key_points": ["kp1"],
            "builds_on_previous": "N/A - premier chapitre",
        },
    ],
}

SECOND_CONTENT = {
    "course_title": SECOND_COURSE_TITLE,
    "niche": "Excel avancé",
    "level": "intermédiaire",
    "running_example": "Fil rouge",
    "chapters_content": [
        {
            "chapter_number": 1,
            "chapter_title": "Tableaux croisés dynamiques",
            "lesson_script": "Paragraphe suffisamment long pour la validation minimale attendue par le Bloc 2, "
            "largement au-dessus des deux cents caractères requis pour ce test de fixture.",
            "comprehension_exercises": [
                {"question": "Q1?", "type": "short_answer", "options": None, "correct_answer": "R1"},
                {"question": "Q2?", "type": "short_answer", "options": None, "correct_answer": "R2"},
                {"question": "Q3?", "type": "short_answer", "options": None, "correct_answer": "R3"},
            ],
            "practical_exercise": {
                "title": "Exercice",
                "instructions": "Fais ceci.",
                "expected_outcome": "Résultat.",
                "deliverables": ["Livrable"],
                "step_by_step_instructions": ["Étape"],
                "evaluation_criteria": ["Critère"],
            },
        },
    ],
}


@pytest.fixture
def multi_course_client(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    curriculum_path = data_dir / "second_curriculum.json"
    content_path = data_dir / "second_content.json"
    curriculum_path.write_text(json.dumps(SECOND_CURRICULUM), encoding="utf-8")
    content_path.write_text(json.dumps(SECOND_CONTENT), encoding="utf-8")

    published = {
        "courses": [
            {
                "slug": SLUG_COURS_1,
                "title": "Agents IA en production",
                "domain": "AI Automation",
                "price_usd": 15.0,
                "paddle_price_id": "pri_cours1",
                "curriculum_file": str(DEFAULT_CURRICULUM_FILE),
                "content_file": str(DEFAULT_CONTENT_FILE),
            },
            {
                "slug": SECOND_COURSE_SLUG,
                "title": SECOND_COURSE_TITLE,
                "domain": "Excel avancé",
                "price_usd": 19.99,
                "paddle_price_id": "pri_second",
                "curriculum_file": str(curriculum_path),
                "content_file": str(content_path),
            },
        ]
    }
    (data_dir / "published_courses.json").write_text(json.dumps(published), encoding="utf-8")

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
        patch("bloc4_publication.content_loader.DATA_DIR", data_dir),
        patch("pricing_agent.config.PRICING_STATE_FILE", tmp_path / "pricing_state.json"),
        patch("pricing_agent.config.SALES_LOG_FILE", tmp_path / "sales_log.json"),
    ):
        from bloc4_publication.app import create_app

        app = create_app()
        app.config.update(TESTING=True)
        with app.test_client() as test_client:
            yield test_client


def _set_session_email(client, email):
    with client.session_transaction() as sess:
        sess["email"] = email


# --- catalogue dynamique -------------------------------------------------------------------------


def test_catalog_page_lists_both_courses(multi_course_client):
    resp = multi_course_client.get("/cours")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    assert "Agents IA en production" in html
    assert SECOND_COURSE_TITLE in html
    assert f'href="/cours/{SLUG_COURS_1}"' in html
    assert f'href="/cours/{SECOND_COURSE_SLUG}"' in html


# --- course_landing par slug ----------------------------------------------------------------------


def test_course_landing_loads_for_the_second_course(multi_course_client):
    resp = multi_course_client.get(f"/cours/{SECOND_COURSE_SLUG}")
    assert resp.status_code == 200
    assert SECOND_COURSE_TITLE.encode() in resp.data
    assert "$19.99".encode() in resp.data


def test_course_landing_unknown_slug_is_still_404_with_multiple_courses(multi_course_client):
    resp = multi_course_client.get("/cours/un-slug-qui-nexiste-pas")
    assert resp.status_code == 404


def test_course_landing_course_1_still_uses_dynamic_pricing_not_catalog_price(multi_course_client):
    # Le cours 1 est aussi présent dans published_courses.json avec un price_usd figé (15.0) —
    # mais sa landing doit continuer à utiliser pricing_agent (comportement inchangé), pas cette
    # valeur du catalogue.
    resp = multi_course_client.get(f"/cours/{SLUG_COURS_1}")
    assert resp.status_code == 200
    assert "Acheter le cours".encode() in resp.data


def test_course_landing_already_purchased_second_course_links_straight_to_chapter_1(multi_course_client):
    email = "reader2@example.com"
    grant_access(email, SECOND_COURSE_SLUG)
    _set_session_email(multi_course_client, email)

    resp = multi_course_client.get(f"/cours/{SECOND_COURSE_SLUG}")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert "Continuer le cours" in html
    assert f'href="/cours/{SECOND_COURSE_SLUG}/chapitre/1"' in html
    assert "Acheter le cours" not in html


def test_course_landing_already_purchased_course_1_still_links_to_course_home(multi_course_client):
    # Comportement inchangé pour le cours 1 : le bouton "Continuer" mène à /course (le tableau de
    # bord riche, examen/attestation), pas directement au chapitre 1.
    email = "reader_c1@example.com"
    grant_access(email, SLUG_COURS_1)
    _set_session_email(multi_course_client, email)

    resp = multi_course_client.get(f"/cours/{SLUG_COURS_1}")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert "Continuer le cours" in html
    assert 'href="/course"' in html


# --- course_home : 0 / 1 / 2 cours achetés --------------------------------------------------------


def test_course_home_with_zero_courses_purchased_redirects_to_course_1_landing(multi_course_client):
    resp = multi_course_client.get("/course")
    assert resp.status_code == 302
    assert resp.headers["Location"] == f"/cours/{SLUG_COURS_1}"


def test_course_home_with_only_the_second_course_purchased_renders_readonly_dashboard(multi_course_client):
    # Avant fix : redirigeait vers /cours/<slug> (la page de VENTE du cours déjà acheté) — boucle
    # confuse pour l'acheteur (voir landing.html "Accéder au cours" -> /course -> ici -> retour à
    # la page de vente). Rend maintenant un tableau de bord (lecture seule, pas d'exercices —
    # voir course_chapter/chapter_readonly.html) au lieu de renvoyer vers la vente.
    email = "onlysecond@example.com"
    grant_access(email, SECOND_COURSE_SLUG)
    _set_session_email(multi_course_client, email)

    resp = multi_course_client.get("/course")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert SECOND_COURSE_TITLE in html
    assert f'href="/cours/{SECOND_COURSE_SLUG}/chapitre/1"' in html


def test_course_home_with_only_course_1_purchased_renders_dashboard_unchanged(multi_course_client):
    email = "onlycourse1@example.com"
    grant_access(email, SLUG_COURS_1)
    _set_session_email(multi_course_client, email)

    resp = multi_course_client.get("/course")
    assert resp.status_code == 200
    assert "Agents IA en production".encode() in resp.data


def test_course_home_with_both_courses_purchased_shows_a_list(multi_course_client):
    email = "bothcourses@example.com"
    grant_access(email, SLUG_COURS_1)
    grant_access(email, SECOND_COURSE_SLUG)
    _set_session_email(multi_course_client, email)

    resp = multi_course_client.get("/course")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    assert "Agents IA en production" in html
    assert SECOND_COURSE_TITLE in html


# --- Étape D : checkout_start avec/sans slug, webhook multi-cours --------------------------------


def test_checkout_start_with_valid_slug_uses_the_catalog_price_id(multi_course_client):
    with patch("bloc5_payment.routes.create_checkout") as mock_create_checkout:
        mock_create_checkout.return_value = {"checkout_url": "/checkout/mock/tx1?email=x", "mock": True, "transaction_id": "tx1"}
        multi_course_client.get(f"/checkout/start?email=buyer@example.com&slug={SECOND_COURSE_SLUG}")

    mock_create_checkout.assert_called_once_with("buyer@example.com", price_id="pri_second", amount_usd=19.99)


def test_checkout_start_without_slug_uses_current_dynamic_pricing_behavior(multi_course_client):
    from pricing_agent.pricing_state import get_current_price_id, get_current_price_usd

    with patch("bloc5_payment.routes.create_checkout") as mock_create_checkout:
        mock_create_checkout.return_value = {"checkout_url": "/checkout/mock/tx1?email=x", "mock": True, "transaction_id": "tx1"}
        multi_course_client.get("/checkout/start?email=buyer@example.com")

    mock_create_checkout.assert_called_once_with(
        "buyer@example.com", price_id=get_current_price_id(), amount_usd=get_current_price_usd()
    )


def test_checkout_start_with_course_1_slug_explicitly_still_uses_dynamic_pricing(multi_course_client):
    # Le cours 1 figure aussi dans published_courses.json (voir la fixture) avec un price_usd/
    # paddle_price_id FIGÉS — la landing du cours 1 passe désormais toujours son propre slug
    # (voir landing.html), donc ce cas doit rester identique au cas "sans slug" ci-dessus.
    from pricing_agent.pricing_state import get_current_price_id, get_current_price_usd

    with patch("bloc5_payment.routes.create_checkout") as mock_create_checkout:
        mock_create_checkout.return_value = {"checkout_url": "/checkout/mock/tx1?email=x", "mock": True, "transaction_id": "tx1"}
        multi_course_client.get(f"/checkout/start?email=buyer@example.com&slug={SLUG_COURS_1}")

    mock_create_checkout.assert_called_once_with(
        "buyer@example.com", price_id=get_current_price_id(), amount_usd=get_current_price_usd()
    )


def test_checkout_start_with_unknown_slug_falls_back_to_current_behavior(multi_course_client):
    from pricing_agent.pricing_state import get_current_price_id, get_current_price_usd

    with patch("bloc5_payment.routes.create_checkout") as mock_create_checkout:
        mock_create_checkout.return_value = {"checkout_url": "/checkout/mock/tx1?email=x", "mock": True, "transaction_id": "tx1"}
        multi_course_client.get("/checkout/start?email=buyer@example.com&slug=un-slug-inconnu")

    mock_create_checkout.assert_called_once_with(
        "buyer@example.com", price_id=get_current_price_id(), amount_usd=get_current_price_usd()
    )


def test_webhook_grants_access_to_the_second_course_via_its_price_id(multi_course_client):
    resp = multi_course_client.post(
        "/webhook/paddle",
        json={
            "event_type": "transaction.completed",
            "data": {
                "customer": {"email": "buyer2@example.com"},
                "items": [{"price": {"id": "pri_second"}, "quantity": 1}],
            },
        },
    )
    assert resp.status_code == 200

    from bloc4_publication.access_store import has_access

    assert has_access("buyer2@example.com", SECOND_COURSE_SLUG) is True
    assert has_access("buyer2@example.com", SLUG_COURS_1) is False


def test_webhook_with_unknown_price_id_still_falls_back_to_course_1(multi_course_client):
    resp = multi_course_client.post(
        "/webhook/paddle",
        json={
            "event_type": "transaction.completed",
            "data": {
                "customer": {"email": "buyer3@example.com"},
                "items": [{"price": {"id": "pri_totally_unknown"}, "quantity": 1}],
            },
        },
    )
    assert resp.status_code == 200

    from bloc4_publication.access_store import has_access

    assert has_access("buyer3@example.com", SLUG_COURS_1) is True


def test_course_chapter_unknown_slug_is_404(multi_course_client):
    resp = multi_course_client.get("/cours/un-slug-qui-nexiste-pas/chapitre/1")
    assert resp.status_code == 404


def test_course_chapter_without_access_redirects_to_landing(multi_course_client):
    resp = multi_course_client.get(f"/cours/{SECOND_COURSE_SLUG}/chapitre/1")
    assert resp.status_code == 302
    assert resp.headers["Location"] == f"/cours/{SECOND_COURSE_SLUG}"


def test_course_chapter_with_access_renders_readonly_content(multi_course_client):
    email = "reader@example.com"
    grant_access(email, SECOND_COURSE_SLUG)
    _set_session_email(multi_course_client, email)

    resp = multi_course_client.get(f"/cours/{SECOND_COURSE_SLUG}/chapitre/1")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert "Tableaux croisés dynamiques" in html
    assert "Paragraphe suffisamment long" in html
    # Lecture seule : aucun bloc exercice interactif câblé sur les routes /chapter/<n> du cours 1
    # (le nom "exercise-card"/"chapter-complete-block" apparaît aussi dans le JS partagé de
    # base_reading.html, présent sur toute page — on vérifie l'absence de l'ÉLÉMENT HTML réel,
    # pas juste de la sous-chaîne, sinon ce test serait toujours faux).
    assert 'class="exercise-card"' not in html
    assert 'class="chapter-complete-block"' not in html


def test_course_chapter_for_slug_cours_1_redirects_to_legacy_chapter_route(multi_course_client):
    email = "buyer_c1@example.com"
    grant_access(email, SLUG_COURS_1)
    _set_session_email(multi_course_client, email)

    resp = multi_course_client.get(f"/cours/{SLUG_COURS_1}/chapitre/1")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/chapter/1"
