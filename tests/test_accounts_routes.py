"""Tests des routes Flask du module comptes : inscription, connexion, déconnexion,
réinitialisation de mot de passe. Base de comptes isolée par test, en plus des patches habituels
(ACCESS_STORE_FILE, pricing) pour ne toucher aucun fichier réel du projet."""

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from accounts.db import Base
from bloc4_publication.app import create_app


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


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    import accounts.routes as routes_module

    for limiter in (
        routes_module._login_rate_limiter,
        routes_module._register_rate_limiter,
        routes_module._reset_rate_limiter,
    ):
        limiter._hits.clear()
    yield
    for limiter in (
        routes_module._login_rate_limiter,
        routes_module._register_rate_limiter,
        routes_module._reset_rate_limiter,
    ):
        limiter._hits.clear()


# --- _safe_next_path (protection anti open-redirect) -------------------------------------------


def test_safe_next_path_accepts_a_simple_internal_path():
    from accounts.routes import _safe_next_path

    assert _safe_next_path("/chapter/2") == "/chapter/2"


def test_safe_next_path_accepts_an_internal_path_with_query_string():
    from accounts.routes import _safe_next_path

    assert _safe_next_path("/cours?ref=login") == "/cours?ref=login"


def test_safe_next_path_rejects_none_and_empty_string():
    from accounts.routes import _safe_next_path

    assert _safe_next_path(None) is None
    assert _safe_next_path("") is None


@pytest.mark.parametrize(
    "unsafe",
    [
        "https://evil.com",
        "http://evil.com/steal",
        "//evil.com",
        "evil.com",
        "javascript:alert(1)",
        "ftp://evil.com",
    ],
)
def test_safe_next_path_rejects_absolute_and_protocol_relative_urls(unsafe):
    from accounts.routes import _safe_next_path

    assert _safe_next_path(unsafe) is None


# --- inscription -----------------------------------------------------------------------------


def test_register_page_loads(client):
    resp = client.get("/register")
    assert resp.status_code == 200
    assert "Créer un compte".encode() in resp.data


def test_register_creates_account_and_logs_in(client):
    resp = client.post("/register", data={"email": "newuser@example.com", "password": "supersecret1"})
    assert resp.status_code == 302
    # Jamais une URL de cours (voir accounts/routes.py) : /course est gardée par has_access, un
    # compte fraîchement créé (donc sans achat) y serait aussitôt redirigé plus loin.
    assert resp.headers["Location"] == "/"

    with client.session_transaction() as sess:
        assert sess["email"] == "newuser@example.com"


def test_register_redirects_to_a_safe_next_path_when_provided(client):
    resp = client.post(
        "/register",
        data={"email": "nextuser@example.com", "password": "supersecret1", "next": "/cours"},
    )
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/cours"


def test_register_falls_back_to_home_when_next_is_an_external_url(client):
    resp = client.post(
        "/register",
        data={"email": "evilnext@example.com", "password": "supersecret1", "next": "https://evil.com"},
    )
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"


def test_register_page_embeds_the_next_value_in_a_hidden_field(client):
    resp = client.get("/register?next=/chapter/2")
    assert b'name="next" value="/chapter/2"' in resp.data


# --- retour post-paiement Paddle (voir bloc4_publication/templates/landing.html, successUrl) ----


def test_register_prefills_email_from_query_param(client):
    resp = client.get("/register?email=buyer@example.com")
    assert resp.status_code == 200
    assert b'value="buyer@example.com"' in resp.data


def test_register_redirects_to_login_when_account_already_exists_for_email(client):
    client.post("/register", data={"email": "existing@example.com", "password": "supersecret1"})
    with client.session_transaction() as sess:
        sess.clear()  # le POST précédent a connecté ce client — on simule un nouveau visiteur

    resp = client.get("/register?email=existing@example.com")

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/login?email=existing@example.com"


def test_register_redirect_to_login_preserves_next(client):
    client.post("/register", data={"email": "existing2@example.com", "password": "supersecret1"})
    with client.session_transaction() as sess:
        sess.clear()

    resp = client.get("/register?email=existing2@example.com&next=/cours")

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/login?email=existing2@example.com&next=/cours"


