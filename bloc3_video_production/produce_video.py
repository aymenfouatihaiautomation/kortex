"""Bloc 3 — Orchestrateur de production vidéo (diapositives -> TTS -> rendu Remotion -> manifeste).

Voir docs/BLOC3_VIDEO_PRODUCTION.md pour la spec complète. Vidéo UNIQUEMENT pour les lesson_script :
les exercices et le projet final restent des documents texte, conformément au brief.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bloc3_video_production.config import DEFAULT_CONTENT_FILE, VIDEO_OUTPUT_DIR, VOICE_NAME
from bloc3_video_production.render import render_chapter_video
from bloc3_video_production.slides import build_slides
from bloc3_video_production.timing import compute_element_start_frames
from bloc3_video_production.tts import synthesize_slide_audio

WORK_AUDIO_DIR = VIDEO_OUTPUT_DIR / "_audio_work"


def load_final_content(path: Path | str) -> dict:
    path = Path(path)
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def produce_chapter_video(chapter_content: dict, demo: bool = False) -> dict:
    """Produit la vidéo d'un chapitre à partir de son lesson_script et retourne l'entrée de
    manifeste correspondante."""
    chapter_number = chapter_content["chapter_number"]
    chapter_title = chapter_content["chapter_title"]

    slides = build_slides(chapter_title, chapter_content["lesson_script"], demo=demo)

    ext = ".wav" if demo else ".mp3"
    audio_dir = WORK_AUDIO_DIR / f"chapter_{chapter_number}"
    slides_with_audio = []
    for slide in slides:
        audio_path = audio_dir / f"slide_{slide['slide_number']}{ext}"
        audio_result = synthesize_slide_audio(slide["narration_text"], audio_path, demo=demo)

        term_frames, number_frames = compute_element_start_frames(
            slide["narration_text"], slide["key_terms"], slide["key_numbers"],
            audio_result["character_start_times"],
        )
        key_terms = [{"text": t, "start_frame": f} for t, f in zip(slide["key_terms"], term_frames)]
        key_numbers = [{"text": n, "start_frame": f} for n, f in zip(slide["key_numbers"], number_frames)]

        slides_with_audio.append({
            **slide,
            "key_terms": key_terms,
            "key_numbers": key_numbers,
            "audio_path": str(audio_path),
            "duration_seconds": audio_result["duration_seconds"],
        })

    output_path = VIDEO_OUTPUT_DIR / f"chapter_{chapter_number}.mp4"
    total_duration = render_chapter_video(chapter_number, chapter_title, slides_with_audio, output_path)

    return {
        "chapter_number": chapter_number,
        "chapter_title": chapter_title,
        "video_file": str(output_path),
        "duration_seconds": round(total_duration, 1),
        "num_slides": len(slides),
    }


def build_manifest(course_title: str, niche: str | None, video_entries: list[dict]) -> dict:
    return {
        "course_title": course_title,
        "niche": niche,
        "voice": VOICE_NAME,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "videos": sorted(video_entries, key=lambda v: v["chapter_number"]),
    }


def save_manifest(manifest: dict) -> tuple[Path, Path]:
    json_path = VIDEO_OUTPUT_DIR / "manifest.json"
    md_path = VIDEO_OUTPUT_DIR / "manifest.md"
    json_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(manifest_to_markdown(manifest), encoding="utf-8")
    return json_path, md_path


def manifest_to_markdown(manifest: dict) -> str:
    lines = [
        f"# Manifeste vidéo — {manifest['course_title']}",
        "",
        f"Niche : {manifest.get('niche', 'N/A')} | Voix : {manifest['voice']}",
        "",
        "| Chapitre | Titre | Fichier | Durée | Diapositives |",
        "|---|---|---|---|---|",
    ]
    for v in manifest["videos"]:
        minutes, seconds = divmod(int(v["duration_seconds"]), 60)
        lines.append(
            f"| {v['chapter_number']} | {v['chapter_title']} | `{Path(v['video_file']).name}` "
            f"| {minutes}:{seconds:02d} | {v['num_slides']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Bloc 3 — Production vidéo")
    parser.add_argument("--demo", action="store_true", help="Mode démo : TTS silencieux, aucun coût API")
    parser.add_argument("--content-file", type=str, default=str(DEFAULT_CONTENT_FILE))
    parser.add_argument("--chapter", type=int, help="Ne produire que ce chapitre (ex. 1 pour le pilote)")
    parser.add_argument("--all", action="store_true", help="Produire les 7 chapitres (à utiliser après validation du pilote)")
    args = parser.parse_args()

    if not args.chapter and not args.all:
        parser.error("Précise --chapter N (pilote) ou --all (une fois le pilote validé).")

    content = load_final_content(args.content_file)
    chapters = content["chapters_content"]
    if args.chapter:
        chapters = [c for c in chapters if c["chapter_number"] == args.chapter]
        if not chapters:
            parser.error(f"Chapitre {args.chapter} introuvable dans {args.content_file}")

    video_entries = []
    for chapter_content in chapters:
        print(f"--- Chapitre {chapter_content['chapter_number']} — {chapter_content['chapter_title']} ---")
        entry = produce_chapter_video(chapter_content, demo=args.demo)
        print(f"  -> {entry['video_file']} ({entry['duration_seconds']}s, {entry['num_slides']} diapositives)")
        video_entries.append(entry)

    manifest = build_manifest(content["course_title"], content.get("niche"), video_entries)
    json_path, md_path = save_manifest(manifest)
    print(f"\nManifeste : {json_path}")
    print(f"Export lisible : {md_path}")


if __name__ == "__main__":
    main()
