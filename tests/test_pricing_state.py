from pricing_agent import config as pricing_config
from pricing_agent.pricing_state import get_current_price_id, get_current_price_usd, load, record_change, save


def test_load_returns_launch_price_default_when_no_file_exists(tmp_path):
    store = tmp_path / "pricing_state.json"
    state = load(store)

    assert state["current_price_usd"] == pricing_config.LAUNCH_PRICE_USD
    assert state["paddle_price_id"] is None
    assert state["history"] == []
    assert not store.exists()


def test_save_then_load_roundtrip(tmp_path):
    store = tmp_path / "pricing_state.json"
    state = load(store)
    state["current_price_usd"] = 7.5
    save(state, store)

    reloaded = load(store)
    assert reloaded["current_price_usd"] == 7.5


def test_record_change_updates_price_and_appends_history(tmp_path):
    store = tmp_path / "pricing_state.json"
    state = load(store)

    state = record_change(state, event="launch", new_price_usd=5.0, price_id="mock_price_abc", signal="test")

    assert state["current_price_usd"] == 5.0
    assert state["paddle_price_id"] == "mock_price_abc"
    assert len(state["history"]) == 1
    entry = state["history"][0]
    assert entry["event"] == "launch"
    assert entry["old_price_usd"] == pricing_config.LAUNCH_PRICE_USD
    assert entry["new_price_usd"] == 5.0
    assert entry["signal"] == "test"


def test_record_change_without_new_price_only_logs_a_review(tmp_path):
    store = tmp_path / "pricing_state.json"
    state = load(store)
    state = record_change(state, event="demand_no_change", sales_observed=2, threshold=10)

    assert state["current_price_usd"] == pricing_config.LAUNCH_PRICE_USD
    assert state["history"][0]["sales_observed"] == 2


def test_get_current_price_helpers(tmp_path):
    store = tmp_path / "pricing_state.json"
    state = load(store)
    state = record_change(state, event="launch", new_price_usd=6.0, price_id="mock_price_xyz")
    save(state, store)

    assert get_current_price_usd(store) == 6.0
    assert get_current_price_id(store) == "mock_price_xyz"
