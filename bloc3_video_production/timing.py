"""Bloc 3 — Calcule à quelle frame chaque élément visuel d'une diapositive doit apparaître,
à partir de l'alignement caractère->temps retourné par la synthèse vocale (`tts.py`).

Le titre visuel (texte nouveau, pas issu de la narration) apparaît toujours en tout début de
diapositive. Chaque terme clé / chiffre clé (extraits verbatim de la narration par `slides.py`)
apparaît au moment où il est réellement prononcé, repéré par sa position dans `narration_text`.
"""

from bloc3_video_production.config import FPS


def seconds_to_frames(seconds: float) -> int:
    return max(round(seconds * FPS), 0)


def _find_start_time(term: str, narration_text: str, character_start_times: list[float]) -> float:
    if not character_start_times:
        return 0.0
    idx = narration_text.find(term)
    if idx == -1:
        idx = narration_text.lower().find(term.lower())
    if idx == -1:
        return 0.0
    idx = min(idx, len(character_start_times) - 1)
    return character_start_times[idx]


def compute_element_start_frames(
    narration_text: str,
    key_terms: list[str],
    key_numbers: list[str],
    character_start_times: list[float],
) -> tuple[list[int], list[int]]:
    """Retourne (frames de départ des key_terms, frames de départ des key_numbers), dans le même
    ordre que les listes d'entrée, relatives au début de la diapositive."""
    term_frames = [
        seconds_to_frames(_find_start_time(term, narration_text, character_start_times))
        for term in key_terms
    ]
    number_frames = [
        seconds_to_frames(_find_start_time(number, narration_text, character_start_times))
        for number in key_numbers
    ]
    return term_frames, number_frames


def approximate_uniform_start_frames(
    count: int,
    duration_in_frames: int,
    start_fraction: float = 0.1,
    end_fraction: float = 0.75,
) -> list[int]:
    """Répartit `count` instants d'apparition uniformément entre `start_fraction` et
    `end_fraction` de `duration_in_frames` — utilisé quand aucun alignement réel n'est disponible
    (ex. réutilisation d'un audio généré avant l'intégration de l'alignement ElevenLabs)."""
    if count <= 0:
        return []
    if count == 1:
        return [round(duration_in_frames * start_fraction)]
    return [
        round(duration_in_frames * (start_fraction + (end_fraction - start_fraction) * i / (count - 1)))
        for i in range(count)
    ]
