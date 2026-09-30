# PROJECT_BRIEF — Plateforme éducative entièrement automatisée par IA

## 1. Vue d'ensemble

Construction d'une plateforme éducative en ligne, en démarrant avec un seul niche (**AI Automation** — automatisation des processus métier par l'IA : n8n, agents IA, automatisation de workflows), dont les opérations essentielles sont gérées par de l'automatisation IA : découverte des sujets, planification du programme, rédaction du contenu et des exercices, production vidéo, contrôle qualité, publication, paiement, et support des apprenants.

**Objectif de chaque cours** : que l'apprenant en ressorte avec un niveau pratique réel — théorique et appliqué — via des leçons + des exercices par chapitre + un projet final, et non une simple explication théorique superficielle.

**Modèle économique** : vente d'accès aux cours via une plateforme LMS propriétaire, avec traitement des paiements via Paddle (Merchant of Record), et retrait des revenus via Payoneer (déjà relié au compte CCP existant).

## 2. Décisions stratégiques validées (non renégociables à ce stade)

- Plateforme éducative propriétaire (LMS développé en interne), pas de dépendance à Udemy ou à des plateformes intermédiaires
- Paddle comme passerelle de paiement (Merchant of Record), en raison de son support des retraits via Payoneer
- Un seul niche pour le lancement : **AI Automation** — aucune extension vers d'autres domaines avant d'avoir prouvé la qualité et la stabilité du système sur ce niche
- Vidéos Faceless (diapositives + voix TTS) dans la première phase, pas d'avatar humain généré par IA
- Chaque cours doit obligatoirement inclure : des leçons + des exercices par chapitre + un projet final
- Un bloc de contrôle qualité indépendant avant publication (bloc 3.5), avec une logique de révision distincte du bloc de production, et une boucle de correction automatique plutôt qu'un arrêt manuel
- Le bloc marketing/distribution (bloc 7) **n'est pas reporté à la fin du projet** — une version simplifiée (un seul canal de distribution + SEO basique + page d'atterrissage automatique) est construite en parallèle de la phase de lancement (blocs 4/5), et non après

## 3. Structure complète des blocs

| Bloc | Fonction |
|---|---|
| 0 | Découverte des sujets — analyse de la demande réelle (tendances de recherche, lacunes de contenu) dans le niche AI Automation |
| 1 | Planification du programme — construction de la structure du cours : chapitres, objectifs pédagogiques, séquence logique |
| 2 | Rédaction du contenu + exercices + projet final |
| 3 | Production vidéo (Faceless : TTS + diapositives) |
| 3.5 | **Portail de contrôle qualité** (avant publication) : couverture du programme, cohérence logique, exactitude des informations, qualité des exercices. En cas d'échec → retour automatique au bloc 2 pour réécriture |
| 4 | Publication automatique sur le LMS propriétaire + création automatique d'une page d'atterrissage pour chaque cours |
| 5 | Paiement (Paddle) et octroi automatique de l'accès |
| 6 | Support des apprenants (RAG avec ChromaDB) pour répondre aux questions sur le cours |
| 7 (simplifié, en parallèle des blocs 4/5) | Publication automatique d'un extrait/teaser sur YouTube + SEO basique (titre/description/mots-clés générés à partir des données du bloc 0) |

## 4. Stack technique

- **n8n** — orchestration générale du flux de travail entre les blocs
- **LangGraph** — pour le bloc 3.5 (boucle de décision : révision → correction → nouvelle révision)
- **LangChain / Claude Agent SDK** — pour les blocs de planification (1) et de rédaction du contenu (2)
- **ChromaDB** — base de connaissances de chaque cours (bloc 6)
- **Airtable** — tableau de suivi du statut des cours (en production / en attente de contrôle qualité / publié)
- **TTS** (par ex. ElevenLabs) + **Remotion** ou équivalent pour le montage vidéo (bloc 3)
- **Paddle** pour le paiement, **LMS propriétaire** (développé en interne ou open source) pour la publication

## 5. Premier Sprint (périmètre actuel uniquement — ne pas le dépasser)

**Commence uniquement par le bloc 0 et le bloc 1.** Ne construis pas le bloc 3 (vidéo), le bloc 5 (paiement), ni aucun bloc ultérieur dans ce Sprint.

**Bloc 0 — Découverte des sujets :**
- Input : niche fixe = "AI Automation"
- Output attendu : liste de sujets de cours candidats dans ce niche, classés selon un indicateur de demande/lacune de contenu, avec la source/raison de sélection pour chaque sujet

**Bloc 1 — Planification du programme :**
- Input : un sujet unique sélectionné parmi les résultats du bloc 0
- Output attendu : structure complète du cours (titre, chapitres, pour chaque chapitre : objectifs pédagogiques + points clés), avec vérification que les chapitres suivent une séquence logique (chaque chapitre s'appuie sur le précédent)

**Critère d'acceptation du Sprint :** exécuter le bloc 0 puis le bloc 1 successivement sur le niche AI Automation, et obtenir la structure d'un cours complet, prête pour une revue manuelle de ta part.

## 6. Ce qu'il ne faut pas faire à ce stade

- Ne pas construire le bloc 3.5 avant qu'il y ait un contenu réel issu du bloc 2 à réviser
- Ne pas sélectionner plus d'un sujet pour le premier test
- Ne pas étendre à un niche autre que AI Automation
- Ne pas intégrer Paddle ni aucune passerelle de paiement dans ce Sprint
