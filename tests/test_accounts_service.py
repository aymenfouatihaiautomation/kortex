"""Tests unitaires de la logique métier des comptes (accounts/service.py).

Base SQLite temporaire isolée par test (voir `isolated_db`) — ne touche jamais au fichier
accounts.db réel du projet. Patch `accounts.db.engine`/`accounts.db.SessionLocal` (pas
`accounts.service.SessionLocal` : ce module importe `from accounts import db` et appelle
`db.SessionLocal()`, précisément pour rester patchable ainsi — voir accounts/db.py)."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from accounts.db import Base
from accounts.security import ValidationError, utcnow
from accounts.service import (
    EmailAlreadyRegisteredError,
    account_exists,
    authenticate_user,
    get_or_create_google_user,
    register_user,
    request_password_reset,
    reset_password,
    resolve_reset_token,
)


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


# --- register_user -------------------------------------------------------------------------------


def test_register_user_creates_a_user_with_hashed_password(isolated_db):
    user = register_user("New@Example.com", "supersecret1")
    assert user.email == "new@example.com"  # normalisé (strip + lower)
    assert user.password_hash != "supersecret1"
    assert user.id is not None


def test_register_user_rejects_invalid_email_format(isolated_db):
    with pytest.raises(ValidationError):
        register_user("pas-un-email", "supersecret1")


def test_register_user_rejects_password_below_minimum_length(isolated_db):
    with pytest.raises(ValidationError):
        register_user("valid@example.com", "short")


def test_register_user_rejects_an_already_registered_email(isolated_db):
    register_user("dupe@example.com", "supersecret1")
    with pytest.raises(EmailAlreadyRegisteredError):
        register_user("dupe@example.com", "anotherpass1")


def test_register_user_rejects_duplicate_email_regardless_of_case(isolated_db):
    register_user("Case@Example.com", "supersecret1")
    with pytest.raises(EmailAlreadyRegisteredError):
        register_user("case@example.com", "anotherpass1")


# --- account_exists (utilisé par accounts/routes.py::register pour le retour Paddle) -----------


def test_account_exists_false_when_no_account(isolated_db):
    assert account_exists("nobody@example.com") is False


def test_account_exists_true_after_registration(isolated_db):
    register_user("someone@example.com", "supersecret1")
    assert account_exists("someone@example.com") is True


def test_account_exists_is_case_insensitive(isolated_db):
    register_user("Someone@Example.com", "supersecret1")
    assert account_exists("someone@example.com") is True


def test_account_exists_true_for_a_google_only_account(isolated_db):
    get_or_create_google_user("googleuser@example.com", google_sub="sub-123")
    assert account_exists("googleuser@example.com") is True


# --- authenticate_user ----------------------------------------------------------------------------


def test_authenticate_user_succeeds_with_correct_password(isolated_db):
    register_user("auth@example.com", "correctpass1")
    user = authenticate_user("auth@example.com", "correctpass1")
    assert user is not None
    assert user.email == "auth@example.com"


def test_authenticate_user_is_case_insensitive_on_email(isolated_db):
    register_user("auth2@example.com", "correctpass1")
    assert authenticate_user("AUTH2@EXAMPLE.COM", "correctpass1") is not None


def test_authenticate_user_returns_none_for_wrong_password(isolated_db):
    register_user("wrongpass@example.com", "correctpass1")
    assert authenticate_user("wrongpass@example.com", "notthepassword") is None


def test_authenticate_user_returns_none_for_unknown_email(isolated_db):
    assert authenticate_user("nobody@example.com", "whatever123") is None


def test_authenticate_user_returns_none_for_empty_password(isolated_db):
    register_user("emptycheck@example.com", "correctpass1")
    assert authenticate_user("emptycheck@example.com", "") is None


def test_authenticate_user_returns_none_for_a_google_only_account_without_crashing(isolated_db):
    # Un compte créé via Google (password_hash NULL) ne doit jamais faire planter une tentative
    # de connexion par mot de passe — juste échouer comme un mauvais mot de passe.
    get_or_create_google_user("googleonly@example.com", google_sub="sub-123")
    assert authenticate_user("googleonly@example.com", "anypassword123") is None


# --- get_or_create_google_user (réconciliation par email vérifié, Phase 2) ----------------------


def test_get_or_create_google_user_creates_a_new_user_without_a_password(isolated_db):
    user = get_or_create_google_user("newgoogleuser@example.com", google_sub="sub-abc")
    assert user.email == "newgoogleuser@example.com"
    assert user.password_hash is None
    assert user.google_sub == "sub-abc"


def test_get_or_create_google_user_normalizes_email_case(isolated_db):
    user = get_or_create_google_user("MixedCase@Example.com", google_sub="sub-xyz")
    assert user.email == "mixedcase@example.com"


def test_get_or_create_google_user_links_to_an_existing_password_account_without_duplicating(isolated_db):
    existing = register_user("alreadyhasaccount@example.com", "originalpass1")

    linked = get_or_create_google_user("alreadyhasaccount@example.com", google_sub="sub-link")

    assert linked.id == existing.id
    # Le mot de passe existant n'est jamais effacé par une liaison Google.
    assert authenticate_user("alreadyhasaccount@example.com", "originalpass1") is not None


def test_get_or_create_google_user_never_creates_a_duplicate_on_repeated_calls(isolated_db):
    first = get_or_create_google_user("repeat@example.com", google_sub="sub-repeat")
    second = get_or_create_google_user("repeat@example.com", google_sub="sub-repeat")

    assert first.id == second.id

    from accounts import db as accounts_db
    from accounts.models import User

    with accounts_db.SessionLocal() as session:
        assert session.query(User).filter(User.email == "repeat@example.com").count() == 1


def test_get_or_create_google_user_updates_google_sub_on_an_existing_account_missing_it(isolated_db):
    created = register_user("linklater@example.com", "originalpass1")
    assert created.google_sub is None

    linked = get_or_create_google_user("linklater@example.com", google_sub="sub-later")
    assert linked.google_sub == "sub-later"


# --- password reset flow --------------------------------------------------------------------------


def test_request_password_reset_returns_a_token_for_an_existing_account(isolated_db):
    register_user("reset@example.com", "originalpass1")
    assert request_password_reset("reset@example.com") is not None


def test_request_password_reset_returns_none_for_unknown_email(isolated_db):
    assert request_password_reset("ghost@example.com") is None


def test_resolve_reset_token_returns_the_user_for_a_valid_token(isolated_db):
    user = register_user("resolve@example.com", "originalpass1")
    token = request_password_reset("resolve@example.com")
    resolved = resolve_reset_token(token)
    assert resolved is not None
    assert resolved.id == user.id


def test_resolve_reset_token_returns_none_for_an_unknown_token(isolated_db):
    assert resolve_reset_token("not-a-real-token") is None


def test_reset_password_changes_the_password_and_marks_token_used(isolated_db):
    register_user("changeme@example.com", "originalpass1")
    token = request_password_reset("changeme@example.com")

    assert reset_password(token, "brandnewpass1") is True
    assert authenticate_user("changeme@example.com", "brandnewpass1") is not None
    assert authenticate_user("changeme@example.com", "originalpass1") is None


def test_reset_password_token_cannot_be_reused(isolated_db):
    register_user("onceonly@example.com", "originalpass1")
    token = request_password_reset("onceonly@example.com")
    reset_password(token, "firstchange1")

    assert reset_password(token, "secondchange1") is False


def test_reset_password_rejects_a_weak_new_password(isolated_db):
    register_user("weakpass@example.com", "originalpass1")
    token = request_password_reset("weakpass@example.com")
    with pytest.raises(ValidationError):
        reset_password(token, "short")


def test_reset_password_returns_false_for_an_unknown_token(isolated_db):
    assert reset_password("not-a-real-token", "longenoughpass1") is False


def test_reset_password_returns_false_for_an_expired_token(isolated_db):
    from accounts import db as accounts_db
    from accounts.models import PasswordResetToken, User

    register_user("expired@example.com", "originalpass1")
    with accounts_db.SessionLocal() as session:
        user = session.query(User).filter(User.email == "expired@example.com").first()
        now = utcnow()
        session.add(
            PasswordResetToken(
                user_id=user.id,
                token="expired-token-value",
                created_at=now - timedelta(hours=3),
                expires_at=now - timedelta(hours=2),
            )
        )
        session.commit()

    assert reset_password("expired-token-value", "longenoughpass1") is False
