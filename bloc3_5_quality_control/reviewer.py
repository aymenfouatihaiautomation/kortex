"""Bloc 3.5 — Réviseur externe critique, logique séparée de l'auteur du Bloc 2.

Le système prompt et le rôle assignés ici sont volontairement différents de ceux du Bloc 2
(`bloc2_content_writing.write_content.SYSTEM_PROMPT`, un rédacteur) : ce module ne rédige jamais de
contenu, il ne fait qu'évaluer, avec une posture sceptique, celui produit par le Bloc 2. C'est ce
qui évite que le même biais de génération valide son propre travail (contrainte explicite de
l'utilisateur pour ce Sprint).
"""

import json

from common.llm_client import CostTracker, LLMCallError, call_llm_api, extract_json

MODEL = "claude-sonnet-5"  # contrôle qualité, exigence explicite de l'utilisateur

# Formats (2026-08-07, voir bloc1_curriculum_planning.plan_curriculum.FORMAT_ENUM) : "text"/"video"
# utilisent les 4 critères historiques ; "mix" ajoute video_text_complementarity, qui vérifie
# explicitement l'absence de redondance entre vidéo et texte (exigence produit non négociable pour
# ce format). Un chapitre sans champ `format` (cours 1) est traité comme "text", inchangé.
VALID_FIELDS = {
    "lesson_script",
    "comprehension_exercises",
    "practical_exercise",
    "video_script",
    "written_complement",
    "redundancy_check_notes",
}
CRITERIA = ("coverage", "logical_coherence", "technical_accuracy", "exercise_quality")
MIX_EXTRA_CRITERION = "video_text_complementarity"
CRITERIA_MIX = CRITERIA + (MIX_EXTRA_CRITERION,)

REVIEWER_SYSTEM_PROMPT = (
    "Tu es un réviseur pédagogique EXTERNE et INDÉPENDANT de l'auteur du contenu que tu évalues. "
    "Ton rôle est de critiquer de façon rigoureuse et sceptique, jamais de valider par complaisance : "
    "pars du principe que le contenu contient probablement au moins un défaut, et cherche-le "
    "activement. Tu réponds UNIQUEMENT avec un objet JSON valide, sans texte avant ou après, sans "
    "bloc de code markdown."
)

REVIEW_PROMPT_TEMPLATE = """\
Niche : "{niche}". Cours : "{course_title}" (niveau {level}).
Chapitre {number}/{total} : "{chapter_title}".

--- SPÉCIFICATION VALIDÉE DU CHAPITRE (Bloc 1, fixe, ne peut pas être changée) ---
Objectifs pédagogiques :
{objectives}
Points clés à couvrir :
{key_points}
Lien attendu avec le chapitre précédent : {builds_on_previous}

{previous_chapter_context}

--- CONTENU GÉNÉRÉ À ÉVALUER (Bloc 2) ---
Script de la leçon :
{lesson_script}

Exercices de compréhension (JSON) :
{comprehension_exercises_json}

Exercice pratique (JSON) :
{practical_exercise_json}

--- CRITÈRES D'ÉVALUATION (évalue les 4, sans complaisance) ---
1. coverage : le script de leçon couvre-t-il RÉELLEMENT tous les objectifs pédagogiques et points
   clés listés ci-dessus (développés, pas juste mentionnés en une phrase) ?
2. logical_coherence : le chapitre s'appuie-t-il correctement sur le chapitre précédent tel que
   décrit dans "Lien attendu avec le chapitre précédent", sans rupture ni notion utilisée avant
   d'être introduite ?
3. technical_accuracy : y a-t-il des erreurs factuelles ou techniques dans le contenu (sur les
   sujets techniques abordés) ?
4. exercise_quality : les exercices de compréhension et l'exercice pratique mesurent-ils
   réellement la compétence visée, avec un niveau de difficulté cohérent avec le niveau
   "{level}" du cours ?

Pour CHAQUE critère, donne un verdict "pass" ou "fail" avec une justification précise (2-3 phrases,
citant des éléments concrets du contenu évalué, pas une généralité).

overall_verdict = "accepted" SEULEMENT si les 4 critères sont "pass". Sinon "needs_revision".
Si "needs_revision", liste dans "issues" CHAQUE problème précis à corriger : "field" doit être
exactement l'un de "lesson_script", "comprehension_exercises" ou "practical_exercise", et
"description" doit être une instruction actionnable (pas "à améliorer").

Réponds avec EXACTEMENT ce format JSON :
{{
  "chapter_number": {number},
  "overall_verdict": "accepted",
  "criteria": {{
    "coverage": {{"verdict": "pass", "justification": "..."}},
    "logical_coherence": {{"verdict": "pass", "justification": "..."}},
    "technical_accuracy": {{"verdict": "pass", "justification": "..."}},
    "exercise_quality": {{"verdict": "pass", "justification": "..."}}
  }},
  "issues": []
}}
"""