def test_register_shows_form_when_email_provided_but_no_account_exists(client):
    resp = client.get("/register?email=newpayer@example.com")

    assert resp.status_code == 200
    assert "Créer un compte".encode() in resp.data
    assert b'value="newpayer@example.com"' in resp.data


def test_login_prefills_email_from_query_param(client):
    resp = client.get("/login?email=buyer@example.com")
    assert resp.status_code == 200
    assert b'value="buyer@example.com"' in resp.data


def test_register_rejects_duplicate_email(client):
    client.post("/register", data={"email": "dupe@example.com", "password": "supersecret1"})
    resp = client.post("/register", data={"email": "dupe@example.com", "password": "anotherpass1"})
    assert resp.status_code == 400
    assert "existe déjà".encode() in resp.data


def test_register_rejects_invalid_email(client):
    resp = client.post("/register", data={"email": "not-an-email", "password": "supersecret1"})
    assert resp.status_code == 400


def test_register_rejects_short_password(client):
    resp = client.post("/register", data={"email": "shortpw@example.com", "password": "short"})
    assert resp.status_code == 400


def test_register_rate_limits_repeated_attempts_from_the_same_ip(client):
    from accounts.routes import _register_rate_limiter

    for i in range(_register_rate_limiter.max_requests):
        resp = client.post("/register", data={"email": f"ratelimited{i}@example.com", "password": "supersecret1"})
        assert resp.status_code == 302

    resp = client.post("/register", data={"email": "oneTooMany@example.com", "password": "supersecret1"})
    assert resp.status_code == 429


# --- connexion --------------------------------------------------------------------------------


def test_login_page_loads(client):
    resp = client.get("/login")
    assert resp.status_code == 200


def test_login_succeeds_with_correct_credentials(client):
    client.post("/register", data={"email": "loginme@example.com", "password": "correctpass1"})
    client.post("/logout")

    resp = client.post("/login", data={"email": "loginme@example.com", "password": "correctpass1"})
    assert resp.status_code == 302
    # Jamais une URL de cours — voir test_register_creates_account_and_logs_in.
    assert resp.headers["Location"] == "/"
    with client.session_transaction() as sess:
        assert sess["email"] == "loginme@example.com"


def test_login_redirects_to_a_safe_next_path_when_provided(client):
    client.post("/register", data={"email": "loginnext@example.com", "password": "correctpass1"})
    client.post("/logout")

    resp = client.post(
        "/login",
        data={"email": "loginnext@example.com", "password": "correctpass1", "next": "/chapter/2"},
    )
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/chapter/2"


@pytest.mark.parametrize(
    "unsafe_next",
    [
        "https://evil.com",
        "http://evil.com/steal",
        "//evil.com",
        "evil.com",
        "javascript:alert(1)",
    ],
)
def test_login_falls_back_to_home_for_any_unsafe_next_value(client, unsafe_next):
    client.post("/register", data={"email": "unsafenext@example.com", "password": "correctpass1"})
    client.post("/logout")

    resp = client.post(
        "/login",
        data={"email": "unsafenext@example.com", "password": "correctpass1", "next": unsafe_next},
    )
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"


def test_login_page_embeds_the_next_value_in_a_hidden_field(client):
    resp = client.get("/login?next=/chapter/3")
    assert b'name="next" value="/chapter/3"' in resp.data


def test_login_rejects_wrong_password_with_generic_error(client):
    client.post("/register", data={"email": "wrongpw@example.com", "password": "correctpass1"})
    client.post("/logout")

    resp = client.post("/login", data={"email": "wrongpw@example.com", "password": "incorrectpass"})
    assert resp.status_code == 400
    assert "Email ou mot de passe incorrect.".encode() in resp.data


def test_login_rejects_unknown_email_with_the_same_generic_error(client):
    resp = client.post("/login", data={"email": "neverregistered@example.com", "password": "whatever123"})
    assert resp.status_code == 400
    assert "Email ou mot de passe incorrect.".encode() in resp.data


