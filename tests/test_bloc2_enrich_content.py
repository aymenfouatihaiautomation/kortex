import json
from unittest.mock import patch

import pytest

from bloc2_content_writing.enrich_content import (
    VALID_BLOCK_TYPES,
    build_enrichment_prompt,
    enrich_chapter_content,
    enrich_course,
    flatten_content_blocks_to_text,
    run_qc_on_enriched_chapter,
    save_enriched_content,
    validate_content_blocks,
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
            "learning_objectives": ["obj1"],
            "key_points": ["kp1", "kp2"],
            "builds_on_previous": "N/A - premier chapitre",
        },
        {
            "number": 2,
            "title": "Suite",
            "learning_objectives": ["obj1"],
            "key_points": ["kp3"],
            "builds_on_previous": "S'appuie sur le chapitre 1.",
        },
    ],
}

SOURCE_CONTENT = {
    "course_title": "Cours test",
    "chapters_content": [
        {
            "chapter_number": 1,
            "chapter_title": "Intro",
            "lesson_script": "x" * 250,
            "comprehension_exercises": [{"question": "Q?", "type": "short_answer", "options": None, "correct_answer": "R"}],
            "practical_exercise": {"title": "Ex", "instructions": "Fais ceci.", "expected_outcome": "Résultat."},
        },
        {
            "chapter_number": 2,
            "chapter_title": "Suite",
            "lesson_script": "y" * 250,
            "comprehension_exercises": [{"question": "Q2?", "type": "short_answer", "options": None, "correct_answer": "R2"}],
            "practical_exercise": {"title": "Ex2", "instructions": "Fais cela.", "expected_outcome": "Résultat2."},
        },
    ],
}

VALID_BLOCKS = [
    {"type": "paragraph", "text": "Un **terme** important."},
    {"type": "heading", "text": "Section"},
    {"type": "callout", "style": "key_point", "title": "Retenir", "text": "Ceci est important."},
    {"type": "callout", "style": "warning", "title": "Attention", "text": "Ne fais pas ça."},
    {"type": "list", "style": "bullet", "items": ["Un", "Deux"]},
    {"type": "code", "language": "python", "code": "def f():\n    return 1"},
    {
        "type": "diagram",
        "diagram_type": "architecture",
        "title": "Archi",
        "hub": {"id": "h", "label": "Hub", "description": "centre"},
        "satellites": [
            {"id": "a", "label": "A", "description": "satellite A"},
            {"id": "b", "label": "B", "description": "satellite B"},
        ],
    },
    {
        "type": "diagram",
        "diagram_type": "timeline",
        "title": "Chrono",
        "steps": [
            {"number": 1, "label": "Étape 1", "stat": "10", "description": "..."},
            {"number": 2, "label": "Étape 2", "stat": "", "description": "..."},
        ],
    },
    {
        "type": "diagram",
        "diagram_type": "flow",
        "title": "Flux",
        "steps": [{"label": "A", "description": "..."}, {"label": "B", "description": "..."}],
    },
    {
        "type": "diagram",
        "diagram_type": "comparison",
        "title": "Comparaison",
        "left": {"label": "Démo", "points": ["p1"]},
        "right": {"label": "Prod", "points": ["p2"]},
    },
]


# --- validate_content_blocks ---------------------------------------------------------------------


def test_validate_content_blocks_accepts_all_valid_types():
    assert validate_content_blocks(VALID_BLOCKS) == []


def test_validate_content_blocks_rejects_empty_list():
    assert validate_content_blocks([]) != []


def test_validate_content_blocks_rejects_unknown_type():
    errors = validate_content_blocks([{"type": "video", "text": "x"}])
    assert any("type invalide" in e for e in errors)


def test_validate_content_blocks_rejects_paragraph_without_text():
    errors = validate_content_blocks([{"type": "paragraph", "text": "   "}])
    assert any("paragraph" in e for e in errors)


