# Marketing KORTEX — système autonome

Système multi-agents de marketing social media pour KORTEX (`https://cours.aymen-automation.site`),
publiant sur Facebook, Instagram et Telegram. **Autonome** : ne dépend d'aucun module du LMS/pipeline
existant (`common/`, `bloc*/`, `pipeline/`) — uniquement `marketing/config.py` en interne.

## Installation

```bash
pip install -r marketing/requirements.txt
cp marketing/.env.example marketing/.env
# puis remplir marketing/.env avec les vrais secrets (jamais commité, voir .gitignore)
```

## Variables requises (`marketing/.env`)

Voir `marketing/.env.example` pour la liste complète et les commentaires. Résumé :

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Agent 1 (web search) + Agent 2 (génération de contenu) |
| `META_PAGE_ACCESS_TOKEN` | Token d'accès Page Facebook/Instagram (courte durée par défaut) |
| `META_APP_SECRET` | Requis pour `refresh_long_lived_token()` |
| `TELEGRAM_BOT_TOKEN` | Bot Telegram publiant sur `@kortex_edu` |
| `FACEBOOK_PAGE_ID`, `INSTAGRAM_ACCOUNT_ID`, `META_APP_ID`, `TELEGRAM_CHANNEL` | Identifiants publics, déjà pré-remplis dans `.env.example` |
| `KORTEX_SITE_URL` | Lien CTA par défaut |
| `POLLINATIONS_ENABLED` | `true`/`false` — désactive la génération d'image si besoin |

Le token Meta (`META_PAGE_ACCESS_TOKEN`) expire en ~1h-2h par défaut. `agent3_publisher.py
--refresh-token` l'échange contre un token longue durée (~60 jours) et met à jour `marketing/.env`
automatiquement.

## Architecture

```
Agent 1 (stratégie)  -> {topic, format, angle, cta_link}
Agent 2 (contenu)    -> {fb_text, ig_caption, ig_hashtags, tg_text, image_path, image_prompt}
Agent 3 (publication)-> publie sur les 3 canaux, logge marketing/logs/publications.json
Agent 4 (analytics)  -> marketing/analytics/daily_report.json + marketing/strategy/performance_history.json
Agent 5 (supervision)-> orchestre 1->4, retry 3x puis skip, logs marketing/logs/supervisor.log
Planificateur        -> déclenche Agent 5 tous les jours à 08:00 (heure locale)
```

Chaque agent est aussi exécutable seul en CLI (voir `--help` sur chaque fichier) pour du débogage
étape par étape.

## Avant toute publication réelle : `--dry-run`

```bash
python marketing/agent5_supervisor.py --dry-run
```

Vérifie que toutes les variables requises sont présentes et que les 4 APIs externes (Anthropic,
Meta Graph, Telegram, Pollinations.ai) sont joignables. **N'appelle jamais** un endpoint de
génération de contenu ou de publication — aucun post, aucune image générée, aucun message envoyé.
Code de sortie 0 si tout est OK, 1 sinon (voir le JSON imprimé pour le détail).

## Run complet

```bash
# Mode démo (stubs, aucun appel réseau, aucune publication) :
python marketing/agent5_supervisor.py --demo

# Run réel (publie réellement sur les 3 canaux) :
python marketing/agent5_supervisor.py

# Planificateur quotidien (bloquant) :
python marketing/scheduler_marketing.py
```

## Écarts connus vs les hypothèses initiales (vérifiés avant implémentation)

- **Pollinations.ai** : appelé en **GET** (`agent2_content.py::generate_image`), pas en POST —
  vérifié par test direct, aucune route POST documentée pour ce service.
- **tmpfiles.org** : `agent3_publisher.py::upload_to_tmpfiles()` existe pour complétude API, mais
  n'est **pas** utilisée par `publish_instagram()` — l'URL qu'il renvoie sert une page HTML
  d'atterrissage, pas l'image brute (vérifié par `curl -I`, y compris la variante `/dl/`). Le flux
  Instagram réel réutilise directement l'URL Pollinations.ai (confirmée servir l'image brute).

## Fichiers jamais commités (voir `.gitignore` racine)

`marketing/.env`, `marketing/generated/images/*`, `marketing/logs/*`, `marketing/analytics/*`,
`marketing/strategy/*` (sauf les `.gitkeep`) — mêmes règles que `pipeline/` pour le reste du dépôt.
