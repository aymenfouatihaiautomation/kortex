# Bloc 2 — Rédaction du contenu + exercices + projet final

## Rôle
À partir de la structure de cours validée par le Bloc 1 (chapitres, objectifs, points clés — non
modifiés), rédiger pour chaque chapitre : le script complet de la leçon, des exercices de
compréhension, et un exercice pratique appliqué au fil rouge du cours. Le dernier chapitre reçoit en
plus un projet final complet et détaillé. Voir `PROJECT_BRIEF_FR.md` section 3 (bloc 2).

## Entrée
Le fichier JSON produit par le Bloc 1 (`data/bloc1_curriculum_<timestamp>.json`), par défaut le
curriculum validé du Sprint 1 (`data/bloc1_curriculum_20260726_122738.json`). **Les 7 chapitres
(title, learning_objectives, key_points, builds_on_previous) sont traités en lecture seule et ne
sont jamais modifiés** — le Bloc 2 ne fait qu'ajouter du contenu par-dessus.

## Choix d'implémentation
- **Un appel Claude Agent SDK par chapitre** (pas un seul gros appel pour les 7 chapitres) : chaque
  leçon est un texte développé, regrouper les 7 dans un seul appel risquerait la troncature et rend
  le retry par chapitre impossible. `allowed_tools=[]` — pas de WebSearch nécessaire, c'est de la
  rédaction pédagogique à partir d'un plan déjà validé, pas de la recherche.
- **Fil rouge fixé une fois pour toutes** (constante `RUNNING_EXAMPLE` dans `write_content.py`,
  pas généré par le LLM) et injecté identique dans les 7 prompts : un agent IA qui automatise le
  traitement des tickets de support client (classification, recherche dans une base de
  connaissances, réponse, escalade humaine si confiance insuffisante). Sans ce fil rouge fixé en
  dur, 7 appels LLM indépendants inventeraient chacun un exemple différent, cassant la cohérence
  pédagogique demandée.
- **Deux règles ajoutées au `SYSTEM_PROMPT` après le premier run réel du Bloc 3.5** (contrôle
  qualité), qui avait trouvé ces deux défauts de façon récurrente sur plusieurs chapitres : (1) tout
  chiffre inventé à but pédagogique doit être signalé comme illustratif, jamais présenté comme une
  donnée réelle non sourcée ; (2) tout exemple chiffré impliquant un calcul (budgets de temps,
  seuils) doit être vérifié arithmétiquement — le nombre d'éléments annoncés dans le texte doit
  correspondre exactement à ce qui est utilisé dans le calcul final. S'applique à toute génération
  et réécriture future (Bloc 2 ET les réécritures ciblées appelées par le Bloc 3.5, qui partagent le
  même `SYSTEM_PROMPT`).
- Même pattern retry que le Bloc 1 : validation programmatique après génération, 1 retry avec le
  message d'erreur injecté si invalide, pas de boucle infinie (le bloc 3.5/LangGraph reste hors
  périmètre).
- Le dernier chapitre de la liste (`chapter["number"] == len(chapters)`, pas un `7` codé en dur) est
  traité comme projet final — généralise correctement si un futur curriculum a un nombre de
  chapitres différent de 7.

## Schéma de sortie (par chapitre)
```json
{
  "chapter_number": 1,
  "chapter_title": "str (copié du Bloc 1, référence uniquement)",
  "lesson_script": "str — texte pédagogique développé, plusieurs paragraphes",
  "comprehension_exercises": [
    {"question": "str", "type": "mcq", "options": ["str", "..."], "correct_answer": "str"},
    {"question": "str", "type": "short_answer", "options": null, "correct_answer": "str"}
  ],
  "practical_exercise": {
    "title": "str",
    "instructions": "str",
    "expected_outcome": "str"
  }
}
```

Pour le **dernier chapitre (projet final)**, `practical_exercise` contient en plus :
```json
{
  "deliverables": ["str", "..."],
  "step_by_step_instructions": ["str", "..."],
  "evaluation_criteria": ["str", "..."]
}
```

## Mode démo
`write_content.py --demo` génère un contenu placeholder générique par chapitre (basé sur le titre du
chapitre chargé, quel que soit le curriculum) — valide le chargement/validation/sauvegarde/export
sans appel réseau.

## Export pour revue manuelle
`data/bloc2_content_<timestamp>.json` (structure complète) + `data/bloc2_content_<timestamp>.md`
(script de leçon, exercices et projet final rendus en Markdown lisible).

## Hors périmètre (rappel)
Pas de Bloc 3 (vidéo), pas de Bloc 3.5 (contrôle qualité/LangGraph) dans ce Sprint. La structure des
7 chapitres du Bloc 1 n'est pas modifiée par ce bloc.
