"""Examen final de cours — tirage, mélange et notation. 100% déterministe, AUCUN appel LLM (voir
le garde-fou explicite de la Phase 2, Étape 2) : la notation compare seulement le TEXTE de
l'option choisie au texte de la bonne réponse dans la banque vérifiée (bloc7_exam_generation,
exam_questions.json).

Pourquoi comparer par TEXTE plutôt que par index d'origine : les options sont mélangées à chaque
tirage (voir `shuffle_options`). Faire transiter la correspondance mélange -> index d'origine par
la session Flask exposerait la bonne réponse à l'apprenant AVANT qu'il ne réponde — une session
Flask par défaut est un cookie SIGNÉ (protégé contre la falsification) mais PAS CHIFFRÉ (lisible
en base64 par quiconque inspecte son propre cookie). Comparer par texte évite ce problème sans
table ni session supplémentaire : le serveur relit la banque par `id` au moment de la notation,
jamais confiance dans un `correct_index` renvoyé par le client."""

import random

QUESTIONS_PER_ATTEMPT = 10
PASS_THRESHOLD_PERCENT = 70


def draw_questions(bank: list[dict], n: int = QUESTIONS_PER_ATTEMPT) -> list[dict]:
    """Tire au hasard `n` questions de la banque (ou moins si elle en contient moins) — retourne
    les questions ORIGINALES, options dans leur ordre canonique. Un nouveau tirage à chaque appel
    (jamais mis en cache) : chaque tentative d'examen retire un tirage différent, comme demandé."""
    return random.sample(bank, k=min(n, len(bank)))


def shuffle_options(question: dict) -> list[str]:
    """Retourne les TEXTES des options de cette question dans un ordre mélangé — jamais l'index
    d'origine, jamais un indicateur de correction (contrairement aux QCM de pratique en cours de
    chapitre, qui exposent `data-correct` dans le HTML — un examen qui compte pour l'attestation
    ne doit jamais faire ça, voir le docstring du module)."""
    options = list(question["options"])
    random.shuffle(options)
    return options


def grade_submission(bank_by_id: dict[str, dict], answers: list[tuple[str, str | None]]) -> dict:
    """Note une soumission. `answers` : liste de `(question_id, texte_choisi_ou_None)`, dans
    l'ordre des questions présentées — reconstruite par la route à partir des champs du
    formulaire. Une question absente de `bank_by_id` est ignorée (jamais une exception) : ça ne
    peut arriver qu'en cas de banque changée entre l'affichage et la soumission, un cas limite qui
    ne doit jamais faire planter la notation.

    Toujours déterministe : la bonne réponse de chaque question est relue depuis `bank_by_id`
    (jamais un `correct_index` fourni par le client). Une question sans réponse sélectionnée
    (`None`) est toujours comptée comme incorrecte.

    Retourne `{"correct_count", "total", "score_percent", "passed", "wrong_questions"}` —
    `wrong_questions` liste, pour chaque question ratée, `{"question", "explanation",
    "correct_answer"}` : exactement ce qu'affiche la page de résultat, jamais l'`id` ni le
    `correct_index` brut."""
    valid_answers = [(qid, text) for qid, text in answers if qid in bank_by_id]
    total = len(valid_answers)

    wrong_questions = []
    correct_count = 0
    for question_id, chosen_text in valid_answers:
        question = bank_by_id[question_id]
        correct_text = question["options"][question["correct_index"]]
        if chosen_text == correct_text:
            correct_count += 1
        else:
            wrong_questions.append(
                {
                    "question": question["question"],
                    "explanation": question["explanation"],
                    "correct_answer": correct_text,
                }
            )

    score_percent = round(100 * correct_count / total) if total else 0
    return {
        "correct_count": correct_count,
        "total": total,
        "score_percent": score_percent,
        "passed": score_percent >= PASS_THRESHOLD_PERCENT,
        "wrong_questions": wrong_questions,
    }
