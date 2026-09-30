from pricing_agent.research import build_prompt, research_comparable_prices

SAMPLE_COURSE = {
    "title": "Agents en production : gestion des erreurs, évaluation et déploiement fiable",
    "level": "intermédiaire",
    "description": "Fiabiliser des agents LLM en production.",
    "chapters": [
        {"number": 1, "has_video": True},
        {"number": 2, "has_video": False},
        {"number": 3, "has_video": False},
    ],
}


def test_research_comparable_prices_demo_mode_makes_no_network_call():
    result = research_comparable_prices(SAMPLE_COURSE, demo=True)

    assert "comparable_courses" in result
    assert "price_range_observed_usd" in result
    assert "reasoning" in result
    assert len(result["comparable_courses"]) >= 1


def test_build_prompt_includes_specialization_and_video_readiness_context():
    prompt = build_prompt(SAMPLE_COURSE)

    assert "1/3 chapitres avec vidéo" in prompt
    assert SAMPLE_COURSE["title"] in prompt
    assert "généralistes" in prompt
