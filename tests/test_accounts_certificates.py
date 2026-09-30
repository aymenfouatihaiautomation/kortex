"""Tests unitaires de la persistance des attestations (accounts/certificates.py) et du rendu PDF
(accounts/certificate_pdf.py).

Base SQLite temporaire isolée par test — même pattern que test_accounts_service.py."""

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from accounts.certificate_pdf import render_certificate_pdf
from accounts.certificates import get_certificate_by_token, issue_certificate
from accounts.db import Base


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


def test_issue_certificate_creates_a_row_with_a_token(isolated_db):
    certificate = issue_certificate(
        email="Alice@Example.com",
        course_slug="cours-ia",
        course_title="Agents IA en production",
        learner_name="  Alice Dupont  ",
    )

    assert certificate.token
    assert certificate.email == "alice@example.com"
    assert certificate.course_slug == "cours-ia"
    assert certificate.course_title == "Agents IA en production"
    assert certificate.learner_name == "Alice Dupont"
    assert certificate.issued_at is not None


def test_two_certificates_get_different_tokens(isolated_db):
    first = issue_certificate("alice@example.com", "cours-ia", "Cours IA", "Alice")
    second = issue_certificate("alice@example.com", "cours-ia", "Cours IA", "Alice")

    assert first.token != second.token


def test_get_certificate_by_token_returns_the_matching_certificate(isolated_db):
    certificate = issue_certificate("alice@example.com", "cours-ia", "Cours IA", "Alice Dupont")

    found = get_certificate_by_token(certificate.token)

    assert found is not None
    assert found.learner_name == "Alice Dupont"
    assert found.course_title == "Cours IA"


def test_get_certificate_by_token_returns_none_for_unknown_token(isolated_db):
    assert get_certificate_by_token("unknown-token") is None


def test_render_certificate_pdf_returns_valid_pdf_bytes():
    pdf_bytes = render_certificate_pdf(
        learner_name="Jean Dupont",
        course_title="Agents IA en production",
        issued_at="10/08/2026",
        verify_url="https://example.com/certificate/abc123",
        certificate_id="abc123",
    )

    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF-1.4")
    assert len(pdf_bytes) > 0
