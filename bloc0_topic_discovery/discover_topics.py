"""Bloc 0 — Découverte des sujets de cours dans le niche AI Automation.

Voir docs/BLOC0_TOPIC_DISCOVERY.md pour la spec complète.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.llm_client import LLMCallError, extract_json, run_prompt
from config import DATA_DIR, NICHE

SYSTEM_PROMPT = (
    "Tu es un analyste de marché spécialisé dans la formation en ligne. "
    "Tu réponds UNIQUEMENT avec un objet JSON valide, sans texte avant ou après, "
    "sans bloc de code markdown."
)

PROMPT_TEMPLATE = """\
Niche : "{niche}".

Utilise la recherche web pour identifier des sujets de cours candidats dans cette niche, à partir
de signaux réels : tendances de recherche, discussions récentes (forums, réseaux sociaux, articles),
lacunes de contenu constatées (ce qui est demandé mais mal couvert par les cours existants).

Propose entre 5 et 8 sujets de cours candidats. Pour chaque sujet, donne :
- title : titre du cours candidat, précis et actionnable (pas juste le nom d'un outil)
- demand_score : score de 0.0 à 1.0 estimant la demande réelle / lacune de contenu (1.0 = très
  demandé et mal couvert)
- gap_reason : pourquoi ce sujet est demandé et/ou sous-couvert, en une ou deux phrases
- sources : liste de 1 à 3 indications de source (URL, nom de forum/plateforme, ou requête de
  recherche utilisée)

Réponds avec EXACTEMENT ce format JSON, trié par demand_score décroissant :
{{
  "niche": "{niche}",
  "topics": [
    {{
      "title": "...",
      "demand_score": 0.0,
      "gap_reason": "...",
      "sources": ["..."]
    }}
  ]
}}
"""

DEMO_TOPICS = [
    {
        "title": "Automatiser ses workflows métier avec n8n (de zéro à la production)",
        "demand_score": 0.91,
        "gap_reason": "Forte demande sur les forums no-code/automatisation, peu de cours couvrent le passage du prototype à un workflow fiable en production.",
        "sources": ["r/n8n (Reddit)", "recherche : \"n8n course production\""],
    },
    {
        "title": "Construire des agents IA avec LangGraph : de l'idée au déploiement",
        "demand_score": 0.87,
        "gap_reason": "LangGraph est récent et change vite ; la doc officielle est technique, peu de contenu pédagogique progressif existe.",
        "sources": ["LangChain Discord", "recherche : \"LangGraph tutorial beginner\""],
    },
    {
        "title": "Automatisation IA pour PME : audit, ROI et premiers cas d'usage",
        "demand_score": 0.78,
        "gap_reason": "Les dirigeants de PME cherchent une approche business, pas technique ; la plupart des cours existants sont trop orientés développeur.",
        "sources": ["LinkedIn (posts PME + IA)", "recherche : \"automatisation IA PME ROI\""],
    },
    {
        "title": "Claude Agent SDK et MCP : créer des outils IA connectés à ses propres données",
        "demand_score": 0.74,
        "gap_reason": "MCP est un standard émergent, peu de formations structurées, forte activité développeur récente.",
        "sources": ["recherche : \"MCP server tutorial\"", "GitHub (repos MCP récents)"],
    },
    {
        "title": "Piloter une équipe d'agents IA avec CrewAI pour des tâches métier répétitives",
        "demand_score": 0.68,
        "gap_reason": "Beaucoup de démos CrewAI existent mais peu de cours vont jusqu'à un cas d'usage métier complet et fiable.",
        "sources": ["recherche : \"CrewAI real use case\""],
    },
]


def build_prompt(niche: str) -> str:
    return PROMPT_TEMPLATE.format(niche=niche)


def _validate_and_sort(result: dict) -> dict:
    if "topics" not in result or not isinstance(result["topics"], list) or not result["topics"]:
        raise LLMCallError(f"Réponse sans liste 'topics' exploitable : {result!r}")

    for topic in result["topics"]:
        for field in ("title", "demand_score", "gap_reason", "sources"):
            if field not in topic:
                raise LLMCallError(f"Sujet incomplet, champ '{field}' manquant : {topic!r}")

    result["topics"].sort(key=lambda t: t["demand_score"], reverse=True)
    return result


def discover_topics(demo: bool = False) -> dict:
    """Exécute le Bloc 0 et retourne le résultat conforme au schéma documenté."""
    if demo:
        result = {"niche": NICHE, "topics": [dict(t) for t in DEMO_TOPICS]}
    else:
        response_text = run_prompt(
            prompt=build_prompt(NICHE),
            allowed_tools=["WebSearch"],
            system_prompt=SYSTEM_PROMPT,
            max_turns=8,
        )
        result = extract_json(response_text)

    result = _validate_and_sort(result)
    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    return result


def save_result(result: dict) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = DATA_DIR / f"bloc0_topics_{timestamp}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def print_topics_table(result: dict) -> None:
    print(f"\nSujets candidats — niche : {result['niche']}\n")
    for i, topic in enumerate(result["topics"]):
        print(f"[{i}] (score {topic['demand_score']:.2f}) {topic['title']}")
        print(f"    Raison : {topic['gap_reason']}")
        print(f"    Sources : {', '.join(topic['sources'])}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bloc 0 — Découverte des sujets (AI Automation)")
    parser.add_argument(
        "--demo", action="store_true", help="Mode démo : données stub, aucun appel réseau"
    )
    args = parser.parse_args()

    result = discover_topics(demo=args.demo)
    print_topics_table(result)
    out_path = save_result(result)
    print(f"Résultat sauvegardé : {out_path}")


if __name__ == "__main__":
    main()
