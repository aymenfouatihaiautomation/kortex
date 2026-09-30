"""Bloc 7, Étape 1 — Orchestrateur : génère PUIS vérifie la banque de questions d'examen (QCM)
d'un cours, hors-ligne, en local. Ne branche RIEN dans l'application (bloc4_publication) : la
sortie est un fichier JSON autonome, lu par personne pour l'instant.

Boucle génération -> vérification, par chapitre, avec un plafond d'itérations (voir
MAX_ITERATIONS) pour ne jamais tourner indéfiniment si le cours ne fournit pas assez de contenu
vérifiable pour atteindre TARGET_TOTAL_QUESTIONS — dans ce cas, le run s'arrête proprement avec
moins de questions que la cible, jamais en erreur (le rapport le dit explicitement).

Voir docs/BLOC3_5_QUALITY_CONTROL.md et bloc3_5_quality_control/quality_control.py pour le même
principe de pipeline (génération/révision + rapport JSON+MD), réutilisé ici pour l'examen."""

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bloc4_publication.content_loader import load_course
from bloc7_exam_generation.question_generator import generate_candidate_questions
from bloc7_exam_generation.question_verifier import verify_question
from common.llm_client import CostTracker
from config import DATA_DIR

TARGET_TOTAL_QUESTIONS = 24
BATCH_SIZE = 7
MAX_ITERATIONS = 3


def _per_chapter_bounds(num_chapters: int, target_total: int) -> tuple[int, int]:
    """(target, max) par chapitre — target = répartition égale de `target_total` sur les chapitres
    du cours (jamais une constante codée en dur, dérivée du nombre RÉEL de chapitres ET de la
    cible RÉELLEMENT demandée pour ce run, pas d'une constante de module) ; max = target + marge,
    pour qu'un chapitre avec plus de rejets que la moyenne puisse quand même contribuer sa part
    sans qu'un autre chapitre n'accapare toute la banque."""
    target = math.ceil(target_total / num_chapters)
    return target, target + 2


