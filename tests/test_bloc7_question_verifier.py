"""Tests unitaires de l'agent vérificateur adversarial (bloc7_exam_generation/question_verifier.py).

Le point critique du pipeline : ces tests vérifient explicitement que le vérificateur REJETTE en
cas de désaccord avec le générateur, sur chacun des 4 autres critères, et sur toute réponse
malformée (fail-closed — jamais une acceptation par défaut)."""

import json
from unittest.mock import patch

import pytest

from bloc7_exam_generation.question_verifier import _validate_verdict_shape, verify_question

CHAPTER = {"number": 1, "title": "Chapitre de test", "learning_objectives": [], "key_points": [], "content_blocks": None, "lesson_script": "Contenu du chapitre.", "written_complement": None}

CANDIDATE = {
    "question": "Une question ?",
    "options": ["A", "B", "C", "D"],
    "correct_index": 2,
    "explanation": "Parce que le cours le dit.",
}

FULLY_VALID_VERDICT = {
    "resolved_index": 2,
    "answerable_from_course": True,
    "single_defensible_answer": True,
    "distractors_clearly_wrong": True,
    "unambiguous_wording": True,
    "reasoning": "Tout est clair.",
}


def _verdict_json(**overrides):
    return json.dumps({**FULLY_VALID_VERDICT, **overrides})


# --- _validate_verdict_shape -------------------------------------------------------------------


def test_validate_verdict_shape_accepts_well_formed_verdict():
    assert _validate_verdict_shape(FULLY_VALID_VERDICT) == []


def test_validate_verdict_shape_rejects_non_dict():
    assert _validate_verdict_shape("not a dict") == ["la réponse n'est pas un objet JSON."]


def test_validate_verdict_shape_rejects_bad_resolved_index():
    errors = _validate_verdict_shape({**FULLY_VALID_VERDICT, "resolved_index": 9})
    assert any("resolved_index" in e for e in errors)


def test_validate_verdict_shape_rejects_non_boolean_field():
    errors = _validate_verdict_shape({**FULLY_VALID_VERDICT, "answerable_from_course": "yes"})
    assert any("answerable_from_course" in e for e in errors)


# --- demo mode -----------------------------------------------------------------------------------


def test_demo_mode_accepts_by_default():
    verdict = verify_question(CHAPTER, "Cours de test", CANDIDATE, demo=True)
    assert verdict["accepted"] is True
    assert verdict["reasons"] == []


def test_demo_mode_can_force_a_rejection():
    verdict = verify_question(CHAPTER, "Cours de test", CANDIDATE, demo=True, demo_reject=True)
    assert verdict["accepted"] is False
    assert "verifier_disagrees_with_generator" in verdict["reasons"]


# --- appel réel (mocké) : le point critique --------------------------------------------------------


@patch("bloc7_exam_generation.question_verifier.call_llm_api")
def test_accepts_when_verifier_agrees_and_all_criteria_pass(mock_call):
    mock_call.return_value = _verdict_json()

    verdict = verify_question(CHAPTER, "Cours de test", CANDIDATE)

    assert verdict["accepted"] is True
    assert verdict["reasons"] == []
    assert verdict["resolved_index"] == 2


@patch("bloc7_exam_generation.question_verifier.call_llm_api")
def test_rejects_on_disagreement_between_generator_and_verifier(mock_call):
    # Le générateur propose l'index 2 (CANDIDATE["correct_index"]), le vérificateur résout 0.
    mock_call.return_value = _verdict_json(resolved_index=0)

    verdict = verify_question(CHAPTER, "Cours de test", CANDIDATE)

    assert verdict["accepted"] is False
    assert "verifier_disagrees_with_generator" in verdict["reasons"]


@patch("bloc7_exam_generation.question_verifier.call_llm_api")
def test_rejects_when_not_answerable_from_course_alone(mock_call):
    mock_call.return_value = _verdict_json(answerable_from_course=False)

    verdict = verify_question(CHAPTER, "Cours de test", CANDIDATE)

    assert verdict["accepted"] is False
    assert "not_answerable_from_course_alone" in verdict["reasons"]


@patch("bloc7_exam_generation.question_verifier.call_llm_api")
def test_rejects_when_multiple_defensible_answers(mock_call):
    mock_call.return_value = _verdict_json(single_defensible_answer=False)

    verdict = verify_question(CHAPTER, "Cours de test", CANDIDATE)

    assert verdict["accepted"] is False
    assert "multiple_defensible_answers" in verdict["reasons"]


@patch("bloc7_exam_generation.question_verifier.call_llm_api")
def test_rejects_when_a_distractor_is_not_clearly_wrong(mock_call):
    mock_call.return_value = _verdict_json(distractors_clearly_wrong=False)

    verdict = verify_question(CHAPTER, "Cours de test", CANDIDATE)

    assert verdict["accepted"] is False
    assert "distractor_not_clearly_wrong" in verdict["reasons"]


@patch("bloc7_exam_generation.question_verifier.call_llm_api")
def test_rejects_when_wording_is_ambiguous(mock_call):
    mock_call.return_value = _verdict_json(unambiguous_wording=False)

    verdict = verify_question(CHAPTER, "Cours de test", CANDIDATE)

    assert verdict["accepted"] is False
    assert "ambiguous_wording" in verdict["reasons"]


@patch("bloc7_exam_generation.question_verifier.call_llm_api")
def test_multiple_failed_criteria_are_all_reported(mock_call):
    mock_call.return_value = _verdict_json(resolved_index=0, unambiguous_wording=False)

    verdict = verify_question(CHAPTER, "Cours de test", CANDIDATE)

    assert verdict["accepted"] is False
    assert "verifier_disagrees_with_generator" in verdict["reasons"]
    assert "ambiguous_wording" in verdict["reasons"]


@patch("bloc7_exam_generation.question_verifier.call_llm_api")
def test_malformed_response_is_rejected_fail_closed_not_raised(mock_call):
    # Reste malformé même après le retry -> REJET, jamais une exception qui interromprait tout le run.
    mock_call.return_value = "not json at all"

    verdict = verify_question(CHAPTER, "Cours de test", CANDIDATE)

    assert verdict["accepted"] is False
    assert verdict["reasons"] == ["verifier_response_malformed"]
    assert mock_call.call_count == 2


@patch("bloc7_exam_generation.question_verifier.call_llm_api")
def test_recovers_after_one_malformed_attempt_via_retry(mock_call):
    mock_call.side_effect = ["not json", _verdict_json()]

    verdict = verify_question(CHAPTER, "Cours de test", CANDIDATE)

    assert verdict["accepted"] is True
    assert mock_call.call_count == 2


@patch("bloc7_exam_generation.question_verifier.call_llm_api")
def test_verifier_never_receives_the_generators_correct_index_or_explanation(mock_call):
    mock_call.return_value = _verdict_json()

    verify_question(CHAPTER, "Cours de test", CANDIDATE)

    prompt_sent = mock_call.call_args.kwargs["prompt"]
    assert "Parce que le cours le dit." not in prompt_sent
    # L'index correct n'apparaît nulle part sous une forme qui le révélerait (ex. "correct_index: 2").
    assert "correct_index" not in prompt_sent
