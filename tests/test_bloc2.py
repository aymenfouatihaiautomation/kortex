import json
from unittest.mock import patch

import pytest

from bloc2_content_writing.write_content import (
    generate_chapter_content,
    load_curriculum,
    revise_chapter_content,
    validate_chapter_content,
    write_content,
)
from common.llm_client import LLMCallError

CURRICULUM = {
    "title": "Cours test",
    "niche": "AI Automation",
    "level": "intermédiaire",
    "chapters": [
        {
            "number": 1,
            "title": "Intro",
            "learning_objectives": ["obj1", "obj2"],
            "key_points": ["kp1", "kp2", "kp3"],
            "builds_on_previous": "N/A - premier chapitre",
        },
        {
            "number": 2,
            "title": "Projet final",
            "learning_objectives": ["obj1"],
            "key_points": ["kp1"],
            "builds_on_previous": "S'appuie sur le chapitre 1.",
        },
    ],
}

VALID_REGULAR_CONTENT = {
    "chapter_number": 1,
    "chapter_title": "Intro",
    "lesson_script": "x" * 250,
    "comprehension_exercises": [
        {"question": "Q1?", "type": "mcq", "options": ["A", "B"], "correct_answer": "A", "explanation": "Car A."},
        {"question": "Q2?", "type": "short_answer", "options": None, "correct_answer": "R2"},
        {"question": "Q3?", "type": "mcq", "options": ["A", "B"], "correct_answer": "B", "explanation": "Car B."},
    ],
    "practical_exercise": {
        "title": "Exercice",
        "instructions": "Fais ceci.",
        "expected_outcome": "Résultat attendu.",
    },
}

VALID_FINAL_CONTENT = {
    "chapter_number": 2,
    "chapter_title": "Projet final",
    "lesson_script": "y" * 250,
    "comprehension_exercises": VALID_REGULAR_CONTENT["comprehension_exercises"],
    "practical_exercise": {
        "title": "Projet final",
        "instructions": "Assemble tout.",
        "expected_outcome": "Système complet livré.",
        "deliverables": ["Livrable 1"],
        "step_by_step_instructions": ["Étape 1", "Étape 2"],
        "evaluation_criteria": ["Critère 1"],
    },
}


def test_load_curriculum_reads_json(tmp_path):
    path = tmp_path / "curriculum.json"
    path.write_text(json.dumps(CURRICULUM), encoding="utf-8")
    loaded = load_curriculum(path)
    assert loaded["title"] == "Cours test"
    assert len(loaded["chapters"]) == 2


def test_validate_chapter_content_accepts_valid_regular_chapter():
    assert validate_chapter_content(VALID_REGULAR_CONTENT, is_final_chapter=False) == []


def test_validate_chapter_content_accepts_valid_final_chapter():
    assert validate_chapter_content(VALID_FINAL_CONTENT, is_final_chapter=True) == []


def test_validate_chapter_content_rejects_short_lesson_script():
    bad = json.loads(json.dumps(VALID_REGULAR_CONTENT))
    bad["lesson_script"] = "trop court"
    errors = validate_chapter_content(bad, is_final_chapter=False)
    assert any("lesson_script" in e for e in errors)


def test_validate_chapter_content_rejects_too_few_exercises():
    bad = json.loads(json.dumps(VALID_REGULAR_CONTENT))
    bad["comprehension_exercises"] = bad["comprehension_exercises"][:1]
    errors = validate_chapter_content(bad, is_final_chapter=False)
    assert any("comprehension_exercises" in e for e in errors)


def test_validate_chapter_content_rejects_mcq_without_options():
    bad = json.loads(json.dumps(VALID_REGULAR_CONTENT))
    bad["comprehension_exercises"][0]["options"] = None
    errors = validate_chapter_content(bad, is_final_chapter=False)
    assert any("QCM" in e for e in errors)


