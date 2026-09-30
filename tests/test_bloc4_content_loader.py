import json
from unittest.mock import patch

from bloc4_publication.content_loader import (
    exam_bank_available,
    get_chapter,
    get_course_by_slug,
    lesson_paragraphs,
    load_course,
    load_exam_questions,
    load_published_courses,
    render_inline_emphasis,
    resolve_full_course,
    slugify,
)

CURRICULUM = {
    "title": "Cours test",
    "niche": "AI Automation",
    "level": "intermédiaire",
    "prerequisites": "Rien de particulier.",
    "source_topic": {"title": "Sujet test", "gap_reason": "Raison du cours."},
    "chapters": [
        {
            "number": 1,
            "title": "Intro",
            "learning_objectives": ["obj1", "obj2"],
            "key_points": ["kp1"],
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

CONTENT = {
    "course_title": "Cours test",
    "niche": "AI Automation",
    "level": "intermédiaire",
    "running_example": "Fil rouge test",
    "chapters_content": [
        {
            "chapter_number": 1,
            "chapter_title": "Intro",
            "lesson_script": "Premier paragraphe.\n\nDeuxième paragraphe.",
            "comprehension_exercises": [{"question": "Q?", "type": "mcq", "options": ["A", "B"], "correct_answer": "A"}],
            "practical_exercise": {"title": "Ex", "instructions": "Fais ceci.", "expected_outcome": "Résultat."},
        },
        {
            "chapter_number": 2,
            "chapter_title": "Projet final",
            "lesson_script": "Texte du projet final.",
            "comprehension_exercises": [{"question": "Q2?", "type": "short_answer", "options": None, "correct_answer": "R2"}],
            "practical_exercise": {
                "title": "Projet",
                "instructions": "Assemble tout.",
                "expected_outcome": "Système livré.",
                "deliverables": ["Livrable 1"],
                "step_by_step_instructions": ["Étape 1"],
                "evaluation_criteria": ["Critère 1"],
            },
        },
    ],
}


def _write_fixtures(tmp_path):
    curriculum_path = tmp_path / "curriculum.json"
    content_path = tmp_path / "content.json"
    curriculum_path.write_text(json.dumps(CURRICULUM), encoding="utf-8")
    content_path.write_text(json.dumps(CONTENT), encoding="utf-8")
    return curriculum_path, content_path


def test_load_course_merges_curriculum_and_content(tmp_path):
    curriculum_path, content_path = _write_fixtures(tmp_path)
    course = load_course(curriculum_path, content_path)

    assert course["title"] == "Cours test"
    assert course["description"] == "Raison du cours."
    assert len(course["chapters"]) == 2
    assert course["chapters"][0]["lesson_script"] == "Premier paragraphe.\n\nDeuxième paragraphe."
    assert course["chapters"][0]["learning_objectives"] == ["obj1", "obj2"]


def test_load_course_sets_content_blocks_to_none_when_absent(tmp_path):
    curriculum_path, content_path = _write_fixtures(tmp_path)
    course = load_course(curriculum_path, content_path)

    assert course["chapters"][0]["content_blocks"] is None
    assert course["chapters"][1]["content_blocks"] is None


def test_load_course_passes_through_content_blocks_when_present(tmp_path):
    content_with_blocks = json.loads(json.dumps(CONTENT))
    content_with_blocks["chapters_content"][0]["content_blocks"] = [
        {"type": "paragraph", "text": "Un paragraphe enrichi."}
    ]
    curriculum_path = tmp_path / "curriculum.json"
    content_path = tmp_path / "content.json"
    curriculum_path.write_text(json.dumps(CURRICULUM), encoding="utf-8")
    content_path.write_text(json.dumps(content_with_blocks), encoding="utf-8")

    course = load_course(curriculum_path, content_path)

    assert course["chapters"][0]["content_blocks"] == [{"type": "paragraph", "text": "Un paragraphe enrichi."}]
    assert course["chapters"][1]["content_blocks"] is None


def test_render_inline_emphasis_converts_double_asterisk_to_strong():
    result = render_inline_emphasis("un **terme important** dans le texte")
    assert str(result) == "un <strong>terme important</strong> dans le texte"


def test_render_inline_emphasis_escapes_html_from_source_text():
    result = render_inline_emphasis("<script>alert(1)</script> **ok**")
    assert "<script>" not in str(result)
    assert "&lt;script&gt;" in str(result)
    assert "<strong>ok</strong>" in str(result)


def test_load_course_includes_a_slug_derived_from_title(tmp_path):
    curriculum_path, content_path = _write_fixtures(tmp_path)
    course = load_course(curriculum_path, content_path)

    assert course["slug"] == "cours-test"


def test_slugify_strips_accents_and_punctuation():
    assert slugify("Agents IA : gérer, évaluer et déployer !") == "agents-ia-gerer-evaluer-et-deployer"


def test_slugify_collapses_repeated_separators_and_trims_edges():
    assert slugify("  Hello   World--Test  ") == "hello-world-test"


def test_load_course_flags_video_only_on_chapter_1(tmp_path):
    curriculum_path, content_path = _write_fixtures(tmp_path)
    course = load_course(curriculum_path, content_path)

    assert course["chapters"][0]["has_video"] is True
    assert course["chapters"][1]["has_video"] is False


def test_load_course_flags_final_project_on_last_chapter(tmp_path):
    curriculum_path, content_path = _write_fixtures(tmp_path)
    course = load_course(curriculum_path, content_path)

    assert course["chapters"][0]["is_final_project"] is False
    assert course["chapters"][1]["is_final_project"] is True
    assert course["chapters"][1]["practical_exercise"]["deliverables"] == ["Livrable 1"]


def test_get_chapter_returns_none_for_missing_number(tmp_path):
    curriculum_path, content_path = _write_fixtures(tmp_path)
    course = load_course(curriculum_path, content_path)

    assert get_chapter(course, 1)["title"] == "Intro"
    assert get_chapter(course, 99) is None


def test_lesson_paragraphs_splits_on_blank_lines():
    assert lesson_paragraphs("A.\n\nB.\n\nC.") == ["A.", "B.", "C."]


def test_lesson_paragraphs_does_not_alter_text_content():
    text = "Un seul paragraphe, avec des virgules, et 82% de précision."
    assert lesson_paragraphs(text) == [text]


# --- format par chapitre (2026-08-07) : text/video/mix, rétrocompatibilité cours 1 -------------

def test_load_course_defaults_format_to_text_when_absent(tmp_path):
    """Rétrocompatibilité cours 1 : curriculum sans champ 'format' -> "text" partout."""
    curriculum_path, content_path = _write_fixtures(tmp_path)
    course = load_course(curriculum_path, content_path)

    assert course["chapters"][0]["format"] == "text"
    assert course["chapters"][1]["format"] == "text"
    assert course["chapters"][0]["video_script"] is None
    assert course["chapters"][0]["written_complement"] is None


def test_load_course_passes_through_chapter_format_from_curriculum(tmp_path):
    curriculum_with_formats = json.loads(json.dumps(CURRICULUM))
    curriculum_with_formats["chapters"][0]["format"] = "video"
    curriculum_with_formats["chapters"][0]["format_reasoning"] = "Démo visuelle."
    curriculum_with_formats["chapters"][1]["format"] = "mix"

    content_video_mix = json.loads(json.dumps(CONTENT))
    content_video_mix["chapters_content"][0] = {
        "chapter_number": 1,
        "chapter_title": "Intro",
        "video_script": {"summary": "Résumé.", "scenes": [{"beat": "A", "narration": "B", "visual": "C"}]},
        "written_complement": "Complément court.",
        "comprehension_exercises": CONTENT["chapters_content"][0]["comprehension_exercises"],
        "practical_exercise": CONTENT["chapters_content"][0]["practical_exercise"],
    }

    curriculum_path = tmp_path / "curriculum.json"
    content_path = tmp_path / "content.json"
    curriculum_path.write_text(json.dumps(curriculum_with_formats), encoding="utf-8")
    content_path.write_text(json.dumps(content_video_mix), encoding="utf-8")

    course = load_course(curriculum_path, content_path)

    assert course["chapters"][0]["format"] == "video"
    assert course["chapters"][0]["video_script"]["summary"] == "Résumé."
    assert course["chapters"][0]["written_complement"] == "Complément court."
    assert course["chapters"][0]["lesson_script"] is None
    assert course["chapters"][1]["format"] == "mix"


# --- banque d'examen (bloc7_exam_generation) : robustesse à l'absence de fichier ----------------


def test_exam_bank_available_false_when_file_missing(tmp_path):
    with patch("bloc4_publication.content_loader.DATA_DIR", tmp_path):
        assert exam_bank_available("un-cours-sans-banque") is False


def test_exam_bank_available_true_when_file_present(tmp_path):
    course_dir = tmp_path / "un-cours"
    course_dir.mkdir()
    (course_dir / "exam_questions.json").write_text("[]", encoding="utf-8")

    with patch("bloc4_publication.content_loader.DATA_DIR", tmp_path):
        assert exam_bank_available("un-cours") is True


def test_load_exam_questions_returns_none_when_file_missing(tmp_path):
    with patch("bloc4_publication.content_loader.DATA_DIR", tmp_path):
        assert load_exam_questions("un-cours-sans-banque") is None


def test_load_exam_questions_returns_the_parsed_bank_when_present(tmp_path):
    course_dir = tmp_path / "un-cours"
    course_dir.mkdir()
    bank = [{"id": "q1", "chapter": 1, "question": "Q ?", "options": ["A", "B", "C", "D"], "correct_index": 0, "explanation": "E."}]
    (course_dir / "exam_questions.json").write_text(json.dumps(bank), encoding="utf-8")

    with patch("bloc4_publication.content_loader.DATA_DIR", tmp_path):
        assert load_exam_questions("un-cours") == bank


# --- catalogue multi-cours (Changement 4, Étape B) : fallback garanti sur le cours 1 -----------


def test_load_published_courses_falls_back_to_course_1_when_file_missing(tmp_path):
    with patch("bloc4_publication.content_loader.DATA_DIR", tmp_path):
        courses = load_published_courses()

    assert len(courses) == 1
    assert courses[0] == load_course()


def test_load_published_courses_falls_back_to_course_1_when_courses_list_is_empty(tmp_path):
    (tmp_path / "published_courses.json").write_text(json.dumps({"courses": []}), encoding="utf-8")

    with patch("bloc4_publication.content_loader.DATA_DIR", tmp_path):
        courses = load_published_courses()

    assert len(courses) == 1
    assert courses[0] == load_course()


def test_load_published_courses_falls_back_to_course_1_on_corrupted_json(tmp_path):
    (tmp_path / "published_courses.json").write_text("{ceci n'est pas du JSON valide", encoding="utf-8")

    with patch("bloc4_publication.content_loader.DATA_DIR", tmp_path):
        courses = load_published_courses()  # ne doit JAMAIS lever

    assert len(courses) == 1
    assert courses[0] == load_course()


def test_load_published_courses_falls_back_to_course_1_on_unexpected_json_shape(tmp_path):
    # JSON valide, mais pas la forme {"courses": [...]} attendue.
    (tmp_path / "published_courses.json").write_text(json.dumps(["pas", "la", "bonne", "forme"]), encoding="utf-8")

    with patch("bloc4_publication.content_loader.DATA_DIR", tmp_path):
        courses = load_published_courses()

    assert len(courses) == 1
    assert courses[0] == load_course()


def test_load_published_courses_returns_all_entries_when_present(tmp_path):
    entries = [
        {"slug": "cours-a", "title": "Cours A", "domain": "Finance personnelle", "price_usd": 19.99, "paddle_price_id": "pri_a"},
        {"slug": "cours-b", "title": "Cours B", "domain": "Vente", "price_usd": 24.99, "paddle_price_id": "pri_b"},
    ]
    (tmp_path / "published_courses.json").write_text(json.dumps({"courses": entries}), encoding="utf-8")

    with patch("bloc4_publication.content_loader.DATA_DIR", tmp_path):
        courses = load_published_courses()

    assert courses == entries


def test_get_course_by_slug_finds_existing_entry(tmp_path):
    entries = [
        {"slug": "cours-a", "title": "Cours A", "domain": "Finance personnelle", "price_usd": 19.99, "paddle_price_id": "pri_a"},
        {"slug": "cours-b", "title": "Cours B", "domain": "Vente", "price_usd": 24.99, "paddle_price_id": "pri_b"},
    ]
    (tmp_path / "published_courses.json").write_text(json.dumps({"courses": entries}), encoding="utf-8")

    with patch("bloc4_publication.content_loader.DATA_DIR", tmp_path):
        found = get_course_by_slug("cours-b")

    assert found == entries[1]


def test_get_course_by_slug_returns_none_when_not_found(tmp_path):
    entries = [{"slug": "cours-a", "title": "Cours A", "domain": "Finance personnelle", "price_usd": 19.99, "paddle_price_id": "pri_a"}]
    (tmp_path / "published_courses.json").write_text(json.dumps({"courses": entries}), encoding="utf-8")

    with patch("bloc4_publication.content_loader.DATA_DIR", tmp_path):
        assert get_course_by_slug("inconnu") is None


def test_get_course_by_slug_finds_course_1_in_fallback_mode(tmp_path):
    with patch("bloc4_publication.content_loader.DATA_DIR", tmp_path):
        found = get_course_by_slug(load_course()["slug"])

    assert found == load_course()


# --- réconciliation price_id / paddle_price_id (fichiers écrits avant le renommage) -----------


def test_load_published_courses_normalizes_legacy_price_id_key(tmp_path):
    entries = [{"slug": "cours-a", "title": "Cours A", "domain": "Finance personnelle", "price_usd": 19.99, "price_id": "pri_legacy"}]
    (tmp_path / "published_courses.json").write_text(json.dumps({"courses": entries}), encoding="utf-8")

    with patch("bloc4_publication.content_loader.DATA_DIR", tmp_path):
        courses = load_published_courses()

    assert courses[0]["paddle_price_id"] == "pri_legacy"
    assert courses[0]["price_id"] == "pri_legacy"  # ancienne clé conservée, pas retirée


def test_load_published_courses_prefers_paddle_price_id_when_both_present(tmp_path):
    entries = [{
        "slug": "cours-a", "title": "Cours A", "domain": "Finance personnelle", "price_usd": 19.99,
        "paddle_price_id": "pri_new", "price_id": "pri_old",
    }]
    (tmp_path / "published_courses.json").write_text(json.dumps({"courses": entries}), encoding="utf-8")

    with patch("bloc4_publication.content_loader.DATA_DIR", tmp_path):
        courses = load_published_courses()

    assert courses[0]["paddle_price_id"] == "pri_new"


# --- resolve_full_course : cours 1 (fallback) inchangé, entrée légère -> load_course + métadonnées


def test_resolve_full_course_returns_course_1_unchanged_in_fallback_mode():
    course_1 = load_course()
    assert resolve_full_course(course_1) == course_1


def test_resolve_full_course_merges_catalog_metadata_onto_full_content(tmp_path):
    curriculum_path, content_path = _write_fixtures(tmp_path)

    entry = {
        "slug": "cours-test",
        "title": "Cours test",
        "domain": "Finance personnelle",
        "price_usd": 19.99,
        "paddle_price_id": "pri_test",
        "curriculum_file": str(curriculum_path),
        "content_file": str(content_path),
    }

    full = resolve_full_course(entry)

    assert "chapters" in full
    assert full["domain"] == "Finance personnelle"
    assert full["price_usd"] == 19.99
    assert full["paddle_price_id"] == "pri_test"
