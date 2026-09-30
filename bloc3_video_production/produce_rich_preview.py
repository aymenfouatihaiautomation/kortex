"""Bloc 3 — Pilote de style visuel riche pour un chapitre, en RÉUTILISANT l'audio déjà généré
(zéro nouvel appel ElevenLabs). Même principe que le preview v2 (audio et visuel = deux timelines
indépendantes de même durée totale, timing visuel APPROXIMATIF) — ce qui change ici : chaque
diapositive reçoit un traitement visuel adapté à son contenu (diagram/timeline/default enrichi),
généralisé à partir des POC (architecture_diagram_v2, timeline_diagram), pas limité à 1-2
diapositives. Sert à valider le style avant de décider de lancer le plan ElevenLabs payant sur les
chapitres restants — ne modifie jamais le texte du lesson_script déjà validé.
"""

import argparse
import json
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bloc3_video_production.config import DEFAULT_CONTENT_FILE, FPS, REMOTION_PUBLIC_AUDIO_DIR, VIDEO_OUTPUT_DIR
from bloc3_video_production.render import render_composition
from bloc3_video_production.slides import build_rich_slides
from bloc3_video_production.timing import approximate_uniform_start_frames
from bloc3_video_production.tts import get_audio_duration_seconds

RICH_PREVIEW_COMPOSITION_ID = "ChapterVideoRichPreview"


def load_final_content(path: Path | str) -> dict:
    path = Path(path)
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_existing_audio_segments(chapter_number: int) -> list[dict]:
    """Retourne les clips audio .mp3 déjà générés pour ce chapitre (pilote v1), triés par numéro
    de diapositive d'origine, avec leur durée réelle (lue via mutagen, jamais ré-estimée)."""
    audio_dir = REMOTION_PUBLIC_AUDIO_DIR / f"chapter_{chapter_number}"
    mp3_files = sorted(audio_dir.glob("slide_*.mp3"), key=lambda p: int(p.stem.split("_")[1]))
    if not mp3_files:
        raise FileNotFoundError(
            f"Aucun clip audio .mp3 trouvé dans {audio_dir} — le pilote v1 (ElevenLabs) doit avoir "
            "été produit avant de pouvoir réutiliser son audio pour ce preview."
        )
    segments = []
    for f in mp3_files:
        duration = get_audio_duration_seconds(f)
        segments.append(
            {
                "file": f"audio/chapter_{chapter_number}/{f.name}",
                "duration_in_frames": max(round(duration * FPS), 1),
            }
        )
    return segments


def assign_visual_durations(slides: list[dict], total_duration_frames: int) -> list[dict]:
    """Répartit la durée totale (celle de l'audio réutilisé) entre les diapositives visuelles,
    proportionnellement au nombre de mots de leur narration — deux timelines indépendantes de même
    durée totale, comme pour le preview v2. Le dernier slide absorbe l'écart d'arrondi pour que la
    somme corresponde exactement à la durée audio."""
    word_counts = [max(len(s["narration_text"].split()), 1) for s in slides]
    total_words = sum(word_counts)

    out = []
    for slide, words in zip(slides, word_counts):
        duration = max(round(total_duration_frames * words / total_words), 1)
        out.append({**slide, "duration_in_frames": duration})

    diff = total_duration_frames - sum(s["duration_in_frames"] for s in out)
    out[-1]["duration_in_frames"] += diff
    return out


def build_visual_slide_props(slide: dict) -> dict:
    """Construit les props Remotion d'UNE diapositive selon son `visual_type`."""
    base = {
        "slideNumber": slide["slide_number"],
        "visualTitle": slide["visual_title"],
        "visualType": slide["visual_type"],
        "durationInFrames": slide["duration_in_frames"],
    }

    if slide["visual_type"] == "diagram":
        base["diagramHub"] = slide["diagram_hub"]
        base["diagramSatellites"] = slide["diagram_satellites"]
    elif slide["visual_type"] == "timeline":
        base["timelineSteps"] = slide["timeline_steps"]
    else:
        term_frames = approximate_uniform_start_frames(len(slide["key_terms"]), slide["duration_in_frames"])
        number_frames = approximate_uniform_start_frames(
            len(slide["key_numbers"]), slide["duration_in_frames"], start_fraction=0.3, end_fraction=0.85
        )
        base["keyTerms"] = [{"text": t, "startFrame": f} for t, f in zip(slide["key_terms"], term_frames)]
        base["keyNumbers"] = [{"text": n, "startFrame": f} for n, f in zip(slide["key_numbers"], number_frames)]

    return base


def produce_rich_preview(chapter_content: dict, demo: bool = False) -> Path:
    """Produit le preview de style visuel riche d'un chapitre, en réutilisant son audio déjà
    généré. Retourne le chemin du fichier vidéo produit."""
    chapter_number = chapter_content["chapter_number"]
    chapter_title = chapter_content["chapter_title"]

    audio_segments = load_existing_audio_segments(chapter_number)
    total_duration_frames = sum(s["duration_in_frames"] for s in audio_segments)

    slides = build_rich_slides(chapter_title, chapter_content["lesson_script"], demo=demo)
    slides = assign_visual_durations(slides, total_duration_frames)

    props = {
        "chapterNumber": chapter_number,
        "chapterTitle": chapter_title,
        "audioSegments": [
            {"file": s["file"], "durationInFrames": s["duration_in_frames"]} for s in audio_segments
        ],
        "visualSlides": [build_visual_slide_props(s) for s in slides],
    }

    output_path = VIDEO_OUTPUT_DIR / f"chapter_{chapter_number}_richstyle_preview.mp4"
    render_composition(RICH_PREVIEW_COMPOSITION_ID, props, output_path)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Pilote de style visuel riche (réutilise l'audio existant)")
    parser.add_argument("--demo", action="store_true", help="Mode démo : découpage en diapositives stub")
    parser.add_argument("--content-file", type=str, default=str(DEFAULT_CONTENT_FILE))
    parser.add_argument("--chapter", type=int, required=True)
    args = parser.parse_args()

    content = load_final_content(args.content_file)
    chapter_content = next(
        (c for c in content["chapters_content"] if c["chapter_number"] == args.chapter), None
    )
    if chapter_content is None:
        parser.error(f"Chapitre {args.chapter} introuvable dans {args.content_file}")

    print(f"--- Pilote style riche — Chapitre {chapter_content['chapter_number']} — "
          f"{chapter_content['chapter_title']} ---")
    output_path = produce_rich_preview(chapter_content, demo=args.demo)
    print(f"-> {output_path}")


if __name__ == "__main__":
    main()
