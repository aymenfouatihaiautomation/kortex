from datetime import datetime, timedelta, timezone

from pricing_agent.sales_log import record_sale, sales_in_window


def test_sales_in_window_is_zero_when_no_sales(tmp_path):
    store = tmp_path / "sales_log.json"
    assert sales_in_window(days=7, store_path=store) == 0


def test_record_sale_then_counted_in_window(tmp_path):
    store = tmp_path / "sales_log.json"
    record_sale("a@example.com", 5.0, source="mock_checkout", store_path=store)
    record_sale("b@example.com", 5.0, source="webhook", store_path=store)

    assert sales_in_window(days=7, store_path=store) == 2


def test_sales_outside_window_are_not_counted(tmp_path, monkeypatch):
    store = tmp_path / "sales_log.json"
    now = datetime(2026, 8, 1, tzinfo=timezone.utc)

    old_sale_time = now - timedelta(days=10)

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return old_sale_time

    monkeypatch.setattr("pricing_agent.sales_log.datetime", _FrozenDatetime)
    record_sale("old@example.com", 5.0, source="mock_checkout", store_path=store)

    assert sales_in_window(days=7, now=now, store_path=store) == 0
    assert sales_in_window(days=14, now=now, store_path=store) == 1
