"""Bloc 4 — rendu adaptatif de chapter.html selon chapter["format"] (text/video/mix, 2026-08-07).

Rend le template directement (fabrique son propre `chapter`/`course`), plutôt que de dépendre du
contenu réel du cours 1 en production — permet de tester les 3 formats sans donnée réelle "video"/
"mix" (le cours 1 n'en a pas). `create_app()` sert uniquement à obtenir un environnement Jinja
complet (filtres, routes pour `url_for`) ; le contenu réel chargé par l'app n'est pas utilisé ici.
"""

from flask import render_template

from bloc4_publication.app import create_app

COMMON_CHAPTER_FIELDS = {
    "number": 2,
    "title": "Chapitre de test",
    "learning_objectives": ["obj1"],
    "key_points": ["kp1"],
    "content_blocks": None,
    "comprehension_exercises": [
        {"question": "Une question ?", "type": "mcq", "options": ["A", "B"], "correct_answer": "A", "explanation": "Car A."},
    ],
    "practical_exercise": {"title": "Exo", "instructions": "Fais ceci.", "expected_outcome": "Résultat."},
    "is_final_project": False,
    "has_video": False,  # aucun asset vidéo réel pour ces chapitres de test
}

TEXT_CHAPTER = {
    **COMMON_CHAPTER_FIELDS,
    "format": "text",
    "lesson_script": "Premier paragraphe du texte.\n\nDeuxième paragraphe du texte.",
    "video_script": None,
    "written_complement": None,
}

# Cas retrofit cours 1 (2026-08-08) : un chapitre "video"/"mix" issu d'un contenu DÉJÀ écrit en
# entier (pas généré comme un chapitre 100% vidéo) — le lesson_script complet doit rester affiché,
# jamais remplacé par le seul written_complement court.
VIDEO_CHAPTER_WITH_FULL_TEXT = {
    **COMMON_CHAPTER_FIELDS,
    "format": "video",
    "lesson_script": "Texte complet déjà écrit pour ce chapitre, disponible en attendant la vidéo.",
    "video_script": None,
    "written_complement": None,
}

# Cas d'un chapitre 100% vidéo généré nativement par le Bloc 2 (pas de lesson_script, seulement un
# court complément) — robustesse : ne doit jamais laisser la zone de texte totalement vide.
VIDEO_CHAPTER_COMPLEMENT_ONLY = {
    **COMMON_CHAPTER_FIELDS,
    "format": "video",
    "lesson_script": None,
    "video_script": {
        "summary": "La vidéo montre la création d'un workflow de bout en bout.",
        "scenes": [
            {"beat": "Ouverture n8n", "narration": "On ouvre l'éditeur.", "visual": "Capture de l'interface."},
            {"beat": "Ajout d'un node", "narration": "On glisse un node HTTP.", "visual": "Glisser-déposer."},
        ],
    },
    "written_complement": "Point de vigilance non montré à l'écran : bien nommer ses credentials.",
}

MIX_CHAPTER = {
    **COMMON_CHAPTER_FIELDS,
    "format": "mix",
    "lesson_script": "Texte de référence complémentaire, pas montré dans la vidéo.",
    "video_script": {
        "summary": "La vidéo montre la démo visuelle.",
        "scenes": [{"beat": "Démo", "narration": "On observe le résultat.", "visual": "Écran du résultat."}],
    },
    "written_complement": None,
}

COURSE = {"chapters": [TEXT_CHAPTER, VIDEO_CHAPTER_WITH_FULL_TEXT, MIX_CHAPTER]}

RENDER_KWARGS = dict(
    prev_number=1,
    next_number=3,
    max_corrections=3,
    max_answer_length=2000,
    max_practical_length=5000,
    accepted_upload_extensions=".png,.pdf",
)


def _render(chapter):
    app = create_app()
    with app.test_request_context():
        return render_template("chapter.html", course=COURSE, chapter=chapter, **RENDER_KWARGS)


def test_text_format_renders_lesson_paragraphs_and_no_video_box_at_all():
    """Un chapitre 'text' n'a AUCUNE vidéo prévue — aucun encadré vidéo, ni le nouveau placeholder
    "vidéo à venir" ni l'ancien message générique "bientôt disponible", ne doit s'afficher."""
    html = _render(TEXT_CHAPTER)
    assert "Premier paragraphe du texte." in html
    assert "Deuxième paragraphe du texte." in html
    assert "video-placeholder" not in html
    assert "video-script-preview" not in html
    assert "video-missing" not in html
    assert "bientôt disponible" not in html
    assert "<video" not in html


def test_video_format_with_full_existing_text_shows_the_full_lesson_not_just_a_complement():
    """Cas retrofit cours 1 : un chapitre 'video' dont le contenu écrit existe déjà en entier doit
    l'afficher intégralement, jamais un résumé court — 'jamais laisser l'apprenant sans rien'."""
    html = _render(VIDEO_CHAPTER_WITH_FULL_TEXT)
    assert "Texte complet déjà écrit pour ce chapitre, disponible en attendant la vidéo." in html


def test_video_and_mix_formats_show_an_honest_reassuring_placeholder_not_an_empty_box():
    for chapter in (VIDEO_CHAPTER_WITH_FULL_TEXT, MIX_CHAPTER):
        html = _render(chapter)
        assert "video-placeholder" in html
        assert "Vidéo à venir" in html
        assert "La vidéo de ce chapitre arrive prochainement" in html
        assert "couvre l'intégralité du sujet" in html
        assert "<video" not in html


def test_video_format_without_lesson_script_falls_back_to_written_complement():
    """Robustesse : un chapitre 100% vidéo généré nativement (pas de lesson_script) doit quand même
    afficher son written_complement, jamais une zone de texte vide."""
    html = _render(VIDEO_CHAPTER_COMPLEMENT_ONLY)
    assert "video-script-preview" in html
    assert "Ouverture n8n" in html
    assert '<p class="written-complement">' in html
    assert "bien nommer ses credentials" in html


def test_mix_format_renders_both_video_script_preview_and_complementary_lesson_text():
    html = _render(MIX_CHAPTER)
    assert "video-script-preview" in html
    assert "Démo" in html
    assert "Texte de référence complémentaire, pas montré dans la vidéo." in html


def test_all_formats_still_render_exercises_section():
    """Constante non négociable : les exercices sont toujours présents, quel que soit le format."""
    for chapter in (TEXT_CHAPTER, VIDEO_CHAPTER_WITH_FULL_TEXT, VIDEO_CHAPTER_COMPLEMENT_ONLY, MIX_CHAPTER):
        html = _render(chapter)
        assert "Une question ?" in html
        assert "selectMcqOption" in html
        assert "Exo" in html  # titre de l'exercice pratique
        assert "Fais ceci." in html


def test_chapter_with_real_video_asset_shows_video_regardless_of_format():
    chapter_with_asset = {**VIDEO_CHAPTER_WITH_FULL_TEXT, "has_video": True}
    html = _render(chapter_with_asset)
    assert "<video" in html
    assert "video-placeholder" not in html
