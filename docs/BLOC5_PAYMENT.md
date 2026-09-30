# Bloc 5 — Paiement (Paddle, Merchant of Record)

## Rôle
Intégrer Paddle pour vendre le cours publié au Bloc 4 : page de paiement, webhook de confirmation,
octroi automatique de l'accès au LMS une fois le paiement confirmé. Voir `PROJECT_BRIEF_FR.md`
section 5 (bloc 5) : Paddle en tant que Merchant of Record (gère la TVA/facturation internationale
à la place de l'utilisateur).

## Pourquoi tout est construit et testé en mode mock dès maintenant
Le compte vendeur Paddle réel est en cours de création par l'utilisateur en parallèle de ce sprint
(en attente d'approbation, comme pour tout Merchant of Record). Conformément à la demande explicite
("n'attends pas la clé API réelle pour avancer sur le code"), le code respecte fidèlement la forme
réelle de l'API Paddle Billing v2 (endpoint `/transactions`, payload `items`/`customer`, réponse
`data.id`/`data.checkout.url`, header `Paddle-Signature` au format `ts=...;h1=...`, événements
`transaction.completed`/`transaction.paid`) — brancher les vraies clés plus tard change uniquement
la configuration (`.env`), pas le code.

## Bascule mock / réel : `bloc5_payment/config.py::is_mock_mode()`
```python
def is_mock_mode() -> bool:
    return not PADDLE_API_KEY
```
Même logique que pour ElevenLabs au Bloc 3 : présence de la clé réelle = mode réel automatique,
absence = mode mock automatique — jamais de blocage silencieux, jamais d'attente. Le mode actif est
annoncé explicitement au démarrage du serveur (`run_lms.py`) et à chaque appel webhook (`routes.py`
logge quand la vérification de signature est court-circuitée). **Depuis le pricing agent
(2026-07-30, voir `docs/PRICING_AGENT.md`), ce flag ne dépend plus de `PADDLE_PRICE_ID`** : le prix
et le `price_id` actifs viennent maintenant de `pricing_state.json`, pas d'une variable
d'environnement statique — `is_mock_mode()` ne juge plus que "un compte Paddle réel existe-t-il".

**Ce dont j'ai besoin de la part de l'utilisateur pour passer en mode réel** (à fournir dans `.env`,
jamais en dur dans le code) :
- `PADDLE_API_KEY` — clé API du compte vendeur Paddle (une fois approuvé).
- `PADDLE_PRODUCT_ID` — identifiant du Product Paddle (créé une fois côté dashboard), requis par
  `paddle_client.sync_price_to_paddle()` pour créer un nouveau Price à chaque changement de prix
  (Phase 1 et Phase 2 du pricing agent) — les Price Paddle sont immuables, on en crée un nouveau à
  chaque changement, jamais une modification en place.
- `PADDLE_PRICE_ID` — optionnel, fallback statique utilisé seulement si le pricing agent n'a pas
  encore de prix actif enregistré.
- `PADDLE_WEBHOOK_SECRET` — secret de signature du endpoint webhook, généré par Paddle une fois le
  webhook `/webhook/paddle` déclaré dans le dashboard (nécessite une URL publique — donc un
  déploiement, pas juste `localhost`).
- Optionnel : `PADDLE_API_BASE` pour bascule sandbox (`sandbox-api.paddle.com`, valeur par défaut) vs
  production (`api.paddle.com`) — Paddle sépare complètement compte test et compte réel, avec des
  identifiants distincts.

Tant que ces valeurs sont absentes, le système fonctionne intégralement en mock (voir ci-dessous) et
n'a jamais été bloqué par leur absence.

## Structure
```
bloc5_payment/
  config.py         PADDLE_API_KEY / PADDLE_WEBHOOK_SECRET / PADDLE_PRICE_ID / PADDLE_PRODUCT_ID /
                     PADDLE_API_BASE, is_mock_mode()
  paddle_client.py   create_checkout(email, price_id, amount_usd), verify_webhook_signature(body, header),
                     parse_completed_transaction(payload), sync_price_to_paddle(amount_usd), PaddleError
  routes.py          Blueprint bloc5_bp : /checkout/start, /checkout/mock/<id>[/complete],
                     /webhook/paddle — lit le prix/price_id actifs via pricing_agent.pricing_state,
                     journalise chaque paiement confirmé via pricing_agent.sales_log.record_sale
  templates/
    checkout_mock.html    page de paiement simulée (mode mock uniquement) : confirme l'email et le
                          montant, un seul bouton "payer" qui déclenche /complete
    checkout_success.html  confirmation + montant + lien d'accès (`/access/<token>`)
```

## Flux réel (une fois les clés Paddle configurées)
1. `GET /checkout/start?email=...` → `paddle_client.create_checkout()` appelle l'API Paddle réelle,
   redirige vers la page de paiement hébergée par Paddle (`data.checkout.url`).
2. Le client paie sur l'infrastructure Paddle (formulaires de carte, TVA, etc. — jamais géré par ce
   code, c'est tout l'intérêt d'un Merchant of Record).
3. Paddle notifie `/webhook/paddle` (POST) avec un événement `transaction.completed` signé.
4. `verify_webhook_signature()` vérifie le HMAC-SHA256 avant tout traitement — rejette (403) toute
   requête non authentiquement issue de Paddle.
5. `parse_completed_transaction()` extrait l'email, `access_store.grant_access()` (Bloc 4) crée le
   token, le lien d'accès est loggé côté serveur (pas d'envoi email, voir limitation notée au
   Bloc 4).

