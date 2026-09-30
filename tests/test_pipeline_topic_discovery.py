from unittest.mock import patch

import pytest

from pipeline.topic_discovery import discover_topic


def test_discover_topic_demo_mode_returns_input_topic_unmodified_without_network():
    result = discover_topic("Maitriser les tableaux croises dynamiques", "Excel avance", demo=True)
    assert result["title"] == "Maitriser les tableaux croises dynamiques"
    assert result["demand_confirmed"] is True
    assert result["sources"] == ["[DEMO]"]


@patch("pipeline.topic_discovery.call_chat_api")
def test_discover_topic_demo_mode_never_calls_the_api(mock_call_chat_api):
    discover_topic("Un sujet", "Un domaine", demo=True)
    mock_call_chat_api.assert_not_called()


@patch("pipeline.topic_discovery.call_chat_api")
def test_discover_topic_real_mode_uses_web_search_tool_and_returns_parsed_json(mock_call_chat_api):
    mock_call_chat_api.return_value = (
        '{"title": "Titre affine", "gap_reason": "Demande confirmee via recherche.", '
        '"demand_confirmed": true, "sources": ["https://example.com"]}'
    )

    result = discover_topic("Sujet brut", "Vente", angle="angle initial", demo=False)

    assert result == {
        "title": "Titre affine",
        "gap_reason": "Demande confirmee via recherche.",
        "demand_confirmed": True,
        "sources": ["https://example.com"],
    }
    _, kwargs = mock_call_chat_api.call_args
    assert kwargs["tools"] == [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]
    assert "Sujet brut" in kwargs["messages"][0]["content"]
    assert "angle initial" in kwargs["messages"][0]["content"]


@patch("pipeline.topic_discovery.call_chat_api")
def test_discover_topic_real_mode_raises_when_title_missing(mock_call_chat_api):
    mock_call_chat_api.return_value = '{"gap_reason": "sans titre"}'

    from common.llm_client import LLMCallError

    with pytest.raises(LLMCallError):
        discover_topic("Sujet brut", "Vente", demo=False)


@patch("pipeline.topic_discovery.call_chat_api")
def test_discover_topic_real_mode_fills_missing_optional_fields_with_defaults(mock_call_chat_api):
    mock_call_chat_api.return_value = '{"title": "Titre minimal"}'

    result = discover_topic("Sujet brut", "Vente", demo=False)

    assert result["title"] == "Titre minimal"
    assert result["gap_reason"] == ""
    assert result["demand_confirmed"] is None
    assert result["sources"] == []
