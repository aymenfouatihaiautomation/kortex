import json
from unittest.mock import patch

import pytest

from bloc0_topic_discovery.discover_topics import discover_topics, _validate_and_sort
from common.llm_client import LLMCallError


def test_discover_topics_demo_mode_is_sorted_and_stubbed():
    result = discover_topics(demo=True)

    assert result["niche"] == "AI Automation"
    assert "generated_at" in result
    scores = [t["demand_score"] for t in result["topics"]]
    assert scores == sorted(scores, reverse=True)
    for topic in result["topics"]:
        assert {"title", "demand_score", "gap_reason", "sources"} <= topic.keys()


@patch("bloc0_topic_discovery.discover_topics.run_prompt")
def test_discover_topics_real_mode_parses_and_sorts_llm_output(mock_run_prompt):
    mock_run_prompt.return_value = json.dumps(
        {
            "niche": "AI Automation",
            "topics": [
                {"title": "B", "demand_score": 0.3, "gap_reason": "r1", "sources": ["s1"]},
                {"title": "A", "demand_score": 0.9, "gap_reason": "r2", "sources": ["s2"]},
            ],
        }
    )

    result = discover_topics(demo=False)

    assert [t["title"] for t in result["topics"]] == ["A", "B"]
    call_kwargs = mock_run_prompt.call_args.kwargs
    assert call_kwargs["allowed_tools"] == ["WebSearch"]


@patch("bloc0_topic_discovery.discover_topics.run_prompt")
def test_discover_topics_real_mode_wraps_llm_text_in_markdown_fence(mock_run_prompt):
    mock_run_prompt.return_value = (
        "```json\n"
        + json.dumps(
            {
                "niche": "AI Automation",
                "topics": [
                    {"title": "A", "demand_score": 0.5, "gap_reason": "r", "sources": ["s"]}
                ],
            }
        )
        + "\n```"
    )

    result = discover_topics(demo=False)
    assert result["topics"][0]["title"] == "A"


def test_validate_and_sort_rejects_missing_field():
    with pytest.raises(LLMCallError):
        _validate_and_sort({"topics": [{"title": "A", "demand_score": 0.5}]})


def test_validate_and_sort_rejects_empty_topics():
    with pytest.raises(LLMCallError):
        _validate_and_sort({"topics": []})
