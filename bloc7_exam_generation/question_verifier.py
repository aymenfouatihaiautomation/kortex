"""Bloc 7, Étape 1b — Agent vérificateur ADVERSARIAL des questions QCM candidates.

Le point critique de tout le pipeline : un second passage LLM, INDÉPENDANT du générateur
(question_generator.py), qui reçoit chaque question candidate SANS son `correct_index` ni son
`explanation` — il doit résoudre lui-même la question à partir du contenu du cours, en aveugle.
On COMPARE ensuite sa réponse (`resolved_index`) à celle proposée par le générateur : tout
désaccord est un rejet, sans exception.

Ce module ne fait jamais confiance par défaut : toute réponse malformée, tout champ manquant,
toute exception réseau est traitée comme un REJET (jamais une acceptation implicite) — c'est la
traduction directe de la consigne "au moindre doute -> rejet, on préfère moins de questions"."""

import json

from common.llm_client import CostTracker, LLMCallError, call_llm_api, extract_json
from bloc7_exam_generation.content_text import chapter_source_text

MODEL = "claude-sonnet-5"  # même exigence que le générateur et le contrôle qualité (Bloc 3.5)

VERIFIER_SYSTEM_PROMPT = (
    "Tu es un vérificateur d'examen ADVERSARIAL et SCEPTIQUE, totalement indépendant du concepteur "
    "de la question que tu évalues. Ton rôle est de chercher activement des raisons de REJETER une "
    "question, jamais de la valider par complaisance. Au moindre doute sur un des points demandés, "
    "réponds par la valeur la moins favorable (false) plutôt que de donner le bénéfice du doute. Tu "
    "réponds UNIQUEMENT avec un objet JSON valide, sans texte avant ou après, sans bloc de code "
    "markdown."
)

VERIFY_PROMPT_TEMPLATE = """\
Cours : "{course_title}". Chapitre {number} : "{chapter_title}".

--- CONTENU VALIDÉ DU CHAPITRE (SEULE source autorisée pour juger cette question) ---
{source_text}

--- QUESTION À VÉRIFIER (tu ne connais PAS la réponse proposée par le concepteur) ---
{question}
Options :
0. {option_0}
1. {option_1}
2. {option_2}
3. {option_3}

Réponds à CHACUN des points suivants, en te basant UNIQUEMENT sur le contenu ci-dessus (jamais une
connaissance externe au cours) :
1. resolved_index : selon TOI, quel est l'index (0, 1, 2 ou 3) de la SEULE bonne réponse d'après le contenu ?
2. answerable_from_course : cette question est-elle répondable en s'appuyant UNIQUEMENT sur le contenu ci-dessus, sans aucune connaissance externe au cours ?
3. single_defensible_answer : y a-t-il EXACTEMENT une réponse défendable parmi les 4 options (pas deux options toutes deux défendables, même partiellement) ?
4. distractors_clearly_wrong : les 3 autres options sont-elles CLAIREMENT fausses selon le contenu (aucune n'est une variante plausible ou partiellement correcte) ?
5. unambiguous_wording : la formulation de la question est-elle claire, sans ambiguïté ni double sens ?

Sois CONSERVATEUR : au moindre doute sur un de ces points, réponds "false" pour ce point plutôt que
de donner le bénéfice du doute.

Réponds avec EXACTEMENT ce format JSON :
{{"resolved_index": 0, "answerable_from_course": true, "single_defensible_answer": true, "distractors_clearly_wrong": true, "unambiguous_wording": true, "reasoning": "..."}}
"""

# Une entrée par critère de rejet possible — utilisée par le rapport (build_exam_bank.py) pour
# compter les rejets PAR RAISON, pas seulement un total.
REJECTION_REASONS = (
    "verifier_disagrees_with_generator",
    "not_answerable_from_course_alone",
    "multiple_defensible_answers",
    "distractor_not_clearly_wrong",
    "ambiguous_wording",
    "verifier_response_malformed",
)

_BOOLEAN_FIELDS = (
    ("answerable_from_course", "not_answerable_from_course_alone"),
    ("single_defensible_answer", "multiple_defensible_answers"),
    ("distractors_clearly_wrong", "distractor_not_clearly_wrong"),
    ("unambiguous_wording", "ambiguous_wording"),
)


