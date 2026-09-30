"""Pipeline — Module 1 : agent de veille multi-domaines.

Cherche, pour une liste de domaines de formation (au-delà de la seule niche "AI Automation" des
blocs 0-3.5), les sujets tendance via le web (recherche serveur Anthropic — voir `search_domain_trends`),
les score sur 3 critères, et retourne le TOP N des sujets pas encore produits (voir
`produced_courses.json`).

Volontairement séparé de `bloc0_topic_discovery/discover_topics.py` : ce dernier est câblé en dur
sur `config.NICHE` ("AI Automation", un seul domaine) et n'accepte aucun paramètre de domaine —
le modifier pour le rendre multi-domaines violerait la consigne de ne pas toucher aux blocs
existants. Ce module joue donc le même rôle que le Bloc 0, mais pour N domaines arbitraires,
sans dépendre de lui.

Utilise `common.llm_client.call_chat_api` (API Anthropic directe, `ANTHROPIC_API_KEY`) avec l'outil
serveur `web_search` — PAS le Claude Agent SDK/`claude login` (`run_prompt`, utilisé par le Bloc 0),
qui suppose une session CLI authentifiée absente sur un serveur de production. `call_chat_api` existe
déjà dans `common/llm_client.py` et accepte un paramètre `tools` — aucune modification de ce module
partagé n'est nécessaire."""

import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.llm_client import CostTracker, LLMCallError, call_chat_api, extract_json

PIPELINE_DIR = Path(__file__).resolve().parent
PRODUCED_COURSES_FILE = PIPELINE_DIR / "produced_courses.json"

MODEL = "claude-sonnet-5"

# 6 domaines cibles (liste de départ, ajustable via --domains ou DOMAINS_ENABLED dans
# scheduler_config.json) — restreints à la niche tech, alignés sur les domaines du système
# marketing autonome (voir marketing/agent0_director.py::DOMAINS).
DOMAINS = [
    "AI & Automation",
    "DevOps & Cloud",
    "Cybersecurity",
    "Web Development",
    "Networking & Telecom",
    "Data Science",
]

SYSTEM_PROMPT = (
    "Tu es un analyste de marché spécialisé dans la formation professionnelle en ligne. "
    "Tu réponds UNIQUEMENT avec un objet JSON valide, sans texte avant ou après, "
    "sans bloc de code markdown."
)

PROMPT_TEMPLATE = """\
Domaine : "{domain}".

Cherche sur le web les sujets de formation les plus demandés dans ce domaine EN CE MOMENT :
- Cours les mieux vendus sur Udemy, Coursera, LinkedIn Learning dans ce domaine
- Tendances de recherche Google Trends liées à ce domaine
- Discussions Reddit (sous-reddits pertinents) qui révèlent une demande ou une frustration

Pour CHAQUE sujet candidat identifié à partir de ces recherches (3 à 6 sujets), évalue avec des
VRAIES données trouvées (pas des estimations inventées) :
- search_volume_score (0-10) : popularité / volume de recherche observé
- low_competition_fr_score (0-10) : 10 = très peu de cours FR de qualité sur ce sujet précis,
  0 = marché FR déjà saturé de cours similaires
- observed_avg_price_usd : prix moyen observé sur le marché pour un cours comparable (en USD)
- angle : un angle spécifique différenciant pour aborder ce sujet (pas un titre générique)
- justification : pourquoi ce sujet précisément, en citant les sources concrètes trouvées
- sources : URLs ou noms de sources concrètes utilisées pour ce candidat

Réponds avec EXACTEMENT ce format JSON :
{{
  "domain": "{domain}",
  "candidates": [
    {{
      "topic": "...",
      "angle": "...",
      "search_volume_score": 0,
      "low_competition_fr_score": 0,
      "observed_avg_price_usd": 0.0,
      "justification": "...",
      "sources": ["...", "..."]
    }}
  ]
}}
"""


