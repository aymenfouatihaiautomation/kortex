"""Bloc 2 — Rédaction du contenu, exercices et projet final pour un curriculum validé (Bloc 1).

Voir docs/BLOC2_CONTENT_WRITING.md pour la spec complète. Les chapitres du curriculum d'entrée
(title, learning_objectives, key_points, builds_on_previous) sont traités en lecture seule et ne
sont jamais modifiés par ce bloc.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.llm_client import CostTracker, LLMCallError, call_llm_api, extract_json
from config import DATA_DIR

DEFAULT_CURRICULUM_FILE = DATA_DIR / "bloc1_curriculum_20260726_122738.json"

MODEL = "claude-sonnet-5"  # rédaction pédagogique, cf. mapping bloc->modèle validé

SYSTEM_PROMPT = (
    "Tu es un rédacteur pédagogique expert en formation professionnelle. "
    "Tu réponds UNIQUEMENT avec un objet JSON valide, sans texte avant ou après, "
    "sans bloc de code markdown. "
    "Deux règles non négociables, ajoutées après un run réel du Bloc 3.5 (contrôle qualité) ayant "
    "trouvé ces deux défauts récurrents : "
    "(1) tout chiffre inventé à but pédagogique (statistique, exemple de calcul) doit être signalé "
    "explicitement comme illustratif (ex. 'prenons un exemple illustratif typique'), jamais présenté "
    "comme une donnée réelle non sourcée ; "
    "(2) tout exemple chiffré impliquant un calcul (durées cumulées, budgets, seuils) doit être "
    "vérifié arithmétiquement avant d'être inclus — le nombre d'éléments annoncés dans le texte "
    "(tentatives, intervalles) doit correspondre exactement à ce qui est utilisé dans le calcul final."
)

# Fil rouge fixé une fois pour toutes (pas généré par le LLM) et injecté identique dans les 7
# prompts, pour garantir la cohérence de l'exercice pratique d'un chapitre à l'autre.
RUNNING_EXAMPLE = (
    "Un agent IA qui automatise le traitement des tickets de support client entrants : il "
    "classifie la demande, interroge une base de connaissances (RAG) pour trouver l'information "
    "pertinente, rédige une réponse, et escalade à un humain si sa confiance est insuffisante."
)

PROMPT_TEMPLATE = """\
Niche : "{niche}".
Cours : "{course_title}" (niveau {level}).
Chapitre {number}/{total} : "{chapter_title}".

Objectifs pédagogiques de ce chapitre (déjà validés, NE PAS les modifier, les développer) :
{objectives}

Points clés à couvrir (déjà validés, NE PAS les modifier, les développer) :
{key_points}

