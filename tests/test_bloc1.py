import json
from unittest.mock import patch

import pytest

from bloc1_curriculum_planning.plan_curriculum import (
    DEMO_LEVEL,
    DEMO_PREREQUISITES,
    decide_chapter_format,
    plan_curriculum,
    regenerate_level_and_prerequisites,
    validate_curriculum,
)
from common.llm_client import LLMCallError

VALID_CURRICULUM = {
    "title": "Cours test",
    "niche": "AI Automation",
    "level": "intermédiaire",
    "prerequisites": "Savoir déjà utiliser un tableur et avoir un compte email professionnel.",
    "source_topic": {"title": "Sujet test", "gap_reason": "raison"},
    "chapters": [
        {
            "number": 1,
            "title": "Intro",
            "learning_objectives": ["obj1", "obj2"],
            "key_points": ["kp1", "kp2", "kp3"],
            "builds_on_previous": "N/A - premier chapitre",
            "format": "text",
            "format_reasoning": "Contenu de référence, mieux servi par du texte.",
        },
        {
            "number": 2,
            "title": "Suite",
            "learning_objectives": ["obj1"],
            "key_points": ["kp1"],
            "builds_on_previous": "S'appuie sur le chapitre 1.",
            "format": "video",
            "format_reasoning": "Démonstration d'un flux d'actions à l'écran.",
        },
    ],
}


def test_validate_curriculum_accepts_valid_structure():
    assert validate_curriculum(VALID_CURRICULUM) == []


def test_validate_curriculum_rejects_gap_in_numbering():
    bad = json.loads(json.dumps(VALID_CURRICULUM))
    bad["chapters"][1]["number"] = 3
    errors = validate_curriculum(bad)
    assert any("Numérotation" in e for e in errors)


def test_validate_curriculum_rejects_empty_objectives():
    bad = json.loads(json.dumps(VALID_CURRICULUM))
    bad["chapters"][0]["learning_objectives"] = []
    errors = validate_curriculum(bad)
    assert any("learning_objectives vide" in e for e in errors)


def test_validate_curriculum_rejects_missing_builds_on_previous():
    bad = json.loads(json.dumps(VALID_CURRICULUM))
    bad["chapters"][1]["builds_on_previous"] = ""
    errors = validate_curriculum(bad)
    assert any("builds_on_previous vide" in e for e in errors)


# --- Régression : level/prerequisites doivent être dérivés du sujet, pas d'une constante partagée
# (bug réel trouvé sur le 2ème cours — "agence d'automatisation IA" héritait des prérequis du 1er
# cours, "savoir construire un agent LLM basique", ce qui était faux et trompeur). ------------------

def test_validate_curriculum_rejects_level_outside_closed_enum():
    bad = json.loads(json.dumps(VALID_CURRICULUM))
    bad["level"] = "expert"  # hors de l'enum fermé {débutant, intermédiaire, avancé}
    errors = validate_curriculum(bad)
    assert any("level invalide" in e for e in errors)


def test_validate_curriculum_rejects_missing_prerequisites():
    bad = json.loads(json.dumps(VALID_CURRICULUM))
    bad["prerequisites"] = ""
    errors = validate_curriculum(bad)
    assert any("prerequisites" in e for e in errors)


# --- format par chapitre (2026-08-07) : un chapitre sans format valide/justifié est invalide, mais
# le champ reste absent sur les curriculums déjà en production (cours 1) — voir test_bloc4 pour la
# rétrocompatibilité de l'AFFICHAGE d'un chapitre sans champ "format". ------------------------------

def test_validate_curriculum_rejects_format_outside_closed_enum():
    bad = json.loads(json.dumps(VALID_CURRICULUM))
    bad["chapters"][0]["format"] = "audio"
    errors = validate_curriculum(bad)
    assert any("format invalide" in e for e in errors)


def test_validate_curriculum_rejects_missing_format():
    bad = json.loads(json.dumps(VALID_CURRICULUM))
    del bad["chapters"][0]["format"]
    errors = validate_curriculum(bad)
    assert any("format invalide" in e for e in errors)


def test_validate_curriculum_rejects_empty_format_reasoning():
    bad = json.loads(json.dumps(VALID_CURRICULUM))
    bad["chapters"][0]["format_reasoning"] = "   "
    errors = validate_curriculum(bad)
    assert any("format_reasoning manquant ou vide" in e for e in errors)


def test_validate_curriculum_accepts_all_three_formats():
    for fmt in ("text", "video", "mix"):
        ok = json.loads(json.dumps(VALID_CURRICULUM))
        ok["chapters"][0]["format"] = fmt
        assert validate_curriculum(ok) == []


