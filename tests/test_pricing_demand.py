from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from pricing_agent import config as pricing_config
from pricing_agent.demand_pricing import evaluate_and_apply
from pricing_agent.pricing_state import load, record_change, save
from pricing_agent.sales_log import record_sale

NOW = datetime(2026, 8, 6, tzinfo=timezone.utc)


def _seed_state(state_path, current_price_usd=5.0, last_reviewed_at=None):
    state = load(state_path)
    state = record_change(state, event="launch", new_price_usd=current_price_usd, price_id="mock_price_seed")
    state["last_reviewed_at"] = last_reviewed_at
    save(state, state_path)


def _seed_sales(sales_path, count, at):
    for i in range(count):
        record_sale(f"buyer{i}@example.com", 5.0, source="mock_checkout", store_path=sales_path)
    # force le timestamp de chaque vente à `at`, indépendamment de l'heure réelle d'exécution du test
    import json

    data = json.loads(sales_path.read_text(encoding="utf-8"))
    for sale in data["sales"]:
        sale["at"] = at.isoformat()
    sales_path.write_text(json.dumps(data), encoding="utf-8")


def test_below_threshold_makes_no_change(tmp_path):
    state_path = tmp_path / "pricing_state.json"
    sales_path = tmp_path / "sales_log.json"
    _seed_state(state_path, current_price_usd=5.0)
    _seed_sales(sales_path, pricing_config.SALES_THRESHOLD_PER_WINDOW - 1, NOW - timedelta(days=1))

    result = evaluate_and_apply(now=NOW, state_path=state_path, sales_path=sales_path)

    assert result["action"] == "no_change"
    assert load(state_path)["current_price_usd"] == 5.0


@patch("pricing_agent.demand_pricing.sync_price_to_paddle", return_value="mock_price_increased")
def test_above_threshold_increases_price_by_fixed_percentage(mock_sync, tmp_path):
    state_path = tmp_path / "pricing_state.json"
    sales_path = tmp_path / "sales_log.json"
    _seed_state(state_path, current_price_usd=5.0)
    _seed_sales(sales_path, pricing_config.SALES_THRESHOLD_PER_WINDOW + 5, NOW - timedelta(days=1))

    result = evaluate_and_apply(now=NOW, state_path=state_path, sales_path=sales_path)

    expected_price = round(5.0 * (1 + pricing_config.DEMAND_INCREASE_PCT), 2)
    assert result["action"] == "increased"
    assert result["new_price_usd"] == expected_price
    state = load(state_path)
    assert state["current_price_usd"] == expected_price
    assert state["paddle_price_id"] == "mock_price_increased"
    assert state["history"][-1]["event"] == "demand_increase"
    mock_sync.assert_called_once_with(expected_price)


@patch("pricing_agent.demand_pricing.sync_price_to_paddle", return_value="mock_price_capped")
def test_increase_is_capped_at_ceiling(mock_sync, tmp_path):
    state_path = tmp_path / "pricing_state.json"
    sales_path = tmp_path / "sales_log.json"
    near_ceiling = pricing_config.PRICE_CEILING_USD - 1
    _seed_state(state_path, current_price_usd=near_ceiling)
    _seed_sales(sales_path, pricing_config.SALES_THRESHOLD_PER_WINDOW + 1, NOW - timedelta(days=1))

    result = evaluate_and_apply(now=NOW, state_path=state_path, sales_path=sales_path)

    assert result["action"] == "increased"
    assert result["new_price_usd"] == pricing_config.PRICE_CEILING_USD
    assert load(state_path)["history"][-1]["capped"] is True


def test_never_exceeds_ceiling_once_already_at_it(tmp_path):
    state_path = tmp_path / "pricing_state.json"
    sales_path = tmp_path / "sales_log.json"
    _seed_state(state_path, current_price_usd=pricing_config.PRICE_CEILING_USD)
    _seed_sales(sales_path, pricing_config.SALES_THRESHOLD_PER_WINDOW + 1, NOW - timedelta(days=1))

    result = evaluate_and_apply(now=NOW, state_path=state_path, sales_path=sales_path)

    assert result["action"] == "ceiling_reached"
    assert load(state_path)["current_price_usd"] == pricing_config.PRICE_CEILING_USD


def test_periodic_not_realtime_skips_review_within_the_same_window(tmp_path):
    state_path = tmp_path / "pricing_state.json"
    sales_path = tmp_path / "sales_log.json"
    _seed_state(state_path, current_price_usd=5.0, last_reviewed_at=(NOW - timedelta(days=1)).isoformat())
    _seed_sales(sales_path, pricing_config.SALES_THRESHOLD_PER_WINDOW + 5, NOW - timedelta(hours=1))

    result = evaluate_and_apply(now=NOW, state_path=state_path, sales_path=sales_path)

    assert result["action"] == "skipped_not_due"
    assert load(state_path)["current_price_usd"] == 5.0


def test_review_is_due_again_after_window_elapses(tmp_path):
    state_path = tmp_path / "pricing_state.json"
    sales_path = tmp_path / "sales_log.json"
    long_ago = NOW - timedelta(days=pricing_config.REVIEW_WINDOW_DAYS + 1)
    _seed_state(state_path, current_price_usd=5.0, last_reviewed_at=long_ago.isoformat())
    _seed_sales(sales_path, pricing_config.SALES_THRESHOLD_PER_WINDOW - 1, NOW - timedelta(hours=1))

    result = evaluate_and_apply(now=NOW, state_path=state_path, sales_path=sales_path)

    assert result["action"] == "no_change"