VIDEO_REVIEW_PROMPT_TEMPLATE = """\
Niche : "{niche}". Cours : "{course_title}" (niveau {level}).
Chapitre {number}/{total} : "{chapter_title}" (chapitre VIDÉO — pas de leçon-texte complète).

--- SPÉCIFICATION VALIDÉE DU CHAPITRE (Bloc 1, fixe, ne peut pas être changée) ---
Objectifs pédagogiques :
{objectives}
Points clés à couvrir :
{key_points}
Lien attendu avec le chapitre précédent : {builds_on_previous}

{previous_chapter_context}

--- CONTENU GÉNÉRÉ À ÉVALUER (Bloc 2) ---
Plan de la vidéo (contenu PRINCIPAL de ce chapitre) :
{video_script_text}

Complément écrit (COURT, ne doit PAS dupliquer la vidéo) :
{written_complement}

Exercices de compréhension (JSON) :
{comprehension_exercises_json}

Exercice pratique (JSON) :
{practical_exercise_json}

--- CRITÈRES D'ÉVALUATION (évalue les 4, sans complaisance) ---
1. coverage : le plan de la vidéo ET le complément écrit couvrent-ils RÉELLEMENT, ensemble, tous
   les objectifs pédagogiques et points clés listés ci-dessus ?
2. logical_coherence : le chapitre s'appuie-t-il correctement sur le chapitre précédent tel que
   décrit dans "Lien attendu avec le chapitre précédent", sans rupture ni notion utilisée avant
   d'être introduite ?
3. technical_accuracy : y a-t-il des erreurs factuelles ou techniques dans le plan de la vidéo ou
   le complément écrit ?
4. exercise_quality : les exercices de compréhension et l'exercice pratique mesurent-ils
   réellement la compétence visée, avec un niveau de difficulté cohérent avec le niveau
   "{level}" du cours ? Vérifie AUSSI que le complément écrit n'est PAS une leçon-texte déguisée
   qui redirait ce que la vidéo montre déjà (si c'est le cas, note-le comme un défaut de qualité,
   field="written_complement").

Pour CHAQUE critère, donne un verdict "pass" ou "fail" avec une justification précise (2-3 phrases,
citant des éléments concrets du contenu évalué, pas une généralité).

overall_verdict = "accepted" SEULEMENT si les 4 critères sont "pass". Sinon "needs_revision".
Si "needs_revision", liste dans "issues" CHAQUE problème précis à corriger : "field" doit être
exactement l'un de "video_script", "written_complement", "comprehension_exercises" ou
"practical_exercise", et "description" doit être une instruction actionnable (pas "à améliorer").

Réponds avec EXACTEMENT ce format JSON :
{{
  "chapter_number": {number},
  "overall_verdict": "accepted",
  "criteria": {{
    "coverage": {{"verdict": "pass", "justification": "..."}},
    "logical_coherence": {{"verdict": "pass", "justification": "..."}},
    "technical_accuracy": {{"verdict": "pass", "justification": "..."}},
    "exercise_quality": {{"verdict": "pass", "justification": "..."}}
  }},
  "issues": []
}}
"""

