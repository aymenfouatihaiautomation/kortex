import json
import time
from unittest.mock import patch

import pytest

from pipeline.run_pipeline import (
    _aggregate_cost,
    _new_checkpoint,
    add_pending_validation,
    apply_validation_decision,
    load_checkpoint,
    load_pending_validation,
    prompt_validation,
    remove_pending_validation,
    run_pipeline,
    save_report,
)


def test_new_checkpoint_has_expected_shape():
    checkpoint = _new_checkpoint("mon-slug", "Mon Sujet", "Finance personnelle", 19.99, dry_run=True)
    assert checkpoint["slug"] == "mon-slug"
    assert checkpoint["status"] == "in_progress"
    assert checkpoint["stages"] == {}
    assert checkpoint["dry_run"] is True


def test_aggregate_cost_sums_across_stages_and_ignores_stages_without_cost():
    checkpoint = {
        "stages": {
            "bloc0": {"status": "done"},  # pas de cle "cost" - ne doit pas planter
            "bloc1": {"cost": {"calls": 1, "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.01}},
            "bloc2": {"cost": {"calls": 2, "input_tokens": 200, "output_tokens": 100, "cost_usd": 0.02}},
        }
    }
    assert _aggregate_cost(checkpoint) == {"calls": 3, "input_tokens": 300, "output_tokens": 150, "cost_usd": 0.03}


def test_apply_validation_decision_oui_writes_ready_to_publish(tmp_path):
    with patch("pipeline.run_pipeline.DATA_DIR", tmp_path):
        path = apply_validation_decision("mon-slug", "oui", price_usd=19.99)
    assert path.name == "READY_TO_PUBLISH"
    assert json.loads(path.read_text(encoding="utf-8"))["price_usd"] == 19.99


def test_apply_validation_decision_non_writes_rejected_with_reason(tmp_path):
    with patch("pipeline.run_pipeline.DATA_DIR", tmp_path):
        path = apply_validation_decision("mon-slug", "non", reason="pas assez de demande")
    assert path.name == "REJECTED"
    assert json.loads(path.read_text(encoding="utf-8"))["reason"] == "pas assez de demande"


def test_apply_validation_decision_rejects_attente_as_invalid():
    with pytest.raises(ValueError):
        apply_validation_decision("mon-slug", "attente")


def test_pending_validation_add_then_remove_roundtrip(tmp_path):
    path = tmp_path / "pending.json"
    add_pending_validation({"slug": "a", "topic": "T"}, path=path)
    add_pending_validation({"slug": "b", "topic": "T2"}, path=path)
    assert [p["slug"] for p in load_pending_validation(path)] == ["a", "b"]

    remove_pending_validation("a", path=path)
    assert [p["slug"] for p in load_pending_validation(path)] == ["b"]


def test_pending_validation_add_replaces_existing_entry_for_same_slug(tmp_path):
    path = tmp_path / "pending.json"
    add_pending_validation({"slug": "a", "topic": "V1"}, path=path)
    add_pending_validation({"slug": "a", "topic": "V2"}, path=path)
    pending = load_pending_validation(path)
    assert len(pending) == 1
    assert pending[0]["topic"] == "V2"


def test_save_report_writes_json_and_readable_text(tmp_path):
    report = {
        "slug": "mon-slug",
        "topic": "Mon Sujet",
        "domain": "Finance personnelle",
        "titre": "Mon Sujet — Formation complète",
        "plan": ["1. Chapitre 1"],
        "chapitres": [{"number": 1, "title": "Chapitre 1"}],
        "score_qc": {"accepted": 1, "escalated": 0},
        "cout_tokens_estime": {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
        "prix_suggere_usd": 19.99,
        "statut_banque_examen": "done",
        "statut_pipeline": "completed",
        "generated_at": "2026-01-01T00:00:00+00:00",
    }
    with patch("pipeline.run_pipeline.REPORTS_DIR", tmp_path):
        json_path, txt_path = save_report(report)

    assert json.loads(json_path.read_text(encoding="utf-8"))["slug"] == "mon-slug"
    assert "Mon Sujet" in txt_path.read_text(encoding="utf-8")


def test_prompt_validation_returns_input_when_answered_in_time():
    with patch("builtins.input", return_value="oui"):
        assert prompt_validation(timeout_seconds=5) == "oui"


def test_prompt_validation_normalizes_and_rejects_unknown_answers():
    with patch("builtins.input", return_value="  OUI  "):
        assert prompt_validation(timeout_seconds=5) == "oui"
    with patch("builtins.input", return_value="peut-etre"):
        assert prompt_validation(timeout_seconds=5) == "attente"


def test_prompt_validation_falls_back_to_attente_on_timeout():
    def _slow_input(_prompt):
        time.sleep(1)
        return "oui"

    with patch("builtins.input", side_effect=_slow_input):
        assert prompt_validation(timeout_seconds=0.1) == "attente"


@pytest.fixture
def pipeline_paths(tmp_path):
    """Redirige TOUS les emplacements d'écriture disque de run_pipeline (+ celui du Bloc 7, qui
    garde son propre DATA_DIR importé séparément) vers un répertoire temporaire — aucun test ne
    doit écrire dans data/ ou pipeline/ du vrai dépôt."""
    paths = {
        "data_dir": tmp_path / "data",
        "checkpoints_dir": tmp_path / "checkpoints",
        "reports_dir": tmp_path / "reports",
        "pending_file": tmp_path / "pending_validation.json",
        "produced_file": tmp_path / "produced_courses.json",
    }
    with patch("pipeline.run_pipeline.DATA_DIR", paths["data_dir"]), \
         patch("pipeline.run_pipeline.CHECKPOINTS_DIR", paths["checkpoints_dir"]), \
         patch("pipeline.run_pipeline.REPORTS_DIR", paths["reports_dir"]), \
         patch("pipeline.run_pipeline.PENDING_VALIDATION_FILE", paths["pending_file"]), \
         patch("pipeline.domain_agent.PRODUCED_COURSES_FILE", paths["produced_file"]), \
         patch("bloc7_exam_generation.build_exam_bank.DATA_DIR", paths["data_dir"]):
        yield paths


def test_run_pipeline_dry_run_end_to_end_completes_and_queues_for_validation(pipeline_paths):
    result = run_pipeline(
        topic="Automatiser ses tableaux Excel",
        domain="Excel avancé",
        price_usd=19.99,
        dry_run=True,
        interactive=False,
    )

    assert result["status"] == "completed"
    assert result["decision"] == "attente"
    slug = result["slug"]

    checkpoint = json.loads((pipeline_paths["checkpoints_dir"] / f"{slug}.json").read_text(encoding="utf-8"))
    assert checkpoint["status"] == "completed"
    assert checkpoint["stages"]["bloc0"]["status"] == "done"
    assert checkpoint["stages"]["bloc1"]["status"] == "done"
    assert checkpoint["stages"]["bloc2"]["status"] == "done"
    assert checkpoint["stages"]["bloc3_5"]["status"] == "done"
    assert checkpoint["stages"]["enrich"]["status"] == "done"
    assert checkpoint["stages"]["bloc7"]["status"] == "done"

    course_dir = pipeline_paths["data_dir"] / slug
    assert (course_dir / "pipeline" / "curriculum.json").exists()
    assert (course_dir / "pipeline" / "final_content.json").exists()
    assert (course_dir / "exam_questions.json").exists()

    final_content = json.loads((course_dir / "pipeline" / "final_content.json").read_text(encoding="utf-8"))
    # Bloc 2.5 (enrichissement) en mode démo réussit toujours (blocs placeholder validés) — chaque
    # chapitre avec lesson_script doit avoir gagné son content_blocks, comme le cours 1.
    for chap in final_content["chapters_content"]:
        if chap.get("lesson_script"):
            assert "content_blocks" in chap

    report = json.loads((pipeline_paths["reports_dir"] / f"{slug}_report.json").read_text(encoding="utf-8"))
    assert report["domain"] == "Excel avancé"
    assert len(report["chapitres"]) > 0

    pending = json.loads(pipeline_paths["pending_file"].read_text(encoding="utf-8"))["pending"]
    assert any(p["slug"] == slug for p in pending)

    produced = json.loads(pipeline_paths["produced_file"].read_text(encoding="utf-8"))["produced"]
    assert any(p["slug"] == slug for p in produced)


def test_run_pipeline_dry_run_with_skip_qc_marks_stage_skipped(pipeline_paths):
    result = run_pipeline(
        topic="Négocier son salaire",
        domain="Négociation",
        price_usd=14.99,
        skip_qc=True,
        dry_run=True,
        interactive=False,
    )

    assert result["status"] == "completed"
    slug = result["slug"]
    checkpoint = json.loads((pipeline_paths["checkpoints_dir"] / f"{slug}.json").read_text(encoding="utf-8"))
    assert checkpoint["stages"]["bloc3_5"]["status"] == "skipped"
    assert checkpoint["stages"]["bloc7"]["status"] == "done"


def test_run_pipeline_resume_reuses_completed_stages_instead_of_recomputing(pipeline_paths):
    first = run_pipeline(
        topic="Piloter un projet agile",
        domain="Gestion de projet",
        price_usd=17.99,
        dry_run=True,
        interactive=False,
    )
    slug = first["slug"]
    checkpoint_path = pipeline_paths["checkpoints_dir"] / f"{slug}.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    bloc1_completed_at_before = checkpoint["stages"]["bloc1"]["completed_at"]

    # Simule une interruption APRES le Bloc 1 : on retire tout ce qui suit, sans toucher bloc0/1.
    checkpoint["stages"] = {"bloc0": checkpoint["stages"]["bloc0"], "bloc1": checkpoint["stages"]["bloc1"]}
    checkpoint["status"] = "in_progress"
    checkpoint_path.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")

    second = run_pipeline(
        topic="Piloter un projet agile",
        domain="Gestion de projet",
        price_usd=17.99,
        dry_run=True,
        interactive=False,
        resume=True,
    )

    assert second["status"] == "completed"
    resumed_checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    # Le Bloc 1 n'a pas ete recalcule : son horodatage de completion est identique.
    assert resumed_checkpoint["stages"]["bloc1"]["completed_at"] == bloc1_completed_at_before
    assert resumed_checkpoint["stages"]["bloc7"]["status"] == "done"


def test_run_pipeline_non_interactive_never_prompts(pipeline_paths):
    with patch("pipeline.run_pipeline.prompt_validation") as mock_prompt:
        run_pipeline(
            topic="Prendre la parole en public",
            domain="Communication",
            price_usd=12.99,
            dry_run=True,
            interactive=False,
        )
    mock_prompt.assert_not_called()
