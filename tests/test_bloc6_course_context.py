from bloc6_chatbot.course_context import build_course_content_context

BASE_CHAPTER = {
    "number": 1,
    "title": "Pourquoi les agents IA échouent en production",
    "learning_objectives": ["Identifier les catégories de pannes"],
    "key_points": ["La démo n'est pas un indicateur de robustesse"],
    "comprehension_exercises": [
        {
            "question": "Qu'est-ce qu'un timeout ?",
            "type": "mcq",
            "options": ["Une erreur réseau", "Une réponse trop lente", "Un bug de code"],
            "correct_answer": "Une réponse trop lente",
        },
        {
            "question": "Explique pourquoi un agent peut halluciner un appel d'outil.",
            "type": "short_answer",
            "correct_answer": "Parce que le modèle génère un nom de fonction plausible mais inexistant.",
        },
    ],
    "practical_exercise": {
        "title": "Diagnostiquer une panne",
        "instructions": "Analyse les logs fournis.",
        "expected_outcome": "Un rapport identifiant la cause racine.",
    },
}


def _course(chapters):
    return {
        "title": "Agents IA en production",
        "description": "Gérer les erreurs, évaluer et déployer sans risque.",
        "chapters": chapters,
    }


def test_build_course_content_context_includes_course_title_and_description():
    context = build_course_content_context(_course([BASE_CHAPTER]))
    assert "Agents IA en production" in context
    assert "Gérer les erreurs" in context


def test_build_course_content_context_includes_chapter_metadata():
    context = build_course_content_context(_course([BASE_CHAPTER]))
    assert "Pourquoi les agents IA échouent en production" in context
    assert "Identifier les catégories de pannes" in context
    assert "La démo n'est pas un indicateur de robustesse" in context


def test_build_course_content_context_never_leaks_short_answer_correct_answer():
    # Garde-fou anti-contournement : le corrigé d'une question ouverte ne doit JAMAIS apparaître
    # dans le contexte du tuteur — c'est le seul corrigé jamais montré à l'apprenant sur la page.
    context = build_course_content_context(_course([BASE_CHAPTER]))
    assert "Parce que le modèle génère un nom de fonction plausible mais inexistant" not in context


def test_build_course_content_context_includes_short_answer_question_text():
    # La question elle-même (sans le corrigé) reste utile au tuteur pour en discuter.
    context = build_course_content_context(_course([BASE_CHAPTER]))
    assert "Explique pourquoi un agent peut halluciner un appel d'outil" in context


def test_build_course_content_context_includes_mcq_options():
    # Le corrigé d'un QCM n'est pas un secret (déjà dans le DOM une fois répondu) — les options
    # peuvent donc apparaître sans risque.
    context = build_course_content_context(_course([BASE_CHAPTER]))
    assert "Une réponse trop lente" in context


def test_build_course_content_context_includes_practical_exercise_expected_outcome():
    # Déjà affiché en clair sur la page — pas un secret, contrairement au corrigé short_answer.
    context = build_course_content_context(_course([BASE_CHAPTER]))
    assert "Un rapport identifiant la cause racine" in context


def test_build_course_content_context_uses_lesson_script_when_present():
    chapter = dict(BASE_CHAPTER, lesson_script="Voici le contenu détaillé de la leçon sur les pannes.")
    context = build_course_content_context(_course([chapter]))
    assert "Voici le contenu détaillé de la leçon sur les pannes." in context


def test_build_course_content_context_falls_back_to_written_complement_and_video_narration():
    chapter = dict(
        BASE_CHAPTER,
        lesson_script=None,
        written_complement="Complément écrit du chapitre.",
        video_script={
            "summary": "Résumé de la vidéo.",
            "scenes": [{"beat": "intro", "narration": "Narration de la première scène."}],
        },
    )
    context = build_course_content_context(_course([chapter]))
    assert "Complément écrit du chapitre." in context
    assert "Résumé de la vidéo." in context
    assert "Narration de la première scène." in context


def test_build_course_content_context_prioritizes_content_blocks_over_lesson_script():
    chapter = dict(
        BASE_CHAPTER,
        lesson_script="Contenu brut non enrichi.",
        content_blocks=[{"type": "paragraph", "text": "Contenu enrichi prioritaire."}],
    )
    context = build_course_content_context(_course([chapter]))
    assert "Contenu enrichi prioritaire." in context
    assert "Contenu brut non enrichi." not in context


def test_build_course_content_context_flattens_callout_and_code_blocks():
    chapter = dict(
        BASE_CHAPTER,
        lesson_script=None,
        content_blocks=[
            {"type": "callout", "style": "warning", "title": "Attention", "text": "Ne jamais ignorer un rate limit."},
            {"type": "code", "code": "retry(max_attempts=3)"},
            {"type": "list", "style": "bullet", "items": ["Point A", "Point B"]},
        ],
    )
    context = build_course_content_context(_course([chapter]))
    assert "Attention" in context
    assert "Ne jamais ignorer un rate limit." in context
    assert "retry(max_attempts=3)" in context
    assert "Point A" in context
    assert "Point B" in context


def test_build_course_content_context_flattens_architecture_diagram():
    chapter = dict(
        BASE_CHAPTER,
        lesson_script=None,
        content_blocks=[
            {
                "type": "diagram",
                "diagram_type": "architecture",
                "title": "Architecture de l'agent",
                "hub": {"label": "Orchestrateur", "description": "Coordonne les appels"},
                "satellites": [{"label": "Outil de recherche", "description": "Appelle une API externe"}],
            }
        ],
    )
    context = build_course_content_context(_course([chapter]))
    assert "Orchestrateur" in context
    assert "Outil de recherche" in context


def test_build_course_content_context_flattens_comparison_diagram():
    chapter = dict(
        BASE_CHAPTER,
        lesson_script=None,
        content_blocks=[
            {
                "type": "diagram",
                "diagram_type": "comparison",
                "title": "Prototype vs Production",
                "left": {"label": "Prototype", "points": ["Un seul utilisateur"]},
                "right": {"label": "Production", "points": ["Des milliers de requêtes"]},
            }
        ],
    )
    context = build_course_content_context(_course([chapter]))
    assert "Un seul utilisateur" in context
    assert "Des milliers de requêtes" in context


def test_build_course_content_context_handles_multiple_chapters():
    chapter2 = dict(BASE_CHAPTER, number=2, title="Observabilité et logs")
    context = build_course_content_context(_course([BASE_CHAPTER, chapter2]))
    assert "Pourquoi les agents IA échouent en production" in context
    assert "Observabilité et logs" in context
