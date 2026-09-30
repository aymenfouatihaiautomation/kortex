import json
from unittest.mock import patch

import pytest

from bloc3_5_quality_control.graph import run_chapter_qc
from bloc3_5_quality_control.quality_control import apply_manual_correction, run_quality_control
from bloc3_5_quality_control.reviewer import CRITERIA_MIX, build_review_prompt, review_chapter, validate_review
from common.llm_client import LLMCallError

CURRICULUM = {
    "title": "Cours test",
    "niche": "AI Automation",
    "level": "intermédiaire",
    "chapters": [
        {
            "number": 1,
            "title": "Intro",
            "learning_objectives": ["obj1"],
            "key_points": ["kp1"],
            "builds_on_previous": "N/A - premier chapitre",
        },
        {
            "number": 2,
            "title": "Suite",
            "learning_objectives": ["obj1"],
            "key_points": ["kp1"],
            "builds_on_previous": "S'appuie sur le chapitre 1.",
        },
    ],
}

CONTENT_CH1 = {
    "chapter_number": 1,
    "chapter_title": "Intro",
    "lesson_script": "x" * 250,
    "comprehension_exercises": [
        {"question": "Q1?", "type": "mcq", "options": ["A", "B"], "correct_answer": "A"},
        {"question": "Q2?", "type": "short_answer", "options": None, "correct_answer": "R2"},
        {"question": "Q3?", "type": "mcq", "options": ["A", "B"], "correct_answer": "B"},
    ],
    "practical_exercise": {"title": "Ex", "instructions": "Fais ceci.", "expected_outcome": "Résultat."},
}

BLOC2_RESULT = {
    "course_title": "Cours test",
    "niche": "AI Automation",
    "level": "intermédiaire",
    "running_example": "Fil rouge test",
    "chapters_content": [
        CONTENT_CH1,
        {**CONTENT_CH1, "chapter_number": 2, "chapter_title": "Suite"},
    ],
}

ACCEPTED_REVIEW = {
    "chapter_number": 1,
    "overall_verdict": "accepted",
    "criteria": {
        "coverage": {"verdict": "pass", "justification": "ok"},
        "logical_coherence": {"verdict": "pass", "justification": "ok"},
        "technical_accuracy": {"verdict": "pass", "justification": "ok"},
        "exercise_quality": {"verdict": "pass", "justification": "ok"},
    },
    "issues": [],
}

NEEDS_REVISION_REVIEW = {
    "chapter_number": 1,
    "overall_verdict": "needs_revision",
    "criteria": {
        "coverage": {"verdict": "pass", "justification": "ok"},
        "logical_coherence": {"verdict": "pass", "justification": "ok"},
        "technical_accuracy": {"verdict": "pass", "justification": "ok"},
        "exercise_quality": {"verdict": "fail", "justification": "trop générique"},
    },
    "issues": [{"field": "practical_exercise", "description": "Rendre plus spécifique."}],
}


# --- validate_review ---------------------------------------------------------------------------

def test_validate_review_accepts_consistent_accepted_review():
    assert validate_review(ACCEPTED_REVIEW) == []


def test_validate_review_accepts_consistent_needs_revision_review():
    assert validate_review(NEEDS_REVISION_REVIEW) == []


def test_validate_review_rejects_accepted_with_a_failing_criterion():
    bad = json.loads(json.dumps(ACCEPTED_REVIEW))
    bad["criteria"]["technical_accuracy"]["verdict"] = "fail"
    errors = validate_review(bad)
    assert any("incohérent" in e for e in errors)


def test_validate_review_rejects_needs_revision_without_issues():
    bad = json.loads(json.dumps(NEEDS_REVISION_REVIEW))
    bad["issues"] = []
    errors = validate_review(bad)
    assert any("issues" in e for e in errors)


def test_validate_review_rejects_invalid_issue_field():
    bad = json.loads(json.dumps(NEEDS_REVISION_REVIEW))
    bad["issues"][0]["field"] = "not_a_real_field"
    errors = validate_review(bad)
    assert any("field invalide" in e for e in errors)


# --- review_chapter (mode démo) -----------------------------------------------------------------

