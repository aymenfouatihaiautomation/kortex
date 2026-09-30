import json
from unittest.mock import patch

import pytest

from bloc2_content_writing.backfill_exercise_explanations import (
    backfill_content,
    build_prompt,
    generate_explanations_for_chapter,
)
from common.llm_client import LLMCallError

CONTENT = {
    "course_title": "Cours test",
    "level": "intermédiaire",
    "chapters_content": [
        {
            "chapter_number": 1,
            "chapter_title": "Intro",
            "lesson_script": "x" * 250,
            "comprehension_exercises": [
                {"question": "Q1?", "type": "mcq", "options": ["A", "B"], "correct_answer": "A"},
                {"question": "Q2?", "type": "short_answer", "options": None, "correct_answer": "R2"},
                {"question": "Q3?", "type": "mcq", "options": ["A", "B"], "correct_answer": "B"},
            ],
            "practical_exercise": {"title": "Ex", "instructions": "Fais ceci.", "expected_outcome": "Résultat."},
        },
        {
            "chapter_number": 2,
            "chapter_title": "Déjà expliqué",
            "lesson_script": "y" * 250,
            "comprehension_exercises": [
                {
                    "question": "Q4?",
                    "type": "mcq",
                    "options": ["A", "B"],
                    "correct_answer": "A",
                    "explanation": "Déjà présent.",
                },
            ],
            "practical_exercise": {"title": "Ex2", "instructions": "Fais cela.", "expected_outcome": "Résultat2."},
        },
    ],
}


def test_build_prompt_marks_the_correct_option_and_lists_all_questions():
    mcq = CONTENT["chapters_content"][0]["comprehension_exercises"]
    mcq_only = [ex for ex in mcq if ex["type"] == "mcq"]
    prompt = build_prompt("Cours test", "intermédiaire", "Intro", 1, mcq_only)
    assert "Q1?" in prompt
    assert "Q3?" in prompt
    assert "(BONNE RÉPONSE)" in prompt
    assert "2 élément(s)" in prompt


def test_generate_explanations_for_chapter_returns_empty_list_when_no_mcq():
    assert generate_explanations_for_chapter("Cours", "niveau", 1, "Titre", [], demo=True) == []


def test_generate_explanations_for_chapter_demo_mode_no_network_call():
    mcq = [{"question": "Q1?", "options": ["A", "B"], "correct_answer": "A"}]
    explanations = generate_explanations_for_chapter("Cours", "niveau", 1, "Titre", mcq, demo=True)
    assert len(explanations) == 1
    assert explanations[0].startswith("[DEMO]")


@patch("bloc2_content_writing.backfill_exercise_explanations.call_llm_api")
def test_generate_explanations_for_chapter_real_mode_parses_llm_response(mock_run_prompt):
    mock_run_prompt.return_value = json.dumps({"explanations": ["Explication 1.", "Explication 2."]})
    mcq = [
        {"question": "Q1?", "options": ["A", "B"], "correct_answer": "A"},
        {"question": "Q3?", "options": ["A", "B"], "correct_answer": "B"},
    ]

    explanations = generate_explanations_for_chapter("Cours", "niveau", 1, "Intro", mcq, demo=False)

    assert explanations == ["Explication 1.", "Explication 2."]
    mock_run_prompt.assert_called_once()


@patch("bloc2_content_writing.backfill_exercise_explanations.call_llm_api")
def test_generate_explanations_for_chapter_raises_on_count_mismatch(mock_run_prompt):
    mock_run_prompt.return_value = json.dumps({"explanations": ["Une seule."]})
    mcq = [
        {"question": "Q1?", "options": ["A", "B"], "correct_answer": "A"},
        {"question": "Q3?", "options": ["A", "B"], "correct_answer": "B"},
    ]

    with pytest.raises(LLMCallError):
        generate_explanations_for_chapter("Cours", "niveau", 1, "Intro", mcq, demo=False)


def test_backfill_content_demo_mode_adds_explanation_only_to_missing_mcq():
    result = backfill_content(CONTENT, demo=True)

    ch1_exercises = result["chapters_content"][0]["comprehension_exercises"]
    assert ch1_exercises[0]["explanation"].startswith("[DEMO]")
    assert ch1_exercises[2]["explanation"].startswith("[DEMO]")
    assert "explanation" not in ch1_exercises[1]  # short_answer jamais touché

    ch2_exercises = result["chapters_content"][1]["comprehension_exercises"]
    assert ch2_exercises[0]["explanation"] == "Déjà présent."  # inchangé, pas régénéré


def test_backfill_content_never_mutates_the_original_dict():
    original = json.loads(json.dumps(CONTENT))
    backfill_content(CONTENT, demo=True)
    assert CONTENT == original


def test_backfill_content_never_touches_question_options_or_correct_answer():
    result = backfill_content(CONTENT, demo=True)
    ch1_before = CONTENT["chapters_content"][0]["comprehension_exercises"]
    ch1_after = result["chapters_content"][0]["comprehension_exercises"]
    for before, after in zip(ch1_before, ch1_after):
        assert before["question"] == after["question"]
        assert before["options"] == after["options"]
        assert before["correct_answer"] == after["correct_answer"]


@patch("bloc2_content_writing.backfill_exercise_explanations.call_llm_api")
def test_backfill_content_skips_llm_call_for_chapter_with_no_missing_explanation(mock_run_prompt):
    single_chapter_content = {
        "course_title": "Cours test",
        "level": "intermédiaire",
        "chapters_content": [CONTENT["chapters_content"][1]],  # déjà expliqué
    }
    backfill_content(single_chapter_content, demo=False)
    mock_run_prompt.assert_not_called()
