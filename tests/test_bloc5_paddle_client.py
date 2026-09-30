import hashlib
import hmac
import json
import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from bloc4_publication.access_store import SLUG_COURS_1
from bloc5_payment.paddle_client import (
    PaddleError,
    create_checkout,
    parse_completed_transaction,
    resolve_price_id,
    sync_price_to_paddle,
    verify_webhook_signature,
)


@patch("bloc5_payment.paddle_client.is_mock_mode", return_value=True)
def test_create_checkout_mock_mode_makes_no_network_call(mock_is_mock):
    result = create_checkout("client@example.com")
    assert result["mock"] is True
    assert result["checkout_url"].startswith("/checkout/mock/")
    assert "client@example.com" in result["checkout_url"]


@patch("bloc5_payment.paddle_client.is_mock_mode", return_value=False)
@patch("bloc5_payment.paddle_client.PADDLE_API_KEY", "fake-key")
@patch("bloc5_payment.paddle_client.PADDLE_PRICE_ID", "pri_123")
@patch("bloc5_payment.paddle_client.requests.post")
def test_create_checkout_real_mode_calls_paddle_api(mock_post, mock_is_mock):
    mock_post.return_value = MagicMock(
        status_code=200,
        json=lambda: {"data": {"id": "txn_123", "checkout": {"url": "https://paddle.example/checkout/txn_123"}}},
    )

    result = create_checkout("client@example.com")

    assert result == {"checkout_url": "https://paddle.example/checkout/txn_123", "mock": False, "transaction_id": "txn_123"}
    mock_post.assert_called_once()
    sent_json = mock_post.call_args.kwargs["json"]
    assert sent_json["customer"]["email"] == "client@example.com"
    assert sent_json["items"][0]["price_id"] == "pri_123"


@patch("bloc5_payment.paddle_client.is_mock_mode", return_value=False)
@patch("bloc5_payment.paddle_client.PADDLE_API_KEY", "fake-key")
@patch("bloc5_payment.paddle_client.PADDLE_PRICE_ID", "pri_123")
@patch("bloc5_payment.paddle_client.requests.post")
def test_create_checkout_real_mode_http_error_raises(mock_post, mock_is_mock):
    mock_post.return_value = MagicMock(status_code=400, text="bad request")

    with pytest.raises(PaddleError, match="400"):
        create_checkout("client@example.com")


@patch("bloc5_payment.paddle_client.PADDLE_WEBHOOK_SECRET", None)
def test_verify_webhook_signature_mock_mode_always_true():
    assert verify_webhook_signature(b"anything", "") is True
    assert verify_webhook_signature(b"anything", "garbage") is True


@patch("bloc5_payment.paddle_client.PADDLE_WEBHOOK_SECRET", "shh-secret")
def test_verify_webhook_signature_accepts_valid_hmac():
    body = json.dumps({"event_type": "transaction.completed"}).encode("utf-8")
    ts = str(int(time.time()))
    signed_payload = f"{ts}:{body.decode('utf-8')}"
    h1 = hmac.new(b"shh-secret", signed_payload.encode("utf-8"), hashlib.sha256).hexdigest()

    assert verify_webhook_signature(body, f"ts={ts};h1={h1}") is True


@patch("bloc5_payment.paddle_client.PADDLE_WEBHOOK_SECRET", "shh-secret")
def test_verify_webhook_signature_rejects_tampered_body():
    body = json.dumps({"event_type": "transaction.completed"}).encode("utf-8")
    ts = str(int(time.time()))
    signed_payload = f"{ts}:{body.decode('utf-8')}"
    h1 = hmac.new(b"shh-secret", signed_payload.encode("utf-8"), hashlib.sha256).hexdigest()

    tampered_body = json.dumps({"event_type": "transaction.completed", "extra": "x"}).encode("utf-8")
    assert verify_webhook_signature(tampered_body, f"ts={ts};h1={h1}") is False


@patch("bloc5_payment.paddle_client.PADDLE_WEBHOOK_SECRET", "shh-secret")
def test_verify_webhook_signature_rejects_malformed_header():
    assert verify_webhook_signature(b"x", "not-the-right-format") is False


