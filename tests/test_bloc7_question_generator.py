"""Tests unitaires du générateur de questions candidates (bloc7_exam_generation/question_generator.py)."""

import json
from unittest.mock import patch

import pytest

from bloc7_exam_generation.question_generator import _validate_candidates, generate_candidate_questions
from common.llm_client import LLMCallError

CHAPTER = {"number": 1, "title": "Chapitre de test", "learning_objectives": [], "key_points": [], "content_blocks": None, "lesson_script": "Contenu du chapitre.", "written_complement": None}

VALID_QUESTION = {
    "question": "Une question ?",
    "options": ["A", "B", "C", "D"],
    "correct_index": 2,
    "explanation": "Parce que le cours le dit.",
}


def _valid_payload(n=1):
    return json.dumps({"questions": [VALID_QUESTION] * n})


# --- _validate_candidates --------------------------------------------------------------------------


def test_validate_candidates_accepts_well_formed_list():
    assert _validate_candidates([VALID_QUESTION, VALID_QUESTION], expected_count=2) == []


def test_validate_candidates_rejects_wrong_count():
    errors = _validate_candidates([VALID_QUESTION], expected_count=2)
    assert errors


def test_validate_candidates_rejects_non_list():
    assert _validate_candidates({"not": "a list"}, expected_count=1) == ["'questions' doit être une liste."]


def test_validate_candidates_rejects_missing_fields():
    bad = {**VALID_QUESTION, "options": ["only", "two"]}
    errors = _validate_candidates([bad], expected_count=1)
    assert any("options" in e for e in errors)


def test_validate_candidates_rejects_out_of_range_correct_index():
    bad = {**VALID_QUESTION, "correct_index": 7}
    errors = _validate_candidates([bad], expected_count=1)
    assert any("correct_index" in e for e in errors)


def test_validate_candidates_rejects_empty_question_text():
    bad = {**VALID_QUESTION, "question": "   "}
    errors = _validate_candidates([bad], expected_count=1)
    assert any("question" in e for e in errors)


# --- demo mode --------------------------------------------------------------------------------------


def test_demo_mode_returns_n_deterministic_candidates_without_network_call():
    candidates = generate_candidate_questions(CHAPTER, "Cours de test", n=3, demo=True)
    assert len(candidates) == 3
    for c in candidates:
        assert set(c.keys()) == {"question", "options", "correct_index", "explanation"}
        assert len(c["options"]) == 4


def test_demo_mode_varies_question_text_by_existing_count():
    candidates = generate_candidate_questions(CHAPTER, "Cours de test", n=2, existing_questions=["q1", "q2"], demo=True)
    assert candidates[0]["question"] != candidates[1]["question"]


# --- appel réel (mocké) -----------------------------------------------------------------------------


@patch("bloc7_exam_generation.question_generator.call_llm_api")
def test_real_call_returns_parsed_candidates_on_valid_json(mock_call):
    mock_call.return_value = _valid_payload(n=2)

    candidates = generate_candidate_questions(CHAPTER, "Cours de test", n=2)

    assert candidates == [VALID_QUESTION, VALID_QUESTION]
    mock_call.assert_called_once()


@patch("bloc7_exam_generation.question_generator.call_llm_api")
def test_real_call_retries_once_on_malformed_json_then_succeeds(mock_call):
    mock_call.side_effect = ["not json at all", _valid_payload(n=1)]

    candidates = generate_candidate_questions(CHAPTER, "Cours de test", n=1)

    assert candidates == [VALID_QUESTION]
    assert mock_call.call_count == 2


@patch("bloc7_exam_generation.question_generator.call_llm_api")
def test_real_call_raises_after_exhausting_retries(mock_call):
    mock_call.return_value = "still not json"

    with pytest.raises(LLMCallError):
        generate_candidate_questions(CHAPTER, "Cours de test", n=1)

    assert mock_call.call_count == 2


@patch("bloc7_exam_generation.question_generator.call_llm_api")
def test_existing_questions_are_passed_into_the_prompt_to_avoid_duplicates(mock_call):
    mock_call.return_value = _valid_payload(n=1)

    generate_candidate_questions(CHAPTER, "Cours de test", n=1, existing_questions=["Question déjà posée ?"])

    prompt_sent = mock_call.call_args.kwargs["prompt"]
    assert "Question déjà posée ?" in prompt_sent
