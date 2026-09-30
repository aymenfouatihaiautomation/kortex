# Déploiement — LMS (Bloc 4 + Bloc 5) sur Render

## Rôle
Mettre en ligne le LMS (publication + paiement Paddle) sur un service Render **payant** (jamais le
tier gratuit — sa mise en veille après inactivité est incompatible avec un webhook de paiement
fiable, qui doit répondre à tout moment), sous `cours.aymen-automation.site`, un sous-domaine ajouté
à un domaine Namecheap qui héberge déjà une instance n8n — **sans toucher à ses enregistrements DNS
existants**.

## Changements de code nécessaires au déploiement (déjà faits)
1. **`wsgi.py`** (nouveau) : point d'entrée de production. Le serveur de dev Flask
   (`run_lms.py`, `debug=True`) n'est pas fait pour tourner en ligne — `gunicorn wsgi:app` sert
   l'app en production. `run_lms.py` reste l'entrypoint local, inchangé.
2. **`LMS_STATE_DIR`** (`bloc4_publication/config.py`, `pricing_agent/config.py`) : le système de
   fichiers d'un service Render est **éphémère** — tout ce qui est écrit sur disque pendant
   l'exécution (accès payants accordés, prix actif, historique des ventes) serait perdu à chaque
   redéploiement/redémarrage sans un disque persistant. Cette variable redirige
   `access_grants.json`/`pricing_state.json`/`sales_log.json` vers le disque persistant Render
   (`/var/data`) en production ; en local, absente, elle ne change rien (reste dans `data/`).
3. **`FLASK_SECRET_KEY` fail-fast** (`bloc4_publication/config.py`) : refuse de démarrer si
   `RENDER` est détectée (positionnée automatiquement par Render) sans une vraie clé fournie —
   empêche de tourner en ligne avec la clé de dev par défaut (bien connue, donc un vrai risque de
   sécurité : falsification de session).
