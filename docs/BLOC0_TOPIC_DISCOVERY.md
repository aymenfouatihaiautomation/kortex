# Bloc 0 — Découverte des sujets

## Rôle
Analyser la demande réelle dans le niche fixe "AI Automation" et produire une liste de sujets de
cours candidats, classée par indicateur de demande/lacune de contenu, avec source/raison pour
chaque sujet. Voir `PROJECT_BRIEF_FR.md` section 5 pour la spec exacte.

## Choix d'implémentation
- Niche codée en dur (`config.py::NICHE = "AI Automation"`) — le brief interdit d'étendre à un
  autre niche pour ce Sprint.
- Recherche via l'outil **WebSearch** du Claude Agent SDK plutôt qu'une API tierce (Reddit/
  YouTube/Google Trends) — choix explicite de l'utilisateur, évite d'avoir à provisionner des
  clés API supplémentaires pour ce premier Sprint.
- Sortie JSON strict (schéma ci-dessous) demandée directement dans le prompt, parsée et validée
  côté Python (pas de dépendance à un function-calling structuré spécifique).

## Schéma de sortie
```json
{
  "niche": "AI Automation",
  "generated_at": "ISO-8601",
  "topics": [
    {
      "title": "str",
      "demand_score": 0.0,
      "gap_reason": "str — pourquoi ce sujet est demandé / sous-couvert",
      "sources": ["str", "..."]
    }
  ]
}
```
Trié par `demand_score` décroissant.

## Mode démo
`discover_topics.py --demo` retourne un jeu de données stub (5 sujets plausibles pour AI
Automation) sans appel réseau ni coût API — sert à valider le parsing/tri/sauvegarde et le
câblage avec l'orchestrateur.

## Point d'attention (à documenter après le premier run réel)
Comportement réel de l'outil WebSearch du Claude Agent SDK observé lors du build : authentification
utilisée (session `claude login` vs `ANTHROPIC_API_KEY` séparée) et coût éventuel par recherche.
