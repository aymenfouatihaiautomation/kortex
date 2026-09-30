"""Bloc 7, Étape 1a — Générateur de questions QCM candidates pour l'examen de fin de cours.

Un candidat n'est JAMAIS mis dans la banque finale directement : chaque candidat produit ici doit
ensuite passer par l'agent vérificateur adversarial (question_verifier.py), un second passage LLM
totalement indépendant. Ce module ne fait que proposer, jamais valider — voir le docstring de
question_verifier.py pour la raison (le même biais de génération ne doit jamais juger son propre
travail, même principe que bloc3_5_quality_control/reviewer.py)."""

import json

from common.llm_client import CostTracker, LLMCallError, call_llm_api, extract_json
from bloc7_exam_generation.content_text import chapter_source_text

MODEL = "claude-sonnet-5"  # génération d'examen : exige la même rigueur que le contrôle qualité (Bloc 3.5)

GENERATOR_SYSTEM_PROMPT = (
    "Tu es un concepteur de questions d'examen à choix multiples (QCM), rigoureux et factuel. Tu "
    "génères des questions STRICTEMENT dérivables du contenu de cours fourni ci-dessous — jamais un "
    "fait, un chiffre, un exemple ou une affirmation qui n'y figure pas explicitement. Tu réponds "
    "UNIQUEMENT avec un objet JSON valide, sans texte avant ou après, sans bloc de code markdown."
)

GENERATE_PROMPT_TEMPLATE = """\
Cours : "{course_title}".
Chapitre {number} : "{chapter_title}".

--- CONTENU VALIDÉ DU CHAPITRE (SEULE source autorisée) ---
{source_text}

--- QUESTIONS DÉJÀ GÉNÉRÉES POUR CE CHAPITRE (ne pas répéter, varier les angles et les passages du contenu couverts) ---
{existing_questions}

Génère {n} NOUVELLES questions à choix multiples (QCM) sur ce chapitre, chacune avec EXACTEMENT 4
options.

Règles strictes :
- La question et sa bonne réponse doivent être dérivables UNIQUEMENT du contenu ci-dessus. Aucun
  fait, chiffre, exemple ou affirmation inventé, aucune connaissance externe au cours.
- Exactement une option correcte ; les 3 autres doivent être CLAIREMENT fausses selon ce contenu —
  jamais une variante plausible ou partiellement correcte de la bonne réponse.
- "explanation" doit citer ou paraphraser précisément le passage du cours qui justifie la réponse.
- Formulation claire, sans ambiguïté ni double négation.
- Ne répète aucune des questions déjà générées listées ci-dessus.

Réponds avec EXACTEMENT ce format JSON :
{{"questions": [{{"question": "...", "options": ["...", "...", "...", "..."], "correct_index": 0, "explanation": "..."}}]}}
(exactement {n} éléments dans "questions", "correct_index" est un entier 0, 1, 2 ou 3, "options" a exactement 4 éléments)
"""

_DEMO_TEMPLATE = {
    "question": "[DEMO] Question sur le chapitre {number} ({variant}) ?",
    "options": ["[DEMO] Option A", "[DEMO] Option B", "[DEMO] Option C", "[DEMO] Option D"],
    "correct_index": 0,
    "explanation": "[DEMO] Justification déterministe pour les tests.",
}


def _validate_candidates(candidates: object, expected_count: int) -> list[str]:
    errors: list[str] = []
    if not isinstance(candidates, list):
        return ["'questions' doit être une liste."]
    if len(candidates) != expected_count:
        errors.append(f"{expected_count} questions attendues, {len(candidates)} reçues.")
    for i, q in enumerate(candidates):
        if not isinstance(q, dict):
            errors.append(f"Élément {i} : pas un objet.")
            continue
        if not isinstance(q.get("question"), str) or not q["question"].strip():
            errors.append(f"Élément {i} : 'question' manquante ou vide.")
        options = q.get("options")
        if not isinstance(options, list) or len(options) != 4 or not all(isinstance(o, str) and o.strip() for o in options):
            errors.append(f"Élément {i} : 'options' doit contenir exactement 4 chaînes non vides.")
        if not isinstance(q.get("correct_index"), int) or q.get("correct_index") not in (0, 1, 2, 3):
            errors.append(f"Élément {i} : 'correct_index' doit être un entier 0-3.")
        if not isinstance(q.get("explanation"), str) or not q["explanation"].strip():
            errors.append(f"Élément {i} : 'explanation' manquante ou vide.")
    return errors


def _demo_candidates(chapter: dict, n: int, existing_count: int) -> list[dict]:
    return [
        {**_DEMO_TEMPLATE, "question": _DEMO_TEMPLATE["question"].format(number=chapter["number"], variant=existing_count + i)}
        for i in range(n)
    ]


def generate_candidate_questions(
    chapter: dict,
    course_title: str,
    n: int,
    existing_questions: list[str] | None = None,
    demo: bool = False,
    tracker: CostTracker | None = None,
) -> list[dict]:
    """Génère `n` questions QCM candidates pour ce chapitre. Chaque candidat retourné a les clés
    `question`/`options`/`correct_index`/`explanation` — jamais `id`/`chapter` (ajoutés par
    l'orchestrateur, build_exam_bank.py, une fois la question VÉRIFIÉE).

    `existing_questions` : textes déjà générés (acceptés ou rejetés) pour ce chapitre lors d'un
    tour précédent — passés au modèle pour éviter les doublons/répétitions entre itérations de la
    boucle génération -> vérification (voir build_exam_bank.py).

    Lève LLMCallError si la réponse reste invalide après un retry sur erreur de schéma (mêmes
    conventions que bloc3_5_quality_control/reviewer.py::review_chapter)."""
    existing_questions = existing_questions or []

    if demo:
        return _demo_candidates(chapter, n, len(existing_questions))

    own_tracker = tracker is None
    if own_tracker:
        tracker = CostTracker(label=f"Bloc 7 - generate_candidate_questions (chapitre {chapter['number']})")

    source_text = chapter_source_text(chapter)
    existing_block = "\n".join(f"- {q}" for q in existing_questions) if existing_questions else "(aucune)"

    prompt = GENERATE_PROMPT_TEMPLATE.format(
        course_title=course_title,
        number=chapter["number"],
        chapter_title=chapter["title"],
        source_text=source_text,
        existing_questions=existing_block,
        n=n,
    )

    last_errors: list[str] = []
    for attempt in range(2):  # 1 essai + 1 retry sur invalidité de schéma (pas sur le fond)
        response_text = call_llm_api(
            prompt=prompt if attempt == 0 else prompt + "\n\nErreurs de format à corriger :\n" + "\n".join(last_errors),
            model=MODEL,
            max_tokens=4096,
            system_prompt=GENERATOR_SYSTEM_PROMPT,
            tracker=tracker,
            use_gemini=False,
            task="exam_questions",
        )
        try:
            payload = extract_json(response_text)
            candidates = payload.get("questions")
            last_errors = _validate_candidates(candidates, n)
        except (json.JSONDecodeError, LLMCallError) as exc:
            last_errors = [f"Réponse non-JSON ou JSON malformé : {exc}"]
        else:
            if not last_errors:
                if own_tracker:
                    tracker.print_summary()
                return candidates

    if own_tracker:
        tracker.print_summary()
    raise LLMCallError(
        f"Génération de questions invalide pour le chapitre {chapter['number']} après {attempt + 1} tentative(s) : "
        f"{last_errors}"
    )
