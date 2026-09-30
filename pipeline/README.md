# Pipeline — Système autonome de création de cours multi-domaines (Phase 1)

Génère des cours dans des domaines variés (Finance, RH, Marketing, Excel, Droit, Comptabilité,
Développement personnel, Data pour managers, Négociation, Gestion de projet, Vente, Immobilier,
Entrepreneuriat, Communication, Leadership — voir `domain_agent.DOMAINS`), au-delà de la seule
niche "AI Automation" des blocs 0-3.5 existants, **sans modifier ces blocs**.

## Ce que fait ce module, et ce qu'il ne fait pas

- Il produit des **brouillons de cours validés** sur disque (`data/<slug>/pipeline/*.json` +
  `data/<slug>/exam_questions.json`) et un rapport (`pipeline/reports/<slug>_report.{json,txt}`).
- Il **ne publie rien automatiquement** sur le site : `bloc4_publication` charge aujourd'hui UN
  seul cours, via des chemins de fichiers fixes (`bloc4_publication/config.py`) — brancher
  plusieurs cours dans le catalogue public est un changement de plateforme, hors du périmètre de
  cette Phase 1 (garde-fou explicite : ne pas toucher au code de la plateforme). Un cours validé
  (`data/<slug>/READY_TO_PUBLISH`) est prêt à être branché manuellement, pas branché lui-même.

## Modules

| Fichier | Rôle |
|---|---|
| `domain_agent.py` | Cherche les sujets tendance (web) sur N domaines, les score, retourne le TOP 5 non encore produits. |
| `run_pipeline.py` | Enchaîne Bloc0 (sujet déjà choisi) → Bloc1 → Bloc2 → Bloc3.5 → Bloc7 pour UN sujet, avec checkpoint/reprise et validation humaine. |
| `scheduler.py` | Boucle de fond : respecte le quota/délai, choisit un sujet, lance `run_pipeline` sans interaction, journalise. |
| `validate.py` | Revue humaine des cours produits par le scheduler (en attente de validation). |

## Comment lancer

### Un cours ponctuel (sujet choisi à la main)

```bash
python pipeline/run_pipeline.py --topic "Maîtriser les tableaux croisés dynamiques Excel" \
  --domain "Excel avancé" --price 24.99
```

- `--skip-qc` : saute le Bloc 3.5 (contrôle qualité) — contenu du Bloc 2 utilisé tel quel.
- `--dry-run` : force le mode démo sur TOUS les blocs (aucun appel réseau/coût réel) — pour tester
  le câblage de bout en bout gratuitement.
- `--resume` : reprend un cours interrompu (checkpoint dans `pipeline/checkpoints/<slug>.json`) à
  partir de la première étape non terminée, sans tout relancer.
- `--non-interactive` : pas de prompt de validation (utilisé par `scheduler.py`) — le cours part
  directement en `pending_validation.json`.

À la fin, le pipeline affiche le rapport et demande `oui`/`non`/`attente` (délai de 30 min, réponse
automatique `attente` sinon) :

- `oui` → `data/<slug>/READY_TO_PUBLISH`
- `non` → `data/<slug>/REJECTED`
- `attente` → rien n'est écrit, le cours est ajouté à `pipeline/pending_validation.json` (voir
  `validate.py`)

### Trouver un sujet automatiquement

```bash
python pipeline/domain_agent.py --top-n 5
python pipeline/domain_agent.py --demo --top-n 3          # sans appel réseau/coût
python pipeline/domain_agent.py --domains "Finance personnelle,Vente"
```

### Le planificateur autonome (2 cours/jour, 12h d'écart minimum)

```bash
python pipeline/scheduler.py &            # boucle de fond
python pipeline/scheduler.py --status     # état actuel, prochaine exécution
python pipeline/scheduler.py --next       # quel sujet serait produit ensuite (sans lancer)
python pipeline/scheduler.py --pause      # met en pause
python pipeline/scheduler.py --resume     # relance
python pipeline/scheduler.py --once       # une seule itération (test manuel) au lieu de la boucle
```

Chaque cours produit par le scheduler part en `attente` (pas de terminal pour valider) — c'est
`pipeline/validate.py` qui donne le feu vert ensuite.

### Valider les cours en attente

```bash
python pipeline/validate.py               # tous les cours en attente, un par un
python pipeline/validate.py --slug <slug> # un seul
```

## Configuration

`pipeline/scheduler_config.json` :

```json
{
  "MAX_COURSES_PER_DAY": 2,
  "MIN_HOURS_BETWEEN_COURSES": 12,
  "DOMAINS_ENABLED": ["Finance personnelle", "..."],
  "AUTO_SELECT_TOPIC": true
}
```

## Fichiers d'état (non versionnés — voir `.gitignore`)

| Fichier | Rôle |
|---|---|
| `pipeline/produced_courses.json` | Historique des sujets déjà produits (évite les doublons dans `domain_agent`). |
| `pipeline/checkpoints/<slug>.json` | Progression par cours (Bloc0-7), pour `--resume`. |
| `pipeline/reports/<slug>_report.{json,txt}` | Rapport final d'un cours (titre, plan, chapitres, QC, coût estimé, prix). |
| `pipeline/pending_validation.json` | File d'attente des cours à valider (`validate.py`). |
| `pipeline/scheduler_state.json` | Quota du jour, dernier cours, pause/reprise. |
| `pipeline/scheduler.log` | Journal du planificateur. |

## Limitations connues de cette Phase 1

- Dédoublonnage des sujets par correspondance exacte (après normalisation) — pas de similarité
  sémantique.
- Le coût en tokens du rapport final est une **estimation** obtenue en interceptant les lignes
  `[cost]` déjà imprimées par chaque appel LLM (les blocs 1/2/3.5 ne renvoient pas leur
  `CostTracker` interne à l'appelant — les modifier violerait la consigne de ne pas toucher aux
  blocs existants), pas une valeur garantie exacte.
- `bloc1_curriculum_planning.plan_curriculum` est câblé sur `config.NICHE` au niveau module ;
  `run_pipeline.py` patche temporairement ce nom (`unittest.mock.patch.object`) le temps de
  l'appel pour lui faire produire un curriculum dans le domaine demandé, sans toucher son code.
- Pas de publication automatique dans le catalogue public (voir plus haut).
