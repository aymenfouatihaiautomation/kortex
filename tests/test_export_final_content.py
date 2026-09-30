import pytest

from bloc3_5_quality_control.export_final_content import export_final_content

VALID_CONTENT_1 = {
    "chapter_number": 1,
    "chapter_title": "Intro",
    "lesson_script": "x" * 250,
    "comprehension_exercises": [
        {"question": "Q1?", "type": "mcq", "options": ["A", "B"], "correct_answer": "A", "explanation": "Car A."},
        {"question": "Q2?", "type": "short_answer", "options": None, "correct_answer": "R2"},
        {"question": "Q3?", "type": "mcq", "options": ["A", "B"], "correct_answer": "B", "explanation": "Car B."},
    ],
    "practical_exercise": {"title": "Ex", "instructions": "Fais ceci.", "expected_outcome": "Résultat."},
}

VALID_CONTENT_2_FINAL = {
    **VALID_CONTENT_1,
    "chapter_number": 2,
    "chapter_title": "Projet final",
    "practical_exercise": {
        **VALID_CONTENT_1["practical_exercise"],
        "deliverables": ["Livrable 1"],
        "step_by_step_instructions": ["Étape 1"],
        "evaluation_criteria": ["Critère 1"],
    },
}

REPORT = {
    "course_title": "Cours test",
    "niche": "AI Automation",
    "level": "intermédiaire",
    "chapters": [
        {"chapter_number": 1, "final_status": "accepted", "final_content": VALID_CONTENT_1},
        {"chapter_number": 2, "final_status": "accepted", "final_content": VALID_CONTENT_2_FINAL},
    ],
}


def test_export_final_content_assembles_sorted_chapters():
    result = export_final_content(REPORT)
    assert result["course_title"] == "Cours test"
    assert [c["chapter_number"] for c in result["chapters_content"]] == [1, 2]
    assert "running_example" in result


def test_export_final_content_refuses_if_a_chapter_not_accepted():
    bad_report = {**REPORT, "chapters": [
        {"chapter_number": 1, "final_status": "accepted", "final_content": VALID_CONTENT_1},
        {"chapter_number": 2, "final_status": "escalated", "final_content": VALID_CONTENT_2_FINAL},
    ]}
    with pytest.raises(ValueError, match="non 'accepted'"):
        export_final_content(bad_report)


def test_export_final_content_refuses_invalid_chapter_content():
    invalid_content = {**VALID_CONTENT_1, "lesson_script": "trop court"}
    bad_report = {**REPORT, "chapters": [
        {"chapter_number": 1, "final_status": "accepted", "final_content": invalid_content},
    ]}
    with pytest.raises(ValueError, match="invalide"):
        export_final_content(bad_report)
