"""Bloc 3 — Génère des échantillons audio pour comparer plusieurs voix ElevenLabs.

Utilitaire ponctuel (audio seul, pas de vidéo) pour choisir la voix définitive avant de produire
un pilote complet. Réutilise `tts.synthesize_slide_audio` avec un `voice_id` différent par
échantillon — même mécanisme que la production réelle, donc représentatif.
"""

import argparse
import json
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bloc3_video_production.config import DEFAULT_CONTENT_FILE, VIDEO_OUTPUT_DIR
from bloc3_video_production.slides import split_sentences
from bloc3_video_production.tts import synthesize_slide_audio

SAMPLES_DIR = VIDEO_OUTPUT_DIR / "voice_samples"

# Voix premade du compte jugées adaptées à une narration éducative en français (testées via
# GET /v1/voices) : Alice (déjà utilisée au pilote v1), plus deux alternatives pour comparaison.
VOICES_TO_TEST = [
    {"voice_id": "Xb7hH8MSUJpSbSDYk0k2", "name": "alice", "label": "Alice - Clear, Engaging Educator"},
    {"voice_id": "XrExE9yKIg1WjnnlVkGX", "name": "matilda", "label": "Matilda - Knowledgable, Professional"},
    {"voice_id": "JBFqnCBsd6RMkjVDRZzb", "name": "george", "label": "George - Warm, Captivating Storyteller"},
]

# Paragraphe du chapitre 1 contenant des termes techniques anglais (timeout, rate limit, LLM,
# hallucination) — bon test de prononciation pour une voix française.
EXCERPT_PARAGRAPH_INDEX = 2
EXCERPT_NUM_SENTENCES = 3


def select_excerpt(lesson_script: str, paragraph_index: int = EXCERPT_PARAGRAPH_INDEX, num_sentences: int = EXCERPT_NUM_SENTENCES) -> str:
    paragraphs = [p.strip() for p in lesson_script.split("\n\n") if p.strip()]
    sentences = split_sentences(paragraphs[paragraph_index])
    return " ".join(sentences[:num_sentences])


def main() -> None:
    parser = argparse.ArgumentParser(description="Génère des échantillons audio multi-voix ElevenLabs")
    parser.add_argument("--content-file", type=str, default=str(DEFAULT_CONTENT_FILE))
    parser.add_argument("--chapter", type=int, default=1)
    args = parser.parse_args()

    with open(args.content_file, encoding="utf-8") as f:
        content = json.load(f)
    chapter = next(c for c in content["chapters_content"] if c["chapter_number"] == args.chapter)
    excerpt = select_excerpt(chapter["lesson_script"])

    print(f"Extrait ({len(excerpt.split())} mots) :\n{excerpt}\n")

    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    for voice in VOICES_TO_TEST:
        output_path = SAMPLES_DIR / f"{voice['name']}.mp3"
        result = synthesize_slide_audio(excerpt, output_path, demo=False, voice_id=voice["voice_id"])
        print(f"{voice['label']} -> {output_path} ({result['duration_seconds']:.1f}s)")


if __name__ == "__main__":
    main()