def test_validate_chapter_content_rejects_mcq_without_explanation():
    bad = json.loads(json.dumps(VALID_REGULAR_CONTENT))
    bad["comprehension_exercises"][0]["explanation"] = ""
    errors = validate_chapter_content(bad, is_final_chapter=False)
    assert any("explanation" in e for e in errors)


def test_validate_chapter_content_rejects_final_chapter_missing_deliverables():
    bad = json.loads(json.dumps(VALID_FINAL_CONTENT))
    del bad["practical_exercise"]["deliverables"]
    errors = validate_chapter_content(bad, is_final_chapter=True)
    assert any("deliverables" in e for e in errors)


def test_write_content_demo_mode_covers_all_chapters_and_marks_final_chapter():
    result = write_content(CURRICULUM, demo=True)

    assert result["course_title"] == "Cours test"
    assert len(result["chapters_content"]) == 2
    assert result["chapters_content"][0]["chapter_number"] == 1
    assert "deliverables" not in result["chapters_content"][0]["practical_exercise"]
    assert "deliverables" in result["chapters_content"][1]["practical_exercise"]


@patch("bloc2_content_writing.write_content.call_llm_api")
def test_generate_chapter_content_real_mode_succeeds_first_try(mock_run_prompt):
    mock_run_prompt.return_value = json.dumps(VALID_REGULAR_CONTENT)

    content = generate_chapter_content(CURRICULUM, CURRICULUM["chapters"][0], total_chapters=2)

    assert content["chapter_number"] == 1
    assert mock_run_prompt.call_count == 1


@patch("bloc2_content_writing.write_content.call_llm_api")
def test_generate_chapter_content_retries_once_then_succeeds(mock_run_prompt):
    invalid = json.loads(json.dumps(VALID_REGULAR_CONTENT))
    invalid["lesson_script"] = "trop court"
    mock_run_prompt.side_effect = [json.dumps(invalid), json.dumps(VALID_REGULAR_CONTENT)]

    content = generate_chapter_content(CURRICULUM, CURRICULUM["chapters"][0], total_chapters=2)

    assert content["chapter_number"] == 1
    assert mock_run_prompt.call_count == 2
    second_call_prompt = mock_run_prompt.call_args_list[1].kwargs["prompt"]
    assert "invalide" in second_call_prompt


@patch("bloc2_content_writing.write_content.call_llm_api")
def test_generate_chapter_content_raises_after_exhausting_retries(mock_run_prompt):
    invalid = json.loads(json.dumps(VALID_REGULAR_CONTENT))
    invalid["lesson_script"] = "trop court"
    mock_run_prompt.return_value = json.dumps(invalid)

    with pytest.raises(LLMCallError):
        generate_chapter_content(CURRICULUM, CURRICULUM["chapters"][0], total_chapters=2)

    assert mock_run_prompt.call_count == 2


@patch("bloc2_content_writing.write_content.call_llm_api")
def test_generate_chapter_content_final_chapter_requires_extra_fields(mock_run_prompt):
    mock_run_prompt.return_value = json.dumps(VALID_FINAL_CONTENT)

    content = generate_chapter_content(CURRICULUM, CURRICULUM["chapters"][1], total_chapters=2)

    assert content["practical_exercise"]["deliverables"] == ["Livrable 1"]


@patch("bloc2_content_writing.write_content.call_llm_api")
def test_write_content_real_mode_calls_llm_once_per_chapter(mock_run_prompt):
    mock_run_prompt.side_effect = [
        json.dumps(VALID_REGULAR_CONTENT),
        json.dumps(VALID_FINAL_CONTENT),
    ]

    result = write_content(CURRICULUM, demo=False)

    assert mock_run_prompt.call_count == 2
    assert [c["chapter_number"] for c in result["chapters_content"]] == [1, 2]


