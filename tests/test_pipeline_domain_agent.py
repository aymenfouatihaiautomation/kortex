import json
from unittest.mock import patch

from pipeline.domain_agent import (
    compute_scores,
    get_top_topics,
    is_topic_produced,
    load_produced_courses,
    price_score,
    record_produced_course,
    search_domain_trends,
    suggested_price_usd,
)


def test_price_score_scales_linearly_below_cap():
    assert price_score(0) == 0.0
    assert price_score(25) == 5.0


def test_price_score_caps_at_10_for_high_price():
    assert price_score(50) == 10.0
    assert price_score(500) == 10.0


def test_price_score_never_negative_for_bad_input():
    assert price_score(-10) == 0.0


def test_suggested_price_usd_is_undercut_and_bounded():
    assert suggested_price_usd(25.0) == 20.0  # 0.8 * 25
    assert suggested_price_usd(1.0) == 9.99  # plancher
    assert suggested_price_usd(1000.0) == 49.99  # plafond


def test_compute_scores_sums_three_criteria_and_adds_suggested_price():
    candidate = {
        "topic": "Sujet X",
        "search_volume_score": 8,
        "low_competition_fr_score": 6,
        "observed_avg_price_usd": 20.0,
    }
    enriched = compute_scores(candidate)
    assert enriched["price_score"] == 4.0
    assert enriched["score_total"] == 18.0  # 8 + 6 + 4
    assert enriched["suggested_price_usd"] == 16.0  # 0.8 * 20
    assert enriched["high_price_signal"] is True


def test_compute_scores_high_price_signal_false_below_threshold():
    candidate = {"topic": "Sujet Y", "search_volume_score": 5, "low_competition_fr_score": 5, "observed_avg_price_usd": 10.0}
    assert compute_scores(candidate)["high_price_signal"] is False


def test_is_topic_produced_matches_after_normalization():
    produced = [{"topic": "Maîtriser Excel  avancé", "domain": "Excel avancé"}]
    assert is_topic_produced("maitriser excel avance", produced) is True
    assert is_topic_produced("Un autre sujet", produced) is False


def test_load_produced_courses_missing_file_returns_empty(tmp_path):
    assert load_produced_courses(tmp_path / "does_not_exist.json") == []


def test_record_produced_course_appends_without_overwriting(tmp_path):
    path = tmp_path / "produced.json"
    record_produced_course("Finance personnelle", "Sujet A", slug="sujet-a", path=path)
    record_produced_course("Vente", "Sujet B", slug="sujet-b", path=path)

    produced = load_produced_courses(path)
    assert [p["topic"] for p in produced] == ["Sujet A", "Sujet B"]
    assert produced[0]["domain"] == "Finance personnelle"
    assert produced[0]["slug"] == "sujet-a"

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert list(raw.keys()) == ["produced"]


def test_search_domain_trends_demo_mode_returns_stub_without_network():
    result = search_domain_trends("Vente", demo=True)
    assert result["domain"] == "Vente"
    assert len(result["candidates"]) == 1
    assert "Vente" in result["candidates"][0]["topic"]


@patch("pipeline.domain_agent.call_chat_api")
def test_search_domain_trends_real_mode_never_calls_api_in_demo(mock_call_chat_api):
    search_domain_trends("Vente", demo=True)
    mock_call_chat_api.assert_not_called()


def test_get_top_topics_demo_mode_sorts_by_score_and_respects_top_n(tmp_path):
    produced_file = tmp_path / "produced.json"
    topics = get_top_topics(
        domains=["Domaine A", "Domaine B", "Domaine C"], top_n=2, demo=True, produced_file=produced_file
    )
    assert len(topics) == 2
    assert topics[0]["score_total"] >= topics[1]["score_total"]
    for t in topics:
        assert set(t.keys()) >= {
            "domain", "topic", "angle", "score_total", "score_breakdown",
            "suggested_price_usd", "justification", "sources",
        }


def test_get_top_topics_filters_out_already_produced_topics(tmp_path):
    produced_file = tmp_path / "produced.json"
    # Le stub demo produit toujours "[DEMO] Sujet tendance en {domain}" pour un domaine donné.
    record_produced_course("Domaine A", "[DEMO] Sujet tendance en Domaine A", path=produced_file)

    topics = get_top_topics(domains=["Domaine A", "Domaine B"], top_n=5, demo=True, produced_file=produced_file)

    assert all(t["domain"] != "Domaine A" for t in topics)
    assert any(t["domain"] == "Domaine B" for t in topics)


def test_get_top_topics_demo_mode_never_calls_llm_api(tmp_path):
    with patch("pipeline.domain_agent.call_chat_api") as mock_call_chat_api:
        get_top_topics(domains=["Domaine A"], top_n=1, demo=True, produced_file=tmp_path / "produced.json")
    mock_call_chat_api.assert_not_called()
