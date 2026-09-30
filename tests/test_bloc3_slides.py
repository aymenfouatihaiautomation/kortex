import json
from unittest.mock import patch

import pytest

from bloc3_video_production.slides import (
    build_slides,
    split_sentences,
    validate_slide_plan,
)
from common.llm_client import LLMCallError

LESSON_SCRIPT = (
    "Un agent IA en production doit gérer les erreurs. C'est la base de ce chapitre. "
    "Il existe trois familles de pannes principales. La première est réseau. "
    "La deuxième est le raisonnement. Enfin, la troisième est l'exécution d'outils."
)


def test_split_sentences_is_reversible_modulo_whitespace():
    sentences = split_sentences(LESSON_SCRIPT)
    assert len(sentences) == 6
    assert " ".join(sentences) == LESSON_SCRIPT


def test_split_sentences_handles_empty_text():
    assert split_sentences("   ") == []


def test_validate_slide_plan_accepts_full_coverage():
    plan = [
        {"start_sentence": 1, "end_sentence": 3, "visual_title": "Intro", "key_terms": ["pannes"], "key_numbers": []},
        {"start_sentence": 4, "end_sentence": 6, "visual_title": "Familles", "key_terms": [], "key_numbers": []},
    ]
    assert validate_slide_plan(plan, num_sentences=6) == []


def test_validate_slide_plan_rejects_gap():
    plan = [
        {"start_sentence": 1, "end_sentence": 2, "visual_title": "A", "key_terms": [], "key_numbers": []},
        {"start_sentence": 4, "end_sentence": 6, "visual_title": "B", "key_terms": [], "key_numbers": []},
    ]
    errors = validate_slide_plan(plan, num_sentences=6)
    assert any("devrait commencer" in e for e in errors)


def test_validate_slide_plan_rejects_incomplete_coverage():
    plan = [{"start_sentence": 1, "end_sentence": 4, "visual_title": "A", "key_terms": [], "key_numbers": []}]
    errors = validate_slide_plan(plan, num_sentences=6)
    assert any("couvrent jusqu'à" in e for e in errors)


def test_validate_slide_plan_rejects_empty_title():
    plan = [{"start_sentence": 1, "end_sentence": 6, "visual_title": "  ", "key_terms": [], "key_numbers": []}]
    errors = validate_slide_plan(plan, num_sentences=6)
    assert any("visual_title vide" in e for e in errors)


def test_build_slides_demo_mode_covers_all_sentences_verbatim():
    slides = build_slides("Titre chapitre", LESSON_SCRIPT, demo=True)
    reconstructed = " ".join(s["narration_text"] for s in slides)
    assert reconstructed == LESSON_SCRIPT
    assert slides[0]["slide_number"] == 1


@patch("bloc3_video_production.slides.run_prompt")
def test_build_slides_real_mode_reconstructs_narration_from_plan(mock_run_prompt):
    mock_run_prompt.return_value = json.dumps(
        {
            "slides": [
                {"start_sentence": 1, "end_sentence": 2, "visual_title": "Intro", "key_terms": ["agent"], "key_numbers": []},
                {"start_sentence": 3, "end_sentence": 6, "visual_title": "Familles", "key_terms": ["pannes"], "key_numbers": []},
            ]
        }
    )

    slides = build_slides("Titre chapitre", LESSON_SCRIPT, demo=False)

    assert len(slides) == 2
    all_sentences = split_sentences(LESSON_SCRIPT)
    assert slides[0]["narration_text"] == " ".join(all_sentences[0:2])
    assert slides[1]["narration_text"] == " ".join(all_sentences[2:6])
    # Le LLM n'a jamais reçu pour instruction de reproduire le texte : on vérifie que la
    # reconstruction ne dépend que des bornes, pas d'un texte halluciné par le modèle.
    assert " ".join(s["narration_text"] for s in slides) == LESSON_SCRIPT


@patch("bloc3_video_production.slides.run_prompt")
def test_build_slides_retries_once_on_invalid_plan(mock_run_prompt):
    bad_plan = json.dumps({"slides": [{"start_sentence": 1, "end_sentence": 3, "visual_title": "", "key_terms": [], "key_numbers": []}]})
    good_plan = json.dumps(
        {"slides": [{"start_sentence": 1, "end_sentence": 6, "visual_title": "Tout", "key_terms": [], "key_numbers": []}]}
    )
    mock_run_prompt.side_effect = [bad_plan, good_plan]

    slides = build_slides("Titre chapitre", LESSON_SCRIPT, demo=False)

    assert mock_run_prompt.call_count == 2
    assert slides[0]["narration_text"] == LESSON_SCRIPT


@patch("bloc3_video_production.slides.run_prompt")
def test_build_slides_raises_after_exhausting_retries(mock_run_prompt):
    mock_run_prompt.return_value = "pas du JSON"

    with pytest.raises(LLMCallError):
        build_slides("Titre chapitre", LESSON_SCRIPT, demo=False)

    assert mock_run_prompt.call_count == 2
