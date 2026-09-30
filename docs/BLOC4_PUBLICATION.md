# Bloc 4 — Publication (LMS simple)

## Rôle
Publier les 7 chapitres validés (texte + exercices + projet final, post-QC Bloc 3.5) sur un LMS
minimal — un seul cours, navigation séquentielle par chapitre — et générer une page de vente
automatique à partir des métadonnées déjà connues (titre, niveau, prérequis, description). Voir
`PROJECT_BRIEF_FR.md` section 4 (bloc 4) : "un LMS simple suffit, pas de système multi-cours élaboré".

## Entrées (lecture seule, aucune n'est modifiée par ce bloc)
- `data/bloc1_curriculum_20260726_122738.json` — titre, niche, niveau, prérequis, `source_topic.
  gap_reason` (réutilisé comme description de vente), et les 7 chapitres (titre/objectifs/points clés).
- `data/bloc2_content_final.json` — contenu final post-QC (`lesson_script`, `comprehension_exercises`,
  `practical_exercise`) exporté par `bloc3_5_quality_control/export_final_content.py`.
- `data/bloc3_video/chapter_1.mp4` — la seule vidéo disponible à ce stade.

## Choix d'architecture

**Flask, application-factory (`create_app()`), pas de base de données.** Un seul cours ne justifie
pas un CMS ni une BDD — le contenu est chargé une fois au démarrage (`content_loader.load_course()`,
fusion Bloc 1 + Bloc 2/3.5) et reste en mémoire, en lecture seule. Seul l'état d'accès (qui a payé)
est persisté, dans un fichier JSON plat (`data/bloc4_lms/access_grants.json`) — cohérent avec le
choix déjà fait au Bloc 3.5 (rapports JSON, pas de BDD) et avec "LMS simple" du brief.

**Choix explicite de la vidéo du chapitre 1 : `chapter_1.mp4` (pilote v1), pas
`chapter_1_v2_preview.mp4`.** Deux candidats existaient à la fin du Bloc 3 :
- `chapter_1_v2_preview.mp4` — animations plus riches, mais timing d'apparition des
  termes/chiffres **approximatif par construction** (`timing.py::approximate_uniform_start_frames`,
  documenté dans `docs/BLOC3_VIDEO_PRODUCTION.md`) puisque cet audio réutilisé n'a pas d'alignement
  parole réel.
- `chapter_1.mp4` — animations plus simples, mais synchronisation EXACTE sur la parole réelle
  (alignement ElevenLabs `with-timestamps`).

Un client payant qui verrait un surlignage de terme clé décalé de la parole le lirait comme un bug,
pas comme un choix esthétique mineur — contrairement au manque de richesse visuelle (diagrammes),
qui est un gap cosmétique déjà connu et accepté temporairement. D'où le choix du v1 exact plutôt que
du v2 approximatif. Le v2 preview et les POC de diagramme restent disponibles sur disque, inchangés,
pour une reconstruction future du chapitre 1 une fois le style visuel validé (Bloc 3, hors périmètre
de ce sprint).

**Accès simple par token, pas d'authentification par mot de passe.** Le brief ne demande pas de
compte utilisateur complet pour ce sprint — juste "octroi automatique de l'accès après paiement
confirmé". `access_store.py` génère un token opaque (`secrets.token_urlsafe(24)`) par achat,
associé à l'email ; visiter `/access/<token>` ouvre une session Flask (cookie signé, pas de mot de
passe à gérer). Le lien est actuellement affiché sur la page de succès et loggé côté serveur
(pas d'envoi d'email — aucun SMTP configuré dans ce projet, hors périmètre de ce sprint).

**Les 6 chapitres sans vidéo affichent un bandeau "vidéo bientôt disponible"**, jamais un blocage —
conforme à la demande explicite ("ne bloque pas l'accès au texte"). `content_loader.load_course()`
marque `has_video = (number == 1)` par construction, pas par un champ manuel.

