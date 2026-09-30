# Pricing agent — Phase 1 (prix de lancement) + Phase 2 (ajustement à la demande)

Ce n'est PAS un bloc du `PROJECT_BRIEF_FR.md` (les numéros 0 à 7 y sont déjà pris) — c'est un
système transverse ajouté sur demande explicite, qui pilote le prix affiché/facturé par le Bloc 4
(landing page) et le Bloc 5 (Paddle). Tout en dollars, cohérent avec Paddle — jamais d'euros.

## Rôle
- **Phase 1** (une fois, avant le tout premier lancement) : rechercher des prix de cours
  comparables, proposer un prix de lancement, attendre une confirmation humaine explicite avant
  tout appel réel à Paddle.
- **Phase 2** (en continu après le lancement) : surveiller un signal de demande (ventes/semaine) et
  augmenter le prix d'un pourcentage fixe si le signal dépasse un seuil, avec un plafond dur jamais
  franchi sans nouvelle validation explicite.

## Principe clé : la recherche informe, ne décide pas
Comme pour `LEVEL`/`PREREQUISITES` (Bloc 1) ou `RUNNING_EXAMPLE` (Bloc 2), le chiffre business
final (`LAUNCH_PRICE_USD = 5.00`, `DEMAND_INCREASE_PCT = 0.15`, `PRICE_CEILING_USD = 79.00`,
`SALES_THRESHOLD_PER_WINDOW = 10`, `REVIEW_WINDOW_DAYS = 7`) est une **constante de `config.py`**,
jamais un output du LLM. La recherche web (`research.py`, même mécanisme que le Bloc 0 — Claude
Agent SDK + outil WebSearch) fournit uniquement le contexte marché et un raisonnement qualitatif
qui accompagnent la proposition affichée à l'utilisateur.

## Phase 1 — `launch_pricing.py`
1. `build_launch_proposal(demo=False)` : charge le cours (Bloc 1+2/3.5, lecture seule), lance la
   recherche marché (exclut explicitement les cours généralistes "0 à agent", cible les cours
   spécialisés intermédiaire/avancé sur la fiabilité des agents en production), calcule les frais
   Paddle estimés (~5% + $0.50) au prix proposé, et assemble une proposition complète. **Aucun
   effet de bord, aucun appel Paddle.**
2. `print_proposal()` affiche la recherche + le raisonnement + le prix proposé, avec un message
   explicite "EN ATTENTE DE CONFIRMATION".
3. `apply_launch_price(proposal)` — **à n'appeler qu'après confirmation explicite de
   l'utilisateur** — appelle `paddle_client.sync_price_to_paddle()` (réel ou mock selon les
   identifiants disponibles) et enregistre le résultat dans `pricing_state.json` avec une entrée
   d'historique `event="launch"`.

### Exécution réelle effectuée, prix reconsidéré et appliqué (2026-07-30)
`python -m pricing_agent.launch_pricing` a été exécuté pour de vrai (recherche web réelle, comme le
Bloc 0). Résultat : 6 cours comparables trouvés (Udemy/DeepLearning.AI entre $0 et $120, cohortes
Maven entre $1800 et $4200 — format différent, mentorat live). Raisonnement du modèle : la
spécialisation du cours le positionnerait normalement en haut de la fourchette "vidéo asynchrone"
($80-120), mais avec seulement 1/7 chapitres en vidéo, le modèle recommande lui-même un prix prudent
plutôt dans une fourchette $10-30 — **plus haut que les $5 initialement fixés**. Cette tension a été
signalée explicitement à l'utilisateur (pas masquée), qui a **reconsidéré le prix de lancement à
$15.00** (`LAUNCH_PRICE_USD` dans `config.py`, mis à jour) : nettement meilleure marge que $5 (frais
Paddle ≈8.3% du prix contre 15%), tout en restant dans la fourchette prudente suggérée par la
recherche vu le catalogue vidéo incomplet. **`apply_launch_price()` exécuté après cette
confirmation explicite** : `pricing_state.json` a maintenant `current_price_usd: 15.0`,
`paddle_price_id: "mock_price_7fff589cad"` (mode mock — aucun compte Paddle réel n'existe encore),
et une entrée d'historique `event: "launch"`. Proposition complète (avec la décision de
reconsidération documentée) : `data/pricing/launch_proposal_20260729_224140.json`.

**Bug réel trouvé et corrigé pendant cette exécution** : `research.py` utilisait `max_turns=8`
(comme le Bloc 0) — insuffisant pour une recherche qui doit trouver 4 à 8 cours comparables via
plusieurs requêtes WebSearch distinctes, provoquant `Reached maximum number of turns (8)`. Augmenté
à `max_turns=16`. Même famille de bug que celui déjà rencontré au Bloc 2
(`revise_chapter_content`, `max_turns` 4→8) : un prompt qui demande plusieurs recherches/étapes a
besoin de plus de tours qu'une génération simple.

## Phase 2 — `demand_pricing.py`
`evaluate_and_apply()` exécute UN cycle de revue :
1. **Idempotent/périodique** : si moins de `REVIEW_WINDOW_DAYS` (7) se sont écoulés depuis
   `last_reviewed_at`, ne fait rien (`action: "skipped_not_due"`) — pas de vérification en temps
   réel après chaque vente individuelle, conforme à la demande.
2. Compte les ventes confirmées (`sales_log.sales_in_window`) sur la fenêtre.
3. Si le compte < seuil (`SALES_THRESHOLD_PER_WINDOW`, 10 par défaut) : `action: "no_change"`,
   journalisé quand même (pas de changement silencieux, mais pas de changement non plus).
4. Si le compte ≥ seuil ET le prix actuel est déjà au plafond ($79) : `action: "ceiling_reached"`,
   aucune augmentation — **jamais dépassé sans nouvelle validation explicite**.