def test_plan_curriculum_demo_mode_uses_all_three_formats():
    """Le stub démo doit lui-même démontrer les 3 formats (pas juste 'text' partout) — sinon le
    câblage format-dépendant des blocs suivants ne serait jamais exercé en mode démo."""
    curriculum = plan_curriculum({"title": "Sujet démo", "gap_reason": ""}, demo=True)
    formats = {c["format"] for c in curriculum["chapters"]}
    assert formats == {"text", "video", "mix"}
    for c in curriculum["chapters"]:
        assert (c.get("format_reasoning") or "").strip()


def test_plan_curriculum_demo_mode_is_valid():
    curriculum = plan_curriculum({"title": "Sujet démo", "gap_reason": ""}, demo=True)
    assert validate_curriculum(curriculum) == []
    assert curriculum["chapters"][-1]["number"] == len(curriculum["chapters"])


def test_plan_curriculum_demo_mode_has_level_and_prerequisites():
    curriculum = plan_curriculum({"title": "Sujet démo", "gap_reason": ""}, demo=True)
    assert curriculum["level"] == DEMO_LEVEL
    assert curriculum["prerequisites"] == DEMO_PREREQUISITES


@patch("bloc1_curriculum_planning.plan_curriculum.call_llm_api")
def test_plan_curriculum_real_mode_succeeds_first_try(mock_run_prompt):
    mock_run_prompt.return_value = json.dumps(VALID_CURRICULUM)

    curriculum = plan_curriculum({"title": "Sujet test", "gap_reason": "raison"}, demo=False)

    assert curriculum["title"] == "Cours test"
    assert mock_run_prompt.call_count == 1
    # level/prerequisites viennent de la réponse du LLM (validée), pas d'une constante forcée après coup.
    assert curriculum["level"] == VALID_CURRICULUM["level"]
    assert curriculum["prerequisites"] == VALID_CURRICULUM["prerequisites"]


@patch("bloc1_curriculum_planning.plan_curriculum.call_llm_api")
def test_plan_curriculum_two_different_topics_get_different_prerequisites(mock_run_prompt):
    """Preuve de non-régression du bug : deux cours de sujets différents ne doivent PAS obtenir
    les mêmes prérequis — chacun doit refléter ce que son propre LLM a renvoyé pour SON sujet."""
    curriculum_a = json.loads(json.dumps(VALID_CURRICULUM))
    curriculum_a["level"] = "avancé"
    curriculum_a["prerequisites"] = "Déjà savoir construire un agent LLM basique (LLM + outils + mémoire)."

    curriculum_b = json.loads(json.dumps(VALID_CURRICULUM))
    curriculum_b["title"] = "Lancer une agence d'automatisation IA"
    curriculum_b["level"] = "débutant"
    curriculum_b["prerequisites"] = "Aucun prérequis technique particulier, juste l'envie de se lancer."

    mock_run_prompt.side_effect = [json.dumps(curriculum_a), json.dumps(curriculum_b)]

    result_a = plan_curriculum({"title": "Sujet A", "gap_reason": ""}, demo=False)
    result_b = plan_curriculum({"title": "Sujet B", "gap_reason": ""}, demo=False)

    assert result_a["level"] != result_b["level"]
    assert result_a["prerequisites"] != result_b["prerequisites"]
    assert result_a["prerequisites"] == curriculum_a["prerequisites"]
    assert result_b["prerequisites"] == curriculum_b["prerequisites"]


@patch("bloc1_curriculum_planning.plan_curriculum.call_llm_api")
def test_plan_curriculum_retries_once_then_succeeds(mock_run_prompt):
    invalid = json.loads(json.dumps(VALID_CURRICULUM))
    invalid["chapters"][0]["learning_objectives"] = []
    mock_run_prompt.side_effect = [json.dumps(invalid), json.dumps(VALID_CURRICULUM)]

    curriculum = plan_curriculum({"title": "Sujet test", "gap_reason": "raison"}, demo=False)

    assert curriculum["title"] == "Cours test"
    assert mock_run_prompt.call_count == 2
    second_call_prompt = mock_run_prompt.call_args_list[1].kwargs["prompt"]
    assert "invalide" in second_call_prompt


@patch("bloc1_curriculum_planning.plan_curriculum.call_llm_api")
def test_plan_curriculum_raises_after_exhausting_retries(mock_run_prompt):
    invalid = json.loads(json.dumps(VALID_CURRICULUM))
    invalid["chapters"][0]["learning_objectives"] = []
    mock_run_prompt.return_value = json.dumps(invalid)

    with pytest.raises(LLMCallError):
        plan_curriculum({"title": "Sujet test", "gap_reason": "raison"}, demo=False)

    assert mock_run_prompt.call_count == 2


