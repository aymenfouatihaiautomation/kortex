from unittest.mock import patch

from bloc6_chatbot.general_bot import (
    GENERAL_CHAT_MODEL,
    PERSONA_PROMPT,
    WEB_SEARCH_TOOLS,
    answer_general_chat,
    build_system_blocks,
)

COURSE = {
    "title": "Agents IA en production",
    "slug": "agents-ia-en-production",
    "level": "intermédiaire",
    "prerequisites": "Savoir construire un agent LLM basique.",
    "description": "Gérer les erreurs, évaluer et déployer sans risque.",
    "chapters": [{"number": 1, "title": "Pourquoi les agents IA échouent en production"}],
}


# --- persona / garde-fous anti-injection et anti-invention -----------------------------------


def test_persona_prompt_forbids_inventing_courses_not_in_catalog():
    assert "n'inventes JAMAIS" in PERSONA_PROMPT or "n'invente" in PERSONA_PROMPT.lower()


def test_persona_prompt_forbids_teaching_paid_content_in_depth():
    lowered = PERSONA_PROMPT.lower()
    assert "contenu payant" in lowered


def test_persona_prompt_treats_user_messages_as_data_not_instructions():
    lowered = PERSONA_PROMPT.lower()
    assert "donnée" in lowered
    assert "jamais" in lowered
    assert "instruction" in lowered


def test_persona_prompt_instructs_honesty_when_information_is_missing():
    assert "je n'ai pas cette information" in PERSONA_PROMPT.lower()


def test_persona_prompt_forbids_inventing_statistics():
    # Régression constatée en test réel (2026-08-08) : sans cette règle explicite, le modèle a
    # inventé une statistique ("78% des formations...") comme argument commercial, alors qu'elle
    # ne venait ni du catalogue ni d'une recherche web.
    lowered = PERSONA_PROMPT.lower()
    assert "statistique" in lowered or "chiffre" in lowered
    assert "n'invente jamais" in lowered or "jamais un chiffre" in lowered


def test_persona_prompt_requires_relative_course_links_without_inventing_a_domain():
    # Régression constatée en test réel (2026-08-08) : sans cette règle, le modèle a renvoyé un
    # lien vers un nom de domaine inventé au lieu du chemin relatif /cours/<slug>.
    lowered = PERSONA_PROMPT.lower()
    assert "chemin relatif" in lowered
    assert "domaine" in lowered


def test_persona_prompt_is_in_french():
    assert "Tu es" in PERSONA_PROMPT


# --- build_system_blocks : placement du cache_control ------------------------------------------


def test_build_system_blocks_puts_cache_control_on_the_catalog_block():
    blocks = build_system_blocks("Catalogue.", "")
    cached_blocks = [b for b in blocks if "cache_control" in b]
    assert len(cached_blocks) == 1
    assert "Catalogue." in cached_blocks[0]["text"]


def test_build_system_blocks_keeps_price_block_after_the_cache_breakpoint_uncached():
    blocks = build_system_blocks("Catalogue.", "Prix actuels :\n- Cours : $15.00")
    price_blocks = [b for b in blocks if "Prix actuels" in b["text"]]
    assert len(price_blocks) == 1
    assert "cache_control" not in price_blocks[0]
    # Le bloc prix doit être positionné APRÈS le bloc catalogue (mis en cache), pas avant.
    catalog_index = next(i for i, b in enumerate(blocks) if "cache_control" in b)
    price_index = next(i for i, b in enumerate(blocks) if "Prix actuels" in b["text"])
    assert price_index > catalog_index


def test_build_system_blocks_omits_price_block_when_empty():
    blocks = build_system_blocks("Catalogue.", "")
    assert all("Prix actuels" not in b["text"] for b in blocks)


def test_build_system_blocks_includes_the_persona():
    blocks = build_system_blocks("Catalogue.", "")
    assert any(b["text"] == PERSONA_PROMPT for b in blocks)


# --- answer_general_chat : câblage vers call_chat_api -------------------------------------------


@patch("bloc6_chatbot.general_bot.get_current_price_usd", return_value=15.0)
@patch("bloc6_chatbot.general_bot.call_chat_api")
def test_answer_general_chat_uses_the_haiku_model(mock_call_chat_api, mock_price):
    mock_call_chat_api.return_value = "Réponse."
    answer_general_chat([{"role": "user", "content": "Bonjour"}], [COURSE])

    assert mock_call_chat_api.call_args.kwargs["model"] == GENERAL_CHAT_MODEL
    assert "haiku" in GENERAL_CHAT_MODEL.lower()


@patch("bloc6_chatbot.general_bot.get_current_price_usd", return_value=15.0)
@patch("bloc6_chatbot.general_bot.call_chat_api")
def test_answer_general_chat_passes_the_web_search_tool(mock_call_chat_api, mock_price):
    mock_call_chat_api.return_value = "Réponse."
    answer_general_chat([{"role": "user", "content": "Bonjour"}], [COURSE])

    assert mock_call_chat_api.call_args.kwargs["tools"] == WEB_SEARCH_TOOLS


@patch("bloc6_chatbot.general_bot.get_current_price_usd", return_value=15.0)
@patch("bloc6_chatbot.general_bot.call_chat_api")
def test_answer_general_chat_forwards_messages_untouched(mock_call_chat_api, mock_price):
    mock_call_chat_api.return_value = "Réponse."
    messages = [{"role": "user", "content": "Bonjour"}]
    answer_general_chat(messages, [COURSE])

    assert mock_call_chat_api.call_args.kwargs["messages"] == messages


@patch("bloc6_chatbot.general_bot.get_current_price_usd", return_value=15.0)
@patch("bloc6_chatbot.general_bot.call_chat_api")
def test_answer_general_chat_includes_course_in_system_blocks(mock_call_chat_api, mock_price):
    mock_call_chat_api.return_value = "Réponse."
    answer_general_chat([{"role": "user", "content": "Bonjour"}], [COURSE])

    system_blocks = mock_call_chat_api.call_args.kwargs["system_blocks"]
    joined = "\n".join(b["text"] for b in system_blocks)
    assert COURSE["title"] in joined
    assert "$15.00" in joined


@patch("bloc6_chatbot.general_bot.get_current_price_usd", return_value=15.0)
@patch("bloc6_chatbot.general_bot.call_chat_api")
def test_answer_general_chat_passes_the_tracker_through(mock_call_chat_api, mock_price):
    from common.llm_client import CostTracker

    mock_call_chat_api.return_value = "Réponse."
    tracker = CostTracker(label="test")
    answer_general_chat([{"role": "user", "content": "Bonjour"}], [COURSE], tracker=tracker)

    assert mock_call_chat_api.call_args.kwargs["tracker"] is tracker
