"""Tests du flux "Se connecter avec Google" (accounts/oauth.py, accounts/routes.py).

Le fournisseur Google est TOUJOURS mocké : `oauth.google.authorize_redirect` et
`oauth.google.authorize_access_token` sont remplacés — aucun appel réseau réel vers Google n'est
jamais fait par ces tests. Les identifiants (`GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`) sont des
valeurs de test factices posées via `monkeypatch.setenv`, jamais les vraies (qui vivent dans
`.env`, gitignored)."""

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from accounts.db import Base
from bloc4_publication.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Identifiants Google FACTICES — juste assez pour que accounts/oauth.py::init_oauth
    # enregistre un client Authlib réel (aucun appel réseau tant qu'on ne l'utilise pas), afin de
    # pouvoir mocker ses méthodes (authorize_redirect/authorize_access_token) ci-dessous.
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")

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


def _fake_token(email, email_verified=True, sub="google-sub-123", **extra_userinfo):
    userinfo = {"sub": sub, "email": email, "email_verified": email_verified, "name": "Test User"}
    userinfo.update(extra_userinfo)
    return {"access_token": "fake-access-token", "userinfo": userinfo}


def _count_users_with_email(email):
    from accounts import db
    from accounts.models import User

    with db.SessionLocal() as session:
        return session.query(User).filter(User.email == email).count()


# --- /login/google : redirige vers Google (mocké) -----------------------------------------------


def test_login_google_redirects_to_google_when_configured(client):
    with patch("accounts.oauth.oauth.google.authorize_redirect") as mock_redirect:
        mock_redirect.return_value = "fake-redirect-response"
        resp = client.get("/login/google")

    assert resp.status_code == 200
    assert resp.data == b"fake-redirect-response"
    mock_redirect.assert_called_once()
    called_redirect_uri = mock_redirect.call_args.args[0]
    assert called_redirect_uri.endswith("/login/google/callback")


def test_login_google_stores_a_safe_next_in_session_before_redirecting(client):
    with patch("accounts.oauth.oauth.google.authorize_redirect", return_value="ok"):
        client.get("/login/google?next=/chapter/2")

    with client.session_transaction() as sess:
        assert sess["oauth_next"] == "/chapter/2"


def test_login_google_never_stores_an_unsafe_next_in_session(client):
    with patch("accounts.oauth.oauth.google.authorize_redirect", return_value="ok"):
        client.get("/login/google?next=https://evil.com")

    with client.session_transaction() as sess:
        assert sess["oauth_next"] == ""


# --- désactivation propre quand Google n'est pas configuré ---------------------------------------