Fil rouge du cours (à réutiliser de façon cohérente dans l'exercice pratique de CE chapitre,
ne l'invente pas différemment) :
{running_example}

Génère le contenu pédagogique complet de ce chapitre :
1. lesson_script : le script complet de la leçon — un texte pédagogique développé de plusieurs
   paragraphes qui explique et illustre chaque point clé, PAS une simple reformulation des points
   clés en une phrase chacun.
2. comprehension_exercises : au moins 3 exercices de compréhension (QCM ou question courte)
   validant la compréhension des objectifs pédagogiques ci-dessus. Pour CHAQUE exercice de type
   QCM (mcq), ajoute un champ "explanation" : 2 à 4 phrases qui expliquent pourquoi la bonne
   réponse est correcte et, si utile, pourquoi les autres options sont des erreurs courantes.
   Cette explication est affichée à l'apprenant juste après qu'il ait répondu (bonne ou mauvaise
   réponse) : elle doit être pédagogique et autonome, pas une simple reformulation de la réponse.
3. practical_exercise : un exercice pratique appliqué au fil rouge ci-dessus, cohérent avec ce
   chapitre précis.
{extra_instructions}

Réponds avec EXACTEMENT ce format JSON :
{{
  "chapter_number": {number},
  "chapter_title": "{chapter_title}",
  "lesson_script": "...",
  "comprehension_exercises": [
    {{"question": "...", "type": "mcq", "options": ["...", "..."], "correct_answer": "...", "explanation": "..."}},
    {{"question": "...", "type": "short_answer", "options": null, "correct_answer": "..."}}
  ],
  "practical_exercise": {{
    "title": "...",
    "instructions": "...",
    "expected_outcome": "..."{extra_json_fields}
  }}
}}
"""

# Format "video" (2026-08-07) : contenu principal = vidéo, PAS de lesson_script complet qui
# doublonnerait ce que la vidéo montre — voir FORMAT_ENUM (bloc1_curriculum_planning.plan_curriculum).
VIDEO_PROMPT_TEMPLATE = """\
Niche : "{niche}".
Cours : "{course_title}" (niveau {level}).
Chapitre {number}/{total} : "{chapter_title}".

Objectifs pédagogiques de ce chapitre (déjà validés, NE PAS les modifier, les développer) :
{objectives}

Points clés à couvrir (déjà validés, NE PAS les modifier, les développer) :
{key_points}

Fil rouge du cours (à réutiliser de façon cohérente dans l'exercice pratique de CE chapitre,
ne l'invente pas différemment) :
{running_example}

Ce chapitre a été désigné comme un chapitre VIDÉO (raison du choix : {format_reasoning}) : le
contenu principal est une démonstration/un flux visuel, PAS un texte de leçon complet — ne produis
surtout pas un texte qui ferait doublon avec ce que la vidéo montre.

Génère le contenu pédagogique complet de ce chapitre :
1. video_script : le script/plan de la vidéo à produire —
   - summary : 2-3 phrases résumant ce que la vidéo montre.
   - scenes : liste ordonnée d'au moins 3 scènes, chacune avec :
     - beat : le titre court de l'étape (ex. "Ouvrir n8n et créer un workflow")
     - narration : ce qui est dit/expliqué à l'oral pendant cette scène
     - visual : ce qui est montré à l'écran pendant cette scène (ex. "capture d'écran de l'éditeur
       n8n, glisser-déposer d'un node HTTP Request")
2. written_complement : un COURT complément écrit (quelques phrases, PAS un texte de leçon
   complet) qui apporte une information UTILE et NON MONTRÉE dans la vidéo (ex. un récapitulatif à
   garder sous les yeux, un point de vigilance, un lien avec le chapitre suivant) — ne réexplique
   PAS ce que la vidéo montre déjà.
3. comprehension_exercises : au moins 3 exercices de compréhension (QCM ou question courte)
   validant la compréhension des objectifs pédagogiques ci-dessus, à partir de ce que la vidéo
   enseigne. Pour CHAQUE exercice de type QCM (mcq), ajoute un champ "explanation" : 2 à 4 phrases
   qui expliquent pourquoi la bonne réponse est correcte et, si utile, pourquoi les autres options
   sont des erreurs courantes. Cette explication est affichée à l'apprenant juste après qu'il ait
   répondu (bonne ou mauvaise réponse) : elle doit être pédagogique et autonome.
4. practical_exercise : un exercice pratique appliqué au fil rouge ci-dessus, cohérent avec ce
   chapitre précis.
{extra_instructions}

Réponds avec EXACTEMENT ce format JSON :
{{
  "chapter_number": {number},
  "chapter_title": "{chapter_title}",
  "video_script": {{
    "summary": "...",
    "scenes": [
      {{"beat": "...", "narration": "...", "visual": "..."}},
      {{"beat": "...", "narration": "...", "visual": "..."}},
      {{"beat": "...", "narration": "...", "visual": "..."}}
    ]
  }},
  "written_complement": "...",
  "comprehension_exercises": [
    {{"question": "...", "type": "mcq", "options": ["...", "..."], "correct_answer": "...", "explanation": "..."}},
    {{"question": "...", "type": "short_answer", "options": null, "correct_answer": "..."}}
  ],
  "practical_exercise": {{
    "title": "...",
    "instructions": "...",
    "expected_outcome": "..."{extra_json_fields}
  }}
}}
"""

# Format "mix" (2026-08-07) : vidéo ET texte, COMPLÉMENTAIRES — le prompt exige explicitement un
# partage des rôles (redundancy_check_notes) que le Bloc 3.5 pourra vérifier (voir reviewer.py).
MIX_PROMPT_TEMPLATE = """\
Niche : "{niche}".
Cours : "{course_title}" (niveau {level}).
Chapitre {number}/{total} : "{chapter_title}".

Objectifs pédagogiques de ce chapitre (déjà validés, NE PAS les modifier, les développer) :
{objectives}

Points clés à couvrir (déjà validés, NE PAS les modifier, les développer) :
{key_points}

Fil rouge du cours (à réutiliser de façon cohérente dans l'exercice pratique de CE chapitre,
ne l'invente pas différemment) :
{running_example}

Ce chapitre a été désigné comme un chapitre MIXTE vidéo + texte (raison du choix :
{format_reasoning}) : les deux doivent être COMPLÉMENTAIRES, jamais redondants. Répartis
clairement les rôles, par exemple : la vidéo montre la démonstration/le flux visuel, le texte sert
de référence à part entière/donne du code à copier/approfondit ce que la vidéo ne montre pas.
N'écris JAMAIS en texte ce que la vidéo montre déjà, et inversement.

Génère le contenu pédagogique complet de ce chapitre :
1. video_script : le script/plan de la vidéo (la partie DÉMONSTRATION/FLUX du chapitre) —
   - summary : 2-3 phrases résumant ce que la vidéo montre.
   - scenes : liste ordonnée d'au moins 3 scènes, chacune avec "beat" (titre court), "narration"
     (ce qui est dit), "visual" (ce qui est montré à l'écran).
2. lesson_script : le texte de RÉFÉRENCE complémentaire (la partie que la vidéo NE montre PAS) —
   un texte pédagogique développé qui approfondit, donne du code/des définitions précises à
   consulter, sans réexpliquer ce que la vidéo couvre déjà.
3. redundancy_check_notes : 2-3 phrases qui expliquent EXPLICITEMENT le partage des rôles entre la
   vidéo et le texte de CE chapitre précis (ce que fait l'un, ce que fait l'autre) — utilisé par le
   contrôle qualité pour vérifier l'absence de redondance.
4. comprehension_exercises : au moins 3 exercices de compréhension (QCM ou question courte)
   validant la compréhension des objectifs pédagogiques ci-dessus (vidéo + texte combinés). Pour
   CHAQUE exercice de type QCM (mcq), ajoute un champ "explanation" : 2 à 4 phrases qui expliquent
   pourquoi la bonne réponse est correcte et, si utile, pourquoi les autres options sont des
   erreurs courantes.
5. practical_exercise : un exercice pratique appliqué au fil rouge ci-dessus, cohérent avec ce
   chapitre précis.
{extra_instructions}

Réponds avec EXACTEMENT ce format JSON :
{{
  "chapter_number": {number},
  "chapter_title": "{chapter_title}",
  "video_script": {{
    "summary": "...",
    "scenes": [
      {{"beat": "...", "narration": "...", "visual": "..."}},
      {{"beat": "...", "narration": "...", "visual": "..."}},
      {{"beat": "...", "narration": "...", "visual": "..."}}
    ]
  }},
  "lesson_script": "...",
  "redundancy_check_notes": "...",
  "comprehension_exercises": [
    {{"question": "...", "type": "mcq", "options": ["...", "..."], "correct_answer": "...", "explanation": "..."}},
    {{"question": "...", "type": "short_answer", "options": null, "correct_answer": "..."}}
  ],
  "practical_exercise": {{
    "title": "...",
    "instructions": "...",
    "expected_outcome": "..."{extra_json_fields}
  }}
}}
"""

FINAL_CHAPTER_INSTRUCTIONS = """\
Ce chapitre est également le PROJET FINAL du cours. practical_exercise doit décrire ce projet
final complet tel que défini par ses objectifs pédagogiques (assemblage de l'agent complet,
golden dataset, dashboard de coûts/latence, runbook d'incident), avec des consignes assez
détaillées pour qu'un apprenant puisse le réaliser SEUL, sans accompagnement. En plus de
title/instructions/expected_outcome, ajoute dans practical_exercise :
- deliverables : liste des livrables concrets attendus
- step_by_step_instructions : liste d'étapes détaillées et actionnables, dans l'ordre
- evaluation_criteria : liste de critères permettant de vérifier que le projet est réussi
"""

FINAL_CHAPTER_JSON_FIELDS = """,
    "deliverables": ["...", "..."],
    "step_by_step_instructions": ["...", "..."],
    "evaluation_criteria": ["...", "..."]"""

RETRY_SUFFIX = """

ATTENTION : ta réponse précédente était invalide pour la raison suivante :
{errors}
Corrige ces problèmes et renvoie un JSON complet et valide respectant strictement le format demandé.
"""

# Réécriture ciblée appelée par le Bloc 3.5 (contrôle qualité) après un verdict "needs_revision" —
# reste dans le Bloc 2 car c'est l'auteur qui réécrit, le réviseur (Bloc 3.5) ne fait qu'évaluer.
REVISE_PROMPT_TEMPLATE = """\
Niche : "{niche}".
Cours : "{course_title}" (niveau {level}).
Chapitre {number}/{total} : "{chapter_title}".

Objectifs pédagogiques de ce chapitre (déjà validés, NE PAS les modifier) :
{objectives}

Points clés à couvrir (déjà validés, NE PAS les modifier) :
{key_points}

Fil rouge du cours (déjà validé, NE PAS le changer) :
{running_example}

Voici le contenu ACTUEL de ce chapitre, jugé insuffisant par un réviseur externe indépendant :
--- CONTENU ACTUEL ---
lesson_script : {current_lesson_script}
comprehension_exercises : {current_exercises_json}
practical_exercise : {current_practical_exercise_json}

--- PROBLÈMES SIGNALÉS À CORRIGER (ne réécris QUE les champs concernés, garde le reste identique) ---
{issues}
{extra_instructions}

Réponds avec EXACTEMENT ce format JSON complet (même si un champ n'a pas changé, renvoie-le) :
{{
  "chapter_number": {number},
  "chapter_title": "{chapter_title}",
  "lesson_script": "...",
  "comprehension_exercises": [
    {{"question": "...", "type": "mcq", "options": ["...", "..."], "correct_answer": "...", "explanation": "..."}}
  ],
  "practical_exercise": {{
    "title": "...",
    "instructions": "...",
    "expected_outcome": "..."{extra_json_fields}
  }}
}}
"""

VIDEO_REVISE_PROMPT_TEMPLATE = """\
Niche : "{niche}".
Cours : "{course_title}" (niveau {level}).
Chapitre {number}/{total} : "{chapter_title}" (chapitre VIDÉO — pas de lesson_script complet).

Objectifs pédagogiques de ce chapitre (déjà validés, NE PAS les modifier) :
{objectives}

Points clés à couvrir (déjà validés, NE PAS les modifier) :
{key_points}

Fil rouge du cours (déjà validé, NE PAS le changer) :
{running_example}

Voici le contenu ACTUEL de ce chapitre, jugé insuffisant par un réviseur externe indépendant :
--- CONTENU ACTUEL ---
video_script : {current_video_script_json}
written_complement : {current_written_complement}
comprehension_exercises : {current_exercises_json}
practical_exercise : {current_practical_exercise_json}

--- PROBLÈMES SIGNALÉS À CORRIGER (ne réécris QUE les champs concernés, garde le reste identique) ---
{issues}
{extra_instructions}

Réponds avec EXACTEMENT ce format JSON complet (même si un champ n'a pas changé, renvoie-le) :
{{
  "chapter_number": {number},
  "chapter_title": "{chapter_title}",
  "video_script": {{
    "summary": "...",
    "scenes": [{{"beat": "...", "narration": "...", "visual": "..."}}]
  }},
  "written_complement": "...",
  "comprehension_exercises": [
    {{"question": "...", "type": "mcq", "options": ["...", "..."], "correct_answer": "...", "explanation": "..."}}
  ],
  "practical_exercise": {{
    "title": "...",
    "instructions": "...",
    "expected_outcome": "..."{extra_json_fields}
  }}
}}
"""

MIX_REVISE_PROMPT_TEMPLATE = """\
Niche : "{niche}".
Cours : "{course_title}" (niveau {level}).
Chapitre {number}/{total} : "{chapter_title}" (chapitre MIXTE vidéo + texte complémentaires).

Objectifs pédagogiques de ce chapitre (déjà validés, NE PAS les modifier) :
{objectives}

Points clés à couvrir (déjà validés, NE PAS les modifier) :
{key_points}

Fil rouge du cours (déjà validé, NE PAS le changer) :
{running_example}

Voici le contenu ACTUEL de ce chapitre, jugé insuffisant par un réviseur externe indépendant :
--- CONTENU ACTUEL ---
video_script : {current_video_script_json}
lesson_script : {current_lesson_script}
redundancy_check_notes : {current_redundancy_check_notes}
comprehension_exercises : {current_exercises_json}
practical_exercise : {current_practical_exercise_json}

--- PROBLÈMES SIGNALÉS À CORRIGER (ne réécris QUE les champs concernés, garde le reste identique ;
si le problème signalé est une redondance entre vidéo et texte, corrige le partage des rôles et
mets à jour redundancy_check_notes en conséquence) ---
{issues}
{extra_instructions}

Réponds avec EXACTEMENT ce format JSON complet (même si un champ n'a pas changé, renvoie-le) :
{{
  "chapter_number": {number},
  "chapter_title": "{chapter_title}",
  "video_script": {{
    "summary": "...",
    "scenes": [{{"beat": "...", "narration": "...", "visual": "..."}}]
  }},
  "lesson_script": "...",
  "redundancy_check_notes": "...",
  "comprehension_exercises": [
    {{"question": "...", "type": "mcq", "options": ["...", "..."], "correct_answer": "...", "explanation": "..."}}
  ],
  "practical_exercise": {{
    "title": "...",
    "instructions": "...",
    "expected_outcome": "..."{extra_json_fields}
  }}
}}
"""


def build_revise_prompt(
    curriculum: dict,
    chapter: dict,
    total_chapters: int,
    is_final_chapter: bool,
    current_content: dict,
    issues: list[dict],
    error_feedback: str | None = None,
    running_example: str = RUNNING_EXAMPLE,
) -> str:
    """Dispatche sur le format du chapitre (`chapter.get("format", "text")`) — un chapitre sans
    champ `format` (cours 1, généré avant cette fonctionnalité) suit le gabarit "text" existant,
    inchangé."""
    content_format = chapter.get("format", "text")
    objectives = "\n".join(f"- {o}" for o in chapter["learning_objectives"])
    key_points = "\n".join(f"- {kp}" for kp in chapter["key_points"])
    issues_text = "\n".join(f"- [{i['field']}] {i['description']}" for i in issues)

    common_kwargs = dict(
        niche=curriculum.get("niche", ""),
        course_title=curriculum["title"],
        level=curriculum.get("level", "N/A"),
        number=chapter["number"],
        total=total_chapters,
        chapter_title=chapter["title"],
        objectives=objectives,
        key_points=key_points,
        running_example=running_example,
        current_exercises_json=json.dumps(current_content["comprehension_exercises"], ensure_ascii=False),
        current_practical_exercise_json=json.dumps(current_content["practical_exercise"], ensure_ascii=False),
        issues=issues_text,
        extra_instructions=FINAL_CHAPTER_INSTRUCTIONS if is_final_chapter else "",
        extra_json_fields=FINAL_CHAPTER_JSON_FIELDS if is_final_chapter else "",
    )

    if content_format == "video":
        prompt = VIDEO_REVISE_PROMPT_TEMPLATE.format(
            current_video_script_json=json.dumps(current_content.get("video_script"), ensure_ascii=False),
            current_written_complement=current_content.get("written_complement", ""),
            **common_kwargs,
        )
    elif content_format == "mix":
        prompt = MIX_REVISE_PROMPT_TEMPLATE.format(
            current_video_script_json=json.dumps(current_content.get("video_script"), ensure_ascii=False),
            current_lesson_script=current_content.get("lesson_script", ""),
            current_redundancy_check_notes=current_content.get("redundancy_check_notes", ""),
            **common_kwargs,
        )
    else:
        prompt = REVISE_PROMPT_TEMPLATE.format(
            current_lesson_script=current_content["lesson_script"],
            **common_kwargs,
        )

    if error_feedback:
        prompt += RETRY_SUFFIX.format(errors=error_feedback)
    return prompt


def _demo_revised_chapter_content(chapter: dict, is_final_chapter: bool, issues: list[dict]) -> dict:
    content = _demo_chapter_content(chapter, is_final_chapter)
    fixed_fields = ", ".join(sorted({i["field"] for i in issues})) or "aucun"
    marker = f" [DEMO] Version corrigée (champs retravaillés : {fixed_fields})."
    if chapter.get("format", "text") == "video":
        content["written_complement"] += marker
    else:
        content["lesson_script"] += marker
    return content


def revise_chapter_content(
    curriculum: dict,
    chapter: dict,
    total_chapters: int,
    current_content: dict,
    issues: list[dict],
    demo: bool = False,
    running_example: str = RUNNING_EXAMPLE,
    tracker: CostTracker | None = None,
) -> dict:
    """Réécrit CIBLÉ un chapitre déjà généré, à partir des problèmes signalés par le Bloc 3.5.

    Ne régénère pas le chapitre from scratch : le prompt inclut le contenu actuel et demande de ne
    corriger que les champs concernés par `issues`. `running_example` doit être le MÊME fil rouge
    que celui utilisé pour la génération initiale de ce contenu (voir `bloc2_result["running_example"]`).

    `tracker` : passe un `CostTracker` partagé si cet appel s'inscrit dans une boucle de correction
    plus large (review -> revise -> review, pilotée par le Bloc 3.5) pour un coût cumulé unique ;
    sinon un tracker local est créé et son résumé affiché avant de retourner."""
    is_final_chapter = chapter["number"] == total_chapters
    content_format = chapter.get("format", "text")

    if demo:
        content = _demo_revised_chapter_content(chapter, is_final_chapter, issues)
        errors = validate_chapter_content(content, is_final_chapter, format=content_format)
        if errors:
            raise LLMCallError(f"Données démo de révision invalides (bug interne) : {errors}")
        return content

    own_tracker = tracker is None
    if own_tracker:
        tracker = CostTracker(label=f"Bloc 2 - revise_chapter_content (chapitre {chapter['number']})")

    error_feedback = None
    last_errors: list[str] = []

    for attempt in range(2):  # 1 essai + 1 retry
        response_text = call_llm_api(
            prompt=build_revise_prompt(
                curriculum, chapter, total_chapters, is_final_chapter,
                current_content, issues, error_feedback, running_example,
            ),
            model=MODEL,
            system_prompt=SYSTEM_PROMPT,
            # 8192 s'est révélé insuffisant sur un run réel (2026-08-07) : la réécriture doit
            # reproduire tout le chapitre (lesson_script inchangé + exercices) donc peut dépasser le
            # budget de la génération initiale, en particulier si un corrigé détaillé est demandé
            # (ex. practical_exercise à 4 étapes) — réponse tronquée en JSON invalide, non rattrapée
            # par le retry (qui ne corrige que les échecs de VALIDATION de schéma, pas la troncature).
            max_tokens=16384,
            tracker=tracker,
            task="content",
        )
        # JSON malformé (troncature, guillemet interne mal échappé, etc.) traité comme une erreur
        # de validation plutôt qu'une exception qui court-circuite le retry — même correctif que
        # bloc1_curriculum_planning::plan_curriculum (constaté en production sur cette fonction
        # précisément, voir le commentaire sur max_tokens ci-dessus qui documentait déjà le symptôme
        # sans le corriger).
        try:
            content = extract_json(response_text)
        except LLMCallError as exc:
            last_errors = [f"Réponse JSON invalide : {exc}"]
            error_feedback = "\n".join(f"- {e}" for e in last_errors)
            continue
        last_errors = validate_chapter_content(content, is_final_chapter, format=content_format)
        if not last_errors:
            content["format"] = content_format
            if own_tracker:
                tracker.print_summary()
            return content
        error_feedback = "\n".join(f"- {e}" for e in last_errors)

    if own_tracker:
        tracker.print_summary()
    raise LLMCallError(
        f"Révision du chapitre {chapter['number']} invalide après {attempt + 1} tentative(s) : "
        f"{last_errors}"
    )


def load_curriculum(path: Path | str) -> dict:
    path = Path(path)
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def build_prompt(
    curriculum: dict,
    chapter: dict,
    total_chapters: int,
    is_final_chapter: bool,
    error_feedback: str | None = None,
    running_example: str = RUNNING_EXAMPLE,
) -> str:
    """Dispatche sur le format du chapitre (`chapter.get("format", "text")`) — un chapitre sans
    champ `format` (cours 1, généré avant cette fonctionnalité) suit le gabarit "text" existant,
    inchangé."""
    content_format = chapter.get("format", "text")
    objectives = "\n".join(f"- {o}" for o in chapter["learning_objectives"])
    key_points = "\n".join(f"- {kp}" for kp in chapter["key_points"])

    common_kwargs = dict(
        niche=curriculum.get("niche", ""),
        course_title=curriculum["title"],
        level=curriculum.get("level", "N/A"),
        number=chapter["number"],
        total=total_chapters,
        chapter_title=chapter["title"],
        objectives=objectives,
        key_points=key_points,
        running_example=running_example,
        extra_instructions=FINAL_CHAPTER_INSTRUCTIONS if is_final_chapter else "",
        extra_json_fields=FINAL_CHAPTER_JSON_FIELDS if is_final_chapter else "",
    )

    if content_format == "video":
        prompt = VIDEO_PROMPT_TEMPLATE.format(format_reasoning=chapter.get("format_reasoning", ""), **common_kwargs)
    elif content_format == "mix":
        prompt = MIX_PROMPT_TEMPLATE.format(format_reasoning=chapter.get("format_reasoning", ""), **common_kwargs)
    else:
        prompt = PROMPT_TEMPLATE.format(**common_kwargs)

    if error_feedback:
        prompt += RETRY_SUFFIX.format(errors=error_feedback)
    return prompt


def _validate_video_script(video_script, num: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(video_script, dict):
        return [f"Chapitre {num} : video_script manquant ou invalide."]
    if not (video_script.get("summary") or "").strip():
        errors.append(f"Chapitre {num} : video_script.summary manquant ou vide.")
    scenes = video_script.get("scenes")
    if not isinstance(scenes, list) or len(scenes) < 3:
        errors.append(f"Chapitre {num} : video_script.scenes doit contenir au moins 3 scènes.")
    else:
        for i, scene in enumerate(scenes):
            if not (scene.get("beat") or "").strip() or not (scene.get("narration") or "").strip():
                errors.append(f"Chapitre {num} : scène {i} du video_script incomplète (beat/narration).")
    return errors


def validate_chapter_content(content: dict, is_final_chapter: bool, format: str = "text") -> list[str]:
    """Retourne la liste des erreurs de validation (vide = valide).

    `format` : "text" (défaut, comportement inchangé), "video" ou "mix" — voir FORMAT_ENUM. Les
    exercices (comprehension_exercises/practical_exercise) sont TOUJOURS requis, quel que soit le
    format (constante non négociable côté produit)."""
    errors: list[str] = []
    num = content.get("chapter_number", "?")

    if format == "video":
        errors += _validate_video_script(content.get("video_script"), num)
        written_complement = (content.get("written_complement") or "").strip()
        if not written_complement:
            errors.append(f"Chapitre {num} : written_complement manquant ou vide.")
        elif len(written_complement) > 1200:
            errors.append(
                f"Chapitre {num} : written_complement trop long ({len(written_complement)} caractères) — "
                "un chapitre vidéo ne doit pas dupliquer une leçon-texte complète."
            )
    elif format == "mix":
        errors += _validate_video_script(content.get("video_script"), num)
        lesson = content.get("lesson_script", "")
        if not lesson or len(lesson.strip()) < 200:
            errors.append(f"Chapitre {num} : lesson_script (texte complémentaire) trop court ou vide.")
        if not (content.get("redundancy_check_notes") or "").strip():
            errors.append(
                f"Chapitre {num} : redundancy_check_notes manquant ou vide (partage des rôles "
                "vidéo/texte non explicité, non vérifiable par le Bloc 3.5)."
            )
    else:
        lesson = content.get("lesson_script", "")
        if not lesson or len(lesson.strip()) < 200:
            errors.append(f"Chapitre {num} : lesson_script trop court ou vide (texte développé attendu).")

    exercises = content.get("comprehension_exercises")
    if not exercises or len(exercises) < 3:
        errors.append(f"Chapitre {num} : au moins 3 comprehension_exercises attendus.")
    else:
        for i, ex in enumerate(exercises):
            if not ex.get("question") or not ex.get("correct_answer"):
                errors.append(f"Chapitre {num} : exercice de compréhension {i} incomplet.")
            if ex.get("type") == "mcq":
                if not ex.get("options"):
                    errors.append(f"Chapitre {num} : exercice QCM {i} sans options.")
                if not (ex.get("explanation") or "").strip():
                    errors.append(f"Chapitre {num} : exercice QCM {i} sans explanation.")

    pe = content.get("practical_exercise")
    if not pe or not pe.get("title") or not pe.get("instructions") or not pe.get("expected_outcome"):
        errors.append(f"Chapitre {num} : practical_exercise incomplet.")
    elif is_final_chapter:
        for field in ("deliverables", "step_by_step_instructions", "evaluation_criteria"):
            if not pe.get(field):
                errors.append(f"Chapitre {num} (projet final) : champ '{field}' manquant ou vide.")

    return errors


def _demo_exercises_and_practical(chapter: dict, is_final_chapter: bool) -> tuple[list[dict], dict]:
    """Exercices/projet démo — identiques quel que soit le format (constante non négociable : les
    exercices sont TOUJOURS présents, cf. docstring de `validate_chapter_content`)."""
    practical_exercise = {
        "title": f"[DEMO] Exercice pratique — {chapter['title']}",
        "instructions": "[DEMO] Applique les notions de ce chapitre au fil rouge du cours.",
        "expected_outcome": "[DEMO] Résultat attendu illustrant l'objectif du chapitre.",
    }
    if is_final_chapter:
        practical_exercise.update(
            deliverables=["[DEMO] Livrable 1", "[DEMO] Livrable 2"],
            step_by_step_instructions=["[DEMO] Étape 1", "[DEMO] Étape 2", "[DEMO] Étape 3"],
            evaluation_criteria=["[DEMO] Critère 1", "[DEMO] Critère 2"],
        )
    comprehension_exercises = [
        {
            "question": "[DEMO] Question à choix multiple 1 ?",
            "type": "mcq",
            "options": ["Option A", "Option B", "Option C"],
            "correct_answer": "Option A",
            "explanation": "[DEMO] Explication de la bonne réponse.",
        },
        {
            "question": "[DEMO] Question courte 2 ?",
            "type": "short_answer",
            "options": None,
            "correct_answer": "[DEMO] Réponse attendue",
        },
        {
            "question": "[DEMO] Question à choix multiple 3 ?",
            "type": "mcq",
            "options": ["Option A", "Option B"],
            "correct_answer": "Option B",
            "explanation": "[DEMO] Explication de la bonne réponse.",
        },
    ]
    return comprehension_exercises, practical_exercise


def _demo_video_script(chapter: dict) -> dict:
    return {
        "summary": f"[DEMO] La vidéo montre la démonstration pas à pas de '{chapter['title']}'.",
        "scenes": [
            {"beat": "[DEMO] Introduction", "narration": "[DEMO] Présentation de l'objectif.", "visual": "[DEMO] Écran titre."},
            {"beat": "[DEMO] Démonstration", "narration": "[DEMO] Étapes réalisées à l'écran.", "visual": "[DEMO] Capture d'écran de l'outil."},
            {"beat": "[DEMO] Résultat", "narration": "[DEMO] Récapitulatif du résultat obtenu.", "visual": "[DEMO] Résultat final affiché."},
        ],
    }


def _demo_chapter_content(chapter: dict, is_final_chapter: bool) -> dict:
    """Stub démo (aucun appel réseau) — respecte le format du chapitre (`chapter.get("format",
    "text")`) : un chapitre sans champ `format` (cours 1) produit le stub "text" historique,
    inchangé."""
    content_format = chapter.get("format", "text")
    comprehension_exercises, practical_exercise = _demo_exercises_and_practical(chapter, is_final_chapter)
    base = {
        "chapter_number": chapter["number"],
        "chapter_title": chapter["title"],
        "format": content_format,
        "comprehension_exercises": comprehension_exercises,
        "practical_exercise": practical_exercise,
    }

    if content_format == "video":
        base["video_script"] = _demo_video_script(chapter)
        base["written_complement"] = (
            f"[DEMO] Complément court pour '{chapter['title']}' : un point non montré dans la vidéo."
        )
    elif content_format == "mix":
        base["video_script"] = _demo_video_script(chapter)
        base["lesson_script"] = (
            f"[DEMO] Texte de référence complémentaire pour '{chapter['title']}'. "
            "En mode réel, ce champ approfondit ou documente ce que la vidéo ne montre pas "
            "(référence, code à copier), sans réexpliquer ce qui est déjà montré à l'écran. Ce "
            "texte de remplacement sert uniquement à valider le câblage du pipeline sans "
            "consommer d'appel réseau ni de coût API."
        )
        base["redundancy_check_notes"] = (
            f"[DEMO] La vidéo montre la démonstration de '{chapter['title']}' ; le texte apporte "
            "la référence/le code à copier — aucun recouvrement."
        )
    else:
        base["lesson_script"] = (
            f"[DEMO] Script de leçon complet pour '{chapter['title']}'. "
            "En mode réel, ce champ contient un texte pédagogique développé de plusieurs "
            "paragraphes expliquant et illustrant chaque point clé du chapitre, avec des exemples "
            "concrets liés au fil rouge du cours. Ce texte de remplacement sert uniquement à "
            "valider le câblage du pipeline (chargement, génération, validation, sauvegarde) sans "
            "consommer d'appel réseau ni de coût API."
        )

    return base


def generate_chapter_content(
    curriculum: dict,
    chapter: dict,
    total_chapters: int,
    demo: bool = False,
    running_example: str = RUNNING_EXAMPLE,
    tracker: CostTracker | None = None,
) -> dict:
    """`tracker` : passe un `CostTracker` partagé pour accumuler le coût sur plusieurs chapitres
    (voir `write_content`) ; sinon un tracker local est créé et son résumé affiché avant de retourner."""
    is_final_chapter = chapter["number"] == total_chapters
    content_format = chapter.get("format", "text")

    if demo:
        content = _demo_chapter_content(chapter, is_final_chapter)
        errors = validate_chapter_content(content, is_final_chapter, format=content_format)
        if errors:
            raise LLMCallError(f"Données démo invalides (bug interne) : {errors}")
        return content

    own_tracker = tracker is None
    if own_tracker:
        tracker = CostTracker(label=f"Bloc 2 - generate_chapter_content (chapitre {chapter['number']})")

    error_feedback = None
    last_errors: list[str] = []

    for attempt in range(2):  # 1 essai + 1 retry
        response_text = call_llm_api(
            prompt=build_prompt(
                curriculum, chapter, total_chapters, is_final_chapter, error_feedback, running_example
            ),
            model=MODEL,
            system_prompt=SYSTEM_PROMPT,
            max_tokens=16384,  # cf. commentaire sur revise_chapter_content : 8192 s'est révélé trop juste
            tracker=tracker,
            task="content",
        )
        # Voir revise_chapter_content ci-dessus : JSON malformé traité comme une erreur de
        # validation (retry), pas une exception qui court-circuite le retry.
        try:
            content = extract_json(response_text)
        except LLMCallError as exc:
            last_errors = [f"Réponse JSON invalide : {exc}"]
            error_feedback = "\n".join(f"- {e}" for e in last_errors)
            continue
        last_errors = validate_chapter_content(content, is_final_chapter, format=content_format)
        if not last_errors:
            content["format"] = content_format
            if own_tracker:
                tracker.print_summary()
            return content
        error_feedback = "\n".join(f"- {e}" for e in last_errors)

    if own_tracker:
        tracker.print_summary()
    raise LLMCallError(
        f"Contenu du chapitre {chapter['number']} invalide après {attempt + 1} tentative(s) : "
        f"{last_errors}"
    )


def write_content(curriculum: dict, demo: bool = False, running_example: str = RUNNING_EXAMPLE) -> dict:
    """Exécute le Bloc 2 sur un curriculum validé et retourne le contenu de tous les chapitres.

    `running_example` : fil rouge injecté identique dans les 7 prompts. Par défaut, l'agent support
    client du Sprint 1 — passer un fil rouge différent (adapté au sujet du cours) pour un nouveau
    cours, sans affecter le comportement par défaut des appels existants."""
    chapters = curriculum["chapters"]
    total = len(chapters)
    tracker = None if demo else CostTracker(label="Bloc 2 - write_content (cours complet)")

    chapters_content = [
        generate_chapter_content(
            curriculum, chapter, total, demo=demo, running_example=running_example, tracker=tracker
        )
        for chapter in chapters
    ]

    if tracker is not None:
        tracker.print_summary()

    return {
        "course_title": curriculum["title"],
        "niche": curriculum.get("niche"),
        "level": curriculum.get("level"),
        "running_example": running_example,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "chapters_content": chapters_content,
    }


def save_result(result: dict) -> tuple[Path, Path]:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = DATA_DIR / f"bloc2_content_{timestamp}.json"
    md_path = DATA_DIR / f"bloc2_content_{timestamp}.md"

    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(to_markdown(result), encoding="utf-8")
    return json_path, md_path


def to_markdown(result: dict) -> str:
    lines = [
        f"# {result['course_title']} — Contenu détaillé",
        "",
        f"Niche : {result.get('niche', 'N/A')}",
        f"Niveau : {result.get('level', 'N/A')}",
        "",
        f"**Fil rouge du cours :** {result['running_example']}",
        "",
    ]

    for c in result["chapters_content"]:
        lines.append(f"## Chapitre {c['chapter_number']} — {c['chapter_title']}")
        lines.append("")
        if c.get("video_script"):
            lines.append("### Plan vidéo")
            lines.append("")
            lines.append(c["video_script"].get("summary", ""))
            lines.append("")
            for i, scene in enumerate(c["video_script"].get("scenes", []), start=1):
                lines.append(f"{i}. **{scene.get('beat', '')}** — {scene.get('narration', '')} ({scene.get('visual', '')})")
            lines.append("")
        if c.get("lesson_script"):
            lines.append("### Script de la leçon" if not c.get("video_script") else "### Texte complémentaire")
            lines.append("")
            lines.append(c["lesson_script"])
            lines.append("")
        if c.get("written_complement"):
            lines.append("### Complément écrit")
            lines.append("")
            lines.append(c["written_complement"])
            lines.append("")
        lines.append("### Exercices de compréhension")
        lines.append("")
        for i, ex in enumerate(c["comprehension_exercises"], start=1):
            lines.append(f"{i}. {ex['question']}")
            if ex.get("type") == "mcq" and ex.get("options"):
                for opt in ex["options"]:
                    lines.append(f"   - {opt}")
            lines.append(f"   *Réponse attendue :* {ex['correct_answer']}")
        lines.append("")

        pe = c["practical_exercise"]
        is_final = "deliverables" in pe
        lines.append("### Projet final" if is_final else "### Exercice pratique")
        lines.append("")
        lines.append(f"**{pe['title']}**")
        lines.append("")
        lines.append(pe["instructions"])
        lines.append("")
        lines.append(f"**Résultat attendu :** {pe['expected_outcome']}")
        lines.append("")
        if is_final:
            lines.append("**Livrables :**")
            for d in pe["deliverables"]:
                lines.append(f"- {d}")
            lines.append("")
            lines.append("**Étapes détaillées :**")
            for i, step in enumerate(pe["step_by_step_instructions"], start=1):
                lines.append(f"{i}. {step}")
            lines.append("")
            lines.append("**Critères d'évaluation :**")
            for crit in pe["evaluation_criteria"]:
                lines.append(f"- {crit}")
            lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bloc 2 — Rédaction du contenu et des exercices")
    parser.add_argument("--demo", action="store_true", help="Mode démo : contenu placeholder")
    parser.add_argument(
        "--curriculum-file",
        type=str,
        default=str(DEFAULT_CURRICULUM_FILE),
        help="Chemin du JSON de curriculum produit par le Bloc 1",
    )
    parser.add_argument(
        "--running-example",
        type=str,
        default=RUNNING_EXAMPLE,
        help="Fil rouge à injecter dans les exercices pratiques (par défaut : celui du Sprint 1)",
    )
    args = parser.parse_args()

    curriculum = load_curriculum(args.curriculum_file)
    result = write_content(curriculum, demo=args.demo, running_example=args.running_example)

    for c in result["chapters_content"]:
        fmt = c.get("format", "text")
        word_count = len((c.get("lesson_script") or c.get("written_complement") or "").split())
        print(f"Chapitre {c['chapter_number']} — {c['chapter_title']} [{fmt}] ({word_count} mots de texte)")

    json_path, md_path = save_result(result)
    print(f"\nSauvegardé : {json_path}")
    print(f"Export lisible : {md_path}")


if __name__ == "__main__":
    main()
