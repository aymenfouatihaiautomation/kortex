# Bloc 3 — Production vidéo (Faceless : diapositives + voix)

## Rôle
Transformer le `lesson_script` de chaque chapitre (contenu validé par les Blocs 2 + 3.5) en une
vidéo Faceless : diapositives + voix off, sans avatar. Voir `PROJECT_BRIEF_FR.md` section 3
(bloc 3). **Uniquement les 7 `lesson_script`** — les exercices et le projet final restent des
documents texte (décision du brief, confirmée explicitement par l'utilisateur pour ce Sprint).

## Entrée
`data/bloc2_content_final.json` — le contenu **post-QC** consolidé par
`bloc3_5_quality_control/export_final_content.py` à partir du rapport de qualité le plus récent
(PAS le fichier `bloc2_content_<timestamp>.json` brut du Bloc 2, périmé pour les chapitres
corrigés). `export_final_content.py` refuse de produire ce fichier si un chapitre du rapport n'est
pas `accepted`.

## Architecture

```
lesson_script (texte validé, non modifié)
   │
   ▼ split_sentences()                    — découpage déterministe, Python, réversible
   │
   ▼ LLM (regroupement en diapositives)   — bloc3_video_production/slides.py
   │   ne reçoit QUE des phrases numérotées, ne reproduit JAMAIS le texte,
   │   choisit seulement des bornes (start_sentence/end_sentence) + titre/termes/chiffres clés
   │
   ▼ ElevenLabs TTS + alignement caractère — bloc3_video_production/tts.py
   │   endpoint `with-timestamps` (pas le TTS simple) : renvoie l'audio ET, pour chaque
   │   caractère du texte, l'instant (en secondes) où il est prononcé
   │
   ▼ Calcul des temps d'apparition        — bloc3_video_production/timing.py
   │   repère chaque key_term/key_number dans narration_text, lit son instant de prononciation
   │   dans l'alignement, le convertit en frame (relative au début de la diapositive)
   │
   ▼ Remotion (rendu vidéo)                — bloc3_video_production/render.py + remotion/
       composition générique avec TransitionSeries (fondu enchaîné entre diapositives) +
       animations d'entrée par élément (titre, chips, chiffres), synchronisées sur la parole
```

## Pourquoi ce découpage (et pas un découpage par le LLM du texte lui-même)
Demander au LLM de reproduire de larges portions de `lesson_script` dans sa réponse JSON (pour
« découper » le texte) est fragile : risque de dérive du texte (typos, reformulations
involontaires) sur des paragraphes de 200+ mots, ce qui violerait l'interdiction explicite de ne
pas retoucher le contenu déjà validé. À la place, Python découpe le texte en phrases
(`split_sentences`, déterministe et réversible : `" ".join(split_sentences(t))` reconstruit `t`),
numérote ces phrases, et le LLM ne fait que choisir des **bornes** (`start_sentence`/
`end_sentence`) + un titre visuel + des termes/chiffres à mettre en valeur. Le texte narré de
chaque diapositive est ensuite reconstruit par simple découpe Python de la liste de phrases — la
fidélité verbatim est garantie **par construction**, pas par une validation a posteriori.

## Stack (décidée dans le brief)
- **TTS : ElevenLabs**, modèle `eleven_multilingual_v2`, voix unique fixe pour les 7 vidéos.
  Voix candidate actuelle : `Xb7hH8MSUJpSbSDYk0k2` ("Alice — Clear, Engaging Educator"). **Choix
  final en attente** de la revue utilisateur des échantillons (`voice_samples/`, voir plus bas).
- **Montage : Remotion** (`remotion/`, projet Node/React séparé, + `@remotion/transitions`) — une
  composition générique `ChapterVideo` (1920×1080, 30 fps) :
  - Durée totale calculée dynamiquement (`calculateMetadata`) = somme des durées de diapositives
    MOINS le chevauchement des transitions (`TRANSITION_FRAMES × (nombre de diapositives - 1)`) —
    formule vérifiée par smoke test (durée rendue exactement égale à la durée calculée).
  - Diapositives enchaînées via `TransitionSeries` (`@remotion/transitions`), fondu enchaîné de
    15 frames (0.5s) entre deux diapositives, pas de cut brut.
  - Chaque élément visuel (titre, chip de terme clé, chiffre clé) a sa propre animation d'entrée
    (fondu + léger glissement vers le haut, 15 frames), démarrant à sa propre `startFrame` — le
    titre apparaît en tout début de diapositive, chaque terme/chiffre apparaît au moment réel où
    il est prononcé (voir `timing.py`), pas tous en même temps.
- **Langue** : français (texte narré et voix).

## Mode démo
`produce_video.py --demo` : découpage en diapositives par regroupement fixe de phrases (pas de LLM,
pas d'appel réseau), audio silencieux généré localement (durée estimée par nombre de mots,
**plafonnée à 2 secondes par diapositive** — une durée réaliste rendrait le rendu Remotion d'un
chapitre entier très long sans apporter d'information supplémentaire en mode démo), rendu Remotion
réel (valide tout le câblage mécanique du pipeline sans coût API ElevenLabs).

## Pilote avant scale
`produce_video.py --chapter N` limite la production à un seul chapitre. `--all` (les 7 chapitres)
n'est utilisé qu'après validation explicite du pilote par l'utilisateur — jamais automatiquement.

**Pilote v1 produit** (2026-07-29) : `data/bloc3_video/chapter_1.mp4`, 22 diapositives, 10:05, sans
animations (contenu figé par diapositive, cut brut) — retour utilisateur : "ennuyeux".

**Animations ajoutées suite à ce retour** (transitions en fondu + apparition progressive
synchronisée sur la parole, voir Stack ci-dessus) — validées par smoke test technique (données
synthétiques, durée totale rendue exactement conforme au calcul).

## Preview v2 (audio v1 réutilisé, sans nouveau coût ElevenLabs)
`data/bloc3_video/chapter_1_v2_preview.mp4` (2026-07-29) — montre le NOUVEAU style d'animation
(transitions en fondu, apparition progressive) en réutilisant intégralement l'audio déjà généré et
payé du pilote v1 (les 22 fichiers `remotion/public/audio/chapter_1/slide_*.mp3` réels), sans
aucun nouvel appel ElevenLabs. Demandé explicitement pour ne pas consommer de nouveaux crédits sur
le compte gratuit de l'utilisateur avant qu'il ne décide de passer à un plan payant.

**Comment ça marche (composition Remotion dédiée `ChapterVideoPreview`, `remotion/src/
ChapterVideoPreview.tsx`)** : deux timelines indépendantes de même durée totale (606.0s) —
- **Audio** : les 22 segments réels du v1, rejoués bout à bout dans leurs durées exactes
  d'origine (aucune modification).
- **Visuel** : un NOUVEAU découpage en diapositives régénéré par le LLM (21 diapositives cette
  fois, contre 22 au v1 — variation normale, c'est un nouvel appel), avec des durées
  **proportionnelles au nombre de mots** de chaque diapositive (pas les durées exactes d'origine,
  qui n'existent plus sous cette forme) et des apparitions de termes/chiffres **uniformément
  réparties** dans chaque diapositive (`timing.py::approximate_uniform_start_frames`), PAS
  synchronisées sur la parole réelle — cet audio n'a pas d'alignement `with-timestamps` (endpoint
  intégré après coup, voir plus bas).

**Ce que ce fichier montre, et ce qu'il ne montre PAS** : montre fidèlement le style d'animation
(fondu/glissement, transitions) et donne une idée du rythme général. Ne montre PAS la
synchronisation exacte parole/visuel du vrai v2 (celle-ci nécessite l'alignement ElevenLabs sur un
audio généré avec l'endpoint `with-timestamps`, donc un nouvel appel réel). Un décalage visible
entre un terme mis en avant à l'écran et le moment où il est effectivement prononcé est attendu et
normal dans ce fichier.

**Refactor Remotion associé** : `ChapterVideo.tsx` a été réorganisé (extraction de `SlideVisual`,
le contenu visuel d'une diapositive sans son `<Audio>`) pour être réutilisé tel quel par
`ChapterVideoPreview` — pur refactor, aucun changement de comportement de la composition de
production `ChapterVideo`/`produce_video.py`.

## POC diagramme (retour : diapositives trop "texte seul")
Retour utilisateur sur le preview v2 : les diapositives restent uniquement du texte (titre + chips
+ chiffres en jaune) même quand le sujet appelle un visuel — exemple cité :
"L'architecture en quatre composants clés" (LLM/outils/mémoire/orchestrateur) qui devrait être un
vrai diagramme, pas 3-4 chips. Objectif : un style proche des vidéos éducatives YouTube (schémas,
icônes, couleurs), toujours Faceless (pas d'avatar).

**Preuve de concept ciblée sur cette seule diapositive** (2026-07-29), avant de généraliser :
`remotion/src/ArchitectureDiagram.tsx`, composition `ArchitectureDiagramPOC` (120 frames = 4s,
sans audio, zéro coût ElevenLabs). Rendu :
`data/bloc3_video/architecture_diagram_poc.mp4` (séquence animée) et `.png` (image fixe, dernière
frame) — orchestrateur en hub central (icône `Workflow`, orange), LLM/outils/mémoire en satellites
(icônes `Brain`/`Wrench`/`Database`, un code couleur distinct chacun : bleu/vert/violet), reliés
par de vraies flèches SVG bidirectionnelles (pas des lignes de texte). Apparition progressive
échelonnée (hub d'abord, puis chaque satellite+flèche l'un après l'autre) en réutilisant
`useEntranceStyle`/`TitleBlock` déjà existants — cohérent avec le style d'animation déjà validé.
Contenu (titre, 4 composants, leurs relations) délibérément codé en dur : c'est un test de style
ponctuel, pas encore un schéma générique paramétrable.

Nouvelle dépendance : `lucide-react` (icônes), ajoutée à `remotion/package.json`.

**Bug réel trouvé et corrigé en vérifiant le rendu moi-même** : le titre était rendu quasi invisible
(texte noir par défaut sur fond sombre) — `color: "white"` manquant sur le conteneur `AbsoluteFill`
(les autres compositions l'ont, celle-ci l'avait oublié). Corrigé, revérifié visuellement avant de
livrer.

## POC v2 — direction visuelle "mix" tranchée après retours
Retour sur le POC ci-dessus : fond sombre gardé, mais icônes trop fines (simples contours),
termes/chiffres pas assez mis en valeur, connecteurs pas assez présents. Direction validée :
- Icônes pleines dans un badge de couleur pleine (pas un contour fin) — `lucide-react` gardé (pas
  besoin d'une bibliothèque plus illustrée), mais chaque icône rendue en foncé (`#0f172a`) sur un
  disque de couleur pleine, avec `strokeWidth` augmenté (2.5).
- Termes/chiffres clés sur un bloc de couleur pleine façon surligneur (fond coloré, texte foncé,
  coins asymétriques + légère rotation), pas du texte coloré sur fond uni.
- Connecteurs nettement plus épais (`strokeWidth` 10, contre 3 au premier POC), tout en
  représentant toujours de vraies relations (logique hub-and-spoke inchangée pour l'architecture).
- Nouveau type : flux numéroté (1→2→3→4) pour les diapositives séquentielles/chronologiques, même
  traitement visuel riche (pas de croquis en traits noirs).

Nouveau module partagé `remotion/src/DiagramPrimitives.tsx` (`IconBadge`, `MarkerHighlight`,
`ThickArrow`) réutilisé par les deux POC suivants :

1. **`ArchitectureDiagramV2.tsx`** (composition `ArchitectureDiagramV2POC`) — même structure
   hub-and-spoke que le POC v1, habillée du nouveau traitement. Rendu :
   `data/bloc3_video/architecture_diagram_v2_poc.mp4` / `.png`.
2. **`TimelineDiagram.tsx`** (composition `TimelineDiagramPOC`) — nouvelle diapositive "Une semaine
   en production : la chute" en flux numéroté, chiffres repris verbatim du lesson_script validé
   (10 requêtes en démo → ~4 000 tickets/jour → 82% de précision → facture ×5). Rendu :
   `data/bloc3_video/timeline_diagram_poc.mp4` / `.png`.

**2 bugs réels trouvés en vérifiant les rendus moi-même, avant de livrer** :
1. Pointes de flèches démesurées : les `<marker>` SVG utilisent par défaut
   `markerUnits="strokeWidth"`, donc leur taille se multiplie par l'épaisseur du trait (10) —
   avec `markerWidth=14`, la pointe faisait ~140 unités, écrasant le diagramme. Corrigé avec
   `markerUnits="userSpaceOnUse"` (taille absolue, indépendante de l'épaisseur du trait).
2. Le label "LLM" (peint après la flèche, donc par-dessus) masquait la pointe de flèche montante
   vers le LLM — l'écart entre l'icône et son label était trop faible. Corrigé en augmentant cet
   écart (56px) pour laisser la place à la flèche de se terminer avant le label.

**Prochaine étape (décidée avec l'utilisateur, pas encore lancée)** : une fois ce style v2 validé
sur ces 2 POC, reconstruire le chapitre 1 complet avec ce nouveau langage visuel (et généraliser
les composants en un schéma de données paramétrable, pas encore fait — chaque POC a son contenu
codé en dur).

## Comparaison de voix (`generate_voice_samples.py`)
Génère un extrait ~1-2 min du chapitre 1 (paragraphe avec termes techniques anglais : timeout,
rate limit, LLM, hallucination) synthétisé avec plusieurs voix candidates, audio seul (pas de
vidéo), dans `data/bloc3_video/voice_samples/`. Voix testées : Alice, Matilda, George (choisies
parmi les 22 voix premade du compte comme les plus adaptées à une narration éducative).

**Point de blocage (2026-07-29) : quota ElevenLabs quasiment épuisé.** Seul l'échantillon Alice a
pu être généré (`voice_samples/alice.mp3`, 26.2s) — la génération de l'échantillon Matilda a
échoué avec `quota_exceeded` : **107 crédits restants sur un quota de 10 000, alors que 404
crédits étaient nécessaires** pour cette requête. Le pilote v1 (10 minutes d'audio réel) a
vraisemblablement consommé l'essentiel du quota. Conséquence directe : **aucun nouveau pilote v2
réel (voix + animations) ne peut être produit tant que le quota n'est pas renouvelé ou augmenté** —
un chapitre complet nécessite largement plus de crédits qu'il n'en reste. Signalé explicitement
plutôt que de continuer à tenter des appels qui échoueraient à coup sûr. **Décision utilisateur** :
reste sur le plan gratuit ElevenLabs pour l'instant, passera à un plan payant une fois satisfait de
l'ensemble du système (d'où le preview v2 ci-dessus, qui contourne ce blocage sans dépenser de
nouveaux crédits).

## Sortie
- `data/bloc3_video/chapter_<N>.mp4` — une vidéo par chapitre, 1080p.
- `data/bloc3_video/chapter_1_v2_preview.mp4` — preview du nouveau style d'animation sur l'audio v1
  réutilisé (voir section dédiée ci-dessus) ; pas un livrable final, ni le vrai pilote v2.
- `data/bloc3_video/manifest.json` / `.md` — chapitre → fichier → durée → nombre de diapositives
  (ne référence PAS `chapter_1_v2_preview.mp4`, généré par un script ponctuel hors pipeline
  principal, pas par `produce_video.py`).
- `data/bloc3_video/voice_samples/<nom_voix>.mp3` — échantillons de comparaison de voix (audio
  seul), pas un livrable du pipeline principal.
- `data/bloc3_video/_audio_work/` — fichiers audio bruts par diapositive (avant copie dans
  `remotion/public/`), conservés pour inspection/debug, pas un livrable.
- `remotion/public/audio/chapter_<N>/` — copies des audios utilisées par Remotion pour le rendu
  (nécessaire : Remotion sert `public/` comme racine de `staticFile()`).

## Coûts / prérequis
- Clé `ELEVENLABS_API_KEY` dans `.env` (non versionné) — un appel TTS par diapositive, donc par
  chapitre. Sans clé, `tts.py` lève une erreur explicite (`TTSError`) plutôt que d'échouer en
  silence ou de basculer discrètement en mode démo.
- **Quota ElevenLabs à surveiller** : un chapitre complet (~10 min d'audio réel) consomme une
  grosse partie d'un quota de 10 000 crédits (compte actuel quasiment épuisé après le pilote v1 +
  1 échantillon de voix, voir "Comparaison de voix" ci-dessus). Vérifier le solde avant tout run
  réel (`GET /v1/user/subscription`, nécessite la permission `user_read`, pas encore activée sur
  la clé actuelle).
- L'endpoint `with-timestamps` utilisé pour l'alignement (nécessaire aux animations synchronisées)
  ne coûte pas plus cher que l'endpoint TTS simple chez ElevenLabs (facturation au caractère dans
  les deux cas) — l'alignement est une donnée supplémentaire dans la même réponse, pas un appel en
  plus.
- Node.js + `remotion/` (`npm install` déjà fait, ~262 paquets avec `@remotion/transitions`) —
  confirmé compatible avec Node 24.16 sur cette machine (aucun problème de compatibilité
  rencontré).
- Le rendu Remotion d'un chapitre réel (~10 minutes de vidéo) prend plusieurs minutes en local
  (headless Chrome, plusieurs dizaines de processus parallèles).

## Hors périmètre (rappel explicite)
Pas de Bloc 4 (publication) ni de Bloc 5 (paiement). Le contenu texte déjà validé (Blocs 1/2/3.5)
n'est modifié par aucune étape de ce bloc — seul son découpage en diapositives et sa mise en voix
sont produits. Les 6 chapitres restants ne sont générés qu'après accord explicite de l'utilisateur
sur le pilote.
