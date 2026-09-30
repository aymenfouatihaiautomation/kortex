from unittest.mock import patch

from pricing_agent import config as pricing_config
from pricing_agent.launch_pricing import apply_launch_price, build_launch_proposal
from pricing_agent.pricing_state import load

SAMPLE_COURSE = {
    "title": "Agents en production : gestion des erreurs, évaluation et déploiement fiable",
    "level": "intermédiaire",
    "description": "Fiabiliser des agents LLM en production.",
    "chapters": [
        {"number": 1, "has_video": True},
        {"number": 2, "has_video": False},
        {"number": 3, "has_video": False},
        {"number": 4, "has_video": False},
        {"number": 5, "has_video": False},
        {"number": 6, "has_video": False},
        {"number": 7, "has_video": False},
    ],
}


def test_build_launch_proposal_uses_fixed_business_price_not_llm_output():
    proposal = build_launch_proposal(demo=True, course=SAMPLE_COURSE)

    assert proposal["proposed_price_usd"] == pricing_config.LAUNCH_PRICE_USD
    assert proposal["status"] == "awaiting_confirmation"
    assert proposal["video_chapters_ready"] == 1
    assert proposal["total_chapters"] == 7


def test_build_launch_proposal_includes_market_research_and_rationale():
    proposal = build_launch_proposal(demo=True, course=SAMPLE_COURSE)

    assert len(proposal["market_research"]["comparable_courses"]) >= 1
    assert "1/7" in proposal["rationale"]
    assert f"${pricing_config.LAUNCH_PRICE_USD:.2f}" in proposal["rationale"]


def test_build_launch_proposal_estimates_paddle_fee():
    proposal = build_launch_proposal(demo=True, course=SAMPLE_COURSE)

    expected_fee = pricing_config.LAUNCH_PRICE_USD * pricing_config.PADDLE_FEE_PCT + pricing_config.PADDLE_FEE_FIXED_USD
    assert proposal["paddle_fee_estimate_usd"] == round(expected_fee, 2)


@patch("pricing_agent.launch_pricing.sync_price_to_paddle", return_value="mock_price_launch_test")
def test_apply_launch_price_persists_state_and_history(mock_sync, tmp_path, monkeypatch):
    state_path = tmp_path / "pricing_state.json"
    monkeypatch.setattr("pricing_agent.config.PRICING_STATE_FILE", state_path)

    proposal = build_launch_proposal(demo=True, course=SAMPLE_COURSE)
    result_state = apply_launch_price(proposal)

    assert result_state["current_price_usd"] == pricing_config.LAUNCH_PRICE_USD
    assert result_state["paddle_price_id"] == "mock_price_launch_test"
    assert result_state["history"][-1]["event"] == "launch"

    reloaded = load(state_path)
    assert reloaded["current_price_usd"] == pricing_config.LAUNCH_PRICE_USD
    mock_sync.assert_called_once_with(pricing_config.LAUNCH_PRICE_USD)