## Structure
```
bloc4_publication/
  config.py            fichiers sources, chemin de la vidéo choisie, clé Flask, contact légal
                        (le prix vient du pricing agent, voir docs/PRICING_AGENT.md)
  content_loader.py     fusion Bloc 1 + Bloc 2/3.5 -> structure de cours unique pour le rendu ;
                        dérive un `slug` d'URL à partir du titre (slugify(), pas de champ à
                        maintenir séparément)
  access_store.py       grant_access / resolve_token / has_access (JSON plat, un token par achat)
  app.py                create_app() : /, /a-propos, /cours, /cours/<slug>, /access/<token>,
                        /course, /chapter/<n>, /video/..., /terms, /privacy, /refunds,
                        context processor `contact_email`. `courses = [course]` — un seul cours
                        chargé aujourd'hui, mais catalogue/accueil bouclent sur une liste, prêt
                        pour plusieurs cours sans changer l'affichage.
  static/css/
    marketing.css        thème vitrine (fond sombre, dégradé violet/magenta, pleine largeur) —
                        accueil, catalogue, à propos, landing du cours, checkout, pages légales
    reading.css           thème lecture (fond clair, confort de lecture prolongée, colonne de
                        texte ~740px) — course_home, chapter. Même famille de couleurs d'accent
                        que marketing.css, recalibrée pour le contraste sur fond clair.
  templates/
    base_marketing.html  layout partagé thème sombre : nav (Accueil/Cours/À propos + CTA),
                        pied de page avec liens légaux sur toutes les pages vitrine
    base_reading.html     layout partagé thème clair : nav minimale (wordmark + titre du cours),
                        bloc `progress` optionnel (rempli par chapter.html), même pied de page
    home.html             page d'accueil : hero générique (pas spécifique à un domaine) + mise en
                        avant du cours publié (spotlight, jamais de carte vide) + section méthode
    about.html            "À propos" : éditeur (Aymene Ahmed Fouatih, à titre individuel), méthode
    catalog.html           catalogue : boucle sur `courses`, un lien par cours vers sa landing
    landing.html          page de vente du cours : titre/niveau/prérequis/description/prix + plan
                        + bandeau bonus vidéo + formulaire achat (inchangé fonctionnellement)
    course_home.html      tableau de bord des chapitres après accès accordé (thème lecture)
    chapter.html          leçon (paragraphes), vidéo ou bandeau "bientôt disponible", exercices,
                        projet final (dernier chapitre) ou exercice pratique (autres), navigation
                        prev/next, barre de progression (thème lecture)
    terms.html / privacy.html / refunds.html   pages légales publiques (thème vitrine, voir section dédiée)
```