def test_validate_content_blocks_rejects_callout_with_invalid_style():
    errors = validate_content_blocks([{"type": "callout", "style": "fun_fact", "text": "x"}])
    assert any("callout" in e for e in errors)


def test_validate_content_blocks_accepts_reminder_callout_style():
    # Ajouté après l'ajustement de style (2026-08-08) : un 4e style d'encadré, distinct de
    # key_point/warning/tip — le chapitre 1 déjà généré n'en a pas besoin, mais les futurs
    # chapitres doivent pouvoir l'utiliser.
    errors = validate_content_blocks([{"type": "callout", "style": "reminder", "title": "T", "text": "x"}])
    assert errors == []


def test_validate_content_blocks_rejects_code_without_language():
    errors = validate_content_blocks([{"type": "code", "code": "x = 1", "language": ""}])
    assert any("code" in e for e in errors)


def test_validate_content_blocks_rejects_list_without_items():
    errors = validate_content_blocks([{"type": "list", "style": "bullet", "items": []}])
    assert any("list" in e for e in errors)


def test_validate_content_blocks_rejects_architecture_without_satellites():
    errors = validate_content_blocks(
        [{"type": "diagram", "diagram_type": "architecture", "hub": {"id": "h", "label": "H"}, "satellites": []}]
    )
    assert any("architecture" in e for e in errors)


def test_validate_content_blocks_rejects_timeline_with_less_than_two_steps():
    errors = validate_content_blocks(
        [{"type": "diagram", "diagram_type": "timeline", "steps": [{"number": 1, "label": "A"}]}]
    )
    assert any("timeline" in e for e in errors)


def test_validate_content_blocks_rejects_comparison_without_points():
    errors = validate_content_blocks(
        [{"type": "diagram", "diagram_type": "comparison", "left": {"label": "A", "points": []}, "right": {"label": "B", "points": ["x"]}}]
    )
    assert any("comparison" in e for e in errors)


def test_valid_block_types_matches_documented_set():
    assert VALID_BLOCK_TYPES == {"paragraph", "heading", "callout", "code", "list", "diagram"}


# --- flatten_content_blocks_to_text (vue pour la revue Bloc 3.5) --------------------------------


def test_flatten_includes_paragraph_text_without_markdown_markers():
    text = flatten_content_blocks_to_text([{"type": "paragraph", "text": "Un **terme** clé."}])
    assert "Un terme clé." in text
    assert "**" not in text


def test_flatten_includes_heading_as_marked_line():
    text = flatten_content_blocks_to_text([{"type": "heading", "text": "Ma section"}])
    assert "## Ma section" in text


def test_flatten_includes_callout_style_and_text():
    text = flatten_content_blocks_to_text(
        [{"type": "callout", "style": "warning", "title": "Attention", "text": "Ne fais pas ça."}]
    )
    assert "WARNING" in text
    assert "Ne fais pas ça." in text


def test_flatten_includes_code_content():
    text = flatten_content_blocks_to_text([{"type": "code", "language": "python", "code": "x = 1"}])
    assert "x = 1" in text


def test_flatten_includes_list_items():
    text = flatten_content_blocks_to_text([{"type": "list", "style": "bullet", "items": ["Premier", "Second"]}])
    assert "Premier" in text
    assert "Second" in text


def test_flatten_includes_architecture_diagram_nodes():
    text = flatten_content_blocks_to_text(
        [
            {
                "type": "diagram",
                "diagram_type": "architecture",
                "title": "Archi",
                "hub": {"id": "h", "label": "Orchestrateur", "description": "pilote"},
                "satellites": [{"id": "a", "label": "LLM", "description": "raisonne"}],
            }
        ]
    )
    assert "Orchestrateur" in text
    assert "LLM" in text


def test_flatten_includes_all_diagram_types_without_crashing():
    text = flatten_content_blocks_to_text(VALID_BLOCKS)
    for expected in ("Hub", "A", "B", "Étape 1", "Démo", "Prod"):
        assert expected in text


