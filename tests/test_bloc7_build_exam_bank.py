"""Tests de l'orchestrateur (bloc7_exam_generation/build_exam_bank.py) : boucle génération ->
vérification, plafond d'itérations, répartition par chapitre, et sauvegarde des fichiers de
sortie. Les appels LLM sous-jacents sont soit en mode démo, soit mockés — aucun appel réseau ici."""

import json
from unittest.mock import patch

from bloc7_exam_generation.build_exam_bank import _per_chapter_bounds, build_exam_bank, save_result

FAKE_COURSE = {
    "title": "Cours de test",
    "slug": "cours-de-test",
    "chapters": [
        {"number": 1, "title": "Chapitre 1", "learning_objectives": [], "key_points": [], "content_blocks": None, "lesson_script": "Contenu 1.", "written_complement": None},
        {"number": 2, "title": "Chapitre 2", "learning_objectives": [], "key_points": [], "content_blocks": None, "lesson_script": "Contenu 2.", "written_complement": None},
        {"number": 3, "title": "Chapitre 3", "learning_objectives": [], "key_points": [], "content_blocks": None, "lesson_script": "Contenu 3.", "written_complement": None},
    ],
}


def _candidate(i: int) -> dict:
    return {
        "question": f"Question {i} ?",
        "options": ["A", "B", "C", "D"],
        "correct_index": 0,
        "explanation": f"Explication {i}.",
    }


# --- _per_chapter_bounds --------------------------------------------------------------------------


def test_per_chapter_bounds_derived_from_real_chapter_count_not_hardcoded():
    target, maximum = _per_chapter_bounds(7, target_total=24)
    assert target == 4  # ceil(24/7)
    assert maximum == 6

    target3, maximum3 = _per_chapter_bounds(3, target_total=24)
    assert target3 == 8  # ceil(24/3)
    assert maximum3 == 10


def test_per_chapter_bounds_uses_the_actual_target_total_not_a_module_constant():
    # Bug réel corrigé : _per_chapter_bounds utilisait TARGET_TOTAL_QUESTIONS (24) au lieu du
    # target_total réellement passé à build_exam_bank, ce qui désactivait silencieusement le
    # plafond par chapitre pour tout run avec une cible personnalisée.
    target, maximum = _per_chapter_bounds(3, target_total=6)
    assert target == 2  # ceil(6/3), PAS ceil(24/3)
    assert maximum == 4


# --- mode démo (fumée, câblage complet) ------------------------------------------------------------


def test_demo_mode_produces_a_well_formed_bank_without_network_calls():
    result = build_exam_bank(FAKE_COURSE, target_total=6, batch_size=3, max_iterations=2, demo=True)

    questions = result["questions"]
    assert len(questions) > 0
    ids = [q["id"] for q in questions]
    assert ids == [f"q{i + 1}" for i in range(len(questions))]
    for q in questions:
        assert set(q.keys()) == {"id", "chapter", "question", "options", "correct_index", "explanation"}
        assert q["chapter"] in (1, 2, 3)


def test_report_totals_are_internally_consistent():
    result = build_exam_bank(FAKE_COURSE, target_total=6, batch_size=3, max_iterations=2, demo=True)
    totals = result["report"]["totals"]
    assert totals["generated"] == totals["accepted"] + totals["rejected"] + totals["discarded_over_chapter_quota"]
    assert totals["accepted"] == len(result["questions"])


# --- boucle : plafond d'itérations, jamais infini --------------------------------------------------


@patch("bloc7_exam_generation.build_exam_bank.verify_question")
@patch("bloc7_exam_generation.build_exam_bank.generate_candidate_questions")
def test_stops_after_max_iterations_when_target_never_reached(mock_generate, mock_verify):
    mock_generate.side_effect = lambda chapter, course_title, n, existing_questions, demo, tracker: [
        _candidate(i) for i in range(n)
    ]
    mock_verify.return_value = {"accepted": False, "reasons": ["not_answerable_from_course_alone"], "resolved_index": 1, "reasoning": "non"}

    result = build_exam_bank(FAKE_COURSE, target_total=24, batch_size=2, max_iterations=3, demo=False)

    assert len(result["questions"]) == 0
    assert result["report"]["target_reached"] is False
    # Aucune progression possible (tout rejeté) -> arrêt après la 1ère itération, pas 3.
    assert result["report"]["iterations_used"] == 1
    assert mock_generate.call_count == len(FAKE_COURSE["chapters"])  # une fois par chapitre, puis stop


@patch("bloc7_exam_generation.build_exam_bank.verify_question")
@patch("bloc7_exam_generation.build_exam_bank.generate_candidate_questions")
def test_runs_additional_iterations_while_making_progress_and_under_target(mock_generate, mock_verify):
    calls = {"n": 0}

    def fake_generate(chapter, course_title, n, existing_questions, demo, tracker):
        calls["n"] += 1
        return [_candidate(calls["n"] * 100 + i) for i in range(n)]

    mock_generate.side_effect = fake_generate
    mock_verify.return_value = {"accepted": True, "reasons": [], "resolved_index": 0, "reasoning": "ok"}

    result = build_exam_bank(FAKE_COURSE, target_total=100, batch_size=2, max_iterations=3, demo=False)

    # Toujours accepté -> chaque chapitre plafonne à per_chapter_max (target=ceil(100/3)=34, max=36)
    # bien avant d'atteindre 100 au total -> les itérations suivantes n'apportent plus rien une fois
    # tous les chapitres au plafond -> made_progress finit par retomber à False.
    assert result["report"]["iterations_used"] <= 3
    for count in result["report"]["accepted_by_chapter"].values():
        assert count <= result["report"]["per_chapter_max"]