MIX_REVIEW_PROMPT_TEMPLATE = """\
Niche : "{niche}". Cours : "{course_title}" (niveau {level}).
Chapitre {number}/{total} : "{chapter_title}" (chapitre MIXTE — vidéo + texte COMPLÉMENTAIRES).

--- SPÉCIFICATION VALIDÉE DU CHAPITRE (Bloc 1, fixe, ne peut pas être changée) ---
Objectifs pédagogiques :
{objectives}
Points clés à couvrir :
{key_points}
Lien attendu avec le chapitre précédent : {builds_on_previous}

{previous_chapter_context}

--- CONTENU GÉNÉRÉ À ÉVALUER (Bloc 2) ---
Plan de la vidéo :
{video_script_text}

Texte de référence complémentaire :
{lesson_script}

Notes de l'auteur sur le partage des rôles vidéo/texte (À VÉRIFIER, pas à prendre pour argent
comptant — l'auteur peut être auto-complaisant) :
{redundancy_check_notes}

Exercices de compréhension (JSON) :
{comprehension_exercises_json}

Exercice pratique (JSON) :
{practical_exercise_json}

--- CRITÈRES D'ÉVALUATION (évalue les 5, sans complaisance) ---
1. coverage : la vidéo ET le texte couvrent-ils RÉELLEMENT, ensemble, tous les objectifs
   pédagogiques et points clés listés ci-dessus ?
2. logical_coherence : le chapitre s'appuie-t-il correctement sur le chapitre précédent tel que
   décrit dans "Lien attendu avec le chapitre précédent", sans rupture ni notion utilisée avant
   d'être introduite ?
3. technical_accuracy : y a-t-il des erreurs factuelles ou techniques dans la vidéo ou le texte ?
4. exercise_quality : les exercices de compréhension et l'exercice pratique mesurent-ils
   réellement la compétence visée, avec un niveau de difficulté cohérent avec le niveau
   "{level}" du cours ?
5. video_text_complementarity : la vidéo et le texte sont-ils RÉELLEMENT complémentaires ? Compare
   CONCRÈTEMENT le contenu du plan vidéo (scènes/narration) et celui du texte ci-dessus (pas
   seulement les notes de l'auteur, potentiellement auto-complaisantes) : le texte ne doit PAS
   réexpliquer ce que la vidéo montre déjà, et la vidéo ne doit pas se contenter d'illustrer ce que
   le texte dit déjà sans rien apporter de propre. Un recouvrement significatif = "fail".

Pour CHAQUE critère, donne un verdict "pass" ou "fail" avec une justification précise (2-3 phrases,
citant des éléments concrets du contenu évalué, pas une généralité).

overall_verdict = "accepted" SEULEMENT si les 5 critères sont "pass". Sinon "needs_revision".
Si "needs_revision", liste dans "issues" CHAQUE problème précis à corriger : "field" doit être
exactement l'un de "video_script", "lesson_script", "redundancy_check_notes",
"comprehension_exercises" ou "practical_exercise", et "description" doit être une instruction
actionnable (pas "à améliorer").

Réponds avec EXACTEMENT ce format JSON :
{{
  "chapter_number": {number},
  "overall_verdict": "accepted",
  "criteria": {{
    "coverage": {{"verdict": "pass", "justification": "..."}},
    "logical_coherence": {{"verdict": "pass", "justification": "..."}},
    "technical_accuracy": {{"verdict": "pass", "justification": "..."}},
    "exercise_quality": {{"verdict": "pass", "justification": "..."}},
    "video_text_complementarity": {{"verdict": "pass", "justification": "..."}}
  }},
  "issues": []
}}
"""

RETRY_SUFFIX = """

ATTENTION : ta réponse précédente était invalide pour la raison suivante :
{errors}
Corrige ces problèmes et renvoie un JSON complet et valide respectant strictement le format demandé.
"""


def _format_video_script_for_review(video_script: dict | None) -> str:
    if not video_script:
        return "(aucun plan vidéo fourni)"
    lines = [f"Résumé : {video_script.get('summary', '')}"]
    for i, scene in enumerate(video_script.get("scenes", []) or [], start=1):
        lines.append(
            f"  Scène {i} — {scene.get('beat', '')} : "
            f"narration=\"{scene.get('narration', '')}\" ; visuel=\"{scene.get('visual', '')}\""
        )
    return "\n".join(lines)