@patch("bloc2_content_writing.write_content.call_llm_api")
def test_write_content_uses_custom_running_example_when_provided(mock_run_prompt):
    # Reproductibilité du pipeline sur un 2ème cours : le fil rouge doit être injectable sans
    # affecter le comportement par défaut (celui du Sprint 1) des autres appels.
    mock_run_prompt.side_effect = [
        json.dumps(VALID_REGULAR_CONTENT),
        json.dumps(VALID_FINAL_CONTENT),
    ]
    custom_example = "Un freelance qui lance une agence d'automatisation IA."

    result = write_content(CURRICULUM, demo=False, running_example=custom_example)

    assert result["running_example"] == custom_example
    first_call_prompt = mock_run_prompt.call_args_list[0].kwargs["prompt"]
    assert custom_example in first_call_prompt
    assert "ticket de support client" not in first_call_prompt


def test_write_content_demo_mode_uses_custom_running_example():
    custom_example = "Fil rouge alternatif pour un 2ème cours."
    result = write_content(CURRICULUM, demo=True, running_example=custom_example)
    assert result["running_example"] == custom_example


ISSUES = [{"field": "practical_exercise", "description": "Rendre l'exercice plus spécifique."}]


def test_revise_chapter_content_demo_mode_marks_fixed_fields():
    revised = revise_chapter_content(
        CURRICULUM, CURRICULUM["chapters"][0], total_chapters=2,
        current_content=VALID_REGULAR_CONTENT, issues=ISSUES, demo=True,
    )
    assert validate_chapter_content(revised, is_final_chapter=False) == []
    assert "practical_exercise" in revised["lesson_script"]


@patch("bloc2_content_writing.write_content.call_llm_api")
def test_revise_chapter_content_uses_custom_running_example(mock_run_prompt):
    mock_run_prompt.return_value = json.dumps(VALID_REGULAR_CONTENT)
    custom_example = "Un freelance qui lance une agence d'automatisation IA."

    revise_chapter_content(
        CURRICULUM, CURRICULUM["chapters"][0], total_chapters=2,
        current_content=VALID_REGULAR_CONTENT, issues=ISSUES, demo=False,
        running_example=custom_example,
    )

    prompt_used = mock_run_prompt.call_args.kwargs["prompt"]
    assert custom_example in prompt_used


@patch("bloc2_content_writing.write_content.call_llm_api")
def test_revise_chapter_content_real_mode_succeeds_first_try(mock_run_prompt):
    mock_run_prompt.return_value = json.dumps(VALID_REGULAR_CONTENT)

    revised = revise_chapter_content(
        CURRICULUM, CURRICULUM["chapters"][0], total_chapters=2,
        current_content=VALID_REGULAR_CONTENT, issues=ISSUES, demo=False,
    )

    assert revised["chapter_number"] == 1
    assert mock_run_prompt.call_count == 1
    prompt_used = mock_run_prompt.call_args.kwargs["prompt"]
    assert "Rendre l'exercice plus spécifique." in prompt_used


@patch("bloc2_content_writing.write_content.call_llm_api")
def test_revise_chapter_content_raises_after_exhausting_retries(mock_run_prompt):
    invalid = json.loads(json.dumps(VALID_REGULAR_CONTENT))
    invalid["lesson_script"] = "trop court"
    mock_run_prompt.return_value = json.dumps(invalid)

    with pytest.raises(LLMCallError):
        revise_chapter_content(
            CURRICULUM, CURRICULUM["chapters"][0], total_chapters=2,
            current_content=VALID_REGULAR_CONTENT, issues=ISSUES, demo=False,
        )

    assert mock_run_prompt.call_count == 2


# --- format par chapitre (2026-08-07) : text/video/mix -----------------------------------------

VIDEO_CHAPTER = {
    "number": 1,
    "title": "Démo n8n",
    "learning_objectives": ["obj1", "obj2"],
    "key_points": ["kp1", "kp2", "kp3"],
    "builds_on_previous": "N/A - premier chapitre",
    "format": "video",
    "format_reasoning": "Démonstration d'un flux d'actions à l'écran.",
}

