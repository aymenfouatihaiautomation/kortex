import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from common.llm_client import (
    MODEL_PRICING_PER_MILLION_TOKENS,
    CostTracker,
    LLMCallError,
    call_chat_api,
    call_llm_api,
    estimate_cost_usd,
)


def _fake_response(
    text: str,
    input_tokens: int = 100,
    output_tokens: int = 50,
    cache_read_input_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
            cache_creation_input_tokens=cache_creation_input_tokens,
        ),
    )


def test_estimate_cost_usd_matches_pricing_table():
    pricing = MODEL_PRICING_PER_MILLION_TOKENS["claude-sonnet-5"]
    cost = estimate_cost_usd("claude-sonnet-5", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == pytest.approx(pricing["input"] + pricing["output"])


def test_estimate_cost_usd_unknown_model_returns_zero():
    assert estimate_cost_usd("modele-inconnu", input_tokens=1000, output_tokens=1000) == 0.0


def test_cost_tracker_accumulates_across_calls():
    tracker = CostTracker(label="test-run")
    tracker.record("claude-haiku-4-5-20251001", 100, 50, 0.001)
    tracker.record("claude-sonnet-5", 200, 100, 0.002)

    assert len(tracker.calls) == 2
    assert tracker.total_input_tokens == 300
    assert tracker.total_output_tokens == 150
    assert tracker.total_cost_usd == pytest.approx(0.003)


def test_cost_tracker_print_summary_does_not_raise(capsys):
    tracker = CostTracker(label="test-run")
    tracker.record("claude-haiku-4-5-20251001", 100, 50, 0.001)
    tracker.print_summary()
    captured = capsys.readouterr()
    assert "test-run" in captured.out
    assert "0.001" in captured.out or "0.0010" in captured.out


@patch("common.llm_client.anthropic.Anthropic")
def test_call_llm_api_returns_text_from_response(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _fake_response("Bonjour.")
    mock_anthropic_cls.return_value = mock_client

    result = call_llm_api("Dis bonjour.", model="claude-haiku-4-5-20251001")

    assert result == "Bonjour."
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "claude-haiku-4-5-20251001"
    assert call_kwargs["messages"] == [{"role": "user", "content": "Dis bonjour."}]
    assert "system" not in call_kwargs


@patch("common.llm_client.anthropic.Anthropic")
def test_call_llm_api_passes_system_prompt_when_given(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _fake_response("Ok.")
    mock_anthropic_cls.return_value = mock_client

    call_llm_api("Prompt.", model="claude-sonnet-5", system_prompt="Tu es un assistant.")

    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["system"] == "Tu es un assistant."


@patch("common.llm_client.anthropic.Anthropic")
def test_call_llm_api_records_cost_on_tracker(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _fake_response("Ok.", input_tokens=1000, output_tokens=200)
    mock_anthropic_cls.return_value = mock_client

    tracker = CostTracker(label="bloc-test")
    call_llm_api("Prompt.", model="claude-haiku-4-5-20251001", tracker=tracker)

    assert len(tracker.calls) == 1
    recorded = tracker.calls[0]
    assert recorded["model"] == "claude-haiku-4-5-20251001"
    assert recorded["input_tokens"] == 1000
    assert recorded["output_tokens"] == 200
    expected_cost = estimate_cost_usd("claude-haiku-4-5-20251001", 1000, 200)
    assert recorded["cost_usd"] == pytest.approx(expected_cost)


@patch("common.llm_client.anthropic.Anthropic")
def test_call_llm_api_prints_cost_log_line(mock_anthropic_cls, capsys):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _fake_response("Ok.", input_tokens=500, output_tokens=100)
    mock_anthropic_cls.return_value = mock_client

    call_llm_api("Prompt.", model="claude-sonnet-5")

    captured = capsys.readouterr()
    assert "[cost]" in captured.out
    assert "claude-sonnet-5" in captured.out
    assert "in=500" in captured.out
    assert "out=100" in captured.out


@patch("common.llm_client.anthropic.Anthropic")
def test_call_llm_api_raises_llm_call_error_on_empty_response(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _fake_response("   ")
    mock_anthropic_cls.return_value = mock_client

    with pytest.raises(LLMCallError):
        call_llm_api("Prompt.", model="claude-haiku-4-5-20251001")


@patch("common.llm_client.anthropic.Anthropic")
def test_call_llm_api_wraps_underlying_exception_in_llm_call_error(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = RuntimeError("réseau indisponible")
    mock_anthropic_cls.return_value = mock_client

    with pytest.raises(LLMCallError):
        call_llm_api("Prompt.", model="claude-haiku-4-5-20251001")


# --- call_chat_api (chatbots — historique multi-tours, system en blocs, outils serveur) --------


@patch("common.llm_client.anthropic.Anthropic")
def test_call_chat_api_sends_full_message_history(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _fake_response("Bonjour !")
    mock_anthropic_cls.return_value = mock_client

    messages = [{"role": "user", "content": "Bonjour"}, {"role": "assistant", "content": "Salut"}, {"role": "user", "content": "Ça va ?"}]
    result = call_chat_api(messages, model="claude-haiku-4-5-20251001")

    assert result == "Bonjour !"
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["messages"] == messages
    assert call_kwargs["model"] == "claude-haiku-4-5-20251001"
    assert "system" not in call_kwargs
    assert "tools" not in call_kwargs


@patch("common.llm_client.anthropic.Anthropic")
def test_call_chat_api_passes_system_blocks_with_cache_control_unchanged(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _fake_response("Ok.")
    mock_anthropic_cls.return_value = mock_client

    system_blocks = [
        {"type": "text", "text": "Persona."},
        {"type": "text", "text": "Catalogue.", "cache_control": {"type": "ephemeral"}},
    ]
    call_chat_api([{"role": "user", "content": "Salut"}], model="claude-haiku-4-5-20251001", system_blocks=system_blocks)

    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["system"] == system_blocks


@patch("common.llm_client.anthropic.Anthropic")
def test_call_chat_api_passes_tools_through(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _fake_response("Ok.")
    mock_anthropic_cls.return_value = mock_client

    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}]
    call_chat_api([{"role": "user", "content": "Salut"}], model="claude-haiku-4-5-20251001", tools=tools)

    assert mock_client.messages.create.call_args.kwargs["tools"] == tools


@patch("common.llm_client.anthropic.Anthropic")
def test_call_chat_api_disables_thinking(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _fake_response("Ok.")
    mock_anthropic_cls.return_value = mock_client

    call_chat_api([{"role": "user", "content": "Salut"}], model="claude-haiku-4-5-20251001")

    assert mock_client.messages.create.call_args.kwargs["thinking"] == {"type": "disabled"}


@patch("common.llm_client.anthropic.Anthropic")
def test_call_chat_api_records_cost_including_cache_tokens(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _fake_response(
        "Ok.", input_tokens=200, output_tokens=80, cache_read_input_tokens=4096, cache_creation_input_tokens=0
    )
    mock_anthropic_cls.return_value = mock_client

    tracker = CostTracker(label="chat-general")
    call_chat_api([{"role": "user", "content": "Salut"}], model="claude-haiku-4-5-20251001", tracker=tracker)

    assert len(tracker.calls) == 1
    assert tracker.calls[0]["input_tokens"] == 200
    assert tracker.calls[0]["output_tokens"] == 80


@patch("common.llm_client.anthropic.Anthropic")
def test_call_chat_api_prints_cache_read_and_write_in_cost_log(mock_anthropic_cls, capsys):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _fake_response(
        "Ok.", cache_read_input_tokens=1234, cache_creation_input_tokens=56
    )
    mock_anthropic_cls.return_value = mock_client

    call_chat_api([{"role": "user", "content": "Salut"}], model="claude-haiku-4-5-20251001")

    captured = capsys.readouterr()
    assert "cache_read=1234" in captured.out
    assert "cache_write=56" in captured.out


@patch("common.llm_client.anthropic.Anthropic")
def test_call_chat_api_raises_on_empty_response(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _fake_response("   ")
    mock_anthropic_cls.return_value = mock_client

    with pytest.raises(LLMCallError):
        call_chat_api([{"role": "user", "content": "Salut"}], model="claude-haiku-4-5-20251001")


@patch("common.llm_client.anthropic.Anthropic")
def test_call_chat_api_wraps_underlying_exception(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = RuntimeError("réseau indisponible")
    mock_anthropic_cls.return_value = mock_client

    with pytest.raises(LLMCallError):
        call_chat_api([{"role": "user", "content": "Salut"}], model="claude-haiku-4-5-20251001")


def test_call_chat_api_raises_llm_call_error_when_api_key_is_missing(monkeypatch):
    # Même bug de classe que exercise_correction.request_correction (2026-08-04) : le SDK
    # anthropic ne lève pas anthropic.APIError quand la clé est absente, mais un TypeError, au
    # moment de l'appel. Le `except Exception` large de call_chat_api doit tout de même le
    # capturer proprement.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(LLMCallError):
        call_chat_api([{"role": "user", "content": "Salut"}], model="claude-haiku-4-5-20251001")
