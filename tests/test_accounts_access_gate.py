"""Garde-fou de sécurité ajouté avec les comptes (accounts/routes.py) : un compte enregistré (mot
de passe correct) mais qui n'a JAMAIS acheté le cours ne doit jamais accéder au contenu payant.

Avant les comptes, `session.get("email")` truthy impliquait forcément "a payé" (seule façon de le
poser : /access/<token>, atteignable seulement après un achat). Avec `/login`, ce n'est plus vrai
— voir bloc4_publication/app.py::_has_paid_access et bloc6_chatbot/course_routes.py, qui vérifient
maintenant explicitement `access_store.has_access(email)` en plus de la présence de l'email."""

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


def _register_without_buying(client, email, password="supersecret1"):
    client.post("/register", data={"email": email, "password": password})


def _buy_as(client, email):
    start = client.get(f"/checkout/start?email={email}")
    transaction_id = start.headers["Location"].split("/checkout/mock/")[1].split("?")[0]
    client.post(f"/checkout/mock/{transaction_id}/complete", data={"email": email})


# --- compte sans achat : refusé partout --------------------------------------------------------


def test_registered_user_without_purchase_is_redirected_from_course_home(client):
    _register_without_buying(client, "noaccess1@example.com")
    resp = client.get("/course")
    assert resp.status_code == 302
    assert resp.headers["Location"] == f"/cours/{COURSE_SLUG}"


def test_registered_user_without_purchase_is_redirected_from_chapter(client):
    _register_without_buying(client, "noaccess2@example.com")
    resp = client.get("/chapter/1")
    assert resp.status_code == 302
    assert resp.headers["Location"] == f"/cours/{COURSE_SLUG}"


def test_registered_user_without_purchase_gets_403_on_exercise_correction(client):
    _register_without_buying(client, "noaccess3@example.com")
    resp = client.post("/chapter/1/exercise/3/correct", json={"answer": "ma réponse"})
    assert resp.status_code == 403


def test_registered_user_without_purchase_gets_403_on_practical_correction(client):
    _register_without_buying(client, "noaccess4@example.com")
    resp = client.post("/chapter/1/practical/correct", data={"answer": "ma solution"})
    assert resp.status_code == 403


def test_registered_user_without_purchase_gets_403_on_video(client):
    _register_without_buying(client, "noaccess5@example.com")
    resp = client.get("/video/chapter_1.mp4")
    assert resp.status_code == 403


def test_registered_user_without_purchase_gets_403_on_course_tutor(client):
    _register_without_buying(client, "noaccess6@example.com")
    resp = client.post(
        f"/api/chat/course/{COURSE_SLUG}", json={"messages": [{"role": "user", "content": "Bonjour"}]}
    )
    assert resp.status_code == 403


# --- réconciliation achat <-> compte : marche, y compris avec une casse différente ------------


def test_registered_user_who_also_bought_gets_full_access(client):
    email = "realbuyer@example.com"
    _register_without_buying(client, email)
    _buy_as(client, email)

    resp = client.post("/login", data={"email": email, "password": "supersecret1"})
    assert resp.status_code == 302

    course_resp = client.get("/course")
    assert course_resp.status_code == 200


def test_purchase_and_login_reconcile_even_with_different_email_case(client):
    _register_without_buying(client, "MixedCase@Example.com")
    _buy_as(client, "mixedcase@example.com")

    client.post("/login", data={"email": "MIXEDCASE@EXAMPLE.COM", "password": "supersecret1"})
    resp = client.get("/course")
    assert resp.status_code == 200


def test_access_token_link_still_works_without_any_account(client):
    # Le mécanisme d'accès existant (achat -> lien /access/<token>, sans compte ni mot de passe)
    # doit continuer à fonctionner tel quel, sans qu'un compte ait jamais été créé.
    email = "noaccountatall@example.com"
    start = client.get(f"/checkout/start?email={email}")
    transaction_id = start.headers["Location"].split("/checkout/mock/")[1].split("?")[0]
    complete = client.post(f"/checkout/mock/{transaction_id}/complete", data={"email": email})
    match = re.search(rb'href="([^"]*/access/[^"]+)"', complete.data)
    access_url = match.group(1).decode()
    client.get(access_url)

    resp = client.get("/course")
    assert resp.status_code == 200