def _demo_candidates(domain: str) -> dict:
    """Stub déterministe, aucun appel réseau — un seul candidat par domaine, suffisant pour
    exercer tout le câblage (scoring, dédoublonnage, tri) sans dépendre du réseau/API."""
    return {
        "domain": domain,
        "candidates": [
            {
                "topic": f"[DEMO] Sujet tendance en {domain}",
                "angle": "[DEMO] angle différenciant",
                "search_volume_score": 7,
                "low_competition_fr_score": 6,
                "observed_avg_price_usd": 25.0,
                "justification": "[DEMO] Stub déterministe, aucun appel réseau.",
                "sources": ["[DEMO]"],
            }
        ],
    }


def search_domain_trends(domain: str, demo: bool = False, tracker: CostTracker | None = None) -> dict:
    """Cherche les sujets tendance d'UN domaine et retourne `{"domain", "candidates": [...]}`.

    Mode démo : aucun appel réseau, retourne `_demo_candidates(domain)`. Mode réel : un seul appel
    `call_chat_api` avec l'outil serveur `web_search_20250305` (recherche basique — suffisante pour
    ce cas d'usage, pas besoin du filtrage dynamique `web_search_20260209`/`_20260318`), qui laisse
    le modèle chercher/recouper plusieurs sources dans UN seul aller-retour API (le serveur exécute
    les recherches lui-même, pas de boucle client à écrire)."""
    if demo:
        return _demo_candidates(domain)

    response_text = call_chat_api(
        messages=[{"role": "user", "content": PROMPT_TEMPLATE.format(domain=domain)}],
        model=MODEL,
        system_blocks=[{"type": "text", "text": SYSTEM_PROMPT}],
        max_tokens=4096,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 8}],
        tracker=tracker,
    )
    return extract_json(response_text)


def price_score(observed_avg_price_usd: float) -> float:
    """(c) Score prix (0-10) : plus le prix moyen OBSERVÉ sur le marché est élevé, plus l'opportunité
    de pricing est grande pour nous (signal de disposition à payer) — pas une note de qualité du
    cours concurrent. Linéaire, plafonné à 10 à partir de $50 observé (au-delà, la marge de
    manoeuvre de pricing ne progresse plus)."""
    return round(min(10.0, max(0.0, observed_avg_price_usd) / 5.0), 2)


def suggested_price_usd(observed_avg_price_usd: float) -> float:
    """Prix de lancement suggéré : légèrement sous le prix moyen observé (positionnement
    compétitif à l'entrée sur un nouveau domaine, même logique que `pricing_agent/launch_pricing.py`
    pour le cours 1 — undercut de lancement, pas un alignement strict), borné à [$9.99, $49.99]
    pour rester dans la fourchette déjà pratiquée par la plateforme."""
    raw = round(observed_avg_price_usd * 0.8, 2)
    return round(min(49.99, max(9.99, raw)), 2)


def compute_scores(candidate: dict) -> dict:
    """Enrichit un candidat brut (sorti de `search_domain_trends`) avec `price_score`,
    `score_total` (somme des 3 critères, 0-30) et `suggested_price_usd` — pure, testable sans
    aucun appel réseau/LLM."""
    enriched = dict(candidate)
    p_score = price_score(candidate.get("observed_avg_price_usd", 0.0))
    enriched["price_score"] = p_score
    enriched["score_total"] = round(
        candidate.get("search_volume_score", 0)
        + candidate.get("low_competition_fr_score", 0)
        + p_score,
        2,
    )
    enriched["suggested_price_usd"] = suggested_price_usd(candidate.get("observed_avg_price_usd", 0.0))
    enriched["high_price_signal"] = candidate.get("observed_avg_price_usd", 0.0) > 15
    return enriched


def _normalize_title(title: str) -> str:
    """Normalisation pour comparaison de doublons : minuscules, accents retirés, espaces
    multiples réduits — un dédoublonnage exact-après-normalisation, pas de fuzzy matching
    (limitation connue de cette Phase 1, volontairement simple)."""
    ascii_text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_text.strip().lower())


def load_produced_courses(path: Path | str | None = None) -> list[dict]:
    """Charge l'historique des sujets déjà produits. Retourne `[]` si le fichier n'existe pas
    encore (premier lancement) — jamais une exception."""
    path = Path(path) if path else PRODUCED_COURSES_FILE
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return json.load(f).get("produced", [])


