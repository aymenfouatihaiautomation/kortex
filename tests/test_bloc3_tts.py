import base64
from unittest.mock import MagicMock, patch

import pytest

from bloc3_video_production.tts import TTSError, get_audio_duration_seconds, synthesize_slide_audio


def test_synthesize_slide_audio_demo_mode_writes_silent_wav(tmp_path):
    output_path = tmp_path / "slide_1.wav"
    result = synthesize_slide_audio("Ceci est un test avec plusieurs mots pour estimer la durée.", output_path, demo=True)

    assert output_path.exists()
    assert result["duration_seconds"] > 0
    assert get_audio_duration_seconds(output_path) == pytest.approx(result["duration_seconds"], abs=0.05)
    assert len(result["character_start_times"]) > 0
    assert result["character_start_times"] == sorted(result["character_start_times"])


def test_synthesize_slide_audio_demo_mode_duration_scales_with_word_count(tmp_path):
    short = synthesize_slide_audio("Un deux trois.", tmp_path / "short.wav", demo=True)
    long = synthesize_slide_audio(" ".join(["mot"] * 50), tmp_path / "long.wav", demo=True)
    assert long["duration_seconds"] > short["duration_seconds"]


@patch("bloc3_video_production.tts.ELEVENLABS_API_KEY", "fake-key")
@patch("bloc3_video_production.tts.requests.post")
def test_synthesize_slide_audio_real_mode_success(mock_post, tmp_path):
    fake_audio = b"\x00" * 100
    mock_response = MagicMock(
        status_code=200,
        json=lambda: {
            "audio_base64": base64.b64encode(fake_audio).decode("ascii"),
            "alignment": {"character_start_times_seconds": [0.0, 0.1, 0.2]},
        },
    )
    mock_post.return_value = mock_response
    output_path = tmp_path / "slide_1.mp3"

    with patch("bloc3_video_production.tts.get_audio_duration_seconds", return_value=3.5):
        result = synthesize_slide_audio("Bonjour", output_path, demo=False)

    assert result == {"duration_seconds": 3.5, "character_start_times": [0.0, 0.1, 0.2]}
    assert output_path.read_bytes() == fake_audio
    mock_post.assert_called_once()
    assert "with-timestamps" in mock_post.call_args[0][0]


@patch("bloc3_video_production.tts.ELEVENLABS_API_KEY", "fake-key")
@patch("bloc3_video_production.tts.requests.post")
def test_synthesize_slide_audio_real_mode_uses_requested_voice_id(mock_post, tmp_path):
    mock_post.return_value = MagicMock(
        status_code=200,
        json=lambda: {
            "audio_base64": base64.b64encode(b"\x00").decode("ascii"),
            "alignment": {"character_start_times_seconds": [0.0]},
        },
    )
    with patch("bloc3_video_production.tts.get_audio_duration_seconds", return_value=1.0):
        synthesize_slide_audio("Bonjour", tmp_path / "slide_1.mp3", demo=False, voice_id="OTHER_VOICE")

    assert "OTHER_VOICE" in mock_post.call_args[0][0]


@patch("bloc3_video_production.tts.ELEVENLABS_API_KEY", "fake-key")
@patch("bloc3_video_production.tts.requests.post")
def test_synthesize_slide_audio_real_mode_http_error_raises(mock_post, tmp_path):
    mock_post.return_value = MagicMock(status_code=401, text="unauthorized")

    with pytest.raises(TTSError, match="401"):
        synthesize_slide_audio("Bonjour", tmp_path / "slide_1.mp3", demo=False)


@patch("bloc3_video_production.tts.ELEVENLABS_API_KEY", None)
def test_synthesize_slide_audio_real_mode_without_key_raises_clear_error(tmp_path):
    with pytest.raises(TTSError, match="ELEVENLABS_API_KEY"):
        synthesize_slide_audio("Bonjour", tmp_path / "slide_1.mp3", demo=False)
