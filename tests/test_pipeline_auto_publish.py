import json
from unittest.mock import MagicMock, patch

import pytest

from pipeline.auto_publish import (
    AutoPublishError,
    add_published_course,
    auto_publish,
    create_paddle_product_and_price,
    load_published_courses,
    publish_course_files,
    save_paddle_info,
    trigger_render_redeploy,
)


@pytest.fixture
def data_dir(tmp_path):
    with patch("pipeline.auto_publish.DATA_DIR", tmp_path), \
         patch("pipeline.auto_publish.PUBLISHED_COURSES_FILE", tmp_path / "published_courses.json"):
        yield tmp_path


def _write_ready_to_publish(data_dir, slug, price_usd=19.99):
    course_dir = data_dir / slug
    course_dir.mkdir(parents=True, exist_ok=True)
    (course_dir / "READY_TO_PUBLISH").write_text(
        json.dumps({"validated_at": "2026-01-01T00:00:00+00:00", "price_usd": price_usd}), encoding="utf-8"
    )


def _write_pipeline_outputs(data_dir, slug):
    pipeline_dir = data_dir / slug / "pipeline"
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    (pipeline_dir / "curriculum.json").write_text(json.dumps({"title": "T"}), encoding="utf-8")
    (pipeline_dir / "final_content.json").write_text(json.dumps({"chapters_content": []}), encoding="utf-8")


def test_auto_publish_raises_when_ready_to_publish_marker_missing(data_dir):
    with pytest.raises(AutoPublishError, match="READY_TO_PUBLISH"):
        auto_publish("mon-slug", "Mon Titre", "Finance personnelle")


def test_create_paddle_product_and_price_raises_when_api_key_missing(monkeypatch):
    monkeypatch.delenv("PADDLE_API_KEY", raising=False)
    with pytest.raises(AutoPublishError, match="PADDLE_API_KEY"):
        create_paddle_product_and_price("Mon Titre", 19.99)


@patch("pipeline.auto_publish.requests.post")
def test_create_paddle_product_and_price_success(mock_post, monkeypatch):
    monkeypatch.setenv("PADDLE_API_KEY", "fake-key")
    mock_post.side_effect = [
        MagicMock(status_code=200, json=lambda: {"data": {"id": "pro_123"}}),
        MagicMock(status_code=200, json=lambda: {"data": {"id": "pri_456"}}),
    ]

    result = create_paddle_product_and_price("Mon Cours", 24.99)

    assert result == {"product_id": "pro_123", "price_id": "pri_456"}
    product_call, price_call = mock_post.call_args_list
    assert product_call.args[0].endswith("/products")
    assert product_call.kwargs["json"]["name"] == "Mon Cours"
    assert product_call.kwargs["json"]["type"] == "standard"
    assert price_call.args[0].endswith("/prices")
    assert price_call.kwargs["json"]["product_id"] == "pro_123"
    assert price_call.kwargs["json"]["unit_price"] == {"amount": "2499", "currency_code": "USD"}


@patch("pipeline.auto_publish.requests.post")
def test_create_paddle_product_and_price_raises_on_product_http_error(mock_post, monkeypatch):
    monkeypatch.setenv("PADDLE_API_KEY", "fake-key")
    mock_post.return_value = MagicMock(status_code=400, text="bad request")

    with pytest.raises(AutoPublishError, match="produit Paddle"):
        create_paddle_product_and_price("Mon Cours", 24.99)


@patch("pipeline.auto_publish.requests.post")
def test_create_paddle_product_and_price_raises_on_price_http_error(mock_post, monkeypatch):
    monkeypatch.setenv("PADDLE_API_KEY", "fake-key")
    mock_post.side_effect = [
        MagicMock(status_code=200, json=lambda: {"data": {"id": "pro_123"}}),
        MagicMock(status_code=500, text="server error"),
    ]

    with pytest.raises(AutoPublishError, match="prix Paddle"):
        create_paddle_product_and_price("Mon Cours", 24.99)


def test_save_paddle_info_writes_expected_json(data_dir):
    path = save_paddle_info("mon-slug", "pro_123", "pri_456")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["product_id"] == "pro_123"
    assert payload["price_id"] == "pri_456"
    assert path == data_dir / "mon-slug" / "paddle_info.json"


def test_publish_course_files_raises_when_source_missing(data_dir):
    with pytest.raises(AutoPublishError, match="introuvables"):
        publish_course_files("mon-slug")


