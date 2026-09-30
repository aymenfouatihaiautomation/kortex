from unittest.mock import patch

from bloc3_video_production.produce_video import (
    build_manifest,
    manifest_to_markdown,
    produce_chapter_video,
)

CHAPTER_CONTENT = {
    "chapter_number": 1,
    "chapter_title": "Pourquoi les agents IA échouent",
    "lesson_script": "Un agent IA doit gérer les erreurs. C'est essentiel en production.",
}

FAKE_SLIDES = [
    {"slide_number": 1, "narration_text": "Un agent IA doit gérer les erreurs.", "visual_title": "Intro", "key_terms": ["agent"], "key_numbers": []},
    {"slide_number": 2, "narration_text": "C'est essentiel en production.", "visual_title": "Production", "key_terms": [], "key_numbers": []},
]


@patch("bloc3_video_production.produce_video.render_chapter_video")
@patch("bloc3_video_production.produce_video.synthesize_slide_audio")
@patch("bloc3_video_production.produce_video.build_slides")
def test_produce_chapter_video_wires_slides_tts_and_render(mock_build_slides, mock_tts, mock_render, tmp_path):
    mock_build_slides.return_value = FAKE_SLIDES
    mock_tts.return_value = {"duration_seconds": 3.0, "character_start_times": [0.0, 0.1, 0.2]}
    mock_render.return_value = 6.0

    with patch("bloc3_video_production.produce_video.VIDEO_OUTPUT_DIR", tmp_path), \
         patch("bloc3_video_production.produce_video.WORK_AUDIO_DIR", tmp_path / "_audio_work"):
        entry = produce_chapter_video(CHAPTER_CONTENT, demo=True)

    assert entry["chapter_number"] == 1
    assert entry["num_slides"] == 2
    assert entry["duration_seconds"] == 6.0
    assert mock_tts.call_count == 2
    mock_render.assert_called_once()
    render_call_args = mock_render.call_args[0]
    assert render_call_args[0] == 1
    slides_with_audio = render_call_args[2]
    assert len(slides_with_audio) == 2
    # "agent" est à l'index 3 dans "Un agent IA...", hors bornes de character_start_times (3
    # valeurs) -> clampé au dernier index disponible (0.2s -> frame 6 à 30fps).
    assert slides_with_audio[0]["key_terms"] == [{"text": "agent", "start_frame": 6}]
    assert slides_with_audio[0]["duration_seconds"] == 3.0


def test_build_manifest_sorts_by_chapter_number():
    entries = [
        {"chapter_number": 2, "chapter_title": "B", "video_file": "b.mp4", "duration_seconds": 5.0, "num_slides": 3},
        {"chapter_number": 1, "chapter_title": "A", "video_file": "a.mp4", "duration_seconds": 4.0, "num_slides": 2},
    ]
    manifest = build_manifest("Cours test", "AI Automation", entries)
    assert [v["chapter_number"] for v in manifest["videos"]] == [1, 2]
    assert "voice" in manifest


def test_manifest_to_markdown_renders_table():
    manifest = build_manifest(
        "Cours test", "AI Automation",
        [{"chapter_number": 1, "chapter_title": "Intro", "video_file": "chapter_1.mp4", "duration_seconds": 125.0, "num_slides": 4}],
    )
    md = manifest_to_markdown(manifest)
    assert "chapter_1.mp4" in md
    assert "2:05" in md