@patch("bloc5_payment.paddle_client.PADDLE_WEBHOOK_SECRET", "shh-secret")
def test_verify_webhook_signature_resists_a_space_after_the_semicolon():
    # Garde-fou : un en-tête "ts=...; h1=..." (espace après le ";") ne doit pas faire échouer
    # la vérification — sans .strip() sur chaque partie, la clé extraite serait " h1" et jamais
    # trouvée par parts.get("h1").
    body = json.dumps({"event_type": "transaction.completed"}).encode("utf-8")
    ts = str(int(time.time()))
    signed_payload = f"{ts}:{body.decode('utf-8')}"
    h1 = hmac.new(b"shh-secret", signed_payload.encode("utf-8"), hashlib.sha256).hexdigest()

    assert verify_webhook_signature(body, f"ts={ts}; h1={h1}") is True


def test_parse_completed_transaction_extracts_email():
    payload = {"event_type": "transaction.completed", "data": {"customer": {"email": "buyer@example.com"}}}
    assert parse_completed_transaction(payload) == ("buyer@example.com", SLUG_COURS_1)


def test_parse_completed_transaction_ignores_other_event_types():
    payload = {"event_type": "transaction.created", "data": {"customer": {"email": "buyer@example.com"}}}
    assert parse_completed_transaction(payload) is None


def test_parse_completed_transaction_handles_missing_email():
    payload = {"event_type": "transaction.paid", "data": {}}
    assert parse_completed_transaction(payload) is None


@patch("bloc5_payment.paddle_client.PADDLE_API_KEY", "fake-key")
@patch("bloc5_payment.paddle_client.PADDLE_API_BASE", "https://api.paddle.example")
@patch("bloc5_payment.paddle_client.requests.get")
def test_parse_completed_transaction_fetches_email_via_customer_id_when_missing_inline(mock_get):
    # Cas réel constaté en production : data.customer est absent, seul customer_id est présent.
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: {"data": {"id": "ctm_01m06pa55bdqvbm8dwmqzakde9", "email": "buyer@example.com"}},
    )
    payload = {"event_type": "transaction.completed", "data": {"customer_id": "ctm_01m06pa55bdqvbm8dwmqzakde9"}}

    assert parse_completed_transaction(payload) == ("buyer@example.com", SLUG_COURS_1)
    mock_get.assert_called_once_with(
        "https://api.paddle.example/customers/ctm_01m06pa55bdqvbm8dwmqzakde9",
        headers={"Authorization": "Bearer fake-key"},
        timeout=10,
    )


@patch("bloc5_payment.paddle_client.PADDLE_API_KEY", "fake-key")
@patch("bloc5_payment.paddle_client.requests.get")
def test_parse_completed_transaction_prefers_inline_email_over_api_call(mock_get):
    payload = {
        "event_type": "transaction.completed",
        "data": {"customer": {"email": "inline@example.com"}, "customer_id": "ctm_xyz"},
    }

    assert parse_completed_transaction(payload) == ("inline@example.com", SLUG_COURS_1)
    mock_get.assert_not_called()


@patch("bloc5_payment.paddle_client.PADDLE_API_KEY", "fake-key")
@patch("bloc5_payment.paddle_client.requests.get")
def test_parse_completed_transaction_returns_none_when_api_call_fails(mock_get):
    mock_get.side_effect = requests.exceptions.Timeout("boom")
    payload = {"event_type": "transaction.completed", "data": {"customer_id": "ctm_xyz"}}

    assert parse_completed_transaction(payload) is None


@patch("bloc5_payment.paddle_client.PADDLE_API_KEY", None)
@patch("bloc5_payment.paddle_client.requests.get")
def test_parse_completed_transaction_skips_api_call_in_mock_mode(mock_get):
    payload = {"event_type": "transaction.completed", "data": {"customer_id": "ctm_xyz"}}

    assert parse_completed_transaction(payload) is None
    mock_get.assert_not_called()


# --- résolution price_id -> slug (Changement 4, Étape D) --------------------------------------


def test_parse_completed_transaction_resolves_slug_from_known_price_id(tmp_path):
    published = {
        "courses": [
            {"slug": "cours-b", "title": "Cours B", "domain": "Vente", "price_usd": 24.99, "paddle_price_id": "pri_b"}
        ]
    }
    (tmp_path / "published_courses.json").write_text(json.dumps(published), encoding="utf-8")

    payload = {
        "event_type": "transaction.completed",
        "data": {"customer": {"email": "buyer@example.com"}, "items": [{"price": {"id": "pri_b"}, "quantity": 1}]},
    }

    with patch("bloc4_publication.content_loader.DATA_DIR", tmp_path):
        assert parse_completed_transaction(payload) == ("buyer@example.com", "cours-b")