MIX_CHAPTER = {
    "number": 1,
    "title": "Connecter une IA",
    "learning_objectives": ["obj1", "obj2"],
    "key_points": ["kp1", "kp2", "kp3"],
    "builds_on_previous": "N/A - premier chapitre",
    "format": "mix",
    "format_reasoning": "Démo visuelle + référence de code complémentaire.",
}

VALID_VIDEO_CONTENT = {
    "chapter_number": 1,
    "chapter_title": "Démo n8n",
    "video_script": {
        "summary": "La vidéo montre la création d'un workflow n8n de bout en bout.",
        "scenes": [
            {"beat": "Ouverture", "narration": "On ouvre n8n.", "visual": "Capture de l'interface."},
            {"beat": "Ajout d'un node", "narration": "On ajoute un node HTTP.", "visual": "Glisser-déposer."},
            {"beat": "Test", "narration": "On exécute le workflow.", "visual": "Résultat affiché."},
        ],
    },
    "written_complement": "Point de vigilance non montré à l'écran : bien nommer ses credentials.",
    "comprehension_exercises": VALID_REGULAR_CONTENT["comprehension_exercises"],
    "practical_exercise": VALID_REGULAR_CONTENT["practical_exercise"],
}

VALID_MIX_CONTENT = {
    "chapter_number": 1,
    "chapter_title": "Connecter une IA",
    "video_script": VALID_VIDEO_CONTENT["video_script"],
    "lesson_script": "z" * 250,
    "redundancy_check_notes": "La vidéo montre la démo, le texte donne la référence de code — pas de recouvrement.",
    "comprehension_exercises": VALID_REGULAR_CONTENT["comprehension_exercises"],
    "practical_exercise": VALID_REGULAR_CONTENT["practical_exercise"],
}


def test_validate_chapter_content_accepts_valid_video_chapter():
    assert validate_chapter_content(VALID_VIDEO_CONTENT, is_final_chapter=False, format="video") == []


def test_validate_chapter_content_rejects_video_chapter_with_too_few_scenes():
    bad = json.loads(json.dumps(VALID_VIDEO_CONTENT))
    bad["video_script"]["scenes"] = bad["video_script"]["scenes"][:1]
    errors = validate_chapter_content(bad, is_final_chapter=False, format="video")
    assert any("scènes" in e for e in errors)


def test_validate_chapter_content_rejects_video_chapter_missing_written_complement():
    bad = json.loads(json.dumps(VALID_VIDEO_CONTENT))
    bad["written_complement"] = ""
    errors = validate_chapter_content(bad, is_final_chapter=False, format="video")
    assert any("written_complement" in e for e in errors)


def test_validate_chapter_content_rejects_video_chapter_with_written_complement_too_long():
    """Garde-fou anti-doublon : un chapitre vidéo ne doit pas récupérer une leçon-texte complète
    sous couvert de 'complément'."""
    bad = json.loads(json.dumps(VALID_VIDEO_CONTENT))
    bad["written_complement"] = "x" * 1500
    errors = validate_chapter_content(bad, is_final_chapter=False, format="video")
    assert any("trop long" in e for e in errors)


def test_validate_chapter_content_video_chapter_still_requires_exercises():
    """Constante non négociable : les exercices sont toujours présents, quel que soit le format."""
    bad = json.loads(json.dumps(VALID_VIDEO_CONTENT))
    bad["comprehension_exercises"] = []
    errors = validate_chapter_content(bad, is_final_chapter=False, format="video")
    assert any("comprehension_exercises" in e for e in errors)


def test_validate_chapter_content_accepts_valid_mix_chapter():
    assert validate_chapter_content(VALID_MIX_CONTENT, is_final_chapter=False, format="mix") == []


