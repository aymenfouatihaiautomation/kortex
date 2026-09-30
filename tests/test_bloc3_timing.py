from bloc3_video_production.config import FPS
from bloc3_video_production.timing import (
    approximate_uniform_start_frames,
    compute_element_start_frames,
    seconds_to_frames,
)

NARRATION = "Le rate limit et le timeout sont deux pannes reseau frequentes."
# index of "rate limit" = 3, "timeout" = 21 (approx, verified via find in test)


def test_seconds_to_frames_rounds_and_floors_at_zero():
    assert seconds_to_frames(1.0) == FPS
    assert seconds_to_frames(0.0) == 0
    assert seconds_to_frames(-1.0) == 0


def test_compute_element_start_frames_matches_character_position():
    char_times = [i * 0.1 for i in range(len(NARRATION))]  # 0.1s par caractère

    term_frames, number_frames = compute_element_start_frames(
        NARRATION, ["rate limit", "timeout"], [], char_times
    )

    idx_rate_limit = NARRATION.find("rate limit")
    idx_timeout = NARRATION.find("timeout")
    assert term_frames[0] == seconds_to_frames(char_times[idx_rate_limit])
    assert term_frames[1] == seconds_to_frames(char_times[idx_timeout])
    assert number_frames == []


def test_compute_element_start_frames_falls_back_to_zero_when_not_found():
    term_frames, _ = compute_element_start_frames(NARRATION, ["mot absent"], [], [0.0, 0.1, 0.2])
    assert term_frames == [0]


def test_compute_element_start_frames_handles_empty_alignment():
    term_frames, number_frames = compute_element_start_frames(NARRATION, ["timeout"], ["42"], [])
    assert term_frames == [0]
    assert number_frames == [0]


def test_compute_element_start_frames_is_case_insensitive_fallback():
    char_times = [i * 0.1 for i in range(len(NARRATION))]
    term_frames, _ = compute_element_start_frames(NARRATION, ["RATE LIMIT"], [], char_times)
    idx = NARRATION.lower().find("rate limit")
    assert term_frames[0] == seconds_to_frames(char_times[idx])


def test_approximate_uniform_start_frames_empty():
    assert approximate_uniform_start_frames(0, 100) == []


def test_approximate_uniform_start_frames_single_uses_start_fraction():
    assert approximate_uniform_start_frames(1, 100, start_fraction=0.2) == [20]


def test_approximate_uniform_start_frames_spreads_evenly_between_fractions():
    frames = approximate_uniform_start_frames(3, 100, start_fraction=0.1, end_fraction=0.7)
    assert frames == [10, 40, 70]
    assert frames == sorted(frames)


def test_approximate_uniform_start_frames_stays_within_bounds():
    frames = approximate_uniform_start_frames(5, 90)
    assert all(0 <= f <= 90 for f in frames)
    assert frames == sorted(frames)
