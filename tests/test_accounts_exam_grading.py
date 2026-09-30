"""Tests unitaires du tirage/mélange/notation de l'examen final (accounts/exam_grading.py).

100% déterministe, aucun appel réseau/LLM — voir le garde-fou explicite de la Phase 2 Étape 2."""

from accounts.exam_grading import PASS_THRESHOLD_PERCENT, draw_questions, grade_submission, shuffle_options

BANK = [
    {"id": f"q{i}", "chapter": 1, "question": f"Question {i} ?", "options": ["A", "B", "C", "D"], "correct_index": i % 4, "explanation": f"Explication {i}."}
    for i in range(1, 16)
]


# --- draw_questions --------------------------------------------------------------------------------


def test_draw_questions_returns_n_distinct_questions():
    drawn = draw_questions(BANK, n=10)
    assert len(drawn) == 10
    assert len({q["id"] for q in drawn}) == 10


def test_draw_questions_caps_at_bank_size():
    small_bank = BANK[:3]
    drawn = draw_questions(small_bank, n=10)
    assert len(drawn) == 3


def test_draw_questions_never_mutates_the_bank():
    before = [q["id"] for q in BANK]
    draw_questions(BANK, n=10)
    assert [q["id"] for q in BANK] == before


# --- shuffle_options ---------------------------------------------------------------------------


def test_shuffle_options_returns_the_same_set_of_texts():
    question = BANK[0]
    shuffled = shuffle_options(question)
    assert sorted(shuffled) == sorted(question["options"])


def test_shuffle_options_never_mutates_the_original_question():
    question = {**BANK[0], "options": list(BANK[0]["options"])}
    original = list(question["options"])
    shuffle_options(question)
    assert question["options"] == original


# --- grade_submission ----------------------------------------------------------------------------


def _bank_by_id(questions):
    return {q["id"]: q for q in questions}


def test_grade_submission_scores_all_correct_as_100_percent():
    questions = BANK[:5]
    bank_by_id = _bank_by_id(questions)
    answers = [(q["id"], q["options"][q["correct_index"]]) for q in questions]

    result = grade_submission(bank_by_id, answers)

    assert result["correct_count"] == 5
    assert result["total"] == 5
    assert result["score_percent"] == 100
    assert result["passed"] is True
    assert result["wrong_questions"] == []


def test_grade_submission_scores_all_wrong_as_0_percent():
    questions = BANK[:5]
    bank_by_id = _bank_by_id(questions)
    # Choisit systématiquement une option différente de la bonne réponse.
    answers = [
        (q["id"], next(opt for i, opt in enumerate(q["options"]) if i != q["correct_index"])) for q in questions
    ]

    result = grade_submission(bank_by_id, answers)

    assert result["correct_count"] == 0
    assert result["score_percent"] == 0
    assert result["passed"] is False
    assert len(result["wrong_questions"]) == 5


def test_grade_submission_pass_threshold_is_70_percent():
    questions = BANK[:10]
    bank_by_id = _bank_by_id(questions)
    # 7/10 correctes -> exactement le seuil.
    answers = []
    for i, q in enumerate(questions):
        if i < 7:
            answers.append((q["id"], q["options"][q["correct_index"]]))
        else:
            answers.append((q["id"], next(opt for j, opt in enumerate(q["options"]) if j != q["correct_index"])))

    result = grade_submission(bank_by_id, answers)

    assert result["score_percent"] == 70 == PASS_THRESHOLD_PERCENT
    assert result["passed"] is True


def test_grade_submission_just_below_threshold_fails():
    questions = BANK[:10]
    bank_by_id = _bank_by_id(questions)
    # 6/10 correctes -> 60%, sous le seuil.
    answers = []
    for i, q in enumerate(questions):
        if i < 6:
            answers.append((q["id"], q["options"][q["correct_index"]]))
        else:
            answers.append((q["id"], next(opt for j, opt in enumerate(q["options"]) if j != q["correct_index"])))

    result = grade_submission(bank_by_id, answers)

    assert result["score_percent"] == 60
    assert result["passed"] is False


def test_grade_submission_treats_no_answer_as_incorrect():
    questions = BANK[:1]
    bank_by_id = _bank_by_id(questions)

    result = grade_submission(bank_by_id, [(questions[0]["id"], None)])

    assert result["correct_count"] == 0
    assert result["total"] == 1
    assert len(result["wrong_questions"]) == 1


def test_grade_submission_wrong_questions_include_explanation_and_correct_answer():
    question = BANK[0]
    bank_by_id = _bank_by_id([question])
    wrong_text = next(opt for i, opt in enumerate(question["options"]) if i != question["correct_index"])

    result = grade_submission(bank_by_id, [(question["id"], wrong_text)])

    wq = result["wrong_questions"][0]
    assert wq["question"] == question["question"]
    assert wq["explanation"] == question["explanation"]
    assert wq["correct_answer"] == question["options"][question["correct_index"]]
    assert "id" not in wq
    assert "correct_index" not in wq


def test_grade_submission_ignores_unknown_question_ids():
    questions = BANK[:2]
    bank_by_id = _bank_by_id(questions)
    answers = [(questions[0]["id"], questions[0]["options"][questions[0]["correct_index"]]), ("unknown-id", "peu importe")]

    result = grade_submission(bank_by_id, answers)

    assert result["total"] == 1
    assert result["correct_count"] == 1