def test_login_error_is_identical_for_unknown_email_and_wrong_password(client):
    # Anti-énumération : les deux échecs doivent produire EXACTEMENT le même statut et le même
    # message, pour qu'on ne puisse jamais distinguer "email inconnu" de "mauvais mot de passe".
    client.post("/register", data={"email": "enum@example.com", "password": "correctpass1"})
    client.post("/logout")

    wrong_password_resp = client.post("/login", data={"email": "enum@example.com", "password": "wrongpass"})
    unknown_email_resp = client.post("/login", data={"email": "neverexisted@example.com", "password": "wrongpass"})

    assert wrong_password_resp.status_code == unknown_email_resp.status_code == 400
    assert "Email ou mot de passe incorrect.".encode() in wrong_password_resp.data
    assert "Email ou mot de passe incorrect.".encode() in unknown_email_resp.data


def test_login_rate_limits_repeated_attempts_from_the_same_ip(client):
    from accounts.routes import _login_rate_limiter

    for _ in range(_login_rate_limiter.max_requests):
        resp = client.post("/login", data={"email": "ratelimit@example.com", "password": "wrongpass"})
        assert resp.status_code == 400

    resp = client.post("/login", data={"email": "ratelimit@example.com", "password": "wrongpass"})
    assert resp.status_code == 429


# --- déconnexion -----------------------------------------------------------------------------


def test_logout_clears_the_session(client):
    client.post("/register", data={"email": "logoutme@example.com", "password": "correctpass1"})
    resp = client.post("/logout")
    assert resp.status_code == 302
    with client.session_transaction() as sess:
        assert "email" not in sess


def test_logout_requires_post(client):
    resp = client.get("/logout")
    assert resp.status_code == 405


# --- réinitialisation de mot de passe ---------------------------------------------------------


def test_reset_password_request_shows_the_same_generic_message_for_known_and_unknown_email(client):
    client.post("/register", data={"email": "willexist@example.com", "password": "originalpass1"})
    client.post("/logout")

    resp_known = client.post("/reset-password", data={"email": "willexist@example.com"})
    resp_unknown = client.post("/reset-password", data={"email": "neverexisted@example.com"})
    assert "Si un compte existe".encode() in resp_known.data
    assert "Si un compte existe".encode() in resp_unknown.data


@patch("accounts.routes.send_password_reset_email")
def test_reset_password_request_sends_the_email_only_for_an_existing_account(mock_send, client):
    client.post("/register", data={"email": "hasaccount@example.com", "password": "originalpass1"})
    client.post("/logout")

    client.post("/reset-password", data={"email": "hasaccount@example.com"})
    mock_send.assert_called_once()
    assert mock_send.call_args.args[0] == "hasaccount@example.com"

    mock_send.reset_mock()
    client.post("/reset-password", data={"email": "neverexisted@example.com"})
    mock_send.assert_not_called()


def test_reset_password_request_rate_limits_repeated_attempts(client):
    from accounts.routes import _reset_rate_limiter

    for _ in range(_reset_rate_limiter.max_requests):
        resp = client.post("/reset-password", data={"email": "someone@example.com"})
        assert resp.status_code == 200

    resp = client.post("/reset-password", data={"email": "someone@example.com"})
    assert resp.status_code == 429


def test_full_password_reset_flow_allows_login_with_the_new_password(client):
    client.post("/register", data={"email": "fullflow@example.com", "password": "originalpass1"})
    client.post("/logout")

    from accounts.service import request_password_reset

    token = request_password_reset("fullflow@example.com")
    confirm_resp = client.post(f"/reset-password/{token}", data={"password": "brandnewpass1"})
    assert confirm_resp.status_code == 302

    login_resp = client.post("/login", data={"email": "fullflow@example.com", "password": "brandnewpass1"})
    assert login_resp.status_code == 302
    assert login_resp.headers["Location"] == "/"

    old_password_resp = client.post("/login", data={"email": "fullflow@example.com", "password": "originalpass1"})
    assert old_password_resp.status_code == 400


def test_reset_password_confirm_page_rejects_an_invalid_token(client):
    resp = client.get("/reset-password/not-a-real-token")
    assert resp.status_code == 400
