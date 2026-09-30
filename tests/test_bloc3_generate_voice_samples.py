from bloc3_video_production.generate_voice_samples import select_excerpt

LESSON_SCRIPT = (
    "Premier paragraphe d'introduction.\n\n"
    "Deuxieme paragraphe avec des chiffres.\n\n"
    "Troisieme paragraphe. Il a plusieurs phrases. En voici une troisieme. Et une quatrieme.\n\n"
    "Quatrieme paragraphe final."
)


def test_select_excerpt_picks_requested_paragraph_and_sentence_count():
    excerpt = select_excerpt(LESSON_SCRIPT, paragraph_index=2, num_sentences=2)
    assert excerpt == "Troisieme paragraphe. Il a plusieurs phrases."


def test_select_excerpt_defaults_match_module_constants():
    excerpt = select_excerpt(LESSON_SCRIPT)
    assert excerpt.startswith("Troisieme paragraphe.")