def build_exam_bank(
    course: dict,
    target_total: int = TARGET_TOTAL_QUESTIONS,
    batch_size: int = BATCH_SIZE,
    max_iterations: int = MAX_ITERATIONS,
    demo: bool = False,
) -> dict:
    """Exécute le pipeline complet (génération -> vérification, en boucle) et retourne un résultat
    structuré : `{"questions": [...], "report": {...}}`. `questions` ne contient QUE des questions
    VÉRIFIÉES (voir question_verifier.py) ; `report` détaille tout le reste (générées, rejetées et
    pourquoi, retenues par chapitre) pour audit humain."""
    chapters = course["chapters"]
    per_chapter_target, per_chapter_max = _per_chapter_bounds(len(chapters), target_total)

    verified: dict[int, list[dict]] = {c["number"]: [] for c in chapters}
    seen_questions: dict[int, list[str]] = {c["number"]: [] for c in chapters}
    rejections: list[dict] = []
    discarded_over_quota: list[dict] = []
    generated_count = 0
    tracker = CostTracker(label=f"Bloc 7 - build_exam_bank ({course['title']})")

    iterations_used = 0
    for iteration in range(1, max_iterations + 1):
        iterations_used = iteration
        total_verified = sum(len(v) for v in verified.values())
        if total_verified >= target_total:
            break

        made_progress = False
        for chapter in chapters:
            number = chapter["number"]
            if len(verified[number]) >= per_chapter_max:
                continue

            candidates = generate_candidate_questions(
                chapter,
                course["title"],
                n=batch_size,
                existing_questions=seen_questions[number],
                demo=demo,
                tracker=tracker,
            )

            for candidate in candidates:
                generated_count += 1
                seen_questions[number].append(candidate["question"])

                # Un seul candidat toujours forcé au rejet en mode démo (le premier de la toute
                # première itération) : exerce le câblage rejet -> comptage du rapport sans appel
                # réseau, sans fausser le reste du parcours démo (accepté par défaut sinon).
                demo_reject = demo and generated_count == 1
                verdict = verify_question(
                    chapter, course["title"], candidate, demo=demo, demo_reject=demo_reject, tracker=tracker
                )

                if not verdict["accepted"]:
                    rejections.append(
                        {
                            "chapter": number,
                            "question": candidate["question"],
                            "options": candidate["options"],
                            "correct_index_by_generator": candidate["correct_index"],
                            "resolved_index_by_verifier": verdict["resolved_index"],
                            "reasons": verdict["reasons"],
                            "reasoning": verdict["reasoning"],
                        }
                    )
                    continue

                if len(verified[number]) >= per_chapter_max:
                    # Accepté sur le fond, mais ce chapitre a déjà sa part maximale — jamais un
                    # rejet qualité, juste une question mise de côté pour préserver la répartition
                    # sur les 7 chapitres (voir le docstring du module).
                    discarded_over_quota.append({"chapter": number, "question": candidate["question"]})
                    continue

                verified[number].append(candidate)
                made_progress = True

        if not made_progress:
            break

    tracker.print_summary()

    final_questions = []
    for chapter in chapters:
        for candidate in verified[chapter["number"]]:
            final_questions.append(
                {
                    "id": f"q{len(final_questions) + 1}",
                    "chapter": chapter["number"],
                    "question": candidate["question"],
                    "options": candidate["options"],
                    "correct_index": candidate["correct_index"],
                    "explanation": candidate["explanation"],
                }
            )

    accepted_by_chapter = {str(c["number"]): len(verified[c["number"]]) for c in chapters}
    rejected_by_reason: dict[str, int] = {}
    for r in rejections:
        for reason in r["reasons"]:
            rejected_by_reason[reason] = rejected_by_reason.get(reason, 0) + 1

    report = {
        "course_title": course["title"],
        "course_slug": course["slug"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_total_questions": target_total,
        "per_chapter_target": per_chapter_target,
        "per_chapter_max": per_chapter_max,
        "iterations_used": iterations_used,
        "max_iterations": max_iterations,
        "totals": {
            "generated": generated_count,
            "accepted": len(final_questions),
            "rejected": len(rejections),
            "discarded_over_chapter_quota": len(discarded_over_quota),
        },
        "target_reached": len(final_questions) >= target_total,
        "accepted_by_chapter": accepted_by_chapter,
        "rejected_by_reason": rejected_by_reason,
        "rejections": rejections,
        "discarded_over_chapter_quota": discarded_over_quota,
        "cost": {
            "calls": len(tracker.calls),
            "input_tokens": tracker.total_input_tokens,
            "output_tokens": tracker.total_output_tokens,
            "usd": round(tracker.total_cost_usd, 4),
        },
    }

    return {"questions": final_questions, "report": report}


def to_markdown(report: dict) -> str:
    totals = report["totals"]
    lines = [
        f"# Rapport de vérification — banque d'examen — {report['course_title']}",
        "",
        f"Généré le {report['generated_at']}",
        f"Cible : {report['target_total_questions']} questions "
        f"({'atteinte' if report['target_reached'] else 'NON atteinte'}) — "
        f"{report['iterations_used']}/{report['max_iterations']} itération(s) utilisée(s)",
        "",
        f"- Générées : {totals['generated']}",
        f"- Retenues (vérifiées) : {totals['accepted']}",
        f"- Rejetées : {totals['rejected']}",
        f"- Écartées pour quota de répartition par chapitre (acceptées sur le fond, mises de côté) : "
        f"{totals['discarded_over_chapter_quota']}",
        f"- Coût du run : {report['cost']['calls']} appel(s), ≈ ${report['cost']['usd']:.4f}",
        "",
        "## Retenues par chapitre",
        "",
    ]
    for chapter, count in report["accepted_by_chapter"].items():
        lines.append(f"- Chapitre {chapter} : {count}")
    lines.append("")
    lines.append("## Rejets par raison")
    lines.append("")
    if report["rejected_by_reason"]:
        for reason, count in sorted(report["rejected_by_reason"].items(), key=lambda kv: -kv[1]):
            lines.append(f"- `{reason}` : {count}")
    else:
        lines.append("(aucun rejet)")
    lines.append("")
    lines.append("## Détail des rejets")
    lines.append("")
    for r in report["rejections"]:
        lines.append(f"### Chapitre {r['chapter']} — {r['question']}")
        lines.append(f"- Raisons : {', '.join(r['reasons'])}")
        lines.append(
            f"- Index proposé par le générateur : {r['correct_index_by_generator']} — "
            f"résolu par le vérificateur : {r['resolved_index_by_verifier']}"
        )
        if r["reasoning"]:
            lines.append(f"- Raisonnement du vérificateur : {r['reasoning']}")
        lines.append("")
    return "\n".join(lines)


def save_result(result: dict) -> tuple[Path, Path, Path]:
    slug = result["report"]["course_slug"]
    course_dir = DATA_DIR / slug
    course_dir.mkdir(parents=True, exist_ok=True)

    questions_path = course_dir / "exam_questions.json"
    report_json_path = course_dir / "exam_verification_report.json"
    report_md_path = course_dir / "exam_verification_report.md"

    questions_path.write_text(json.dumps(result["questions"], ensure_ascii=False, indent=2), encoding="utf-8")
    report_json_path.write_text(json.dumps(result["report"], ensure_ascii=False, indent=2), encoding="utf-8")
    report_md_path.write_text(to_markdown(result["report"]), encoding="utf-8")

    return questions_path, report_json_path, report_md_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Bloc 7 — Génération + vérification de la banque d'examen")
    parser.add_argument("--target-total", type=int, default=TARGET_TOTAL_QUESTIONS)
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--max-iterations", type=int, default=MAX_ITERATIONS)
    parser.add_argument("--demo", action="store_true", help="Mode démo : generateur/vérificateur stubs, aucun appel réseau")
    args = parser.parse_args()

    course = load_course()
    result = build_exam_bank(
        course,
        target_total=args.target_total,
        batch_size=args.batch_size,
        max_iterations=args.max_iterations,
        demo=args.demo,
    )

    report = result["report"]
    print(
        f"\n{report['totals']['accepted']}/{report['target_total_questions']} questions retenues "
        f"({report['totals']['generated']} générées, {report['totals']['rejected']} rejetées)"
    )
    for chapter, count in report["accepted_by_chapter"].items():
        print(f"  Chapitre {chapter} : {count}")

    questions_path, report_json_path, report_md_path = save_result(result)
    print(f"\nBanque d'examen : {questions_path}")
    print(f"Rapport : {report_json_path}")
    print(f"Rapport lisible : {report_md_path}")


if __name__ == "__main__":
    main()