def test_parse_completed_transaction_falls_back_to_course_1_for_unknown_price_id(tmp_path):
    published = {
        "courses": [
            {"slug": "cours-b", "title": "Cours B", "domain": "Vente", "price_usd": 24.99, "paddle_price_id": "pri_b"}
        ]
    }
    (tmp_path / "published_courses.json").write_text(json.dumps(published), encoding="utf-8")

    payload = {
        "event_type": "transaction.completed",
        "data": {"customer": {"email": "buyer@example.com"}, "items": [{"price": {"id": "pri_inconnu"}, "quantity": 1}]},
    }

    with patch("bloc4_publication.content_loader.DATA_DIR", tmp_path):
        assert parse_completed_transaction(payload) == ("buyer@example.com", SLUG_COURS_1)


def test_parse_completed_transaction_falls_back_to_course_1_when_items_absent():
    payload = {"event_type": "transaction.completed", "data": {"customer": {"email": "buyer@example.com"}}}
    assert parse_completed_transaction(payload) == ("buyer@example.com", SLUG_COURS_1)


@patch("bloc5_payment.paddle_client.is_mock_mode", return_value=True)
def test_sync_price_to_paddle_mock_mode_makes_no_network_call(mock_is_mock):
    price_id = sync_price_to_paddle(5.00)
    assert price_id.startswith("mock_price_")


@patch("bloc5_payment.paddle_client.is_mock_mode", return_value=False)
@patch("bloc5_payment.paddle_client.PADDLE_API_KEY", "fake-key")
@patch("bloc5_payment.paddle_client.PADDLE_PRODUCT_ID", "pro_123")
@patch("bloc5_payment.paddle_client.requests.post")
def test_sync_price_to_paddle_real_mode_calls_paddle_api(mock_post, mock_is_mock):
    mock_post.return_value = MagicMock(status_code=201, json=lambda: {"data": {"id": "pri_new_456"}})

    price_id = sync_price_to_paddle(5.75)

    assert price_id == "pri_new_456"
    sent_json = mock_post.call_args.kwargs["json"]
    assert sent_json["product_id"] == "pro_123"
    assert sent_json["unit_price"] == {"amount": "575", "currency_code": "USD"}


@patch("bloc5_payment.paddle_client.is_mock_mode", return_value=False)
@patch("bloc5_payment.paddle_client.PADDLE_API_KEY", "fake-key")
@patch("bloc5_payment.paddle_client.PADDLE_PRODUCT_ID", None)
def test_sync_price_to_paddle_real_mode_without_product_id_raises(mock_is_mock):
    with pytest.raises(PaddleError, match="PADDLE_PRODUCT_ID"):
        sync_price_to_paddle(5.00)


@patch("bloc5_payment.paddle_client.is_mock_mode", return_value=False)
@patch("bloc5_payment.paddle_client.PADDLE_API_KEY", "fake-key")
@patch("bloc5_payment.paddle_client.PADDLE_PRICE_ID", None)
def test_create_checkout_real_mode_without_any_price_id_raises(mock_is_mock):
    with pytest.raises(PaddleError, match="price_id"):
        create_checkout("client@example.com")


@patch("bloc5_payment.paddle_client.is_mock_mode", return_value=False)
@patch("bloc5_payment.paddle_client.PADDLE_API_KEY", "fake-key")
@patch("bloc5_payment.paddle_client.PADDLE_PRICE_ID", "pri_fallback")
@patch("bloc5_payment.paddle_client.requests.post")
def test_create_checkout_real_mode_prefers_explicit_price_id_over_fallback(mock_post, mock_is_mock):
    mock_post.return_value = MagicMock(
        status_code=200,
        json=lambda: {"data": {"id": "txn_123", "checkout": {"url": "https://paddle.example/checkout/txn_123"}}},
    )

    create_checkout("client@example.com", price_id="pri_from_pricing_state")

    sent_json = mock_post.call_args.kwargs["json"]
    assert sent_json["items"][0]["price_id"] == "pri_from_pricing_state"


# --- resolve_price_id (factorisé pour être partagé avec bloc4_publication/app.py::course_landing) ---


@patch("bloc5_payment.paddle_client.PADDLE_PRICE_ID", "pri_fallback")
def test_resolve_price_id_prefers_explicit_value():
    assert resolve_price_id("pri_explicit") == "pri_explicit"


@patch("bloc5_payment.paddle_client.PADDLE_PRICE_ID", "pri_fallback")
def test_resolve_price_id_falls_back_to_env_when_none():
    assert resolve_price_id(None) == "pri_fallback"


@patch("bloc5_payment.paddle_client.PADDLE_PRICE_ID", None)
def test_resolve_price_id_returns_none_when_nothing_configured():
    assert resolve_price_id(None) is None
