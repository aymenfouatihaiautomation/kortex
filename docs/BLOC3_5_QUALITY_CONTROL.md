# Bloc 3.5 — Portail de contrôle qualité

## Rôle
Évaluer le contenu produit par le Bloc 2 et décider, chapitre par chapitre, s'il est publiable en
l'état ou doit repartir en réécriture ciblée — avec boucle de correction automatique et
escalade vers une revue manuelle après un nombre maximal de tentatives. Voir
`PROJECT_BRIEF_FR.md` section 3 (bloc 3.5) : "logique de révision distincte du bloc de production,
boucle de correction automatique plutôt qu'un arrêt manuel".

## Entrées
- Le curriculum validé du Bloc 1 (`data/bloc1_curriculum_20260726_122738.json`) — chapitres non
  modifiés, utilisés en lecture seule comme référence de ce qui était attendu.
- Le contenu généré par le Bloc 2 (`data/bloc2_content_20260727_091307.json`) — évalué chapitre
  par chapitre.

## Choix d'architecture — pourquoi LangGraph, et pourquoi un réviseur séparé
- **LangGraph** est utilisé ici (et nulle part ailleurs dans ce projet) car c'est exactement pour ce
  bloc qu'il est prévu dans le brief (section 4) : une boucle de décision review -> correction ->
  nouvelle review a besoin d'un état qui persiste entre itérations et d'un routage conditionnel —
  c'est un state machine, pas un simple appel séquentiel.
- **Le réviseur (`reviewer.py`) est un module séparé du rédacteur (`bloc2_content_writing`)**, avec
  son propre system prompt ("réviseur externe et indépendant... pars du principe que le contenu
  contient probablement au moins un défaut") — délibérément différent et plus sceptique que le
  system prompt d'auteur du Bloc 2. C'est la contrainte explicite de l'utilisateur pour éviter que
  le biais de génération qui a produit le contenu soit aussi celui qui le valide.
- **La réécriture ciblée reste dans le Bloc 2** (`revise_chapter_content`, ajoutée à
  `bloc2_content_writing/write_content.py`) : c'est l'auteur qui corrige, le réviseur ne fait
  qu'évaluer et lister des problèmes précis (`issues`, chacun avec un champ concerné et une
  description actionnable) — le Bloc 3.5 orchestre l'échange entre les deux, il ne rédige rien
  lui-même.

## Graphe LangGraph (`graph.py`), un par chapitre
```
START -> review --(accepted)--> accept -> END
            |
            |--(needs_revision, tentatives restantes)--> revise --> review (boucle)
            |
            +--(needs_revision, plus de tentatives)--> escalate -> END
```
- `review` : appelle `reviewer.review_chapter` (contenu actuel + spec Bloc 1 du chapitre + du
  chapitre précédent pour la cohérence logique).
- `revise` : appelle `write_content.revise_chapter_content` avec les `issues` de la dernière
  review — ne régénère PAS le chapitre from scratch, ne corrige que les champs signalés.
- `max_attempts` (défaut 3) borne le nombre de cycles revise->review : au-delà, `status="escalated"`
  au lieu d'une boucle infinie, conformément à la demande explicite de l'utilisateur.

## Critères évalués (4, tous doivent passer pour `accepted`)
1. **coverage** — le script de leçon couvre-t-il réellement les objectifs/points clés du Bloc 1 ?
2. **logical_coherence** — le chapitre s'appuie-t-il correctement sur le précédent ?
3. **technical_accuracy** — erreurs factuelles/techniques dans le contenu ?
4. **exercise_quality** — les exercices mesurent-ils la compétence visée, au niveau "intermédiaire" ?

Chaque critère reçoit un verdict `pass`/`fail` + une justification textuelle. `overall_verdict` =
`accepted` seulement si les 4 critères passent, sinon `needs_revision` avec une liste `issues` non
vide (chacune : `field` + `description` actionnable).

## Schéma de sortie (rapport global)
```json
{
  "course_title": "str",
  "niche": "AI Automation",
  "level": "intermédiaire",
  "max_attempts": 3,
  "generated_at": "ISO-8601",
  "summary": {"accepted": 0, "escalated": 0},
  "chapters": [
    {
      "chapter_number": 1,
      "chapter_title": "str",
      "final_status": "accepted | escalated",
      "attempts_used": 0,
      "final_review": { "...schéma reviewer.py..." },
      "final_content": { "...contenu Bloc 2, éventuellement corrigé..." },
      "history": [
        {"stage": "review", "attempt": 0, "overall_verdict": "...", "issues": [...]},
        {"stage": "revise", "attempt": 1, "issues_addressed": [...]}
      ]
    }
  ]
}
```

## Correction manuelle ciblée (hors boucle automatique)
`quality_control.apply_manual_correction()` couvre un second mode d'usage : un humain a examiné un
rapport (typiquement un chapitre `escalated`), a lui-même identifié les problèmes précis à corriger,
et veut UNE correction ciblée + UNE évaluation de confirmation — sans relancer tout le cycle
`max_attempts` du graphe LangGraph. Elle appelle exactement une fois
`bloc2_content_writing.write_content.revise_chapter_content` puis une fois
`bloc3_5_quality_control.reviewer.review_chapter`, et retourne une entrée de rapport substituable
dans un rapport existant (`history` utilise les stages `manual_revise`/`manual_review`, distincts de
`revise`/`review` pour les distinguer visuellement dans l'export Markdown). Si le chapitre est encore
`escalated` après cette correction manuelle, ce statut reflète un désaccord persistant entre la
correction demandée et le jugement du réviseur — à arbitrer par un humain, pas à re-boucler
automatiquement.

## Mode démo
`quality_control.py --demo` utilise un reviewer stub déterministe (rejette une fois puis accepte)
et un reviser stub — valide tout le câblage du graphe (boucle review->revise->review, arrêt sur
accepted) sans appel réseau.

## Export pour revue manuelle
`data/bloc3_5_quality_report_<timestamp>.json` (rapport complet) +
`data/bloc3_5_quality_report_<timestamp>.md` (historique des itérations et verdicts par critère,
lisible pour la revue manuelle — en particulier pour tout chapitre `escalated`).

## Hors périmètre (rappel explicite)
Pas de Bloc 3 (vidéo) dans ce Sprint. La structure des 7 chapitres et le fil rouge validés aux
Blocs 1 et 2 ne sont pas modifiés par ce bloc — seul le contenu (`lesson_script`,
`comprehension_exercises`, `practical_exercise`) peut être réécrit.