def test_review_chapter_demo_rejects_on_first_attempt_then_accepts():
    first = review_chapter(CURRICULUM, CURRICULUM["chapters"][0], None, CONTENT_CH1, 2, attempt=0, demo=True)
    assert first["overall_verdict"] == "needs_revision"
    assert first["issues"]

    second = review_chapter(CURRICULUM, CURRICULUM["chapters"][0], None, CONTENT_CH1, 2, attempt=1, demo=True)
    assert second["overall_verdict"] == "accepted"


@patch("bloc3_5_quality_control.reviewer.call_llm_api")
def test_review_chapter_retries_on_malformed_json(mock_run_prompt):
    # Régression : un JSON tronqué/malformé du LLM ne doit pas planter mais déclencher un retry
    # (bug réel rencontré lors du premier run réel du Bloc 3.5 : JSONDecodeError non rattrapée).
    malformed = '{"chapter_number": 1, "overall_verdict": "accepted", "criteria": {'
    mock_run_prompt.side_effect = [malformed, json.dumps(ACCEPTED_REVIEW)]

    review = review_chapter(CURRICULUM, CURRICULUM["chapters"][0], None, CONTENT_CH1, 2, attempt=0, demo=False)

    assert review["overall_verdict"] == "accepted"
    assert mock_run_prompt.call_count == 2


@patch("bloc3_5_quality_control.reviewer.call_llm_api")
def test_review_chapter_raises_after_exhausting_retries_on_malformed_json(mock_run_prompt):
    mock_run_prompt.return_value = "pas du JSON du tout"

    with pytest.raises(LLMCallError):
        review_chapter(CURRICULUM, CURRICULUM["chapters"][0], None, CONTENT_CH1, 2, attempt=0, demo=False)

    assert mock_run_prompt.call_count == 2


# --- format par chapitre (2026-08-07) : text/video/mix, critère anti-redondance pour "mix" -----

VIDEO_CHAPTER = {**CURRICULUM["chapters"][0], "format": "video", "format_reasoning": "Démo visuelle."}
MIX_CHAPTER = {**CURRICULUM["chapters"][0], "format": "mix", "format_reasoning": "Vidéo + référence."}

VIDEO_CONTENT = {
    "chapter_number": 1,
    "chapter_title": "Intro",
    "video_script": {
        "summary": "La vidéo montre la démo.",
        "scenes": [
            {"beat": "Ouverture", "narration": "...", "visual": "..."},
            {"beat": "Démo", "narration": "...", "visual": "..."},
            {"beat": "Résultat", "narration": "...", "visual": "..."},
        ],
    },
    "written_complement": "Point non montré à l'écran.",
    "comprehension_exercises": CONTENT_CH1["comprehension_exercises"],
    "practical_exercise": CONTENT_CH1["practical_exercise"],
}

MIX_CONTENT = {
    "chapter_number": 1,
    "chapter_title": "Intro",
    "video_script": VIDEO_CONTENT["video_script"],
    "lesson_script": "x" * 250,
    "redundancy_check_notes": "Vidéo = démo, texte = référence, pas de recouvrement.",
    "comprehension_exercises": CONTENT_CH1["comprehension_exercises"],
    "practical_exercise": CONTENT_CH1["practical_exercise"],
}

ACCEPTED_MIX_REVIEW = {
    "chapter_number": 1,
    "overall_verdict": "accepted",
    "criteria": {name: {"verdict": "pass", "justification": "ok"} for name in CRITERIA_MIX},
    "issues": [],
}


def test_build_review_prompt_video_format_includes_video_script_not_lesson_script():
    prompt = build_review_prompt(CURRICULUM, VIDEO_CHAPTER, None, VIDEO_CONTENT, 2)
    assert "chapitre VIDÉO" in prompt
    assert "Ouverture" in prompt  # 1ère scène du video_script
    assert "Point non montré à l'écran." in prompt  # written_complement


def test_build_review_prompt_mix_format_includes_video_and_text_and_fifth_criterion():
    prompt = build_review_prompt(CURRICULUM, MIX_CHAPTER, None, MIX_CONTENT, 2)
    assert "chapitre MIXTE" in prompt
    assert "video_text_complementarity" in prompt
    assert "Vidéo = démo, texte = référence" in prompt  # redundancy_check_notes