4. **`.gitignore`** : `data/` reste exclu par défaut (contenu du cours 2 en test, POC vidéo,
   échantillons voix, stores d'état runtime) — seuls les 3 fichiers nécessaires au cours 1
   **déjà publié** sont explicitement réinclus : `bloc1_curriculum_20260726_122738.json`,
   `bloc2_content_final.json`, `bloc3_video/chapter_1.mp4`.
5. **`render.yaml`** (nouveau) : Blueprint Render — service web, plan payant, région, disque
   persistant, variables d'environnement (secrets en `sync: false`, à saisir manuellement).
6. **`requirements.txt`** : ajout de `gunicorn` (serveur WSGI de production — ne tourne que côté
   Render/Linux, pas besoin en local sur Windows).

## Étape 1 — GitHub (dépôt privé)

Git a été installé sur cette machine et le dépôt local est initialisé et commité (98 fichiers,
premier commit fait).

1. Sur [github.com](https://github.com) : **New repository** → nom au choix (ex.
   `ai-edu-platform`) → **Private** → NE PAS cocher "Add a README"/"Add .gitignore"/"Choose a
   license" (le dépôt local a déjà tout).
2. Une fois créé, copier l'URL HTTPS du dépôt (`https://github.com/<utilisateur>/ai-edu-platform.git`).
3. Donner cette URL pour que le push soit fait, ou l'exécuter soi-même :
   ```powershell
   git remote add origin <URL>
   git branch -M main
   git push -u origin main
   ```

## Étape 2 — Render : créer le service via Blueprint

1. [dashboard.render.com](https://dashboard.render.com) → **New +** → **Blueprint**.
2. Connecter le compte GitHub, autoriser Render sur le dépôt privé, le sélectionner → Render lit
   `render.yaml` à la racine automatiquement et propose le service `ai-edu-platform-lms`.
3. Vérifier avant de valider :
   - **Plan : Starter** (ou tout autre tier payant) — **jamais Free**.
   - **Région** : Frankfurt par défaut dans `render.yaml` (proche de la France) — modifiable.
4. **Apply** → Render crée le service web + le disque persistant (1 Go, monté sur `/var/data`).
   Le premier déploiement échouera de démarrer tant que `FLASK_SECRET_KEY` n'est pas défini (voir
   étape 3) — normal, c'est le garde-fou décrit plus haut qui fonctionne.

## Étape 3 — Variables d'environnement à définir dans Render

Dashboard → le service → **Environment**. Celles listées `sync: false` dans `render.yaml`
n'ont pas de valeur pré-remplie et doivent être saisies ici :

| Variable | Valeur | Où l'obtenir |
|---|---|---|
| `FLASK_SECRET_KEY` | une valeur aléatoire longue | générée pour toi cette session (donnée séparément, ne jamais commiter) — pour en regénérer une autre plus tard : `python -c "import secrets; print(secrets.token_hex(32))"` |
| `ANTHROPIC_API_KEY` | une clé API Anthropic | [console.anthropic.com](https://console.anthropic.com) → API Keys. **Obligatoire** pour que la correction LLM des réponses ouvertes (`/chapter/<n>/exercise/<i>/correct`) fonctionne en ligne — voir note ci-dessous. |
| `PADDLE_API_KEY` | *(laisser vide pour l'instant)* | compte vendeur Paddle, une fois approuvé |
| `PADDLE_WEBHOOK_SECRET` | *(laisser vide pour l'instant)* | Paddle dashboard, une fois le webhook déclaré (étape 6) |
| `PADDLE_PRODUCT_ID` | *(laisser vide pour l'instant)* | Paddle dashboard, une fois le Product créé |
| `PADDLE_PRICE_ID` | *(laisser vide pour l'instant)* | optionnel — fallback si le pricing agent n'a pas encore de prix actif |
| `PADDLE_CLIENT_TOKEN` | *(laisser vide pour l'instant)* | Paddle dashboard → Developer Tools → Authentication, une fois le compte prêt (étape 6) — active l'overlay Paddle.js sur la page de cours, voir la note ci-dessous |

**`PADDLE_CLIENT_TOKEN` n'est PAS un secret au même sens que les autres** : Paddle le conçoit pour être exposé dans le HTML/JS servi au navigateur (comme une clé "publishable" Stripe) — il n'autorise aucun appel API serveur, seulement l'ouverture de l'overlay de paiement. Il reste géré comme variable d'env Render (`sync: false`) simplement parce qu'il est spécifique au compte et ne doit pas être codé en dur dans le repo.

**Tu peux déployer maintenant sans les 5 variables Paddle** : le site tournera en mode mock
(exactement comme en local), annoncé explicitement dans les logs Render — aucun paiement réel n'est
possible tant qu'elles sont absentes, mais rien n'est bloqué en silence. `PADDLE_API_BASE` et
`LMS_STATE_DIR` sont déjà fixées par `render.yaml`, pas besoin d'y toucher.

**`ANTHROPIC_API_KEY` — pourquoi une clé séparée alors que Claude Code est déjà utilisé pour
construire ce projet (2026-08-04)** : tous les blocs de génération de contenu (0 à 3.5) tournent en
scripts lancés à la main sur une machine avec une session `claude login` active — le Claude Agent
SDK (`common/llm_client.py`) réutilise cette session, sans clé API séparée. Mais la correction LLM
des réponses ouvertes (`bloc4_publication/exercise_correction.py`) est appelée EN DIRECT par le
serveur Flask de production à chaque clic d'un apprenant sur le site en ligne — un serveur Render
headless n'a ni navigateur ni session `claude login` possible. Bug réel rencontré : sans cette
variable, chaque appel plantait avec une exception non rattrapée (le CLI `claude` est introuvable
sur le serveur), remontant en 500 générique côté navigateur au lieu d'un message clair. Corrigé en
faisant appeler l'API Anthropic classique (package `anthropic`, facturée au token, indépendante de
l'abonnement Claude Code) directement depuis cette route uniquement — le reste du projet (génération
de contenu hors-ligne) continue d'utiliser `claude login` sans changement. Sans cette variable
définie sur Render, la route renvoie une erreur 502 claire ("correcteur momentanément
indisponible") au lieu de planter silencieusement — le reste du site (achat, lecture des chapitres,
QCM) fonctionne normalement même sans elle.

## Étape 4 — Namecheap : ajouter le sous-domaine (sans toucher aux enregistrements n8n)

1. Dans Render : le service → **Settings** → **Custom Domains** → **Add Custom Domain** → saisir
   `cours.aymen-automation.site`. Render affiche l'enregistrement CNAME exact à créer (une cible du
   type `xxxxx.onrender.com` ou équivalent — copier la valeur EXACTE affichée, elle est spécifique
   à ce service).
2. [Namecheap](https://ap.www.namecheap.com) → **Domain List** → `aymen-automation.site` → **Manage**
   → **Advanced DNS**.
3. **Avant toute modification** : repérer les enregistrements déjà présents (l'instance n8n) —
   ne rien modifier dessus, ne rien supprimer.
4. **Add New Record** :
   - Type : `CNAME Record`
   - Host : `cours`
   - Value : la cible exacte donnée par Render à l'étape 1
   - TTL : Automatic
5. **Save**. Un seul enregistrement ajouté, rien d'autre modifié.
6. Propagation DNS : quelques minutes à quelques heures selon le TTL précédent. Une fois le DNS
   résolu, Render provisionne automatiquement un certificat TLS (Let's Encrypt) — le statut du
   domaine personnalisé passe de "Pending" à "Verified" dans le dashboard.

## Étape 5 — Vérification

- `https://cours.aymen-automation.site` doit afficher la landing page (une fois le certificat émis).
- Refaire le parcours déjà validé en local (achat mock → accès → chapitres) directement en ligne.
- Vérifier dans les logs Render que le message de mode mock Paddle apparaît bien au démarrage.
- Tester la correction LLM d'une question ouverte sur un chapitre : si `ANTHROPIC_API_KEY` est
  absente/invalide, la page affiche un message d'erreur clair (pas de plantage) ; si elle est
  correcte, un feedback personnalisé s'affiche après quelques secondes.

## Étape 6 — Une fois le compte Paddle prêt (plus tard, pas maintenant)

1. Paddle dashboard → Developer Tools → Notifications → ajouter un webhook vers
   `https://cours.aymen-automation.site/webhook/paddle` → Paddle génère un secret → le coller dans
   `PADDLE_WEBHOOK_SECRET` sur Render.
2. Créer le Product (et éventuellement un Price initial) dans Paddle → renseigner
   `PADDLE_PRODUCT_ID` (+ `PADDLE_PRICE_ID` en fallback) → définir `PADDLE_API_KEY`.
3. Exécuter `pricing_agent.launch_pricing.apply_launch_price()` **contre l'environnement de
   production** (pas juste en local) pour créer le vrai Price Paddle au prix confirmé ($15) — sans
   ça, le prix affiché reste correct ($15, valeur par défaut) mais le `price_id` actif reste un
   identifiant mock même une fois la clé API réelle configurée. Modalité exacte (exécution ponctuelle
   via un shell Render, ou script à lancer autrement) à définir ensemble le moment venu.
4. Paddle dashboard → Developer Tools → Authentication → récupérer le **client-side token**
   (`live_...`) → le coller dans `PADDLE_CLIENT_TOKEN` sur Render. **Nécessaire pour que le
   bouton "Acheter" fonctionne réellement** : Paddle Billing n'a pas de page de paiement hébergée
   — le checkout s'ouvre via l'overlay Paddle.js chargé sur `/cours/<slug>`
   (`bloc4_publication/templates/landing.html`), qui a besoin de ce token pour s'initialiser.
   Sans lui, le bouton reste sur l'ancien formulaire GET `/checkout/start` (mode mock), qui ne
   déclenche aucun vrai paiement.
5. Une fois ces variables présentes, `is_mock_mode()` bascule automatiquement en mode réel côté
   serveur (webhook), et `paddle_overlay_enabled()` bascule l'affichage du bouton "Acheter" vers
   l'overlay côté client — les deux annoncés explicitement dans les logs, jamais silencieusement.

## Ce qui reste ouvert
- Création effective du dépôt GitHub, du service Render et modification DNS Namecheap : actions
  manuelles sur des comptes externes, à faire par l'utilisateur (ou avec mon aide ponctuelle si les
  accès/URLs sont partagés dans la conversation).
- Clés Paddle réelles toujours absentes (voir étape 6).
- Le disque persistant Render (1 Go) est largement suffisant pour des fichiers JSON plats ; à
  reconsidérer seulement si le projet migre un jour vers une vraie base de données.