def test_login_google_is_404_when_not_configured(client, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    resp = client.get("/login/google")
    assert resp.status_code == 404


def test_google_callback_is_404_when_not_configured(client, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    resp = client.get("/login/google/callback")
    assert resp.status_code == 404


def test_login_page_hides_the_google_button_when_not_configured(client, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    resp = client.get("/login")
    assert b"Continuer avec Google" not in resp.data


def test_login_page_shows_the_google_button_when_configured(client):
    resp = client.get("/login")
    assert b"Continuer avec Google" in resp.data


def test_register_page_shows_the_google_button_when_configured(client):
    resp = client.get("/register")
    assert b"Continuer avec Google" in resp.data


# --- /login/google/callback : nouvel utilisateur -------------------------------------------------


def test_google_callback_creates_a_new_user_with_no_password(client):
    with patch(
        "accounts.oauth.oauth.google.authorize_access_token",
        return_value=_fake_token("newgoogleuser@example.com", sub="sub-new"),
    ):
        resp = client.get("/login/google/callback")

    assert resp.status_code == 302
    with client.session_transaction() as sess:
        assert sess["email"] == "newgoogleuser@example.com"

    from accounts import db
    from accounts.models import User

    with db.SessionLocal() as session:
        user = session.query(User).filter(User.email == "newgoogleuser@example.com").first()
        assert user is not None
        assert user.password_hash is None
        assert user.google_sub == "sub-new"


def test_google_callback_redirects_to_home_by_default(client):
    with patch(
        "accounts.oauth.oauth.google.authorize_access_token",
        return_value=_fake_token("defaulttarget@example.com"),
    ):
        resp = client.get("/login/google/callback")
    assert resp.headers["Location"] == "/"


def test_google_callback_redirects_to_the_next_path_captured_before_the_roundtrip(client):
    with patch("accounts.oauth.oauth.google.authorize_redirect", return_value="ok"):
        client.get("/login/google?next=/chapter/2")

    with patch(
        "accounts.oauth.oauth.google.authorize_access_token",
        return_value=_fake_token("nextflow@example.com"),
    ):
        resp = client.get("/login/google/callback")

    assert resp.headers["Location"] == "/chapter/2"


# --- /login/google/callback : réconciliation par email (le point critique) -----------------------


def test_google_callback_links_to_an_existing_email_password_account_without_duplicating(client):
    client.post("/register", data={"email": "existingaccount@example.com", "password": "originalpass1"})
    client.post("/logout")
    assert _count_users_with_email("existingaccount@example.com") == 1

    with patch(
        "accounts.oauth.oauth.google.authorize_access_token",
        return_value=_fake_token("existingaccount@example.com", sub="sub-existing"),
    ):
        resp = client.get("/login/google/callback")

    assert resp.status_code == 302
    with client.session_transaction() as sess:
        assert sess["email"] == "existingaccount@example.com"

    # Toujours un seul compte pour cet email — pas de doublon créé par la connexion Google.
    assert _count_users_with_email("existingaccount@example.com") == 1

    # Le mot de passe existant continue de fonctionner après la liaison Google.
    from accounts.service import authenticate_user

    assert authenticate_user("existingaccount@example.com", "originalpass1") is not None


def test_google_callback_reconciles_regardless_of_email_case(client):
    client.post("/register", data={"email": "casetest@example.com", "password": "originalpass1"})
    client.post("/logout")

    with patch(
        "accounts.oauth.oauth.google.authorize_access_token",
        return_value=_fake_token("CaseTest@Example.com", sub="sub-case"),
    ):
        client.get("/login/google/callback")

    assert _count_users_with_email("casetest@example.com") == 1


def test_second_google_login_reuses_the_same_account(client):
    with patch(
        "accounts.oauth.oauth.google.authorize_access_token",
        return_value=_fake_token("returning@example.com", sub="sub-returning"),
    ):
        client.get("/login/google/callback")
        client.post("/logout")
        client.get("/login/google/callback")

    assert _count_users_with_email("returning@example.com") == 1


# --- /login/google/callback : email non vérifié refusé -------------------------------------------


def test_google_callback_rejects_an_unverified_email(client):
    with patch(
        "accounts.oauth.oauth.google.authorize_access_token",
        return_value=_fake_token("unverified@example.com", email_verified=False),
    ):
        resp = client.get("/login/google/callback")

    assert resp.status_code == 400
    assert _count_users_with_email("unverified@example.com") == 0
    with client.session_transaction() as sess:
        assert "email" not in sess


def test_google_callback_rejects_a_response_with_no_userinfo(client):
    with patch("accounts.oauth.oauth.google.authorize_access_token", return_value={"access_token": "x"}):
        resp = client.get("/login/google/callback")
    assert resp.status_code == 400


# --- /login/google/callback : erreur OAuth (state invalide, etc.) --------------------------------


def test_google_callback_handles_an_oauth_error_gracefully(client):
    from authlib.integrations.base_client.errors import OAuthError

    with patch("accounts.oauth.oauth.google.authorize_access_token", side_effect=OAuthError("mismatching_state")):
        resp = client.get("/login/google/callback")

    assert resp.status_code == 400
    with client.session_transaction() as sess:
        assert "email" not in sess