def build_review_prompt(
    curriculum: dict,
    chapter: dict,
    prev_chapter: dict | None,
    content: dict,
    total_chapters: int,
    error_feedback: str | None = None,
) -> str:
    """Dispatche sur le format du chapitre (`chapter.get("format", "text")`) — un chapitre sans
    champ `format` (cours 1, contrôlé avant cette fonctionnalité) suit le gabarit "text" existant,
    inchangé."""
    content_format = chapter.get("format", "text")
    objectives = "\n".join(f"- {o}" for o in chapter["learning_objectives"])
    key_points = "\n".join(f"- {kp}" for kp in chapter["key_points"])

    if prev_chapter is None:
        previous_chapter_context = "Ce chapitre est le premier du cours (pas de chapitre précédent)."
    else:
        prev_key_points = "\n".join(f"- {kp}" for kp in prev_chapter["key_points"])
        previous_chapter_context = (
            f'Chapitre précédent : "{prev_chapter["title"]}", points clés déjà couverts :\n'
            f"{prev_key_points}"
        )

    common_kwargs = dict(
        niche=curriculum.get("niche", ""),
        course_title=curriculum["title"],
        level=curriculum.get("level", "N/A"),
        number=chapter["number"],
        total=total_chapters,
        chapter_title=chapter["title"],
        objectives=objectives,
        key_points=key_points,
        builds_on_previous=chapter.get("builds_on_previous", "N/A"),
        previous_chapter_context=previous_chapter_context,
        comprehension_exercises_json=json.dumps(content["comprehension_exercises"], ensure_ascii=False),
        practical_exercise_json=json.dumps(content["practical_exercise"], ensure_ascii=False),
    )

    if content_format == "video":
        prompt = VIDEO_REVIEW_PROMPT_TEMPLATE.format(
            video_script_text=_format_video_script_for_review(content.get("video_script")),
            written_complement=content.get("written_complement", ""),
            **common_kwargs,
        )
    elif content_format == "mix":
        prompt = MIX_REVIEW_PROMPT_TEMPLATE.format(
            video_script_text=_format_video_script_for_review(content.get("video_script")),
            lesson_script=content.get("lesson_script", ""),
            redundancy_check_notes=content.get("redundancy_check_notes", ""),
            **common_kwargs,
        )
    else:
        prompt = REVIEW_PROMPT_TEMPLATE.format(lesson_script=content["lesson_script"], **common_kwargs)

    if error_feedback:
        prompt += RETRY_SUFFIX.format(errors=error_feedback)
    return prompt


def validate_review(review: dict, criteria_names: tuple[str, ...] = CRITERIA) -> list[str]:
    """Retourne la liste des erreurs de validation (vide = valide). Vérifie le schéma ET la
    cohérence interne (accepted <=> tous les critères pass ; needs_revision => issues non vide).

    `criteria_names` : `CRITERIA` (4, défaut — text/video) ou `CRITERIA_MIX` (5, avec
    video_text_complementarity)."""
    errors: list[str] = []

    verdict = review.get("overall_verdict")
    if verdict not in ("accepted", "needs_revision"):
        return [f"overall_verdict invalide : {verdict!r}"]

    criteria = review.get("criteria")
    if not criteria or set(criteria.keys()) != set(criteria_names):
        return [f"criteria doit contenir exactement {criteria_names}, reçu : {list(criteria or {})}"]

    all_pass = True
    for name in criteria_names:
        c = criteria[name]
        if c.get("verdict") not in ("pass", "fail"):
            errors.append(f"criteria.{name}.verdict invalide : {c.get('verdict')!r}")
        elif c["verdict"] == "fail":
            all_pass = False
        if not c.get("justification", "").strip():
            errors.append(f"criteria.{name}.justification vide.")

    if errors:
        return errors

    if verdict == "accepted" and not all_pass:
        errors.append("overall_verdict='accepted' mais au moins un critère est 'fail' (incohérent).")
    if verdict == "needs_revision" and all_pass:
        errors.append("overall_verdict='needs_revision' mais tous les critères sont 'pass' (incohérent).")

    issues = review.get("issues", [])
    if verdict == "needs_revision" and not issues:
        errors.append("overall_verdict='needs_revision' mais 'issues' est vide.")
    for i, issue in enumerate(issues):
        if issue.get("field") not in VALID_FIELDS:
            errors.append(f"issues[{i}].field invalide : {issue.get('field')!r}")
        if not issue.get("description", "").strip():
            errors.append(f"issues[{i}].description vide.")

    return errors