# --- decide_chapter_format (retrofit d'un chapitre DÉJÀ écrit, ex. cours 1) ---------------------

CHAPTER_ALREADY_WRITTEN = {
    "number": 2,
    "title": "Gérer les erreurs techniques",
    "learning_objectives": ["obj1"],
    "key_points": ["kp1"],
}


@patch("bloc1_curriculum_planning.plan_curriculum.call_llm_api")
def test_decide_chapter_format_returns_format_and_reasoning(mock_run_prompt):
    mock_run_prompt.return_value = json.dumps({"format": "video", "format_reasoning": "Démo de flux."})

    result = decide_chapter_format("AI Automation", "Cours test", "intermédiaire", CHAPTER_ALREADY_WRITTEN, "x" * 300)

    assert result == {"format": "video", "format_reasoning": "Démo de flux."}
    assert mock_run_prompt.call_count == 1


@patch("bloc1_curriculum_planning.plan_curriculum.call_llm_api")
def test_decide_chapter_format_includes_lesson_excerpt_in_prompt(mock_run_prompt):
    mock_run_prompt.return_value = json.dumps({"format": "text", "format_reasoning": "Référence dense."})

    decide_chapter_format("AI Automation", "Cours test", "intermédiaire", CHAPTER_ALREADY_WRITTEN, "contenu réel unique ABC123")

    prompt_used = mock_run_prompt.call_args.kwargs["prompt"]
    assert "contenu réel unique ABC123" in prompt_used


@patch("bloc1_curriculum_planning.plan_curriculum.call_llm_api")
def test_decide_chapter_format_retries_once_on_invalid_format(mock_run_prompt):
    invalid = json.dumps({"format": "audio", "format_reasoning": "..."})
    valid = json.dumps({"format": "mix", "format_reasoning": "Vidéo + référence."})
    mock_run_prompt.side_effect = [invalid, valid]

    result = decide_chapter_format("AI Automation", "Cours test", "intermédiaire", CHAPTER_ALREADY_WRITTEN, "x" * 300)

    assert result["format"] == "mix"
    assert mock_run_prompt.call_count == 2


@patch("bloc1_curriculum_planning.plan_curriculum.call_llm_api")
def test_decide_chapter_format_raises_after_exhausting_retries(mock_run_prompt):
    mock_run_prompt.return_value = json.dumps({"format": "not_valid", "format_reasoning": "..."})

    with pytest.raises(LLMCallError):
        decide_chapter_format("AI Automation", "Cours test", "intermédiaire", CHAPTER_ALREADY_WRITTEN, "x" * 300)

    assert mock_run_prompt.call_count == 2


# --- regenerate_level_and_prerequisites (correction ciblée d'un curriculum déjà généré) -----------

@patch("bloc1_curriculum_planning.plan_curriculum.call_llm_api")
def test_regenerate_level_and_prerequisites_succeeds_first_try(mock_run_prompt):
    mock_run_prompt.return_value = json.dumps(
        {"level": "débutant", "prerequisites": "Aucun prérequis technique particulier."}
    )

    result = regenerate_level_and_prerequisites(VALID_CURRICULUM)

    assert result == {"level": "débutant", "prerequisites": "Aucun prérequis technique particulier."}
    assert mock_run_prompt.call_count == 1


@patch("bloc1_curriculum_planning.plan_curriculum.call_llm_api")
def test_regenerate_level_and_prerequisites_retries_on_invalid_level(mock_run_prompt):
    mock_run_prompt.side_effect = [
        json.dumps({"level": "expert", "prerequisites": "Une phrase assez longue de prérequis."}),
        json.dumps({"level": "avancé", "prerequisites": "Une phrase assez longue de prérequis."}),
    ]

    result = regenerate_level_and_prerequisites(VALID_CURRICULUM)

    assert result["level"] == "avancé"
    assert mock_run_prompt.call_count == 2


@patch("bloc1_curriculum_planning.plan_curriculum.call_llm_api")
def test_regenerate_level_and_prerequisites_raises_after_exhausting_retries(mock_run_prompt):
    mock_run_prompt.return_value = json.dumps({"level": "expert", "prerequisites": "x" * 20})

    with pytest.raises(LLMCallError):
        regenerate_level_and_prerequisites(VALID_CURRICULUM)

    assert mock_run_prompt.call_count == 2