def _validate_verdict_shape(verdict: object) -> list[str]:
    if not isinstance(verdict, dict):
        return ["la réponse n'est pas un objet JSON."]
    errors = []
    if verdict.get("resolved_index") not in (0, 1, 2, 3):
        errors.append("'resolved_index' doit être un entier 0-3.")
    for field, _ in _BOOLEAN_FIELDS:
        if not isinstance(verdict.get(field), bool):
            errors.append(f"'{field}' doit être un booléen.")
    return errors


def _reject(reasons: list[str], resolved_index: int | None = None, reasoning: str = "") -> dict:
    return {"accepted": False, "reasons": reasons, "resolved_index": resolved_index, "reasoning": reasoning}


def _demo_verdict(candidate: dict, reject: bool = False) -> dict:
    if reject:
        return _reject(["verifier_disagrees_with_generator"], resolved_index=(candidate["correct_index"] + 1) % 4, reasoning="[DEMO] rejet forcé.")
    return {
        "accepted": True,
        "reasons": [],
        "resolved_index": candidate["correct_index"],
        "reasoning": "[DEMO] Vérification déterministe pour les tests.",
    }


def verify_question(
    chapter: dict,
    course_title: str,
    candidate: dict,
    demo: bool = False,
    demo_reject: bool = False,
    tracker: CostTracker | None = None,
) -> dict:
    """Vérifie une question candidate de façon adversariale et retourne un verdict :
    `{"accepted": bool, "reasons": [...], "resolved_index": int|None, "reasoning": str}`.

    `reasons` est une liste (vide si accepté) de codes tirés de `REJECTION_REASONS` — plusieurs
    raisons peuvent s'appliquer à la fois (ex. désaccord ET distracteur douteux), toutes sont
    listées pour que le rapport (build_exam_bank.py) reste précis.

    NE reçoit jamais `candidate["correct_index"]` ni `candidate["explanation"]` dans le prompt
    envoyé au modèle (voir VERIFY_PROMPT_TEMPLATE) — la comparaison avec `resolved_index` se fait
    seulement APRÈS coup, côté Python, jamais en donnant l'indice au modèle."""
    if demo:
        return _demo_verdict(candidate, reject=demo_reject)

    own_tracker = tracker is None
    if own_tracker:
        tracker = CostTracker(label=f"Bloc 7 - verify_question (chapitre {chapter['number']})")

    source_text = chapter_source_text(chapter)
    prompt = VERIFY_PROMPT_TEMPLATE.format(
        course_title=course_title,
        number=chapter["number"],
        chapter_title=chapter["title"],
        source_text=source_text,
        question=candidate["question"],
        option_0=candidate["options"][0],
        option_1=candidate["options"][1],
        option_2=candidate["options"][2],
        option_3=candidate["options"][3],
    )

    last_errors: list[str] = []
    verdict = None
    for attempt in range(2):  # 1 essai + 1 retry sur invalidité de schéma (pas sur le fond)
        try:
            response_text = call_llm_api(
                prompt=prompt if attempt == 0 else prompt + "\n\nErreurs de format à corriger :\n" + "\n".join(last_errors),
                model=MODEL,
                max_tokens=1024,
                system_prompt=VERIFIER_SYSTEM_PROMPT,
                tracker=tracker,
                use_gemini=False,
                task="exam_questions",
            )
            verdict = extract_json(response_text)
            last_errors = _validate_verdict_shape(verdict)
        except (json.JSONDecodeError, LLMCallError) as exc:
            last_errors = [f"Réponse non-JSON ou JSON malformé : {exc}"]
            verdict = None
        if not last_errors:
            break

    if own_tracker:
        tracker.print_summary()

    if last_errors or verdict is None:
        # Réponse du vérificateur inexploitable après retry : REJET par défaut (fail-closed), voir
        # le docstring du module — jamais une acceptation par défaut.
        return _reject(["verifier_response_malformed"], reasoning="; ".join(last_errors))

    reasons = []
    if verdict["resolved_index"] != candidate["correct_index"]:
        reasons.append("verifier_disagrees_with_generator")
    for field, reason_code in _BOOLEAN_FIELDS:
        if not verdict[field]:
            reasons.append(reason_code)

    return {
        "accepted": not reasons,
        "reasons": reasons,
        "resolved_index": verdict["resolved_index"],
        "reasoning": verdict.get("reasoning", ""),
    }
