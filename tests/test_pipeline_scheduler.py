import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from pipeline.scheduler import DEFAULT_CONFIG, check_pending_for_tacit_approval, run_once


@pytest.fixture
def pending_paths(tmp_path):
    reports_dir = tmp_path / "reports"
    pending_file = tmp_path / "pending_validation.json"
    data_dir = tmp_path / "data"
    reports_dir.mkdir()
    with patch("pipeline.run_pipeline.REPORTS_DIR", reports_dir), \
         patch("pipeline.run_pipeline.PENDING_VALIDATION_FILE", pending_file), \
         patch("pipeline.run_pipeline.DATA_DIR", data_dir), \
         patch("pipeline.auto_publish.DATA_DIR", data_dir), \
         patch("pipeline.auto_publish.PUBLISHED_COURSES_FILE", data_dir / "published_courses.json"):
        yield {"reports_dir": reports_dir, "pending_file": pending_file, "data_dir": data_dir}


def _write_pending(pending_file, slug, added_at):
    pending_file.write_text(
        json.dumps({"pending": [{"slug": slug, "topic": "T", "domain": "Vente", "added_at": added_at.isoformat()}]}),
        encoding="utf-8",
    )


def _write_report(reports_dir, slug, titre="Titre du cours", prix=19.99):
    (reports_dir / f"{slug}_report.json").write_text(
        json.dumps({"titre": titre, "prix_suggere_usd": prix}), encoding="utf-8"
    )


def test_check_pending_skips_entries_still_within_the_window(pending_paths):
    now = datetime.now(timezone.utc)
    _write_pending(pending_paths["pending_file"], "mon-slug", added_at=now - timedelta(hours=1))
    _write_report(pending_paths["reports_dir"], "mon-slug")

    with patch("pipeline.auto_publish.auto_publish") as mock_auto_publish:
        outcomes = check_pending_for_tacit_approval(config={**DEFAULT_CONFIG, "MAX_VALIDATION_HOURS": 2}, now=now)

    assert outcomes == []
    mock_auto_publish.assert_not_called()
    pending = json.loads(pending_paths["pending_file"].read_text(encoding="utf-8"))["pending"]
    assert len(pending) == 1  # toujours en attente, pas retire


def test_check_pending_publishes_entries_past_the_window(pending_paths):
    now = datetime.now(timezone.utc)
    _write_pending(pending_paths["pending_file"], "mon-slug", added_at=now - timedelta(hours=3))
    _write_report(pending_paths["reports_dir"], "mon-slug", titre="Mon Cours", prix=19.99)

    with patch("pipeline.auto_publish.auto_publish") as mock_auto_publish:
        outcomes = check_pending_for_tacit_approval(config={**DEFAULT_CONFIG, "MAX_VALIDATION_HOURS": 2}, now=now)

    assert outcomes == [{"slug": "mon-slug", "status": "published"}]
    mock_auto_publish.assert_called_once_with("mon-slug", title="Mon Cours", domain="Vente", price_usd=19.99)

    pending = json.loads(pending_paths["pending_file"].read_text(encoding="utf-8"))["pending"]
    assert pending == []  # retire de la file d'attente

    ready_marker = pending_paths["data_dir"] / "mon-slug" / "READY_TO_PUBLISH"
    assert ready_marker.exists()


def test_check_pending_skips_when_report_missing(pending_paths):
    now = datetime.now(timezone.utc)
    _write_pending(pending_paths["pending_file"], "mon-slug", added_at=now - timedelta(hours=5))
    # Pas de rapport ecrit pour ce slug.

    with patch("pipeline.auto_publish.auto_publish") as mock_auto_publish:
        outcomes = check_pending_for_tacit_approval(config={**DEFAULT_CONFIG, "MAX_VALIDATION_HOURS": 2}, now=now)

    assert outcomes == [{"slug": "mon-slug", "status": "skipped_no_report"}]
    mock_auto_publish.assert_not_called()
    pending = json.loads(pending_paths["pending_file"].read_text(encoding="utf-8"))["pending"]
    assert len(pending) == 1  # laisse en attente, jamais silencieusement perdu


def test_check_pending_logs_failure_when_auto_publish_raises(pending_paths):
    from pipeline.auto_publish import AutoPublishError

    now = datetime.now(timezone.utc)
    _write_pending(pending_paths["pending_file"], "mon-slug", added_at=now - timedelta(hours=5))
    _write_report(pending_paths["reports_dir"], "mon-slug")

    with patch("pipeline.auto_publish.auto_publish", side_effect=AutoPublishError("PADDLE_API_KEY manquant")):
        outcomes = check_pending_for_tacit_approval(config={**DEFAULT_CONFIG, "MAX_VALIDATION_HOURS": 2}, now=now)

    assert outcomes == [{"slug": "mon-slug", "status": "failed"}]
    # Deja retire de la file (la decision "oui" a ete appliquee avant l'appel a auto_publish) -
    # evite de re-tenter en boucle indefiniment un cours dont la publication echoue de facon stable.
    pending = json.loads(pending_paths["pending_file"].read_text(encoding="utf-8"))["pending"]
    assert pending == []


# --- run_once : un run demo ne doit jamais consommer le quota/delai reels ----------------------


@patch("pipeline.scheduler.save_state")
@patch("pipeline.scheduler.record_course_started")
@patch("pipeline.scheduler.pick_next_topic")
def test_run_once_demo_mode_never_updates_scheduler_state(mock_pick_topic, mock_record, mock_save):
    # Bug reel corrige ici : un --once --demo appelait quand meme record_course_started/save_state,
    # ce qui faisait bloquer le PROCHAIN run reel pendant MIN_HOURS_BETWEEN_COURSES (12h) a cause
    # d'un simple test gratuit.
    mock_pick_topic.return_value = {
        "domain": "Vente", "topic": "Sujet demo", "score_total": 20,
        "suggested_price_usd": 19.99, "justification": "",
    }
    with patch("pipeline.run_pipeline.run_pipeline") as mock_run_pipeline:
        mock_run_pipeline.return_value = {"slug": "sujet-demo", "status": "completed", "decision": "attente", "report": {}}
        result = run_once(DEFAULT_CONFIG, state={}, demo=True)

    assert result["status"] == "completed"
    mock_record.assert_not_called()
    mock_save.assert_not_called()


@patch("pipeline.scheduler.save_state")
@patch("pipeline.scheduler.record_course_started")
@patch("pipeline.scheduler.pick_next_topic")
def test_run_once_real_mode_updates_scheduler_state_on_completion(mock_pick_topic, mock_record, mock_save):
    mock_pick_topic.return_value = {
        "domain": "Vente", "topic": "Sujet reel", "score_total": 20,
        "suggested_price_usd": 19.99, "justification": "",
    }
    state = {"paused": False}
    with patch("pipeline.run_pipeline.run_pipeline") as mock_run_pipeline:
        mock_run_pipeline.return_value = {"slug": "sujet-reel", "status": "completed", "decision": "attente", "report": {}}
        result = run_once(DEFAULT_CONFIG, state=state, demo=False)

    assert result["status"] == "completed"
    mock_record.assert_called_once_with(state)
    mock_save.assert_called_once_with(state)
