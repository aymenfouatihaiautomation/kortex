"""Bloc 3.5 — Orchestrateur du contrôle qualité : un chapitre à la fois, via le graphe LangGraph.

Voir docs/BLOC3_5_QUALITY_CONTROL.md pour la spec complète.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bloc2_content_writing.write_content import load_curriculum, revise_chapter_content
from bloc3_5_quality_control.graph import run_chapter_qc
from bloc3_5_quality_control.reviewer import review_chapter
from config import DATA_DIR

DEFAULT_CURRICULUM_FILE = DATA_DIR / "bloc1_curriculum_20260726_122738.json"
DEFAULT_CONTENT_FILE = DATA_DIR / "bloc2_content_20260727_091307.json"
DEFAULT_MAX_ATTEMPTS = 3


def load_bloc2_content(path: Path | str) -> dict:
    path = Path(path)
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _index_content_by_chapter(bloc2_result: dict) -> dict[int, dict]:
    return {c["chapter_number"]: c for c in bloc2_result["chapters_content"]}


def run_quality_control(
    curriculum: dict,
    bloc2_result: dict,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    demo: bool = False,
) -> dict:
    """Exécute le Bloc 3.5 sur tous les chapitres et retourne le rapport de qualité complet.

    Le fil rouge utilisé pour une éventuelle réécriture (`revise`) est lu directement dans
    `bloc2_result["running_example"]` — c'est celui qui a servi à générer ce contenu précis, pas
    une valeur à repasser séparément (garantit la cohérence même pour un cours différent du
    Sprint 1)."""
    chapters = curriculum["chapters"]
    total = len(chapters)
    content_by_number = _index_content_by_chapter(bloc2_result)
    running_example = bloc2_result.get("running_example")

    chapter_reports = []
    for i, chapter_spec in enumerate(chapters):
        prev_chapter_spec = chapters[i - 1] if i > 0 else None
        content = content_by_number[chapter_spec["number"]]

        final_state = run_chapter_qc(
            curriculum=curriculum,
            chapter_spec=chapter_spec,
            prev_chapter_spec=prev_chapter_spec,
            content=content,
            total_chapters=total,
            max_attempts=max_attempts,
            demo=demo,
            running_example=running_example,
        )

        chapter_reports.append(
            {
                "chapter_number": chapter_spec["number"],
                "chapter_title": chapter_spec["title"],
                "final_status": final_state["status"],
                "attempts_used": final_state["attempt"],
                "final_review": final_state["review"],
                "final_content": final_state["content"],
                "history": final_state["history"],
            }
        )

    return {
        "course_title": curriculum["title"],
        "niche": curriculum.get("niche"),
        "level": curriculum.get("level"),
        "max_attempts": max_attempts,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "chapters": chapter_reports,
        "summary": {
            "accepted": sum(1 for c in chapter_reports if c["final_status"] == "accepted"),
            "escalated": sum(1 for c in chapter_reports if c["final_status"] == "escalated"),
        },
    }


def apply_manual_correction(
    curriculum: dict,
    chapter_spec: dict,
    prev_chapter_spec: dict | None,
    total_chapters: int,
    current_content: dict,
    issues: list[dict],
    demo: bool = False,
    running_example: str | None = None,
) -> dict:
    """Corrige manuellement UN chapitre à partir de problèmes fournis explicitement (par un humain,
    pas par le réviseur automatique), puis fait une SEULE évaluation de confirmation — sans repasser
    par la boucle LangGraph à `max_attempts`. Pour des corrections ciblées et ponctuelles décidées
    hors du cycle automatique (ex. après une revue manuelle d'un chapitre escaladé).

    `running_example` : fil rouge du cours concerné (voir `bloc2_result["running_example"]`) — par
    défaut celui du Sprint 1, pour rétrocompatibilité.

    Retourne un dict avec les mêmes clés qu'une entrée de rapport standard
    (`final_status`/`final_review`/`final_content`/`history`), directement substituable dans un
    rapport existant.
    """
    kwargs = {"running_example": running_example} if running_example else {}
    revised_content = revise_chapter_content(
        curriculum, chapter_spec, total_chapters, current_content, issues, demo=demo, **kwargs
    )
    review = review_chapter(
        curriculum, chapter_spec, prev_chapter_spec, revised_content, total_chapters, attempt=0, demo=demo
    )

    history = [
        {"stage": "manual_revise", "attempt": "manuelle", "issues_addressed": issues},
        {
            "stage": "manual_review",
            "attempt": "manuelle",
            "overall_verdict": review["overall_verdict"],
            "issues": review["issues"],
        },
    ]

    return {
        "chapter_number": chapter_spec["number"],
        "chapter_title": chapter_spec["title"],
        "final_status": "accepted" if review["overall_verdict"] == "accepted" else "escalated",
        "attempts_used": "manuelle (1 correction ciblée + 1 évaluation, hors boucle automatique)",
        "final_review": review,
        "final_content": revised_content,
        "history": history,
    }


def save_result(result: dict) -> tuple[Path, Path]:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = DATA_DIR / f"bloc3_5_quality_report_{timestamp}.json"
    md_path = DATA_DIR / f"bloc3_5_quality_report_{timestamp}.md"

    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(to_markdown(result), encoding="utf-8")
    return json_path, md_path


def to_markdown(result: dict) -> str:
    lines = [
        f"# Rapport de contrôle qualité — {result['course_title']}",
        "",
        f"Niche : {result.get('niche', 'N/A')} | Niveau : {result.get('level', 'N/A')}",
        f"Tentatives de correction max par chapitre : {result['max_attempts']}",
        f"Résumé : {result['summary']['accepted']} accepté(s), "
        f"{result['summary']['escalated']} escaladé(s) vers revue manuelle",
        "",
    ]

    for c in result["chapters"]:
        badge = "✅ ACCEPTÉ" if c["final_status"] == "accepted" else "⚠️ ESCALADÉ (revue manuelle requise)"
        lines.append(f"## Chapitre {c['chapter_number']} — {c['chapter_title']} — {badge}")
        lines.append("")
        if isinstance(c["attempts_used"], int):
            lines.append(f"Tentatives de correction utilisées : {c['attempts_used']}/{result['max_attempts']}")
        else:
            lines.append(f"Tentatives de correction utilisées : {c['attempts_used']}")
        lines.append("")
        lines.append("### Historique des itérations")
        lines.append("")
        for entry in c["history"]:
            stage = entry["stage"]
            if stage in ("review", "manual_review"):
                label = "évaluation" if stage == "review" else "évaluation manuelle (hors boucle automatique)"
                lines.append(
                    f"- **Tentative {entry['attempt']} — {label} :** verdict `{entry['overall_verdict']}`"
                )
                for issue in entry["issues"]:
                    lines.append(f"  - Problème signalé ({issue['field']}) : {issue['description']}")
            else:
                label = "correction" if stage == "revise" else "correction manuelle ciblée (hors boucle automatique)"
                lines.append(f"- **Tentative {entry['attempt']} — {label} :** champs réécrits ciblés")
                for issue in entry["issues_addressed"]:
                    lines.append(f"  - Corrigé ({issue['field']}) : {issue['description']}")
        lines.append("")

        lines.append("### Verdict final par critère")
        lines.append("")
        for name, c_result in c["final_review"]["criteria"].items():
            mark = "✅" if c_result["verdict"] == "pass" else "❌"
            lines.append(f"- {mark} **{name}** : {c_result['justification']}")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bloc 3.5 — Contrôle qualité")
    parser.add_argument("--demo", action="store_true", help="Mode démo : reviewer/reviser stubs")
    parser.add_argument("--curriculum-file", type=str, default=str(DEFAULT_CURRICULUM_FILE))
    parser.add_argument("--content-file", type=str, default=str(DEFAULT_CONTENT_FILE))
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    args = parser.parse_args()

    curriculum = load_curriculum(args.curriculum_file)
    bloc2_result = load_bloc2_content(args.content_file)

    result = run_quality_control(curriculum, bloc2_result, max_attempts=args.max_attempts, demo=args.demo)

    for c in result["chapters"]:
        print(f"Chapitre {c['chapter_number']} — {c['chapter_title']} : {c['final_status']} "
              f"({c['attempts_used']} tentative(s))")

    json_path, md_path = save_result(result)
    print(f"\nSauvegardé : {json_path}")
    print(f"Export lisible : {md_path}")


if __name__ == "__main__":
    main()
