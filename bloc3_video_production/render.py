"""Bloc 3 — Rendu vidéo via Remotion : assemble les diapositives + audio en un .mp4 1080p."""

import json
import shutil
import subprocess
from pathlib import Path

from bloc3_video_production.config import (
    FPS,
    REMOTION_COMPOSITION_ID,
    REMOTION_DIR,
    REMOTION_ENTRY,
    REMOTION_PUBLIC_AUDIO_DIR,
)


class RenderError(RuntimeError):
    """Levée quand le rendu Remotion échoue."""


def _remotion_binary() -> Path:
    cmd_path = REMOTION_DIR / "node_modules" / ".bin" / "remotion.cmd"
    if cmd_path.exists():
        return cmd_path
    fallback = REMOTION_DIR / "node_modules" / ".bin" / "remotion"
    if fallback.exists():
        return fallback
    raise RenderError(f"Binaire Remotion introuvable dans {REMOTION_DIR / 'node_modules' / '.bin'}")


def _stage_audio_files(chapter_number: int, slides_with_audio: list[dict]) -> list[dict]:
    """Copie les fichiers audio générés dans remotion/public/, et retourne les diapositives avec
    un chemin `audioFile` relatif (utilisable par staticFile() côté Remotion)."""
    chapter_dir = REMOTION_PUBLIC_AUDIO_DIR / f"chapter_{chapter_number}"
    chapter_dir.mkdir(parents=True, exist_ok=True)

    staged_slides = []
    for slide in slides_with_audio:
        source = Path(slide["audio_path"])
        dest_name = f"slide_{slide['slide_number']}{source.suffix}"
        dest = chapter_dir / dest_name
        shutil.copyfile(source, dest)

        duration_in_frames = max(round(slide["duration_seconds"] * FPS), 1)
        staged_slides.append(
            {
                "slideNumber": slide["slide_number"],
                "visualTitle": slide["visual_title"],
                "keyTerms": [{"text": t["text"], "startFrame": t["start_frame"]} for t in slide["key_terms"]],
                "keyNumbers": [{"text": n["text"], "startFrame": n["start_frame"]} for n in slide["key_numbers"]],
                "audioFile": f"audio/chapter_{chapter_number}/{dest_name}",
                "durationInFrames": duration_in_frames,
            }
        )
    return staged_slides


def _invoke_remotion_render(composition_id: str, props_path: Path, output_path: Path) -> None:
    result = subprocess.run(
        [
            str(_remotion_binary()),
            "render",
            REMOTION_ENTRY,
            composition_id,
            str(output_path.resolve()),
            f"--props={props_path.resolve()}",
        ],
        cwd=REMOTION_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RenderError(f"Échec du rendu Remotion (code {result.returncode}) : {result.stderr[-2000:]}")


def render_chapter_video(
    chapter_number: int,
    chapter_title: str,
    slides_with_audio: list[dict],
    output_path: Path,
) -> float:
    """Rend la vidéo d'un chapitre. `slides_with_audio` : liste de dicts
    {slide_number, visual_title, key_terms: [{text, start_frame}], key_numbers: [{text, start_frame}],
    audio_path, duration_seconds}. Retourne la durée totale de la vidéo en secondes."""
    staged_slides = _stage_audio_files(chapter_number, slides_with_audio)
    total_duration = sum(s["duration_seconds"] for s in slides_with_audio)

    props = {
        "chapterNumber": chapter_number,
        "chapterTitle": chapter_title,
        "slides": staged_slides,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    props_path = output_path.parent / f"_props_chapter_{chapter_number}.json"
    props_path.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")

    try:
        _invoke_remotion_render(REMOTION_COMPOSITION_ID, props_path, output_path)
    finally:
        props_path.unlink(missing_ok=True)

    return total_duration


def render_composition(composition_id: str, props: dict, output_path: Path) -> None:
    """Rend une composition Remotion arbitraire à partir de props déjà construites — pour les
    scripts de preview/pilote (ex. `produce_rich_preview.py`) dont le schéma ne correspond pas à
    celui de `ChapterVideo`/`render_chapter_video`."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    props_path = output_path.parent / f"_props_{composition_id}.json"
    props_path.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")

    try:
        _invoke_remotion_render(composition_id, props_path, output_path)
    finally:
        props_path.unlink(missing_ok=True)
