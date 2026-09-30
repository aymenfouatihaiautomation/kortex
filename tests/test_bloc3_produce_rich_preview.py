from unittest.mock import patch

from bloc3_video_production.produce_rich_preview import (
    assign_visual_durations,
    build_visual_slide_props,
    load_existing_audio_segments,
    produce_rich_preview,
)


def test_assign_visual_durations_is_proportional_to_word_count_and_sums_exactly():
    slides = [
        {"narration_text": "un deux"},  # 2 mots
        {"narration_text": "un deux trois quatre"},  # 4 mots
        {"narration_text": "un deux trois quatre cinq six"},  # 6 mots
    ]
    out = assign_visual_durations(slides, total_duration_frames=120)

    assert sum(s["duration_in_frames"] for s in out) == 120
    assert out[0]["duration_in_frames"] < out[1]["duration_in_frames"] < out[2]["duration_in_frames"]


def test_assign_visual_durations_handles_single_slide():
    out = assign_visual_durations([{"narration_text": "quelques mots ici"}], total_duration_frames=90)
    assert out[0]["duration_in_frames"] == 90


def test_build_visual_slide_props_default_computes_approximate_frames():
    slide = {
        "slide_number": 1, "visual_title": "Intro", "visual_type": "default",
        "duration_in_frames": 100, "key_terms": ["a", "b"], "key_numbers": ["50%"],
    }
    props = build_visual_slide_props(slide)
    assert props["visualType"] == "default"
    assert len(props["keyTerms"]) == 2
    assert len(props["keyNumbers"]) == 1
    assert "diagramHub" not in props
    assert "timelineSteps" not in props


def test_build_visual_slide_props_diagram_passes_structured_content_through():
    slide = {
        "slide_number": 2, "visual_title": "Architecture", "visual_type": "diagram",
        "duration_in_frames": 100,
        "diagram_hub": {"label": "Agent", "icon": "Workflow"},
        "diagram_satellites": [{"label": "Outils", "icon": "Wrench"}, {"label": "LLM", "icon": "Brain"}],
    }
    props = build_visual_slide_props(slide)
    assert props["visualType"] == "diagram"
    assert props["diagramHub"] == {"label": "Agent", "icon": "Workflow"}
    assert len(props["diagramSatellites"]) == 2
    assert "keyTerms" not in props


def test_build_visual_slide_props_timeline_passes_structured_content_through():
    slide = {
        "slide_number": 3, "visual_title": "Chute", "visual_type": "timeline",
        "duration_in_frames": 100,
        "timeline_steps": [{"label": "Test", "icon": "FlaskConical", "number": "10"}],
    }
    props = build_visual_slide_props(slide)
    assert props["visualType"] == "timeline"
    assert props["timelineSteps"][0]["number"] == "10"


@patch("bloc3_video_production.produce_rich_preview.get_audio_duration_seconds")
def test_load_existing_audio_segments_sorts_numerically_and_reads_real_durations(mock_get_duration, tmp_path):
    audio_dir = tmp_path / "chapter_1"
    audio_dir.mkdir()
    for n in [1, 2, 10]:
        (audio_dir / f"slide_{n}.mp3").write_bytes(b"\x00")
    mock_get_duration.side_effect = [1.0, 2.0, 3.0]

    with patch("bloc3_video_production.produce_rich_preview.REMOTION_PUBLIC_AUDIO_DIR", tmp_path):
        segments = load_existing_audio_segments(1)

    # tri numérique (pas lexicographique : slide_2 avant slide_10, pas l'inverse)
    assert [s["file"] for s in segments] == [
        "audio/chapter_1/slide_1.mp3",
        "audio/chapter_1/slide_2.mp3",
        "audio/chapter_1/slide_10.mp3",
    ]


def test_load_existing_audio_segments_raises_if_no_pilot_audio_exists(tmp_path):
    with patch("bloc3_video_production.produce_rich_preview.REMOTION_PUBLIC_AUDIO_DIR", tmp_path):
        try:
            load_existing_audio_segments(1)
            assert False, "devrait lever FileNotFoundError"
        except FileNotFoundError as exc:
            assert "pilote v1" in str(exc)


@patch("bloc3_video_production.produce_rich_preview.render_composition")
@patch("bloc3_video_production.produce_rich_preview.load_existing_audio_segments")
def test_produce_rich_preview_wires_audio_and_visual_slides_end_to_end(mock_load_audio, mock_render):
    mock_load_audio.return_value = [
        {"file": "audio/chapter_1/slide_1.mp3", "duration_in_frames": 60},
        {"file": "audio/chapter_1/slide_2.mp3", "duration_in_frames": 60},
    ]
    chapter_content = {
        "chapter_number": 1,
        "chapter_title": "Titre",
        "lesson_script": "Une phrase simple pour ce test. Une deuxième phrase ici.",
    }

    output_path = produce_rich_preview(chapter_content, demo=True)

    assert output_path.name == "chapter_1_richstyle_preview.mp4"
    mock_render.assert_called_once()
    composition_id, props, called_output_path = mock_render.call_args[0]
    assert composition_id == "ChapterVideoRichPreview"
    assert props["chapterNumber"] == 1
    assert sum(s["durationInFrames"] for s in props["visualSlides"]) == 120
    assert called_output_path == output_path
