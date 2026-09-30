"""Tests unitaires de l'aplatissement du contenu de chapitre (bloc7_exam_generation/content_text.py)."""

from bloc7_exam_generation.content_text import chapter_source_text

CHAPTER_WITH_CONTENT_BLOCKS = {
    "title": "Chapitre de test",
    "learning_objectives": ["Objectif 1", "Objectif 2"],
    "key_points": ["Point clé 1"],
    "content_blocks": [
        {"type": "paragraph", "text": "Un paragraphe normal."},
        {"type": "heading", "text": "Un titre de section"},
        {"type": "callout", "style": "key_point", "title": "À retenir", "text": "Ceci est important."},
        {"type": "code", "code": "print('hello')"},
        {"type": "list", "style": "bulleted", "items": ["Item A", "Item B"]},
        {
            "type": "diagram",
            "diagram_type": "architecture",
            "title": "Architecture type",
            "hub": {"label": "Orchestrateur", "description": "Coordonne tout"},
            "satellites": [{"label": "Outil 1", "description": "Fait X"}],
        },
        {
            "type": "diagram",
            "diagram_type": "timeline",
            "steps": [{"label": "Étape 1", "stat": "42%", "description": "Détail"}],
        },
        {
            "type": "diagram",
            "diagram_type": "comparison",
            "left": {"label": "Avant", "points": ["Lent"]},
            "right": {"label": "Après", "points": ["Rapide"]},
        },
    ],
    "lesson_script": None,
    "written_complement": None,
}

CHAPTER_WITH_LESSON_SCRIPT_ONLY = {
    "title": "Chapitre texte simple",
    "learning_objectives": [],
    "key_points": [],
    "content_blocks": None,
    "lesson_script": "Ceci est le script de la leçon.",
    "written_complement": None,
}

CHAPTER_WITH_WRITTEN_COMPLEMENT_ONLY = {
    "title": "Chapitre vidéo",
    "learning_objectives": [],
    "key_points": [],
    "content_blocks": None,
    "lesson_script": None,
    "written_complement": "Complément écrit uniquement.",
}


def test_includes_title_objectives_and_key_points():
    text = chapter_source_text(CHAPTER_WITH_CONTENT_BLOCKS)
    assert "Chapitre de test" in text
    assert "Objectif 1" in text
    assert "Point clé 1" in text


def test_flattens_every_content_block_type():
    text = chapter_source_text(CHAPTER_WITH_CONTENT_BLOCKS)
    assert "Un paragraphe normal." in text
    assert "Un titre de section" in text
    assert "Ceci est important." in text
    assert "print('hello')" in text
    assert "Item A" in text and "Item B" in text
    assert "Orchestrateur" in text and "Outil 1" in text
    assert "Étape 1" in text and "42%" in text
    assert "Avant" in text and "Rapide" in text


def test_falls_back_to_lesson_script_when_no_content_blocks():
    text = chapter_source_text(CHAPTER_WITH_LESSON_SCRIPT_ONLY)
    assert "Ceci est le script de la leçon." in text


def test_falls_back_to_written_complement_when_nothing_else():
    text = chapter_source_text(CHAPTER_WITH_WRITTEN_COMPLEMENT_ONLY)
    assert "Complément écrit uniquement." in text


def test_never_includes_comprehension_exercises_or_practical_exercise():
    chapter = {
        **CHAPTER_WITH_LESSON_SCRIPT_ONLY,
        "comprehension_exercises": [{"question": "Ne doit pas apparaître ici."}],
        "practical_exercise": {"title": "Ne doit pas apparaître ici non plus."},
    }
    text = chapter_source_text(chapter)
    assert "Ne doit pas apparaître ici." not in text
    assert "Ne doit pas apparaître ici non plus." not in text