def test_validate_chapter_content_rejects_mix_chapter_missing_redundancy_notes():
    bad = json.loads(json.dumps(VALID_MIX_CONTENT))
    bad["redundancy_check_notes"] = "   "
    errors = validate_chapter_content(bad, is_final_chapter=False, format="mix")
    assert any("redundancy_check_notes" in e for e in errors)


def test_validate_chapter_content_rejects_mix_chapter_missing_video_script():
    bad = json.loads(json.dumps(VALID_MIX_CONTENT))
    del bad["video_script"]
    errors = validate_chapter_content(bad, is_final_chapter=False, format="mix")
    assert any("video_script" in e for e in errors)


def test_generate_chapter_content_demo_mode_video_format_has_no_full_lesson_script():
    content = generate_chapter_content(
        {"title": "Cours", "niche": "n"}, VIDEO_CHAPTER, total_chapters=1, demo=True
    )
    assert content["format"] == "video"
    assert "video_script" in content
    assert "lesson_script" not in content
    assert len(content["written_complement"]) < 1200


def test_generate_chapter_content_demo_mode_mix_format_has_video_and_complementary_text():
    content = generate_chapter_content(
        {"title": "Cours", "niche": "n"}, MIX_CHAPTER, total_chapters=1, demo=True
    )
    assert content["format"] == "mix"
    assert "video_script" in content
    assert "lesson_script" in content
    assert content["redundancy_check_notes"]


@patch("bloc2_content_writing.write_content.call_llm_api")
def test_generate_chapter_content_video_format_uses_video_prompt_and_stamps_format(mock_run_prompt):
    mock_run_prompt.return_value = json.dumps(VALID_VIDEO_CONTENT)

    content = generate_chapter_content({"title": "Cours", "niche": "n"}, VIDEO_CHAPTER, total_chapters=2)

    assert content["format"] == "video"
    prompt_used = mock_run_prompt.call_args.kwargs["prompt"]
    assert "chapitre VIDÉO" in prompt_used
    assert VIDEO_CHAPTER["format_reasoning"] in prompt_used


@patch("bloc2_content_writing.write_content.call_llm_api")
def test_generate_chapter_content_mix_format_uses_mix_prompt(mock_run_prompt):
    mock_run_prompt.return_value = json.dumps(VALID_MIX_CONTENT)

    content = generate_chapter_content({"title": "Cours", "niche": "n"}, MIX_CHAPTER, total_chapters=2)

    assert content["format"] == "mix"
    prompt_used = mock_run_prompt.call_args.kwargs["prompt"]
    assert "chapitre MIXTE" in prompt_used
    assert "redundancy_check_notes" in prompt_used


@patch("bloc2_content_writing.write_content.call_llm_api")
def test_revise_chapter_content_video_format_includes_current_video_script(mock_run_prompt):
    mock_run_prompt.return_value = json.dumps(VALID_VIDEO_CONTENT)

    revise_chapter_content(
        {"title": "Cours", "niche": "n"}, VIDEO_CHAPTER, total_chapters=2,
        current_content=VALID_VIDEO_CONTENT, issues=ISSUES, demo=False,
    )

    prompt_used = mock_run_prompt.call_args.kwargs["prompt"]
    assert "Ouverture" in prompt_used  # beat de la 1ère scène du video_script actuel


def test_chapter_without_format_field_defaults_to_text_behavior():
    """Rétrocompatibilité cours 1 : un chapitre sans champ 'format' (curriculum généré avant cette
    fonctionnalité) doit produire EXACTEMENT le comportement 'text' historique."""
    chapter_no_format = {
        "number": 1,
        "title": "Intro",
        "learning_objectives": ["obj1"],
        "key_points": ["kp1"],
        "builds_on_previous": "N/A - premier chapitre",
    }
    content = generate_chapter_content({"title": "Cours", "niche": "n"}, chapter_no_format, total_chapters=1, demo=True)
    assert content["format"] == "text"
    assert "lesson_script" in content
    assert "video_script" not in content