def is_topic_produced(topic_title: str, produced: list[dict]) -> bool:
    """Vrai si `topic_title` correspond (après normalisation) à un sujet déjà présent dans
    `produced` (voir `load_produced_courses`)."""
    normalized = _normalize_title(topic_title)
    return any(_normalize_title(p["topic"]) == normalized for p in produced)


def record_produced_course(
    domain: str, topic: str, slug: str | None = None, path: Path | str | None = None
) -> None:
    """Ajoute un sujet à l'historique des sujets produits (append, jamais d'écrasement des entrées
    précédentes) — appelé par `run_pipeline.py` une fois un cours lancé, pour que `get_top_topics`
    ne le proposant plus lors des prochains runs."""
    path = Path(path) if path else PRODUCED_COURSES_FILE
    produced = load_produced_courses(path)
    produced.append(
        {
            "domain": domain,
            "topic": topic,
            "slug": slug,
            "produced_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"produced": produced}, ensure_ascii=False, indent=2), encoding="utf-8")


def get_top_topics(
    domains: list[str] | None = None,
    top_n: int = 5,
    demo: bool = False,
    produced_file: Path | str | None = None,
) -> list[dict]:
    """Cherche les sujets tendance sur tous les `domains` (défaut : `DOMAINS`, les 15 domaines de
    base), les score, filtre ceux déjà produits (voir `produced_courses.json`), et retourne le TOP
    `top_n` trié par `score_total` décroissant.

    Chaque élément retourné : `{"domain", "topic", "angle", "score_total", "score_breakdown":
    {"search_volume_score", "low_competition_fr_score", "price_score"}, "suggested_price_usd",
    "justification", "sources"}`."""
    domains = domains or DOMAINS
    produced = load_produced_courses(produced_file)
    tracker = CostTracker(label="pipeline/domain_agent - get_top_topics") if not demo else None

    all_candidates: list[dict] = []
    for domain in domains:
        result = search_domain_trends(domain, demo=demo, tracker=tracker)
        for candidate in result.get("candidates", []):
            if is_topic_produced(candidate["topic"], produced):
                continue
            enriched = compute_scores(candidate)
            all_candidates.append(
                {
                    "domain": result.get("domain", domain),
                    "topic": enriched["topic"],
                    "angle": enriched.get("angle", ""),
                    "score_total": enriched["score_total"],
                    "score_breakdown": {
                        "search_volume_score": enriched.get("search_volume_score", 0),
                        "low_competition_fr_score": enriched.get("low_competition_fr_score", 0),
                        "price_score": enriched["price_score"],
                    },
                    "suggested_price_usd": enriched["suggested_price_usd"],
                    "high_price_signal": enriched["high_price_signal"],
                    "justification": enriched.get("justification", ""),
                    "sources": enriched.get("sources", []),
                }
            )

    if tracker is not None:
        tracker.print_summary()

    all_candidates.sort(key=lambda c: c["score_total"], reverse=True)
    return all_candidates[:top_n]


def print_topics_table(topics: list[dict]) -> None:
    if not topics:
        print("Aucun sujet disponible (tous déjà produits, ou aucun candidat trouvé).")
        return
    for i, t in enumerate(topics, start=1):
        print(f"\n{i}. [{t['domain']}] {t['topic']} — score {t['score_total']}/30")
        print(f"   Angle : {t['angle']}")
        print(f"   Prix suggéré : ${t['suggested_price_usd']:.2f}")
        print(f"   Justification : {t['justification']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline — Agent de veille multi-domaines")
    parser.add_argument("--demo", action="store_true", help="Mode démo : stubs, aucun appel réseau")
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument(
        "--domains", type=str, default="", help="Liste de domaines séparés par des virgules (défaut : les 15 de base)"
    )
    args = parser.parse_args()

    domains = [d.strip() for d in args.domains.split(",") if d.strip()] or None

    try:
        topics = get_top_topics(domains=domains, top_n=args.top_n, demo=args.demo)
    except LLMCallError as exc:
        print(f"Erreur lors de la recherche de sujets : {exc}")
        raise SystemExit(1) from exc

    print_topics_table(topics)


if __name__ == "__main__":
    main()
