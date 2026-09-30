"""Bloc 3 — Synthèse vocale (ElevenLabs) pour la narration de chaque diapositive.

Une voix unique et fixe (`config.VOICE_ID`) est réutilisée pour toutes les diapositives et tous
les chapitres, pour une narration cohérente sur l'ensemble du cours.

Utilise l'endpoint `with-timestamps` d'ElevenLabs (alignement caractère par caractère), pas le
endpoint TTS simple : le Bloc 3 en a besoin pour synchroniser l'apparition des éléments visuels
(titre, termes clés, chiffres) avec le moment réel où ils sont prononcés (voir `timing.py`).
"""

import base64
import struct
import wave
from pathlib import Path

import requests
from mutagen import File as MutagenFile

from bloc3_video_production.config import (
    DEMO_WORDS_PER_SECOND,
    ELEVENLABS_API_KEY,
    ELEVENLABS_MODEL_ID,
    VOICE_ID,
)

ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"


class TTSError(RuntimeError):
    """Levée quand la synthèse vocale échoue (clé manquante, erreur API, etc.)."""


def get_audio_duration_seconds(path: Path) -> float:
    audio = MutagenFile(path)
    if audio is None or audio.info is None:
        raise TTSError(f"Impossible de lire la durée du fichier audio : {path}")
    return audio.info.length


def _write_silent_wav(path: Path, duration_seconds: float, framerate: int = 44100) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    n_frames = max(int(framerate * duration_seconds), 1)
    with wave.open(str(path), "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(framerate)
        f.writeframes(struct.pack("<h", 0) * n_frames)


def _fabricate_alignment(text: str, duration_seconds: float) -> list[float]:
    """Alignement caractère->temps approximatif (rythme uniforme), utilisé UNIQUEMENT en mode
    démo, où aucun appel ElevenLabs réel n'a lieu."""
    n = len(text)
    if n == 0:
        return []
    return [i / n * duration_seconds for i in range(n)]


def synthesize_slide_audio(
    text: str, output_path: Path, demo: bool = False, voice_id: str | None = None
) -> dict:
    """Synthétise la narration d'une diapositive, écrit le fichier audio à `output_path`, et
    retourne `{"duration_seconds": float, "character_start_times": list[float]}` — le second
    champ permet de savoir à quel moment (en secondes depuis le début de la diapositive) chaque
    caractère du texte est prononcé, pour synchroniser les animations visuelles."""
    voice_id = voice_id or VOICE_ID

    if demo:
        # Plafonnée volontairement courte : le mode démo valide le câblage du pipeline, pas le
        # rythme réel de narration — une durée réaliste rendrait le rendu Remotion très long pour
        # un chapitre entier sans apporter d'information supplémentaire.
        word_count = len(text.split())
        duration = min(max(word_count / DEMO_WORDS_PER_SECOND, 0.5), 2.0)
        _write_silent_wav(output_path, duration)
        return {"duration_seconds": duration, "character_start_times": _fabricate_alignment(text, duration)}

    if not ELEVENLABS_API_KEY:
        raise TTSError(
            "ELEVENLABS_API_KEY absent — impossible de synthétiser de la voix réelle. "
            "Ajoute la clé dans .env, ou utilise --demo pour tester le pipeline sans audio réel."
        )

    response = requests.post(
        ELEVENLABS_TTS_URL.format(voice_id=voice_id),
        headers={"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"},
        json={"text": text, "model_id": ELEVENLABS_MODEL_ID},
        timeout=60,
    )
    if response.status_code != 200:
        raise TTSError(f"Échec ElevenLabs ({response.status_code}) : {response.text[:500]}")

    payload = response.json()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(base64.b64decode(payload["audio_base64"]))

    return {
        "duration_seconds": get_audio_duration_seconds(output_path),
        "character_start_times": payload["alignment"]["character_start_times_seconds"],
    }
