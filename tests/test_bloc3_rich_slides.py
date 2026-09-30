import json
from unittest.mock import patch

import pytest

from bloc3_video_production.slides import (
    DIAGRAM_ICONS,
    build_rich_slides,
    split_sentences,
)
from common.llm_client import LLMCallError

LESSON_SCRIPT = (
    "Un agent IA en production doit gérer les erreurs. C'est la base de ce chapitre. "
    "Il existe trois familles de pannes principales. La première est réseau. "
    "La deuxième est le raisonnement. Enfin, la troisième est l'exécution d'outils."
)

DEFAULT_SLIDE = {
    "start_sentence": 1, "end_sentence": 2, "visual_title": "Intro",
    "key_terms": ["agent"], "key_numbers": [], "visual_type": "default",
}

DIAGRAM_SLIDE = {
    "start_sentence": 3, "end_sentence": 4, "visual_title": "Trois familles de pannes",
    "key_terms": ["réseau", "raisonnement"], "key_numbers": [], "visual_type": "diagram",
    "diagram_hub": {"label": "Agent", "icon": "Workflow"},
    "diagram_satellites": [
        {"label": "Réseau", "icon": "Cloud"},
        {"label": "Raisonnement", "icon": "Brain"},
        {"label": "Outils", "icon": "Wrench"},
    ],
}

TIMELINE_SLIDE = {
    "start_sentence": 5, "end_sentence": 6, "visual_title": "Escalade en production",
    "key_terms": ["exécution"], "key_numbers": ["82%", "×5"], "visual_type": "timeline",
    "timeline_steps": [
        {"label": "Test", "icon": "FlaskConical", "number": "82%"},
        {"label": "Dérive", "icon": "TrendingDown", "number": "×5"},
        {"label": "Panne", "icon": "AlertTriangle", "number": ""},
    ],
}


def test_build_rich_slides_demo_mode_marks_all_slides_default():
    slides = build_rich_slides("Titre chapitre", LESSON_SCRIPT, demo=True)
    assert all(s["visual_type"] == "default" for s in slides)
    assert " ".join(s["narration_text"] for s in slides) == LESSON_SCRIPT


@patch("bloc3_video_production.slides.run_prompt")
def test_build_rich_slides_real_mode_assembles_mixed_visual_types(mock_run_prompt):
    mock_run_prompt.return_value = json.dumps({"slides": [DEFAULT_SLIDE, DIAGRAM_SLIDE, TIMELINE_SLIDE]})

    slides = build_rich_slides("Titre chapitre", LESSON_SCRIPT, demo=False)

    assert [s["visual_type"] for s in slides] == ["default", "diagram", "timeline"]
    assert slides[1]["diagram_hub"] == {"label": "Agent", "icon": "Workflow"}
    assert len(slides[1]["diagram_satellites"]) == 3
    assert slides[2]["timeline_steps"][0]["number"] == "82%"
    # Le texte narré reste reconstruit par découpe Python, jamais par le LLM.
    all_sentences = split_sentences(LESSON_SCRIPT)
    assert slides[0]["narration_text"] == " ".join(all_sentences[0:2])


@patch("bloc3_video_production.slides.run_prompt")
def test_build_rich_slides_rejects_icon_outside_enum(mock_run_prompt):
    bad_slide = {**DIAGRAM_SLIDE, "diagram_hub": {"label": "Agent", "icon": "NotARealIcon"}}
    good_slide = {**DEFAULT_SLIDE, "start_sentence": 1, "end_sentence": 6, "visual_title": "Tout"}
    mock_run_prompt.side_effect = [
        json.dumps({"slides": [bad_slide]}),
        json.dumps({"slides": [good_slide]}),
    ]

    slides = build_rich_slides("Titre chapitre", LESSON_SCRIPT, demo=False)

    assert mock_run_prompt.call_count == 2
    assert slides[0]["visual_type"] == "default"


@patch("bloc3_video_production.slides.run_prompt")
def test_build_rich_slides_rejects_timeline_number_not_in_key_numbers(mock_run_prompt):
    # Régression : un chiffre affiché dans une étape de timeline doit être repris VERBATIM d'un
    # key_numbers de cette diapositive, jamais inventé par le LLM.
    bad_timeline = {**TIMELINE_SLIDE, "start_sentence": 1, "end_sentence": 6, "key_numbers": ["82%"]}
    bad_timeline["timeline_steps"] = [
        {"label": "Test", "icon": "FlaskConical", "number": "82%"},
        {"label": "Dérive", "icon": "TrendingDown", "number": "×12"},  # inventé, pas dans key_numbers
        {"label": "Panne", "icon": "AlertTriangle", "number": ""},
    ]
    good_slide = {**DEFAULT_SLIDE, "start_sentence": 1, "end_sentence": 6, "visual_title": "Tout"}
    mock_run_prompt.side_effect = [
        json.dumps({"slides": [bad_timeline]}),
        json.dumps({"slides": [good_slide]}),
    ]

    slides = build_rich_slides("Titre chapitre", LESSON_SCRIPT, demo=False)

    assert mock_run_prompt.call_count == 2
    assert slides[0]["visual_type"] == "default"


@patch("bloc3_video_production.slides.run_prompt")
def test_build_rich_slides_rejects_diagram_with_too_few_satellites(mock_run_prompt):
    bad_diagram = {**DIAGRAM_SLIDE, "start_sentence": 1, "end_sentence": 6}
    bad_diagram["diagram_satellites"] = [{"label": "Réseau", "icon": "Cloud"}]  # 1 seul, minimum 2
    good_slide = {**DEFAULT_SLIDE, "start_sentence": 1, "end_sentence": 6, "visual_title": "Tout"}
    mock_run_prompt.side_effect = [
        json.dumps({"slides": [bad_diagram]}),
        json.dumps({"slides": [good_slide]}),
    ]

    slides = build_rich_slides("Titre chapitre", LESSON_SCRIPT, demo=False)

    assert mock_run_prompt.call_count == 2


@patch("bloc3_video_production.slides.run_prompt")
def test_build_rich_slides_raises_after_exhausting_retries(mock_run_prompt):
    mock_run_prompt.return_value = "pas du JSON"

    with pytest.raises(LLMCallError):
        build_rich_slides("Titre chapitre", LESSON_SCRIPT, demo=False)

    assert mock_run_prompt.call_count == 2


def test_diagram_icons_enum_is_non_empty_and_unique():
    assert len(DIAGRAM_ICONS) == len(set(DIAGRAM_ICONS))
    assert len(DIAGRAM_ICONS) >= 10
