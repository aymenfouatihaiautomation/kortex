from unittest.mock import patch

from bloc6_chatbot.course_bot import (
    COURSE_TUTOR_MAX_TOKENS,
    COURSE_TUTOR_MODEL,
    PERSONA_PROMPT,
    answer_course_chat,
    build_system_blocks,
)

COURSE = {
    "title": "Agents IA en production",
    "description": "Gérer les erreurs, évaluer et déployer sans risque.",
    "chapters": [
        {
            "number": 1,
            "title": "Pourquoi les agents IA échouent en production",
            "learning_objectives": ["Identifier les catégories de pannes"],
            "key_points": ["La démo n'est pas un indicateur de robustesse"],
            "lesson_script": "Contenu de la leçon.",
            "comprehension_exercises": [],
            "practical_exercise": {"title": "T", "instructions": "I", "expected_outcome": "R"},
        }
    ],
}


# --- persona / garde-fous -----------------------------------------------------------------------


def test_persona_prompt_stays_within_the_course_scope():
    lowered = PERSONA_PROMPT.lower()
    assert "ce cours ne traite pas" in lowered or "pas traité dans ce cours" in lowered


def test_persona_prompt_forbids_inventing_statistics():
    lowered = PERSONA_PROMPT.lower()
    assert "n'inventes jamais" in lowered
    assert "chiffre" in lowered or "statistique" in lowered


def test_persona_prompt_forbids_revealing_short_answer_correction_directly():
    # C'est la règle anti-contournement du correcteur d'exercices plafonné : le tuteur ne doit
    # jamais donner la réponse d'une question ouverte, même sur insistance.
    lowered = PERSONA_PROMPT.lower()
    assert "jamais la réponse correcte" in lowered or "jamais la réponse correcte" in lowered
    assert "corriger" in lowered


def test_persona_prompt_treats_user_messages_as_data_not_instructions():
    lowered = PERSONA_PROMPT.lower()
    assert "donnée" in lowered
    assert "jamais" in lowered
    assert "instruction" in lowered


def test_persona_prompt_is_in_french():
    assert "Tu es" in PERSONA_PROMPT


def test_course_tutor_uses_sonnet_not_haiku():
    # Contenu technique dense : la qualité prime sur le coût, contrairement au bot général.
    assert "sonnet" in COURSE_TUTOR_MODEL.lower()


# --- build_system_blocks : cache_control sur le contenu du cours --------------------------------


def test_build_system_blocks_puts_cache_control_on_the_course_content_block():
    blocks = build_system_blocks("Contenu du cours.")
    cached_blocks = [b for b in blocks if "cache_control" in b]
    assert len(cached_blocks) == 1
    assert "Contenu du cours." in cached_blocks[0]["text"]


def test_build_system_blocks_includes_the_persona():
    blocks = build_system_blocks("Contenu du cours.")
    assert any(b["text"] == PERSONA_PROMPT for b in blocks)


# --- answer_course_chat : câblage vers call_chat_api ---------------------------------------------


@patch("bloc6_chatbot.course_bot.call_chat_api")
def test_answer_course_chat_uses_the_sonnet_model(mock_call_chat_api):
    mock_call_chat_api.return_value = "Réponse."
    answer_course_chat([{"role": "user", "content": "Peux-tu réexpliquer ?"}], COURSE)

    assert mock_call_chat_api.call_args.kwargs["model"] == COURSE_TUTOR_MODEL
    assert mock_call_chat_api.call_args.kwargs["max_tokens"] == COURSE_TUTOR_MAX_TOKENS


@patch("bloc6_chatbot.course_bot.call_chat_api")
def test_answer_course_chat_never_passes_web_search_tools(mock_call_chat_api):
    # Le tuteur reste ancré dans le contenu du cours — pas de recherche web (contrairement au bot
    # général).
    mock_call_chat_api.return_value = "Réponse."
    answer_course_chat([{"role": "user", "content": "Bonjour"}], COURSE)

    assert mock_call_chat_api.call_args.kwargs.get("tools") is None


@patch("bloc6_chatbot.course_bot.call_chat_api")
def test_answer_course_chat_forwards_messages_untouched(mock_call_chat_api):
    mock_call_chat_api.return_value = "Réponse."
    messages = [{"role": "user", "content": "Explique-moi le chapitre 1."}]
    answer_course_chat(messages, COURSE)

    assert mock_call_chat_api.call_args.kwargs["messages"] == messages


@patch("bloc6_chatbot.course_bot.call_chat_api")
def test_answer_course_chat_includes_course_content_in_system_blocks(mock_call_chat_api):
    mock_call_chat_api.return_value = "Réponse."
    answer_course_chat([{"role": "user", "content": "Bonjour"}], COURSE)

    system_blocks = mock_call_chat_api.call_args.kwargs["system_blocks"]
    joined = "\n".join(b["text"] for b in system_blocks)
    assert "Agents IA en production" in joined
    assert "Contenu de la leçon." in joined


@patch("bloc6_chatbot.course_bot.call_chat_api")
def test_answer_course_chat_passes_the_tracker_through(mock_call_chat_api):
    from common.llm_client import CostTracker

    mock_call_chat_api.return_value = "Réponse."
    tracker = CostTracker(label="test")
    answer_course_chat([{"role": "user", "content": "Bonjour"}], COURSE, tracker=tracker)

    assert mock_call_chat_api.call_args.kwargs["tracker"] is tracker