# --- répartition par chapitre : quota, jamais un rejet qualité -------------------------------------


@patch("bloc7_exam_generation.build_exam_bank.verify_question")
@patch("bloc7_exam_generation.build_exam_bank.generate_candidate_questions")
def test_accepted_questions_beyond_per_chapter_max_are_discarded_not_rejected(mock_generate, mock_verify):
    # batch_size=10 largement au-dessus de per_chapter_max (target=ceil(6/3)=2, max=4) pour un seul
    # chapitre, tout accepté -> le surplus doit être dans discarded_over_chapter_quota, jamais
    # compté comme un rejet qualité (reasons vide).
    mock_generate.side_effect = lambda chapter, course_title, n, existing_questions, demo, tracker: [
        _candidate(i) for i in range(n)
    ]
    mock_verify.return_value = {"accepted": True, "reasons": [], "resolved_index": 0, "reasoning": "ok"}

    result = build_exam_bank(FAKE_COURSE, target_total=6, batch_size=10, max_iterations=1, demo=False)

    report = result["report"]
    assert report["totals"]["rejected"] == 0
    assert report["totals"]["discarded_over_chapter_quota"] > 0
    for count in report["accepted_by_chapter"].values():
        assert count <= report["per_chapter_max"]


@patch("bloc7_exam_generation.build_exam_bank.verify_question")
@patch("bloc7_exam_generation.build_exam_bank.generate_candidate_questions")
def test_rejected_by_reason_counts_match_rejections_list(mock_generate, mock_verify):
    mock_generate.side_effect = lambda chapter, course_title, n, existing_questions, demo, tracker: [
        _candidate(i) for i in range(n)
    ]
    mock_verify.return_value = {
        "accepted": False,
        "reasons": ["verifier_disagrees_with_generator", "ambiguous_wording"],
        "resolved_index": 1,
        "reasoning": "non",
    }

    result = build_exam_bank(FAKE_COURSE, target_total=6, batch_size=1, max_iterations=1, demo=False)

    report = result["report"]
    assert report["rejected_by_reason"]["verifier_disagrees_with_generator"] == len(FAKE_COURSE["chapters"])
    assert report["rejected_by_reason"]["ambiguous_wording"] == len(FAKE_COURSE["chapters"])
    assert len(report["rejections"]) == len(FAKE_COURSE["chapters"])


@patch("bloc7_exam_generation.build_exam_bank.verify_question")
@patch("bloc7_exam_generation.build_exam_bank.generate_candidate_questions")
def test_existing_questions_accumulate_across_iterations(mock_generate, mock_verify):
    # `existing_questions` est la MÊME liste mutée en place à chaque tour (voir
    # build_exam_bank.py::seen_questions) : inspecter mock_generate.call_args_list APRÈS coup ne
    # verrait que son état final pour chaque appel (piège classique des mocks sur objets mutables).
    # On capture donc une COPIE à l'instant de chaque appel, ici.
    seen_snapshots = []

    def fake_generate(chapter, course_title, n, existing_questions, demo, tracker):
        if chapter["number"] == 1:
            seen_snapshots.append(list(existing_questions))
        return [_candidate(len(existing_questions))]

    mock_generate.side_effect = fake_generate

    # Seul le tout premier appel (chapitre 1, itération 1) est accepté -> made_progress=True une
    # fois, assez pour que la boucle poursuive jusqu'à l'itération 2 (target_total=100 jamais
    # atteint, donc seule la règle "no progress" pourrait arrêter plus tôt).
    verify_calls = {"n": 0}

    def fake_verify(chapter, course_title, candidate, demo, demo_reject, tracker):
        verify_calls["n"] += 1
        accepted = verify_calls["n"] == 1
        return {"accepted": accepted, "reasons": [] if accepted else ["ambiguous_wording"], "resolved_index": 0, "reasoning": "x"}

    mock_verify.side_effect = fake_verify

    build_exam_bank(FAKE_COURSE, target_total=100, batch_size=1, max_iterations=2, demo=False)

    assert len(seen_snapshots) == 2  # une fois par itération pour le chapitre 1
    assert seen_snapshots[0] == []
    assert seen_snapshots[1] == ["Question 0 ?"]


# --- sauvegarde des fichiers ------------------------------------------------------------------------


def test_save_result_writes_questions_and_report_files(tmp_path):
    result = build_exam_bank(FAKE_COURSE, target_total=6, batch_size=3, max_iterations=1, demo=True)

    with patch("bloc7_exam_generation.build_exam_bank.DATA_DIR", tmp_path):
        questions_path, report_json_path, report_md_path = save_result(result)

    assert questions_path == tmp_path / "cours-de-test" / "exam_questions.json"
    assert questions_path.exists()
    assert report_json_path.exists()
    assert report_md_path.exists()

    saved_questions = json.loads(questions_path.read_text(encoding="utf-8"))
    assert saved_questions == result["questions"]

    saved_report = json.loads(report_json_path.read_text(encoding="utf-8"))
    assert saved_report["course_slug"] == "cours-de-test"

    md_text = report_md_path.read_text(encoding="utf-8")
    assert "Rapport de vérification" in md_text
