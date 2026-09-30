"""Pricing agent — recherche de prix comparables (Phase 1), même mécanisme que le Bloc 0 (Claude
Agent SDK + outil WebSearch).

Cette recherche ne DÉCIDE PAS du prix final — le prix de lancement est une constante produit fixée
dans `config.py` (`LAUNCH_PRICE_USD`). Elle fournit le contexte marché (cours comparables réels) et
un raisonnement qualitatif qui accompagnent la proposition affichée pour confirmation humaine."""

import copy

from common.llm_client import LLMCallError, extract_json, run_prompt

SYSTEM_PROMPT = (
    "Tu es un analyste pricing spécialisé dans la formation en ligne technique. "
    "Tu réponds UNIQUEMENT avec un objet JSON valide, sans texte avant ou après, "
    "sans bloc de code markdown."
)

PROMPT_TEMPLATE = """\
Recherche sur le web des cours en ligne comparables à celui-ci, pour évaluer un CONTEXTE de prix
(tu ne fixes pas le prix toi-même, cette décision est prise séparément) :

Cours à comparer : "{title}", niveau {level}, {chapter_count} chapitres, focalisé sur un sujet
précis et avancé : {description}

IMPORTANT : cherche des cours SPÉCIALISÉS de niveau intermédiaire/avancé sur les agents IA en
production (fiabilité, gestion d'erreurs, évaluation, déploiement) — PAS des cours généralistes
"de zéro à un agent IA" pour débutants, qui ne sont pas comparables à celui-ci.

Pour 4 à 8 cours comparables trouvés, donne : title, price_usd (converti en USD si besoin), level,
source (URL ou plateforme/requête utilisée). Donne aussi un raisonnement (`reasoning`, 3 à 5
phrases) sur où ce cours se situerait dans cette fourchette, en tenant compte explicitement de deux
facteurs : (1) il est très spécialisé (7 chapitres sur un seul gap précis, pas un programme
généraliste), ce qui tire normalement le prix vers le haut de la fourchette spécialisée ; (2) son
catalogue vidéo est encore incomplet ({video_chapters_ready}/{chapter_count} chapitres avec vidéo),
ce qui justifie un prix de lancement prudent en attendant que la vidéo soit complète.

Réponds avec EXACTEMENT ce format JSON :
{{
  "comparable_courses": [
    {{"title": "...", "price_usd": 0.0, "level": "...", "source": "..."}}
  ],
  "price_range_observed_usd": {{"min": 0.0, "max": 0.0, "median": 0.0}},
  "reasoning": "..."
}}
"""

DEMO_RESEARCH = {
    "comparable_courses": [
        {
            "title": "Production-Ready LLM Agents (Advanced)",
            "price_usd": 149.0,
            "level": "avancé",
            "source": "exemple démo — maven.com",
        },
        {
            "title": "Reliable AI Agents: Error Handling & Evals",
            "price_usd": 99.0,
            "level": "intermédiaire/avancé",
            "source": 'exemple démo — recherche : "AI agent reliability course"',
        },
        {
            "title": "LangGraph in Production",
            "price_usd": 79.0,
            "level": "intermédiaire",
            "source": 'exemple démo — recherche : "LangGraph production course"',
        },
    ],
    "price_range_observed_usd": {"min": 79.0, "max": 149.0, "median": 99.0},
    "reasoning": (
        "(démo) Les cours spécialisés production/fiabilité se situent nettement au-dessus des "
        "cours généralistes ; un catalogue vidéo incomplet et un premier lancement justifient de "
        "démarrer bien en dessous de cette fourchette."
    ),
}


def build_prompt(course: dict) -> str:
    total = len(course["chapters"])
    video_ready = sum(1 for c in course["chapters"] if c.get("has_video"))
    return PROMPT_TEMPLATE.format(
        title=course["title"],
        level=course["level"],
        chapter_count=total,
        description=course["description"],
        video_chapters_ready=video_ready,
    )


def research_comparable_prices(course: dict, demo: bool = False) -> dict:
    if demo:
        return copy.deepcopy(DEMO_RESEARCH)

    response_text = run_prompt(
        prompt=build_prompt(course),
        allowed_tools=["WebSearch"],
        system_prompt=SYSTEM_PROMPT,
        max_turns=16,
    )
    result = extract_json(response_text)
    for field in ("comparable_courses", "price_range_observed_usd", "reasoning"):
        if field not in result:
            raise LLMCallError(f"Recherche pricing incomplète, champ '{field}' manquant : {result!r}")
    return result
