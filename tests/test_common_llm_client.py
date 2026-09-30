from unittest.mock import AsyncMock, patch

import pytest

from common.llm_client import LLMCallError, extract_json, run_prompt


@patch("common.llm_client._run_query", new_callable=AsyncMock)
def test_run_prompt_retries_on_transient_sdk_exception_then_succeeds(mock_run_query):
    # Régression : bug réel rencontré lors d'un run réel prolongé du Bloc 3.5 (2ème cours) —
    # "Claude Code returned an error result: success", une exception transitoire du SDK/CLI sous-
    # jacent, pas une erreur liée au prompt. Un unique nouvel essai a permis de terminer le run.
    mock_run_query.side_effect = [Exception("Claude Code returned an error result: success"), "réponse ok"]

    result = run_prompt("un prompt", retry_delay_seconds=0)

    assert result == "réponse ok"
    assert mock_run_query.call_count == 2


@patch("common.llm_client._run_query", new_callable=AsyncMock)
def test_run_prompt_raises_original_exception_after_exhausting_retries(mock_run_query):
    mock_run_query.side_effect = Exception("erreur persistante")

    with pytest.raises(Exception, match="erreur persistante"):
        run_prompt("un prompt", max_retries=2, retry_delay_seconds=0)

    assert mock_run_query.call_count == 3


@patch("common.llm_client._run_query", new_callable=AsyncMock)
def test_run_prompt_raises_llm_call_error_on_empty_text_without_retrying(mock_run_query):
    mock_run_query.return_value = ""

    with pytest.raises(LLMCallError):
        run_prompt("un prompt")

    assert mock_run_query.call_count == 1


def test_extract_json_handles_markdown_fence():
    text = '```json\n{"a": 1}\n```'
    assert extract_json(text) == {"a": 1}


def test_extract_json_handles_raw_json_without_fence():
    text = 'blabla {"a": 1} blabla'
    assert extract_json(text) == {"a": 1}


def test_extract_json_raises_on_no_json_found():
    with pytest.raises(LLMCallError):
        extract_json("pas de JSON ici")
