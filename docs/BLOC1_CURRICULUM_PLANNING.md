# Bloc 1 — Planification du programme

## Rôle
À partir d'un sujet unique sélectionné parmi les résultats du bloc 0, produire la structure
complète du cours (titre, chapitres, objectifs pédagogiques + points clés par chapitre), avec
vérification que les chapitres suivent une séquence logique. Voir `PROJECT_BRIEF_FR.md` section 5.

## Choix d'implémentation
- Un seul appel Claude Agent SDK (pas de LangGraph — cette boucle de décision est réservée au
  bloc 3.5 dans le brief), avec sortie JSON strict.
- Le champ `builds_on_previous` de chaque chapitre force le modèle à expliciter le lien logique
  avec le chapitre précédent — c'est le mécanisme qui matérialise "vérification que les chapitres
  suivent une séquence logique" sans boucle d'agents séparée.
- Validation programmatique (pas de LLM) après génération : numérotation en séquence sans trou,
  ≥1 objectif et ≥1 point clé par chapitre, `builds_on_previous` non vide sauf chapitre 1. Un seul
  retry avec le message d'erreur injecté dans le prompt si la validation échoue — pas de boucle
  infinie.
- `level` et `prerequisites` sont des métadonnées **fixées par décision produit** (constantes
  `LEVEL`/`PREREQUISITES` dans `plan_curriculum.py`), pas générées par le LLM : ce Sprint 1 vise un
  niveau intermédiaire (fiabiliser un agent existant pour la production), pas une introduction aux
  agents IA depuis zéro.

## Schéma de sortie
```json
{
  "title": "str",
  "niche": "AI Automation",
  "level": "intermédiaire",
  "prerequisites": "str — ce que l'apprenant doit déjà savoir avant ce cours",
  "source_topic": {"title": "str", "gap_reason": "str"},
  "generated_at": "ISO-8601",
  "chapters": [
    {
      "number": 1,
      "title": "str",
      "learning_objectives": ["str", "..."],
      "key_points": ["str", "..."],
      "builds_on_previous": "str (N/A - premier chapitre, pour le chapitre 1)"
    }
  ]
}
```

## Mode démo
`plan_curriculum.py --demo --topic "..."` retourne une structure de cours stub (3 chapitres)
sans appel réseau — valide le parsing/validation/sauvegarde/export Markdown.

## Export pour revue manuelle
En plus du JSON, un fichier Markdown lisible (`data/bloc1_curriculum_<timestamp>.md`) est généré
pour la revue manuelle demandée par le critère d'acceptation du Sprint.
