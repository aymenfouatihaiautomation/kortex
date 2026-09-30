import pytest

from accounts.security import (
    ValidationError,
    hash_password,
    normalize_email,
    validate_email_format,
    validate_password_strength,
    verify_password,
)


def test_normalize_email_strips_and_lowercases():
    assert normalize_email("  Foo@Example.COM  ") == "foo@example.com"


def test_normalize_email_handles_empty_input():
    assert normalize_email("") == ""
    assert normalize_email(None) == ""


def test_validate_email_format_accepts_a_valid_email():
    validate_email_format("client@example.com")  # ne lève pas


@pytest.mark.parametrize("bad_email", ["not-an-email", "missing-domain@", "@missing-local.com", "no-at-sign.com", ""])
def test_validate_email_format_rejects_invalid_emails(bad_email):
    with pytest.raises(ValidationError):
        validate_email_format(bad_email)


def test_validate_password_strength_accepts_a_password_at_the_minimum_length():
    validate_password_strength("12345678")  # ne lève pas


@pytest.mark.parametrize("bad_password", ["", "short", "1234567"])
def test_validate_password_strength_rejects_too_short_passwords(bad_password):
    with pytest.raises(ValidationError):
        validate_password_strength(bad_password)


def test_hash_password_never_stores_the_plaintext():
    password = "supersecret1"
    hashed = hash_password(password)
    assert hashed != password
    assert password not in hashed


def test_verify_password_matches_the_correct_password():
    hashed = hash_password("correctpass1")
    assert verify_password("correctpass1", hashed) is True


def test_verify_password_rejects_the_wrong_password():
    hashed = hash_password("correctpass1")
    assert verify_password("wrongpass", hashed) is False


def test_two_hashes_of_the_same_password_are_not_identical():
    # Sel aléatoire (comportement standard de werkzeug.security) : deux hachages du même mot de
    # passe ne doivent jamais être identiques bit à bit.
    assert hash_password("samepassword1") != hash_password("samepassword1")
