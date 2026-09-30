from bloc6_chatbot.catalog_context import build_catalog_context, build_price_context

COURSE = {
    "title": "Agents IA en production",
    "slug": "agents-ia-en-production",
    "level": "intermédiaire",
    "prerequisites": "Savoir construire un agent LLM basique.",
    "description": "Gérer les erreurs, évaluer et déployer sans risque.",
    "chapters": [
        {"number": 1, "title": "Pourquoi les agents IA échouent en production"},
        {"number": 2, "title": "Observabilité et logs"},
    ],
}


def test_build_catalog_context_includes_public_metadata():
    context = build_catalog_context([COURSE])
    assert COURSE["title"] in context
    assert COURSE["slug"] in context
    assert COURSE["level"] in context
    assert COURSE["prerequisites"] in context
    assert COURSE["description"] in context


def test_build_catalog_context_lists_chapter_titles():
    context = build_catalog_context([COURSE])
    assert "Pourquoi les agents IA échouent en production" in context
    assert "Observabilité et logs" in context


def test_build_catalog_context_never_includes_price():
    # Le prix est géré séparément (build_price_context) pour rester en dehors du bloc système mis
    # en cache — voir general_bot.build_system_blocks.
    context = build_catalog_context([COURSE])
    assert "$" not in context


def test_build_catalog_context_handles_multiple_courses():
    other = dict(COURSE, title="Autre cours", slug="autre-cours")
    context = build_catalog_context([COURSE, other])
    assert COURSE["title"] in context
    assert "Autre cours" in context


def test_build_catalog_context_handles_empty_catalog_honestly():
    context = build_catalog_context([])
    assert "catalogue" in context.lower()


def test_build_price_context_includes_price_per_course():
    context = build_price_context([COURSE], 15.0)
    assert "$15.00" in context
    assert COURSE["title"] in context


def test_build_price_context_empty_catalog_returns_empty_string():
    assert build_price_context([], 15.0) == ""
