"""Examen final de cours — routes Flask (Phase 2, Étape 2).

Suit le même pattern que accounts/certificate_routes.py::create_certificate_blueprint : une
factory recevant `courses` (le catalogue complet, un cours recherché par slug à chaque requête —
Changement 4, multi-cours), pour construire les routes sans que ce module dépende de
bloc4_publication.app (qui, lui, l'importe).

GATE D'ACCÈS CRITIQUE : l'examen n'est accessible que si l'email en session a acheté le cours
(`has_access`) ET si `accounts.chapter_completion.is_course_complete` (Phase 1 — complétion
EXPLICITE de tous les chapitres ET participation à tous leurs items) est vrai. C'est la version
FORTE, PAS `accounts.progress.is_course_complete` (le critère historique basé sur la simple
visite de page, utilisé par l'attestation actuelle) — les deux coexistent volontairement, voir
leurs docstrings respectifs. Refus SERVEUR dans les deux cas (GET et POST), jamais juste un lien
masqué côté template.

ROBUSTESSE : si la banque de questions n'existe pas pour ce cours (pas encore générée, ou
absente en production suite à un oubli de déploiement — voir .gitignore), GET et POST affichent
un message propre ("examen indisponible pour ce cours") au lieu de laisser
`load_exam_questions` retourner None et planter plus loin — jamais un 500. Voir
bloc4_publication/content_loader.py::load_exam_questions/exam_bank_available.

AUCUN appel LLM ici : la notation est 100% déterministe, voir accounts/exam_grading.py."""

from flask import Blueprint, abort, redirect, render_template, request, session, url_for

from accounts.chapter_completion import is_course_complete
from accounts.exam import record_attempt
from accounts.exam_grading import draw_questions, grade_submission, shuffle_options
from bloc4_publication.access_store import has_access
from bloc4_publication.content_loader import load_exam_questions


def create_exam_blueprint(courses: list[dict]) -> Blueprint:
    """Un seul blueprint pour TOUT le catalogue (Flask refuse deux blueprints de même nom) : le
    cours est recherché par `slug` À CHAQUE REQUÊTE (voir `_find_course`), pas figé à
    l'enregistrement — nécessaire dès qu'un second cours existe (Changement 4, multi-cours)."""
    bp = Blueprint("exam", __name__)

    def _find_course(slug: str) -> dict | None:
        return next((c for c in courses if c["slug"] == slug), None)

    def _has_paid_access(slug: str) -> bool:
        # Même garde-fou que bloc4_publication/app.py::_has_paid_access et
        # accounts/certificate_routes.py, dupliqué ici plutôt qu'importé : ce module ne dépend
        # jamais de bloc4_publication.app (c'est l'inverse).
        email = session.get("email")
        return bool(email) and has_access(email, slug)

    def _course_complete(email: str, course: dict) -> bool:
        return is_course_complete(email, course["slug"], course["chapters"])

    @bp.route("/course/<slug>/exam", methods=["GET"])
    def take(slug):
        course = _find_course(slug)
        if course is None:
            abort(404)
        if not _has_paid_access(slug):
            return redirect(url_for("course_landing", slug=slug))

        email = session["email"]
        if not _course_complete(email, course):
            return render_template("exam_locked.html", course=course, reason="incomplete")

        bank = load_exam_questions(slug)
        if bank is None:
            return render_template("exam_locked.html", course=course, reason="unavailable")

        drawn = draw_questions(bank)
        questions = [
            {"id": q["id"], "question": q["question"], "shuffled_options": shuffle_options(q)} for q in drawn
        ]
        return render_template("exam_take.html", course=course, questions=questions)

    @bp.route("/course/<slug>/exam", methods=["POST"])
    def submit(slug):
        course = _find_course(slug)
        if course is None:
            abort(404)
        if not _has_paid_access(slug):
            return redirect(url_for("course_landing", slug=slug))

        email = session["email"]
        if not _course_complete(email, course):
            return render_template("exam_locked.html", course=course, reason="incomplete")

        bank = load_exam_questions(slug)
        if bank is None:
            return render_template("exam_locked.html", course=course, reason="unavailable")

        question_ids = request.form.getlist("question_id")
        if not question_ids:
            abort(400)

        bank_by_id = {q["id"]: q for q in bank}
        answers = [(qid, request.form.get(f"answer_{qid}")) for qid in question_ids]

        result = grade_submission(bank_by_id, answers)
        record_attempt(email, slug, result["score_percent"], result["total"], result["passed"])

        return render_template("exam_result.html", course=course, result=result)

    return bp
