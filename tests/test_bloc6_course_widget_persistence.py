"""Persistance côté navigateur (localStorage) de l'historique du tuteur par cours.

Aucune logique serveur nouvelle ici (le serveur reste sans état, voir course_routes.py) — ces
tests vérifient seulement que les pages de lecture rendent bien les ingrédients dont le JS du
widget a besoin pour construire une clé de stockage scopée par utilisateur ET par cours, et le
bouton "Effacer la conversation". Le comportement JS (sauvegarde/restauration/validation du JSON
stocké) n'est pas exécutable depuis la suite pytest (pas de runtime JS ici) — voir
_course_chat_widget.html pour cette logique."""

import re
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from accounts.db import Base
from bloc4_publication.app import create_app
from bloc4_publication.content_loader import load_course

COURSE_SLUG = load_course()["slug"]


@pytest.fixture
def client(tmp_path):
    # /chapter/<n> enregistre désormais la progression (accounts/progress.py) sur accounts.db —
    # même isolation que test_accounts_access_gate.py, sinon ce test polluerait la vraie base.
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


def test_chapter_page_embeds_the_storage_key_prefix_and_course_slug(client):
    _grant_access_via_mock_checkout(client, "buyer@example.com")
    resp = client.get("/chapter/1")
    html = resp.data.decode("utf-8")
    assert "tutor_history:" in html
    assert COURSE_SLUG in html


def test_chapter_page_embeds_the_authenticated_buyer_email_for_key_scoping(client):
    _grant_access_via_mock_checkout(client, "scoped-buyer@example.com")
    resp = client.get("/chapter/1")
    html = resp.data.decode("utf-8")
    assert "scoped-buyer@example.com" in html


def test_course_home_page_embeds_the_storage_key_prefix_and_buyer_email(client):
    _grant_access_via_mock_checkout(client, "homebuyer@example.com")
    resp = client.get("/course")
    html = resp.data.decode("utf-8")
    assert "tutor_history:" in html
    assert "homebuyer@example.com" in html


def test_chapter_page_includes_the_clear_conversation_button(client):
    _grant_access_via_mock_checkout(client, "clearbtn@example.com")
    resp = client.get("/chapter/1")
    html = resp.data.decode("utf-8")
    assert 'id="course-chat-clear"' in html
    assert "Effacer la conversation" in html


def test_two_different_buyers_get_different_embedded_emails_in_the_storage_key(client):
    # Preuve indirecte que la clé ne peut pas être partagée entre deux comptes sur le même
    # navigateur : chaque page rendue embarque l'email du compte réellement connecté à cet
    # instant, jamais un email générique ou celui d'un autre visiteur.
    _grant_access_via_mock_checkout(client, "first@example.com")
    first_html = client.get("/chapter/1").data.decode("utf-8")
    assert "first@example.com" in first_html

    with client.session_transaction() as sess:
        sess.clear()

    _grant_access_via_mock_checkout(client, "second@example.com")
    second_html = client.get("/chapter/1").data.decode("utf-8")
    assert "second@example.com" in second_html
    assert "first@example.com" not in second_html


def test_general_chat_widget_is_untouched_by_persistence_changes(client):
    # Garde-fou de non-régression : la consigne était explicite ("NE touche PAS au bot général").
    resp = client.get("/")
    html = resp.data.decode("utf-8")
    assert "tutor_history" not in html
    assert "course-chat-clear" not in html