# --- build_enrichment_prompt ----------------------------------------------------------------------


def test_build_enrichment_prompt_includes_chapter_title_and_source_text():
    prompt = build_enrichment_prompt("Mon Chapitre", "Texte source unique.", ["kp1"])
    assert "Mon Chapitre" in prompt
    assert "Texte source unique." in prompt
    assert "kp1" in prompt


def test_build_enrichment_prompt_includes_retry_suffix_when_error_feedback_given():
    prompt = build_enrichment_prompt("Titre", "Texte.", [], error_feedback="- erreur X")
    assert "invalide" in prompt
    assert "erreur X" in prompt


def test_build_enrichment_prompt_omits_retry_suffix_by_default():
    prompt = build_enrichment_prompt("Titre", "Texte.", [])
    assert "ATTENTION" not in prompt


# --- enrich_chapter_content ------------------------------------------------------------------------


def test_enrich_chapter_content_demo_mode_returns_valid_blocks_no_network():
    blocks = enrich_chapter_content("Chapitre test", "texte source", ["kp1"], demo=True)
    assert validate_content_blocks(blocks) == []


@patch("bloc2_content_writing.enrich_content.call_llm_api")
def test_enrich_chapter_content_real_mode_parses_llm_response(mock_run_prompt):
    mock_run_prompt.return_value = json.dumps({"content_blocks": VALID_BLOCKS})
    blocks = enrich_chapter_content("Chapitre test", "texte source", ["kp1"], demo=False)
    assert blocks == VALID_BLOCKS
    assert mock_run_prompt.call_count == 1


@patch("bloc2_content_writing.enrich_content.call_llm_api")
def test_enrich_chapter_content_retries_once_then_succeeds(mock_run_prompt):
    invalid = {"content_blocks": [{"type": "paragraph", "text": ""}]}
    valid = {"content_blocks": VALID_BLOCKS}
    mock_run_prompt.side_effect = [json.dumps(invalid), json.dumps(valid)]
    blocks = enrich_chapter_content("Chapitre test", "texte source", ["kp1"], demo=False)
    assert blocks == VALID_BLOCKS
    assert mock_run_prompt.call_count == 2
    second_prompt = mock_run_prompt.call_args_list[1].kwargs["prompt"]
    assert "invalide" in second_prompt


@patch("bloc2_content_writing.enrich_content.call_llm_api")
def test_enrich_chapter_content_raises_after_exhausting_retries(mock_run_prompt):
    invalid = {"content_blocks": [{"type": "paragraph", "text": ""}]}
    mock_run_prompt.return_value = json.dumps(invalid)
    with pytest.raises(LLMCallError):
        enrich_chapter_content("Chapitre test", "texte source", ["kp1"], demo=False)
    assert mock_run_prompt.call_count == 2


# --- enrich_course / save_enriched_content --------------------------------------------------------


def test_enrich_course_demo_mode_processes_only_requested_chapters(tmp_path):
    curriculum_file = tmp_path / "curriculum.json"
    content_file = tmp_path / "content.json"
    curriculum_file.write_text(json.dumps(CURRICULUM), encoding="utf-8")
    content_file.write_text(json.dumps(SOURCE_CONTENT), encoding="utf-8")

    result = enrich_course(curriculum_file, content_file, chapter_numbers=[1], demo=True)

    assert len(result["chapters_content"]) == 1
    assert result["chapters_content"][0]["chapter_number"] == 1
    assert result["chapters_content"][0]["comprehension_exercises"] == SOURCE_CONTENT["chapters_content"][0]["comprehension_exercises"]


def test_enrich_course_never_writes_to_source_content_file(tmp_path):
    curriculum_file = tmp_path / "curriculum.json"
    content_file = tmp_path / "content.json"
    curriculum_file.write_text(json.dumps(CURRICULUM), encoding="utf-8")
    content_file.write_text(json.dumps(SOURCE_CONTENT), encoding="utf-8")
    original_bytes = content_file.read_bytes()

    enrich_course(curriculum_file, content_file, chapter_numbers=[1], demo=True)

    assert content_file.read_bytes() == original_bytes  # jamais écrit, lecture seule garantie