5. Sinon : nouveau prix = `min(prix_actuel × 1.15, 79.00)`, appelle
   `paddle_client.sync_price_to_paddle()` (réel ou mock), journalise `event="demand_increase"`
   avec l'ancien prix, le nouveau prix, le signal observé (ventes vs seuil) et si le résultat a été
   plafonné (`capped`).

Chaque décision (changement ou non) est journalisée dans `pricing_state.json["history"]` —
`old_price_usd` → `new_price_usd` → signal observé → horodatage. Aucune infrastructure de
planification (cron/Task Scheduler/n8n) n'est construite ici — `evaluate_and_apply()` est pensé
pour être invoqué par un déclencheur externe périodique, ajouté plus tard si besoin (hors périmètre
de ce sprint, même logique que "pas de n8n" pour les blocs précédents).

### Testé avec des données mockées (aucune vente réelle pour l'instant — normal, pas un blocage)
`python -m pricing_agent.demand_pricing --demo` : seed un `pricing_state`/`sales_log` isolés
(`data/pricing/demo_*.json`, ne touche jamais les fichiers réels), génère
`SALES_THRESHOLD_PER_WINDOW + 2` ventes synthétiques, exécute un cycle réel, affiche la décision.
Couverture pytest complète (`tests/test_pricing_demand.py`) : sous le seuil (pas de changement), au-
dessus du seuil (augmentation de 15%), augmentation plafonnée à $79, déjà au plafond (aucune
augmentation), revue non due (moins de 7 jours), revue due de nouveau (plus de 7 jours).

## Intégration avec le Bloc 4 (affichage) et le Bloc 5 (Paddle)
- **Bloc 4** (`bloc4_publication/app.py`) : la landing page lit
  `pricing_agent.pricing_state.get_current_price_usd()` à CHAQUE requête (pas caché au démarrage),
  affiché `${prix:.2f}` — remplace l'ancien placeholder statique en euros
  (`COURSE_PRICE_DISPLAY`, supprimé).
- **Bloc 5** (`bloc5_payment/routes.py`) : `checkout_start` lit le prix ET le `price_id` Paddle
  actifs depuis `pricing_state` avant de créer la transaction — plus de prix Paddle statique câblé
  en dur. Chaque paiement confirmé (mock ou webhook réel) enregistre une vente
  (`pricing_agent.sales_log.record_sale`), qui alimente directement le signal de la Phase 2.
- **`paddle_client.sync_price_to_paddle(amount_usd)`** (nouveau) : crée un nouveau Price Paddle
  (Paddle Billing — les Price sont IMMUABLES une fois créés, changer le prix crée toujours un
  nouveau Price rattaché au même Product, jamais une modification en place). Mode mock : retourne
  un identifiant simulé, aucun appel réseau. Mode réel : nécessite `PADDLE_PRODUCT_ID` (nouvelle
  variable, en plus de `PADDLE_API_KEY`) — sans lui, erreur explicite, jamais de blocage silencieux.
- `bloc5_payment.config.is_mock_mode()` a changé de définition : basé uniquement sur
  `PADDLE_API_KEY` (présence d'un compte réel), plus sur `PADDLE_PRICE_ID` — car le prix actif vient
  maintenant de `pricing_state`, pas d'une variable d'environnement statique.

## Schéma de `data/pricing/pricing_state.json`
```json
{
  "current_price_usd": 5.0,
  "paddle_price_id": "mock_price_...",
  "last_reviewed_at": "2026-08-06T00:00:00+00:00",
  "history": [
    {"event": "launch", "old_price_usd": 5.0, "new_price_usd": 5.0, "signal": "...", "at": "..."},
    {"event": "demand_increase", "old_price_usd": 5.0, "new_price_usd": 5.75, "sales_observed": 12, "threshold": 10, "window_days": 7, "capped": false, "at": "..."},
    {"event": "demand_no_change", "sales_observed": 3, "threshold": 10, "window_days": 7, "at": "..."},
    {"event": "demand_ceiling_reached", "sales_observed": 15, "threshold": 10, "window_days": 7, "at": "..."}
  ]
}
```
Avant toute application (Phase 1 pas encore confirmée) : aucun fichier n'existe,
`get_current_price_usd()` retombe sur `LAUNCH_PRICE_USD` (5.00) par défaut — le site affiche donc
déjà le bon prix en mode "brouillon", mais `paddle_price_id` reste `None` tant que
`apply_launch_price()` n'a pas tourné, ce qui bloque explicitement tout paiement RÉEL (mock
fonctionne sans restriction) tant que la Phase 1 n'a pas été formellement confirmée.

## Ce qui reste ouvert
- **Prix de lancement confirmé et appliqué en mode mock ($15.00)** — devra être re-synchronisé
  (`sync_price_to_paddle` en mode réel, via un nouvel appel Phase 1 ou Phase 2) une fois un vrai
  compte Paddle disponible, pour obtenir un `price_id` réel à la place du `mock_price_...` actuel.
- **Clé Paddle réelle toujours absente** (`PADDLE_API_KEY`), et **`PADDLE_PRODUCT_ID`** (nouveau,
  nécessaire pour que `sync_price_to_paddle` fonctionne en mode réel — le Product doit déjà exister
  côté dashboard Paddle).
- Aucune infrastructure de planification pour la Phase 2 (cron/n8n) — à ajouter plus tard si
  besoin, hors périmètre de ce sprint.

## Hors périmètre (rappel explicite)
Pas de Bloc 6 (support/RAG) ni de Bloc 7 (marketing) dans ce sprint. Pas de modification du contenu
texte déjà validé. Pas de retouche au Bloc 3 (vidéo).
