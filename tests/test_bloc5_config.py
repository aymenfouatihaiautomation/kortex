"""Tests for bloc5_payment/config.py::paddle_overlay_enabled — the gate deciding whether
landing.html renders the Paddle.js overlay (live) or the plain GET form to /checkout/start
(mock/tests, unchanged)."""

from unittest.mock import patch

from bloc5_payment.config import paddle_overlay_enabled


@patch("bloc5_payment.config.PADDLE_CLIENT_TOKEN", None)
def test_overlay_disabled_when_client_token_absent():
    assert paddle_overlay_enabled() is False


@patch("bloc5_payment.config.PADDLE_CLIENT_TOKEN", "")
def test_overlay_disabled_when_client_token_is_empty_string():
    assert paddle_overlay_enabled() is False


@patch("bloc5_payment.config.PADDLE_CLIENT_TOKEN", "live_abc123")
def test_overlay_enabled_when_client_token_present():
    assert paddle_overlay_enabled() is True