## Routes
| Route | Protection | Rôle |
|---|---|---|
| `GET /` | publique | accueil (vitrine, thème sombre) |
| `GET /a-propos` | publique | à propos de l'éditeur |
| `GET /cours` | publique | catalogue des cours (1 publié aujourd'hui) |
| `GET /cours/<slug>` | publique | landing/page de vente du cours (404 si slug inconnu) |
| `GET /access/<token>` | token valide requis | résout le token, ouvre la session, redirige vers `/course` |
| `GET /course` | session requise (sinon redirigé vers `/cours/<slug>`) | sommaire du cours (thème lecture) |
| `GET /chapter/<int:number>` | session requise (sinon redirigé vers `/cours/<slug>`) | contenu du chapitre, 404 si numéro invalide |
| `GET /video/chapter_1.mp4` | session requise | stream du fichier vidéo choisi (403 sans session) |
| `GET /terms` | publique | conditions d'utilisation |
| `GET /privacy` | publique | politique de confidentialité |
| `GET /refunds` | publique | politique de remboursement |

## Refonte vitrine + thème de lecture (2026-08-03)
Décision produit : transformer le LMS minimal en site vitrine complet, sans jamais toucher la
mécanique de paiement/accès Paddle (présentation uniquement — templates/CSS/structure de page).
Deux thèmes distincts, validés par l'utilisateur sur artefacts avant portage dans les vrais
templates Flask :
- **Thème vitrine (sombre)** — accueil, catalogue, à propos, landing du cours, checkout, pages
  légales. Référence visuelle : frontendmasters.com/fireship.io/totaltypescript.com/epicweb.dev
  (fond quasi-noir, dégradé violet→magenta, pleine largeur, sans-serif à fort caractère). Design
  volontairement générique (pas d'iconographie "développeur") car la plateforme couvre plusieurs
  domaines à terme, même si le seul cours publié aujourd'hui (IA/automatisation) garde son contenu
  spécifique sur sa propre page.
- **Thème lecture (clair)** — course_home, chapter (contenu déjà acheté). Fond clair, texte
  sombre, interligne généreuse, colonne de texte ~740px pour un confort de lecture prolongée.
  Même famille de couleurs d'accent que le thème sombre, recalibrée pour le contraste.

Nouvelles pages (`home.html`, `about.html`, `catalog.html`) et restructuration des routes pour
séparer l'accueil (`/`) de la landing du cours (`/cours/<slug>`) — nécessaire pour que l'accueil
reste générique (multi-cours) tout en gardant une landing dédiée par cours. Conséquence directe :
les redirections `course_home`/`chapter` sans session pointent désormais vers `/cours/<slug>` au
lieu de `/` — comportement de sécurité identique (redirection si pas de session), seule la
destination change ; tests mis à jour en conséquence.

## Exercices interactifs (2026-08-04)

Les exercices de compréhension (`course_home`/`chapter`, thème lecture) sont interactifs, en JS
côté client uniquement (pas de `<form>`, handlers `onclick`) — aucune logique Paddle touchée.

**QCM** : clic sur une option -> feedback immédiat (vert/rouge) + une explication du pourquoi,
affichée que la réponse soit juste ou fausse. Cette explication vient d'un champ `explanation`
ajouté au schéma `comprehension_exercises` de mcq dans `bloc2_content_writing/write_content.py`
(généré par le LLM au moment de la rédaction du cours, donc couvert par la revue du Bloc 3.5 comme
le reste du contenu). Le cours 1, rédigé avant l'ajout de ce champ, a été complété a posteriori par
`bloc2_content_writing/backfill_exercise_explanations.py` — un appel LLM par chapitre, qui ajoute
uniquement `explanation` aux QCM qui n'en ont pas, sans jamais toucher question/options/
correct_answer déjà validés (vérifié par diff avant commit).

**Questions ouvertes** : l'apprenant écrit sa réponse, clique "Corriger", et reçoit une correction
personnalisée générée en temps réel par le LLM (`bloc4_publication/exercise_correction.py`, route
dédiée `POST /chapter/<n>/exercise/<i>/correct` dans `app.py` — volontairement PAS dans
`bloc5_payment`). Le prompt système est calibré pour un ton de correcteur humain, bienveillant :
juger honnêtement juste/faux/partiel puis expliquer en langage naturel librement rédigé, jamais un
gabarit à sections fixes — la route affiche le texte du LLM tel quel, sans aucun post-traitement.

**Appel API Anthropic direct, pas `common.llm_client`/`claude login` (2026-08-04)** : première
route du projet où le serveur de production (Render, headless) doit appeler un LLM lui-même, en
direct, à chaque requête HTTP — contrairement aux blocs 0-3.5 qui tournent en scripts locaux sur
une machine avec une session `claude login`. Bug réel : ce module utilisait d'abord
`common.llm_client.run_prompt` (CLI Claude Code), qui plantait silencieusement en production (CLI
introuvable sur Render) et remontait en 500 générique côté navigateur. Corrigé en appelant l'API
Anthropic classique (package `anthropic`, clé `ANTHROPIC_API_KEY`, facturée séparément de
l'abonnement Claude Code) directement — voir `docs/DEPLOYMENT.md` pour la configuration Render.

Garde-fous (première fois qu'un LLM de ce projet reçoit une saisie utilisateur libre) :
- accès réservé aux sessions authentifiées (même contrôle que `/chapter/<n>`) — jamais de
  correction gratuite pour un visiteur non payant ;
- anti-injection : la réponse de l'apprenant est explicitement traitée comme une DONNÉE dans le
  prompt système, jamais comme une instruction — testé en réel avec une tentative d'injection
  ("ignore tes consignes...") : le correcteur l'a signalée comme hors-sujet sans changer de rôle ;
- réponse plafonnée à 2000 caractères avant tout appel LLM ;
- 3 corrections maximum par exercice (compteur en session Flask, par `chapitre:index`, jamais
  partagé entre exercices) — le nombre restant est renvoyé à chaque appel et affiché ;
- erreurs réseau/LLM renvoyées en 502 avec message clair, jamais de page cassée.

## Pages légales (2026-08-02, exigence Paddle)
Paddle refuse d'approuver un domaine sans ces trois pages, accessibles depuis le site. Contenu
**dérivé du code réel**, pas générique inventé — relu `access_store.py` et `bloc5_payment/routes.py`
avant rédaction :
- **`/terms`** : produit numérique, achat unique non récurrent (pas d'abonnement), lien d'accès
  personnel non partageable, Paddle explicitement identifié comme revendeur officiel (Merchant of
  Record — apparaît sur le relevé bancaire du client).
- **`/privacy`** : liste exhaustive de ce qui est réellement collecté — email (achat + accès),
  enregistrement de vente (email/montant/date/canal, dans `sales_log.json`), cookie de session
  signé (email uniquement, expire à la fermeture du navigateur) — explicitement **aucune donnée de
  carte bancaire** (Paddle traite tout le paiement), **aucun cookie analytique/publicitaire**
  (aucun code de tracking dans le projet). Conservation : pas de suppression automatique
  actuellement (`access_store.py` n'a pas de fonction de suppression) — traitement manuel sur
  demande, dit honnêtement plutôt que d'inventer un mécanisme self-service inexistant.
- **`/refunds`** : produit à accès immédiat, remboursement intégral sous 14 jours sans justification
  (délai/politique = décision produit, ajustable), traité par Paddle sur le moyen de paiement
  d'origine.

**Identité légale finalisée (2026-08-03)** : `terms.html` identifie l'éditeur — "Ce service est édité
par Aymene Ahmed Fouatih, à titre individuel" (particulier, pas de structure enregistrée, pas de
SIRET). `LEGAL_CONTACT_EMAIL` (`bloc4_publication/config.py`, `contact@aymen-automation.site`) est
une adresse réelle créée via Cloudflare Email Routing, redirigée vers la boîte Gmail de
l'utilisateur — confirmée fonctionnelle, plus un placeholder.

## Landing page — mise en avant du contenu réel, pas du manque de vidéo (2026-08-03)
Décision produit : lancer le cours 1 sans miser sur la vidéo (le style visuel riche visé n'est pas
atteignable avec l'outil actuel — voir `docs/BLOC3_VIDEO_PRODUCTION.md`, section pilote riche —,
à reconsidérer après les premières ventes). L'ancien bandeau "Disponibilité vidéo : X sur Y
chapitres" (calculé dynamiquement, mais qui menait avec ce qui MANQUE) a été retiré.

**Nouvelle section "Ce que vous obtenez"** (avant le programme détaillé) : met en avant le contenu
réel du cours — nombre de chapitres, exercices de compréhension, exercice pratique par chapitre,
projet final intégrateur. La vidéo du chapitre 1 reste mentionnée, mais reformulée en bonus discret
(`{% if course.chapters | selectattr("has_video") | list | length > 0 %}`, calculé dynamiquement
comme avant — pas un texte codé en dur), pas en argument central ni en bandeau d'alerte.
**Reste honnête** : ne prétend pas que d'autres chapitres ont une vidéo, la mention reste spécifique
au chapitre 1.

## Mode démo
Aucun mode `--demo` séparé n'est nécessaire ici : contrairement aux blocs précédents, le Bloc 4 ne
fait aucun appel LLM/API externe — il ne fait que lire des fichiers JSON déjà produits et servir du
HTML. La suite pytest (`tests/test_bloc4_*.py`) et le test manuel du serveur réel jouent ce rôle.

## Ce qui reste ouvert (hors code, à décider par l'utilisateur)
- **Prix affiché** : géré depuis 2026-07-30 par le pricing agent (`docs/PRICING_AGENT.md`), en
  dollars, plus un placeholder statique en euros. Prix de lancement proposé ($5) en attente de
  confirmation explicite avant application réelle sur Paddle.
- **Envoi de l'email d'accès** : actuellement affiché sur la page de succès + loggé côté serveur,
  pas envoyé par email (pas de SMTP dans ce projet) — acceptable pour un flux mock/test, à revoir
  avant un lancement réel si le paiement se fait hors ligne (webhook direct, sans repasser par la
  page de succès mock).

## Hors périmètre (rappel explicite)
Pas de retouche au Bloc 3 (vidéo) au-delà du choix du fichier à servir. Pas de modification du
contenu texte validé (Bloc 1/2/3.5) — `content_loader.py` ne fait que lire et réorganiser pour
l'affichage. Pas de Bloc 6 (support/RAG) ni de Bloc 7 (marketing) dans ce sprint. Pas de système
multi-cours.
