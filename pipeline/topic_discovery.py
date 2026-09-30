"""Pipeline — Équivalent Bloc0 en API directe (autonomie 100%, sans `claude login`).

Le vrai `bloc0_topic_discovery/discover_topics.py` utilise le Claude Agent SDK (`run_prompt`),
qui suppose une session CLI `claude login` déjà authentifiée sur la machine — incompatible avec un
run entièrement autonome sur un serveur (aucune session interactive). Ce module joue le même rôle
(confirmer/affiner un sujet via une recherche web réelle) mais via `common.llm_client.call_chat_api`
(API Anthropic directe, `ANTHROPIC_API_KEY`) + l'outil serveur `web_search` — jamais le SDK.

Le vrai Bloc0 original N'EST PAS modifié et reste utilisable indépendamment (ex. pour la niche
"AI Automation" historique, en local avec `claude login`).

Contrairement à `bloc0_topic_discovery.discover_topics` (qui explore un domaine et retourne
PLUSIEURS candidats à choisir), ce module prend UN sujet déjà choisi (par
`pipeline/domain_agent.py` ou manuellement) et le CONFIRME/AFFINE avec une recherche web réelle —
retourne exactement la forme que `bloc1_curriculum_planning.plan_curriculum` attend en entrée pour
son paramètre `topic` : `{"title", "gap_reason"}` (avec `demand_confirmed`/`sources` en plus,
ignorés par le Bloc 1 mais conservés pour le rapport/l'audit)."""

import argparse
import json
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.llm_client import CostTracker, LLMCallError, call_chat_api, extract_json

MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = (
    "Tu es un concepteur pédagogique qui vérifie et affine un sujet de formation avant de lancer sa "
    "production. Tu réponds UNIQUEMENT avec un objet JSON valide, sans texte avant ou après, sans "
    "bloc de code markdown."
)

PROMPT_TEMPLATE = """\
Domaine : "{domain}".
Sujet proposé : "{topic}".
{angle_line}

Cherche sur le web pour VÉRIFIER la demande RÉELLE de ce sujet précis (pas seulement du domaine en
général) : recherches récentes, discussions, cours existants et leur qualité perçue, tendances.

À partir de ce que tu trouves, produis :
- title : un titre final clair pour ce cours — reste fidèle au sujet proposé (n'en change pas),
  mais peux l'affiner si tes recherches suggèrent une formulation plus précise/porteuse
- gap_reason : la raison, appuyée par ce que tu as trouvé sur le web, pour laquelle CE sujet précis
  mérite d'être produit maintenant (demande réelle observée, absence de bonne offre FR, etc.)
- demand_confirmed : true si tes recherches confirment une demande réelle pour ce sujet, false si
  tes recherches suggèrent le contraire (marché déjà saturé, pas de demande observée, etc.)
- sources : URLs ou noms de sources concrètes utilisées

Réponds avec EXACTEMENT ce format JSON :
{{"title": "...", "gap_reason": "...", "demand_confirmed": true, "sources": ["...", "..."]}}
"""


def _demo_topic(topic: str, domain: str) -> dict:
    """Stub déterministe, aucun appel réseau. `title` reste le sujet reçu TEL QUEL (pas de suffixe
    ajouté ici) : le stub démo de `bloc1_curriculum_planning.plan_curriculum` ajoute déjà son
    propre suffixe (" — Formation complète") au titre qu'il reçoit — en ajouter un ici aussi
    produirait un titre démo doublé lors d'un `--dry-run` bout-en-bout."""
    return {
        "title": topic,
        "gap_reason": f"[DEMO] Sujet confirmé sans appel réseau pour le domaine {domain}.",
        "demand_confirmed": True,
        "sources": ["[DEMO]"],
    }


def discover_topic(
    topic: str,
    domain: str,
    angle: str = "",
    demo: bool = False,
    tracker: CostTracker | None = None,
) -> dict:
    """Confirme/affine UN sujet déjà choisi via l'API Anthropic directe + `web_search`. Retourne
    `{"title", "gap_reason", "demand_confirmed", "sources"}` — `demand_confirmed=False` n'arrête
    PAS le pipeline (aucune instruction explicite pour bloquer sur ce signal) : c'est un signal
    d'audit reporté dans le checkpoint/rapport, à l'opérateur de décider s'il rejette le cours via
    `pipeline/validate.py`."""
    if demo:
        return _demo_topic(topic, domain)

    angle_line = f"Angle proposé : {angle}" if angle else ""
    response_text = call_chat_api(
        messages=[{"role": "user", "content": PROMPT_TEMPLATE.format(domain=domain, topic=topic, angle_line=angle_line)}],
        model=MODEL,
        system_blocks=[{"type": "text", "text": SYSTEM_PROMPT}],
        max_tokens=2048,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
        tracker=tracker,
    )
    result = extract_json(response_text)

    if not result.get("title"):
        raise LLMCallError(f"Réponse invalide de topic_discovery : champ 'title' manquant : {result!r}")
    result.setdefault("gap_reason", "")
    result.setdefault("demand_confirmed", None)
    result.setdefault("sources", [])
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pipeline — Confirmation/affinage d'un sujet (équivalent Bloc0, API directe, sans claude login)"
    )
    parser.add_argument("--topic", type=str, required=True)
    parser.add_argument("--domain", type=str, required=True)
    parser.add_argument("--angle", type=str, default="")
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()

    try:
        result = discover_topic(args.topic, args.domain, angle=args.angle, demo=args.demo)
    except LLMCallError as exc:
        print(f"Erreur : {exc}")
        raise SystemExit(1) from exc

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
