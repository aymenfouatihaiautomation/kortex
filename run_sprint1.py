"""Orchestrateur du Sprint 1 : Bloc 0 (découverte) -> sélection humaine -> Bloc 1 (planification).

Critère d'acceptation du Sprint (PROJECT_BRIEF_FR.md section 5) : exécuter le bloc 0 puis le
bloc 1 successivement sur le niche AI Automation, et obtenir la structure d'un cours complet,
prête pour une revue manuelle.
"""

import argparse
import sys

from bloc0_topic_discovery.discover_topics import (
    discover_topics,
    print_topics_table,
    save_result as save_bloc0_result,
)
from bloc1_curriculum_planning.plan_curriculum import (
    plan_curriculum,
    save_result as save_bloc1_result,
    to_markdown,
)
from common.llm_client import LLMCallError


def prompt_topic_choice(num_topics: int) -> int:
    while True:
        raw = input(f"Choisis un sujet à planifier [0-{num_topics - 1}] : ").strip()
        if raw.isdigit() and 0 <= int(raw) < num_topics:
            return int(raw)
        print(f"Entrée invalide, entre un nombre entre 0 et {num_topics - 1}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sprint 1 — Bloc 0 + Bloc 1")
    parser.add_argument(
        "--demo", action="store_true", help="Mode démo bout-en-bout, aucun appel réseau"
    )
    parser.add_argument(
        "--topic-index",
        type=int,
        default=None,
        help="Index du sujet à sélectionner sans invite interactive (utile en mode démo/CI)",
    )
    args = parser.parse_args()

    print("=== Bloc 0 — Découverte des sujets ===")
    try:
        bloc0_result = discover_topics(demo=args.demo)
    except LLMCallError as exc:
        print(f"Échec du Bloc 0 : {exc}", file=sys.stderr)
        sys.exit(1)

    print_topics_table(bloc0_result)
    save_bloc0_result(bloc0_result)

    topics = bloc0_result["topics"]
    if args.topic_index is not None:
        if not (0 <= args.topic_index < len(topics)):
            print(f"--topic-index hors limites (0-{len(topics) - 1})", file=sys.stderr)
            sys.exit(1)
        choice = args.topic_index
    else:
        choice = prompt_topic_choice(len(topics))

    selected_topic = topics[choice]
    print(f"\nSujet sélectionné : {selected_topic['title']}\n")

    print("=== Bloc 1 — Planification du programme ===")
    try:
        curriculum = plan_curriculum(selected_topic, demo=args.demo)
    except LLMCallError as exc:
        print(f"Échec du Bloc 1 : {exc}", file=sys.stderr)
        sys.exit(1)

    print(to_markdown(curriculum))
    json_path, md_path = save_bloc1_result(curriculum)
    print(f"\nStructure de cours sauvegardée : {json_path}")
    print(f"Export lisible pour revue manuelle : {md_path}")


if __name__ == "__main__":
    main()
