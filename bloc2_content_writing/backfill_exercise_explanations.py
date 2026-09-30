"""Backfill ponctuel : ajoute le champ "explanation" aux exercices QCM d'un contenu DÉJÀ publié
(cours 1), sans toucher aux questions/options/réponses déjà validées par le Bloc 3.5.

Nécessaire car ce cours a été rédigé avant l'introduction du champ `explanation` (2026-08-04) —
les cours suivants le génèrent nativement dans `write_content.py` (le réviseur du Bloc 3.5 le
couvre alors comme le reste du contenu). Un seul appel LLM par chapitre (pas par question) pour
limiter le nombre d'appels.
"""

import argparse
import json
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.llm_client import CostTracker, LLMCallError, call_llm_api, extract_json
from config import DATA_DIR

DEFAULT_CONTENT_FILE = DATA_DIR / "bloc2_content_final.json"

MODEL = "claude-haiku-4-5-20251001"  # tâche mécanique/reformatage, cf. mapping bloc->modèle validé

SYSTEM_PROMPT = (
    "Tu es un rédacteur pédagogique expert. Tu réponds UNIQUEMENT avec un objet JSON valide, sans "
    "texte avant ou après, sans bloc de code markdown. Tu n'inventes ni ne modifies JAMAIS les "
    "questions, options ou réponses correctes qu'on te fournit : ton seul travail est d'expliquer "
    "pourquoi la réponse correcte déjà fournie est correcte."
)

PROMPT_TEMPLATE = """\
Cours : "{course_title}" (niveau {level}). Chapitre {number} : "{chapter_title}".

Voici {count} question(s) à choix multiples DÉJÀ VALIDÉES (question, options, bonne réponse) —
ne les modifie surtout pas, contente-toi de produire une explication pour chacune :

{questions_block}

Pour CHAQUE question, dans l'ordre, rédige une explication ("explanation") de 2 à 4 phrases en
français qui : (1) explique pourquoi la réponse correcte est la bonne, en te basant sur le
raisonnement attendu pour ce chapitre, (2) si c'est utile, mentionne brièvement pourquoi les
autres options sont des erreurs courantes ou des pièges. Ne répète pas mot pour mot l'énoncé ou
les options.

Réponds avec EXACTEMENT ce format JSON :
{{"explanations": ["...", "..."]}}
(un élément par question, dans le même ordre, {count} élément(s) au total)
"""


def build_prompt(course_title: str, level: str, chapter_title: str, number: int, mcq_exercises: list[dict]) -> str:
    lines = []
    for i, ex in enumerate(mcq_exercises, start=1):
        lines.append(f"{i}. Question : {ex['question']}")
        for opt in ex["options"]:
            marker = " (BONNE RÉPONSE)" if opt == ex["correct_answer"] else ""
            lines.append(f"   - {opt}{marker}")
    return PROMPT_TEMPLATE.format(
        course_title=course_title,
        level=level or "N/A",
        chapter_title=chapter_title,
        number=number,
        count=len(mcq_exercises),
        questions_block="\n".join(lines),
    )


def generate_explanations_for_chapter(
    course_title: str,
    level: str,
    chapter_number: int,
    chapter_title: str,
    mcq_exercises: list[dict],
    demo: bool = False,
    tracker: CostTracker | None = None,
) -> list[str]:
    """Retourne une explication par exercice de `mcq_exercises`, dans le même ordre."""
    if not mcq_exercises:
        return []

    if demo:
        return [f"[DEMO] Explication pour : {ex['question'][:40]}..." for ex in mcq_exercises]

    prompt = build_prompt(course_title, level, chapter_title, chapter_number, mcq_exercises)
    response_text = call_llm_api(
        prompt=prompt, model=MODEL, system_prompt=SYSTEM_PROMPT, max_tokens=2048, tracker=tracker
    )
    data = extract_json(response_text)
    explanations = data.get("explanations")
    if not isinstance(explanations, list) or len(explanations) != len(mcq_exercises):
        raise LLMCallError(
            f"Chapitre {chapter_number} : {len(mcq_exercises)} explication(s) attendue(s), "
            f"reçu : {explanations!r}"
        )
    return explanations


def backfill_content(content: dict, demo: bool = False) -> dict:
    """Retourne une COPIE de `content` avec un champ `explanation` ajouté à chaque exercice QCM qui
    n'en a pas déjà un. Ne touche à rien d'autre : question/options/correct_answer/lesson_script/
    practical_exercise inchangés ; chapitres sans QCM manquant d'explication laissés intacts."""
    result = json.loads(json.dumps(content))  # copie profonde, jamais de mutation de l'original
    tracker = None if demo else CostTracker(label="Bloc 2 - backfill_content (cours complet)")

    for chapter in result["chapters_content"]:
        missing = [
            ex
            for ex in chapter["comprehension_exercises"]
            if ex.get("type") == "mcq" and not (ex.get("explanation") or "").strip()
        ]
        if not missing:
            continue

        explanations = generate_explanations_for_chapter(
            result["course_title"],
            result.get("level"),
            chapter["chapter_number"],
            chapter["chapter_title"],
            missing,
            demo=demo,
            tracker=tracker,
        )
        for ex, explanation in zip(missing, explanations):
            ex["explanation"] = explanation

    if tracker is not None:
        tracker.print_summary()

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill des explications QCM sur un contenu déjà publié")
    parser.add_argument("--demo", action="store_true", help="Mode démo : explications placeholder, aucun appel réseau")
    parser.add_argument("--content-file", type=str, default=str(DEFAULT_CONTENT_FILE))
    parser.add_argument("--output", type=str, default=None, help="Par défaut : écrase --content-file")
    args = parser.parse_args()

    content = json.loads(Path(args.content_file).read_text(encoding="utf-8"))
    result = backfill_content(content, demo=args.demo)

    output_path = Path(args.output) if args.output else Path(args.content_file)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    total_mcq = sum(
        1 for c in result["chapters_content"] for ex in c["comprehension_exercises"] if ex.get("type") == "mcq"
    )
    with_explanation = sum(
        1
        for c in result["chapters_content"]
        for ex in c["comprehension_exercises"]
        if ex.get("type") == "mcq" and (ex.get("explanation") or "").strip()
    )
    print(f"{with_explanation}/{total_mcq} exercices QCM ont une explanation dans {output_path}")


if __name__ == "__main__":
    main()