## Flux mock (mode actuel, sans compte Paddle réel)
1. `GET /checkout/start?email=...` → `create_checkout()` ne fait aucun appel réseau, génère un
   `transaction_id` local (`mock_<hex>`), redirige vers `/checkout/mock/<id>?email=...`.
2. `checkout_mock.html` affiche l'email et un unique bouton "payer" (aucune vraie collecte de
   carte — simule juste la confirmation).
3. `POST /checkout/mock/<id>/complete` → accorde l'accès immédiatement (équivalent local du
   webhook), affiche `checkout_success.html` avec le lien d'accès.
4. Le vrai endpoint `/webhook/paddle` reste testable indépendamment en mode mock : sans
   `PADDLE_WEBHOOK_SECRET` configuré, `verify_webhook_signature()` retourne toujours `True` (log
   explicite de court-circuit), ce qui permet de tester le chemin webhook réel (JSON `event_type`/
   `data.customer.email`) sans jamais avoir reçu de vrai webhook Paddle.

## Vérification de signature (`verify_webhook_signature`)
Reproduit le format documenté de Paddle : `Paddle-Signature: ts=<timestamp>;h1=<hmac_hex>`, où
`h1 = HMAC-SHA256(secret, "<ts>:<corps brut de la requête>")`. Comparaison en temps constant
(`hmac.compare_digest`). Testé avec un secret réel simulé (`tests/test_bloc5_paddle_client.py`) :
signature valide acceptée, corps altéré rejeté, header malformé rejeté.

## Tests
`tests/test_bloc5_paddle_client.py` (18 tests) : mode mock (aucun appel réseau), mode réel avec
`requests.post` mocké (payload envoyé + erreur HTTP → `PaddleError`), résolution du `price_id`
(explicite > fallback `PADDLE_PRICE_ID` > erreur claire si aucun des deux), `sync_price_to_paddle`
(mock, réel avec `PADDLE_PRODUCT_ID`, erreur claire si absent), vérification de signature
(valide/altérée/malformée/mode mock toujours vraie), extraction d'email (événements acceptés,
ignorés, email manquant). `tests/test_bloc4_app.py` couvre en plus le flux bout-en-bout via le
client de test Flask (checkout mock → accès → chapitres déverrouillés, prix affiché en dollars,
vente journalisée pour la Phase 2 du pricing agent) et le webhook réel (signature valide requise si
un secret est configuré, `403` sinon).

## Vérification réelle effectuée (serveur Flask réellement démarré, pas seulement pytest)
Flux complet rejoué via de vraies requêtes HTTP (`run_lms.py`, `http://127.0.0.1:5050`) : démarrage
checkout → page de paiement mock → confirmation → lien d'accès → session ouverte → chapitres
déverrouillés ; webhook réel `POST /webhook/paddle` avec un JSON `transaction.completed` → `200
{"status": "ok"}` ; vidéo protégée (`403` sans session, `200` + bon `Content-Length` avec session).
Voir `README.md` section Bloc 4/5 pour le détail des étapes.

## Hors périmètre (rappel explicite)
Pas de vraie clé Paddle utilisée (aucune n'était disponible) — tout validé en mock + inspection du
code contre la documentation Paddle Billing v2. Pas de gestion des remboursements/abonnements
récurrents (le brief ne demande qu'un achat unique pour ce cours). Pas d'envoi d'email transactionnel
réel (pas de SMTP configuré dans ce projet).