def test_build_review_prompt_chapter_without_format_uses_text_template():
    """Rétrocompatibilité cours 1 : pas de champ 'format' -> gabarit text historique, inchangé."""
    chapter_no_format = CURRICULUM["chapters"][0]
    prompt = build_review_prompt(CURRICULUM, chapter_no_format, None, CONTENT_CH1, 2)
    assert "chapitre VIDÉO" not in prompt
    assert "chapitre MIXTE" not in prompt
    assert CONTENT_CH1["lesson_script"] in prompt


def test_validate_review_mix_requires_five_criteria():
    assert validate_review(ACCEPTED_MIX_REVIEW, criteria_names=CRITERIA_MIX) == []
    # Le même review, validé avec les 4 critères "text", doit être rejeté (clé en trop).
    errors = validate_review(ACCEPTED_MIX_REVIEW)
    assert any("criteria doit contenir exactement" in e for e in errors)


def test_review_chapter_demo_mode_mix_chapter_uses_five_criteria():
    review = review_chapter(CURRICULUM, MIX_CHAPTER, None, MIX_CONTENT, 2, attempt=1, demo=True)
    assert set(review["criteria"].keys()) == set(CRITERIA_MIX)
    assert review["overall_verdict"] == "accepted"


@patch("bloc3_5_quality_control.reviewer.call_llm_api")
def test_review_chapter_real_mode_video_format_sends_video_prompt(mock_run_prompt):
    mock_run_prompt.return_value = json.dumps(
        {
            "chapter_number": 1,
            "overall_verdict": "accepted",
            "criteria": {name: {"verdict": "pass", "justification": "ok"} for name in ("coverage", "logical_coherence", "technical_accuracy", "exercise_quality")},
            "issues": [],
        }
    )

    review = review_chapter(CURRICULUM, VIDEO_CHAPTER, None, VIDEO_CONTENT, 2, demo=False)

    assert review["overall_verdict"] == "accepted"
    prompt_used = mock_run_prompt.call_args.kwargs["prompt"]
    assert "chapitre VIDÉO" in prompt_used


# --- run_chapter_qc (graphe LangGraph), routage contrôlé par mocks ------------------------------

@patch("bloc3_5_quality_control.graph.revise_chapter_content")
@patch("bloc3_5_quality_control.graph.review_chapter")
def test_run_chapter_qc_accepts_immediately(mock_review, mock_revise):
    mock_review.return_value = ACCEPTED_REVIEW

    final_state = run_chapter_qc(CURRICULUM, CURRICULUM["chapters"][0], None, CONTENT_CH1, 2, max_attempts=3)

    assert final_state["status"] == "accepted"
    assert final_state["attempt"] == 0
    assert len(final_state["history"]) == 1
    mock_revise.assert_not_called()


@patch("bloc3_5_quality_control.graph.revise_chapter_content")
@patch("bloc3_5_quality_control.graph.review_chapter")
def test_run_chapter_qc_revises_once_then_accepts(mock_review, mock_revise):
    mock_review.side_effect = [NEEDS_REVISION_REVIEW, ACCEPTED_REVIEW]
    mock_revise.return_value = {**CONTENT_CH1, "lesson_script": "y" * 250}

    final_state = run_chapter_qc(CURRICULUM, CURRICULUM["chapters"][0], None, CONTENT_CH1, 2, max_attempts=3)

    assert final_state["status"] == "accepted"
    assert final_state["attempt"] == 1
    assert [h["stage"] for h in final_state["history"]] == ["review", "revise", "review"]
    mock_revise.assert_called_once()


@patch("bloc3_5_quality_control.graph.revise_chapter_content")
@patch("bloc3_5_quality_control.graph.review_chapter")
def test_run_chapter_qc_escalates_after_max_attempts(mock_review, mock_revise):
    mock_review.return_value = NEEDS_REVISION_REVIEW
    mock_revise.return_value = CONTENT_CH1

    final_state = run_chapter_qc(CURRICULUM, CURRICULUM["chapters"][0], None, CONTENT_CH1, 2, max_attempts=2)

    assert final_state["status"] == "escalated"
    assert final_state["attempt"] == 2
    assert mock_revise.call_count == 2
    assert mock_review.call_count == 3


