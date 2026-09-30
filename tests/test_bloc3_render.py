import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bloc3_video_production.render import RenderError, render_chapter_video


def _make_audio_file(tmp_path, name="slide_1.wav"):
    path = tmp_path / name
    path.write_bytes(b"\x00" * 10)
    return path


@patch("bloc3_video_production.render.subprocess.run")
@patch("bloc3_video_production.render._remotion_binary", return_value="remotion.cmd")
def test_render_chapter_video_success_stages_audio_and_returns_duration(mock_bin, mock_run, tmp_path):
    audio_dir = tmp_path / "remotion_public_audio"
    remotion_dir = tmp_path / "remotion"
    remotion_dir.mkdir()
    source_audio = _make_audio_file(tmp_path)
    captured_props = {}

    def _fake_run(cmd, **kwargs):
        props_arg = next(a for a in cmd if a.startswith("--props="))
        captured_props.update(json.loads(Path(props_arg.split("=", 1)[1]).read_text(encoding="utf-8")))
        return MagicMock(returncode=0, stderr="")

    mock_run.side_effect = _fake_run

    slides_with_audio = [
        {
            "slide_number": 1,
            "visual_title": "Intro",
            "key_terms": [{"text": "agent", "start_frame": 12}],
            "key_numbers": [],
            "audio_path": str(source_audio),
            "duration_seconds": 4.2,
        }
    ]
    output_path = tmp_path / "output" / "chapter_1.mp4"

    with patch("bloc3_video_production.render.REMOTION_PUBLIC_AUDIO_DIR", audio_dir), \
         patch("bloc3_video_production.render.REMOTION_DIR", remotion_dir):
        total_duration = render_chapter_video(1, "Titre", slides_with_audio, output_path)

    assert total_duration == 4.2
    staged_file = audio_dir / "chapter_1" / "slide_1.wav"
    assert staged_file.exists()
    mock_run.assert_called_once()
    props_path = output_path.parent / "_props_chapter_1.json"
    assert not props_path.exists()  # nettoyé après le rendu
    assert captured_props["slides"][0]["keyTerms"] == [{"text": "agent", "startFrame": 12}]


@patch("bloc3_video_production.render.subprocess.run")
@patch("bloc3_video_production.render._remotion_binary", return_value="remotion.cmd")
def test_render_chapter_video_failure_raises_and_cleans_up_props(mock_bin, mock_run, tmp_path):
    audio_dir = tmp_path / "remotion_public_audio"
    remotion_dir = tmp_path / "remotion"
    remotion_dir.mkdir()
    source_audio = _make_audio_file(tmp_path)
    mock_run.return_value = MagicMock(returncode=1, stderr="boom")

    slides_with_audio = [
        {
            "slide_number": 1,
            "visual_title": "Intro",
            "key_terms": [],
            "key_numbers": [],
            "audio_path": str(source_audio),
            "duration_seconds": 2.0,
        }
    ]
    output_path = tmp_path / "output" / "chapter_1.mp4"

    with patch("bloc3_video_production.render.REMOTION_PUBLIC_AUDIO_DIR", audio_dir), \
         patch("bloc3_video_production.render.REMOTION_DIR", remotion_dir):
        with pytest.raises(RenderError, match="boom"):
            render_chapter_video(1, "Titre", slides_with_audio, output_path)

    props_path = output_path.parent / "_props_chapter_1.json"
    assert not props_path.exists()