def test_save_enriched_content_merges_with_existing_chapters(tmp_path):
    output = tmp_path / "enriched.json"
    result_ch1 = {
        "course_title": "Cours test",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "chapters_content": [{"chapter_number": 1, "chapter_title": "Intro", "content_blocks": VALID_BLOCKS, "comprehension_exercises": [], "practical_exercise": {}}],
    }
    save_enriched_content(result_ch1, output)

    result_ch2 = {
        "course_title": "Cours test",
        "generated_at": "2026-01-02T00:00:00+00:00",
        "chapters_content": [{"chapter_number": 2, "chapter_title": "Suite", "content_blocks": VALID_BLOCKS, "comprehension_exercises": [], "practical_exercise": {}}],
    }
    save_enriched_content(result_ch2, output)

    merged = json.loads(output.read_text(encoding="utf-8"))
    numbers = sorted(c["chapter_number"] for c in merged["chapters_content"])
    assert numbers == [1, 2]  # le chapitre 1 n'a pas été écrasé par l'ajout du chapitre 2


def test_save_enriched_content_updates_a_chapter_already_present(tmp_path):
    output = tmp_path / "enriched.json"
    v1 = {
        "course_title": "Cours test",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "chapters_content": [{"chapter_number": 1, "chapter_title": "Intro", "content_blocks": [{"type": "paragraph", "text": "v1"}], "comprehension_exercises": [], "practical_exercise": {}}],
    }
    save_enriched_content(v1, output)

    v2 = {
        "course_title": "Cours test",
        "generated_at": "2026-01-03T00:00:00+00:00",
        "chapters_content": [{"chapter_number": 1, "chapter_title": "Intro", "content_blocks": [{"type": "paragraph", "text": "v2"}], "comprehension_exercises": [], "practical_exercise": {}}],
    }
    save_enriched_content(v2, output)

    merged = json.loads(output.read_text(encoding="utf-8"))
    assert len(merged["chapters_content"]) == 1
    assert merged["chapters_content"][0]["content_blocks"][0]["text"] == "v2"


# --- run_qc_on_enriched_chapter (réutilise reviewer.review_chapter tel quel) ---------------------


def test_run_qc_on_enriched_chapter_demo_mode_returns_a_verdict():
    enriched_chapter = {
        "chapter_number": 1,
        "content_blocks": VALID_BLOCKS,
        "comprehension_exercises": SOURCE_CONTENT["chapters_content"][0]["comprehension_exercises"],
        "practical_exercise": SOURCE_CONTENT["chapters_content"][0]["practical_exercise"],
    }
    review = run_qc_on_enriched_chapter(CURRICULUM, CURRICULUM["chapters"][0], None, enriched_chapter, 2, demo=True)
    assert review["overall_verdict"] in ("accepted", "needs_revision")


@patch("bloc3_5_quality_control.reviewer.review_chapter")
def test_run_qc_on_enriched_chapter_passes_flattened_text_not_raw_blocks(mock_review):
    mock_review.return_value = {"overall_verdict": "accepted", "issues": []}
    enriched_chapter = {
        "chapter_number": 1,
        "content_blocks": [{"type": "paragraph", "text": "Contenu unique reconnaissable."}],
        "comprehension_exercises": [],
        "practical_exercise": {},
    }

    run_qc_on_enriched_chapter(CURRICULUM, CURRICULUM["chapters"][0], None, enriched_chapter, 2, demo=False)

    mock_review.assert_called_once()
    content_arg = mock_review.call_args.args[3]
    assert isinstance(content_arg["lesson_script"], str)
    assert "Contenu unique reconnaissable." in content_arg["lesson_script"]