# --- run_quality_control (orchestrateur multi-chapitres, mode démo) -----------------------------

def test_apply_manual_correction_demo_mode_accepts_and_does_a_single_pass():
    # En mode démo, review_chapter accepte dès attempt=0 (voir _demo_review), donc une correction
    # manuelle (toujours attempt=0) doit être acceptée en un seul revise + un seul review.
    manual_issues = [{"field": "practical_exercise", "description": "Rendre plus spécifique."}]

    result = apply_manual_correction(
        CURRICULUM, CURRICULUM["chapters"][0], None, 2, CONTENT_CH1, manual_issues, demo=True
    )

    assert result["final_status"] in ("accepted", "escalated")
    assert [h["stage"] for h in result["history"]] == ["manual_revise", "manual_review"]
    assert result["history"][0]["issues_addressed"] == manual_issues


@patch("bloc3_5_quality_control.quality_control.review_chapter")
@patch("bloc3_5_quality_control.quality_control.revise_chapter_content")
def test_apply_manual_correction_does_exactly_one_revise_and_one_review(mock_revise, mock_review):
    mock_revise.return_value = {**CONTENT_CH1, "lesson_script": "z" * 250}
    mock_review.return_value = ACCEPTED_REVIEW
    manual_issues = [{"field": "lesson_script", "description": "Corriger l'incohérence numérique."}]

    result = apply_manual_correction(
        CURRICULUM, CURRICULUM["chapters"][0], None, 2, CONTENT_CH1, manual_issues, demo=False
    )

    mock_revise.assert_called_once()
    mock_review.assert_called_once()
    assert result["final_status"] == "accepted"
    assert result["final_content"]["lesson_script"] == "z" * 250


@patch("bloc3_5_quality_control.quality_control.review_chapter")
@patch("bloc3_5_quality_control.quality_control.revise_chapter_content")
def test_apply_manual_correction_reports_escalated_without_looping_further(mock_revise, mock_review):
    mock_revise.return_value = CONTENT_CH1
    mock_review.return_value = NEEDS_REVISION_REVIEW
    manual_issues = [{"field": "lesson_script", "description": "Corriger l'incohérence numérique."}]

    result = apply_manual_correction(
        CURRICULUM, CURRICULUM["chapters"][0], None, 2, CONTENT_CH1, manual_issues, demo=False
    )

    assert result["final_status"] == "escalated"
    mock_revise.assert_called_once()
    mock_review.assert_called_once()


@patch("bloc3_5_quality_control.graph.revise_chapter_content")
@patch("bloc3_5_quality_control.graph.review_chapter")
def test_run_quality_control_forwards_bloc2_running_example_to_revise(mock_review, mock_revise):
    # Preuve de reproductibilité du pipeline sur un 2ème cours : le fil rouge utilisé pour une
    # réécriture doit être celui du cours EN COURS (bloc2_result["running_example"]), pas celui du
    # Sprint 1 codé en dur ailleurs.
    mock_review.side_effect = [NEEDS_REVISION_REVIEW, ACCEPTED_REVIEW, ACCEPTED_REVIEW]
    mock_revise.return_value = {**CONTENT_CH1, "lesson_script": "y" * 250}

    custom_bloc2_result = {**BLOC2_RESULT, "running_example": "Fil rouge du 2ème cours."}
    run_quality_control(CURRICULUM, custom_bloc2_result, max_attempts=3, demo=False)

    mock_revise.assert_called_once()
    assert mock_revise.call_args.kwargs["running_example"] == "Fil rouge du 2ème cours."


def test_run_quality_control_demo_mode_processes_all_chapters():
    result = run_quality_control(CURRICULUM, BLOC2_RESULT, max_attempts=3, demo=True)

    assert result["course_title"] == "Cours test"
    assert len(result["chapters"]) == 2
    assert result["summary"]["accepted"] == 2
    assert result["summary"]["escalated"] == 0
    for c in result["chapters"]:
        assert c["final_status"] == "accepted"
        assert c["attempts_used"] == 1  # stub démo : rejeté une fois puis accepté
        assert "final_content" in c
        assert "final_review" in c