def test_publish_course_files_copies_to_stable_location(data_dir):
    _write_pipeline_outputs(data_dir, "mon-slug")

    files = publish_course_files("mon-slug")

    assert files["curriculum_file"] == data_dir / "mon-slug" / "curriculum.json"
    assert files["content_file"] == data_dir / "mon-slug" / "content_final.json"
    assert json.loads(files["curriculum_file"].read_text(encoding="utf-8")) == {"title": "T"}


def test_load_published_courses_missing_file_returns_empty(data_dir):
    assert load_published_courses() == []


def test_add_published_course_appends_and_replaces_existing_slug(data_dir):
    add_published_course({"slug": "a", "title": "Cours A"})
    add_published_course({"slug": "b", "title": "Cours B"})
    assert [c["slug"] for c in load_published_courses()] == ["a", "b"]

    add_published_course({"slug": "a", "title": "Cours A v2"})
    courses = load_published_courses()
    assert len(courses) == 2
    assert next(c for c in courses if c["slug"] == "a")["title"] == "Cours A v2"


def test_trigger_render_redeploy_returns_none_when_not_configured(monkeypatch):
    monkeypatch.delenv("RENDER_API_KEY", raising=False)
    monkeypatch.delenv("RENDER_SERVICE_ID", raising=False)
    assert trigger_render_redeploy() is None


@patch("pipeline.auto_publish.requests.post")
def test_trigger_render_redeploy_calls_api_when_configured(mock_post, monkeypatch):
    monkeypatch.setenv("RENDER_API_KEY", "fake-render-key")
    monkeypatch.setenv("RENDER_SERVICE_ID", "srv-123")
    mock_post.return_value = MagicMock(status_code=201, json=lambda: {"id": "dep_1"})

    result = trigger_render_redeploy()

    assert result == {"id": "dep_1"}
    assert "srv-123" in mock_post.call_args.args[0]


@patch("pipeline.auto_publish.requests.post")
def test_trigger_render_redeploy_degrades_on_http_error(mock_post, monkeypatch):
    monkeypatch.setenv("RENDER_API_KEY", "fake-render-key")
    monkeypatch.setenv("RENDER_SERVICE_ID", "srv-123")
    mock_post.return_value = MagicMock(status_code=500, text="boom")

    assert trigger_render_redeploy() is None


@patch("pipeline.auto_publish.requests.post")
def test_auto_publish_end_to_end_with_mocked_apis(mock_post, monkeypatch, data_dir):
    monkeypatch.setenv("PADDLE_API_KEY", "fake-key")
    monkeypatch.delenv("RENDER_API_KEY", raising=False)
    monkeypatch.delenv("RENDER_SERVICE_ID", raising=False)
    mock_post.side_effect = [
        MagicMock(status_code=200, json=lambda: {"data": {"id": "pro_123"}}),
        MagicMock(status_code=200, json=lambda: {"data": {"id": "pri_456"}}),
    ]

    _write_ready_to_publish(data_dir, "mon-slug", price_usd=19.99)
    _write_pipeline_outputs(data_dir, "mon-slug")

    result = auto_publish("mon-slug", "Mon Cours", "Finance personnelle")

    assert result["slug"] == "mon-slug"
    assert result["paddle"] == {"product_id": "pro_123", "price_id": "pri_456"}
    assert result["render_deploy_triggered"] is False

    published = load_published_courses()
    assert len(published) == 1
    assert published[0]["paddle_price_id"] == "pri_456"
    assert published[0]["price_usd"] == 19.99
    assert published[0]["domain"] == "Finance personnelle"

    assert (data_dir / "mon-slug" / "curriculum.json").exists()
    assert (data_dir / "mon-slug" / "content_final.json").exists()
    assert (data_dir / "mon-slug" / "paddle_info.json").exists()


@patch("pipeline.auto_publish.requests.post")
def test_auto_publish_uses_price_from_marker_when_not_provided_explicitly(mock_post, monkeypatch, data_dir):
    monkeypatch.setenv("PADDLE_API_KEY", "fake-key")
    mock_post.side_effect = [
        MagicMock(status_code=200, json=lambda: {"data": {"id": "pro_1"}}),
        MagicMock(status_code=200, json=lambda: {"data": {"id": "pri_1"}}),
    ]
    _write_ready_to_publish(data_dir, "mon-slug", price_usd=29.5)
    _write_pipeline_outputs(data_dir, "mon-slug")

    auto_publish("mon-slug", "Mon Cours", "Vente", price_usd=None)

    price_call = mock_post.call_args_list[1]
    assert price_call.kwargs["json"]["unit_price"]["amount"] == "2950"