def _demo_review(chapter: dict, attempt: int) -> dict:
    """Mode démo déterministe : rejette une fois (attempt 0) puis accepte (attempt >= 1) —
    permet de valider le câblage de la boucle review -> revise -> review sans appel réseau. Un
    chapitre "mix" exerce aussi CRITERIA_MIX (5 critères), pour que le câblage anti-redondance soit
    testé en mode démo sans appel réseau."""
    criteria_names = CRITERIA_MIX if chapter.get("format") == "mix" else CRITERIA
    if attempt == 0:
        criteria = {name: {"verdict": "pass", "justification": f"[DEMO] {name} jugé correct."} for name in criteria_names}
        criteria["exercise_quality"] = {
            "verdict": "fail",
            "justification": "[DEMO] Exercice pratique jugé trop générique pour le niveau intermédiaire.",
        }
        return {
            "chapter_number": chapter["number"],
            "overall_verdict": "needs_revision",
            "criteria": criteria,
            "issues": [
                {
                    "field": "practical_exercise",
                    "description": "[DEMO] Rendre l'exercice pratique plus spécifique au fil rouge.",
                }
            ],
        }
    return {
        "chapter_number": chapter["number"],
        "overall_verdict": "accepted",
        "criteria": {name: {"verdict": "pass", "justification": "[DEMO] Corrigé et validé."} for name in criteria_names},
        "issues": [],
    }


def review_chapter(
    curriculum: dict,
    chapter: dict,
    prev_chapter: dict | None,
    content: dict,
    total_chapters: int,
    attempt: int = 0,
    demo: bool = False,
    tracker: CostTracker | None = None,
) -> dict:
    """Fait évaluer un chapitre par le réviseur externe et retourne un verdict validé.

    `attempt` est le numéro de la tentative de correction en cours (0 = première évaluation),
    utilisé uniquement par le stub démo pour simuler un cycle rejet -> correction -> acceptation.

    `tracker` : passe un `CostTracker` partagé si cet appel s'inscrit dans une boucle de correction
    plus large (plusieurs chapitres, ou review -> revise -> review) pour un coût cumulé unique sur
    tout le run ; sinon un tracker local est créé et son résumé (coût cumulé de CE run) est affiché
    avant de retourner — Bloc 3.5 étant le plus gros consommateur (boucles de correction), ce résumé
    reste visible même pour un seul appel isolé."""
    content_format = chapter.get("format", "text")
    criteria_names = CRITERIA_MIX if content_format == "mix" else CRITERIA

    if demo:
        review = _demo_review(chapter, attempt)
        errors = validate_review(review, criteria_names=criteria_names)
        if errors:
            raise LLMCallError(f"Révision démo invalide (bug interne) : {errors}")
        return review

    own_tracker = tracker is None
    if own_tracker:
        tracker = CostTracker(label=f"Bloc 3.5 - review_chapter (chapitre {chapter['number']})")

    error_feedback = None
    last_errors: list[str] = []

    for schema_attempt in range(2):  # 1 essai + 1 retry sur invalidité de SCHÉMA (pas sur le fond)
        response_text = call_llm_api(
            prompt=build_review_prompt(curriculum, chapter, prev_chapter, content, total_chapters, error_feedback),
            model=MODEL,
            # "mix" a un 5ème critère (video_text_complementarity) à justifier en plus.
            max_tokens=4096 if content_format == "mix" else 3072,
            system_prompt=REVIEWER_SYSTEM_PROMPT,
            tracker=tracker,
            task="quality_control",
        )
        try:
            review = extract_json(response_text)
            last_errors = validate_review(review, criteria_names=criteria_names)
        except (json.JSONDecodeError, LLMCallError) as exc:
            last_errors = [f"Réponse non-JSON ou JSON malformé : {exc}"]
        else:
            if not last_errors:
                if own_tracker:
                    tracker.print_summary()
                return review
        error_feedback = "\n".join(f"- {e}" for e in last_errors)

    if own_tracker:
        tracker.print_summary()
    raise LLMCallError(
        f"Revue du chapitre {chapter['number']} invalide après {schema_attempt + 1} tentative(s) : "
        f"{last_errors}"
    )
