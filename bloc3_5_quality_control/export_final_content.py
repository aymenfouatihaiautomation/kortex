"""Bloc 3.5 -> Bloc 3 handoff : consolide le contenu final post-QC des 7 chapitres.

Le fichier de sortie brut du Bloc 2 (`bloc2_content_<timestamp>.json`) est un instantané
PRE-QC : les chapitres corrigés lors des passes manuelles du Bloc 3.5 y sont restés dans leur
version d'origine, désormais périmée. Ce script relit le rapport de qualité le plus récent (qui
contient le contenu final de chaque chapitre dans `final_content`, accepté ou non) et reconstruit
un fichier unique, dans le même schéma que la sortie du Bloc 2, pour que le Bloc 3 (et tout
consommateur en aval) n'ait pas besoin de connaître l'historique des corrections.

Refuse de produire un fichier si un chapitre du rapport n'est pas `accepted` — un contenu encore
`escalated` ne doit pas être envoyé en production vidéo.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from bloc2_content_writing.write_content import (
    RUNNING_EXAMPLE,
    to_markdown,
    validate_chapter_content,
)
from config import DATA_DIR

DEFAULT_REPORT_FILE = DATA_DIR / "bloc3_5_quality_report_20260727_164503.json"
DEFAULT_OUTPUT_JSON = DATA_DIR / "bloc2_content_final.json"
DEFAULT_OUTPUT_MD = DATA_DIR / "bloc2_content_final.md"


def load_report(path: Path | str) -> dict:
    path = Path(path)
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def export_final_content(report: dict) -> dict:
    """Reconstruit le contenu final consolidé à partir d'un rapport de qualité Bloc 3.5.

    Lève ValueError si un chapitre n'est pas `accepted` — évite d'envoyer un contenu encore
    en attente de correction vers le Bloc 3.
    """
    not_accepted = [c["chapter_number"] for c in report["chapters"] if c["final_status"] != "accepted"]
    if not_accepted:
        raise ValueError(
            f"Chapitre(s) non 'accepted' dans le rapport, export refusé : {not_accepted}"
        )

    chapters_sorted = sorted(report["chapters"], key=lambda c: c["chapter_number"])
    chapters_content = []
    for c in chapters_sorted:
        content = c["final_content"]
        is_final_chapter = c["chapter_number"] == len(chapters_sorted)
        errors = validate_chapter_content(content, is_final_chapter)
        if errors:
            raise ValueError(f"Chapitre {c['chapter_number']} : contenu invalide à l'export : {errors}")
        chapters_content.append(content)

    return {
        "course_title": report["course_title"],
        "niche": report.get("niche"),
        "level": report.get("level"),
        "running_example": RUNNING_EXAMPLE,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "chapters_content": chapters_content,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Consolide le contenu final post-QC des 7 chapitres (Bloc 3.5 -> Bloc 3)"
    )
    parser.add_argument("--report-file", type=str, default=str(DEFAULT_REPORT_FILE))
    parser.add_argument("--output-json", type=str, default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", type=str, default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    report = load_report(args.report_file)
    result = export_final_content(report)

    for c in result["chapters_content"]:
        print(f"Chapitre {c['chapter_number']} — {c['chapter_title']}")

    Path(args.output_json).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(args.output_md).write_text(to_markdown(result), encoding="utf-8")
    print(f"\nSauvegardé : {args.output_json}")
    print(f"Export lisible : {args.output_md}")


if __name__ == "__main__":
    main()
