"""Attestations de fin de cours — routes Flask.

Suit le même pattern que bloc6_chatbot/course_routes.py::create_course_chat_blueprint : une
factory qui reçoit `courses` (le catalogue complet, un cours recherché par slug à chaque requête
— Changement 4, multi-cours), pour construire les routes sans que ce module dépende de
bloc4_publication.app (qui, lui, l'importe).

CONTRÔLE D'ÉLIGIBILITÉ CRITIQUE (Phase 3 du renforcement de l'attestation, verrouillé) : la
génération est refusée côté SERVEUR (pas seulement masquée côté template) sauf si les 3
conditions suivantes sont TOUTES vraies :
1. l'email en session a acheté ce cours (`has_access`) ;
2. complétion FORTE de tous les chapitres — `accounts.chapter_completion.is_course_complete`
   (Phase 1 : complétion explicite de chaque chapitre ET participation à tous ses items) ;
3. examen final réussi au moins une fois — `accounts.exam.has_passed_exam` (Phase 2, seuil 70%).

L'ANCIEN critère (`accounts.progress.is_course_complete`, simple visite de page) N'EST PLUS
utilisé ici — il ne délivre plus aucune attestation. Il continue d'exister pour le suivi de
visite de `/chapter/<n>` (bloc4_publication/app.py), sans lien avec ce module.

Accès payant mais pas encore éligible -> page `certificate_locked.html` (message propre, pas de
redirection silencieuse) : voir `_is_eligible`/`generate` ci-dessous. La page de vérification et
le téléchargement du PDF restent PUBLICS (aucune session requise) et n'exposent jamais l'email."""

import io
from urllib.parse import urlencode

from flask import Blueprint, abort, redirect, render_template, request, send_file, session, url_for

from accounts.certificate_pdf import render_certificate_pdf
from accounts.certificates import get_certificate_by_token, issue_certificate
from accounts.chapter_completion import is_course_complete
from accounts.exam import has_passed_exam
from bloc4_publication.access_store import has_access


def _build_pdf_for(certificate) -> bytes:
    verify_url = url_for("certificates.verify", token=certificate.token, _external=True)
    return render_certificate_pdf(
        learner_name=certificate.learner_name,
        course_title=certificate.course_title,
        issued_at=certificate.issued_at.strftime("%d/%m/%Y"),
        verify_url=verify_url,
        certificate_id=certificate.token,
    )


def _pdf_response(pdf_bytes: bytes, course_slug: str):
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"attestation-{course_slug}.pdf",
    )


def _linkedin_add_to_profile_url(certificate) -> str:
    verify_url = url_for("certificates.verify", token=certificate.token, _external=True)
    params = {
        "startTask": "CERTIFICATION_NAME",
        "name": certificate.course_title,
        "organizationName": "AI Edu Platform",
        "issueYear": certificate.issued_at.year,
        "issueMonth": certificate.issued_at.month,
        "certUrl": verify_url,
        "certId": certificate.token,
    }
    return "https://www.linkedin.com/profile/add?" + urlencode(params)


def create_certificate_blueprint(courses: list[dict]) -> Blueprint:
    """Un seul blueprint pour TOUT le catalogue (Flask refuse deux blueprints de même nom) : le
    cours est recherché par `slug` À CHAQUE REQUÊTE (voir `_find_course`), pas figé à
    l'enregistrement — nécessaire dès qu'un second cours existe (Changement 4, multi-cours)."""
    bp = Blueprint("certificates", __name__)

    def _find_course(slug: str) -> dict | None:
        return next((c for c in courses if c["slug"] == slug), None)

    def _has_paid_access(slug: str) -> bool:
        # Même garde-fou que bloc4_publication/app.py::_has_paid_access, dupliqué ici plutôt
        # qu'importé : ce module ne dépend jamais de bloc4_publication.app (c'est l'inverse).
        email = session.get("email")
        return bool(email) and has_access(email, slug)

    def _is_eligible(email: str, course: dict) -> bool:
        # Les 2 conditions restantes une fois l'accès payant déjà vérifié (voir _has_paid_access
        # ci-dessus) — les 3 ENSEMBLE forment le garde-fou complet de la Phase 3.
        return is_course_complete(email, course["slug"], course["chapters"]) and has_passed_exam(
            email, course["slug"]
        )

    @bp.route("/certificate/generate/<slug>", methods=["GET", "POST"])
    def generate(slug):
        course = _find_course(slug)
        if course is None:
            abort(404)

        # Refus SERVEUR, pas seulement un bouton masqué côté template — mêmes conséquences que
        # pour /chapter/<n> : pas d'accès payant -> retour à la page d'achat.
        if not _has_paid_access(slug):
            return redirect(url_for("course_landing", slug=slug))

        email = session["email"]
        if not _is_eligible(email, course):
            # A le droit d'être ici (a payé), mais pas encore éligible (chapitres et/ou examen) :
            # message propre plutôt qu'une redirection silencieuse ou une attestation nulle.
            return render_template("certificate_locked.html", course=course)

        if request.method == "GET":
            return render_template(
                "certificate_generate.html",
                course=course,
                learner_name=session.get("google_name", ""),
            )

        learner_name = (request.form.get("learner_name") or "").strip()
        if not learner_name:
            return (
                render_template(
                    "certificate_generate.html",
                    course=course,
                    learner_name="",
                    error="Indique ton nom pour générer l'attestation.",
                ),
                400,
            )

        certificate = issue_certificate(
            email=email,
            course_slug=course["slug"],
            course_title=course["title"],
            learner_name=learner_name,
        )
        # Redirige vers la page de vérification (plutôt que de renvoyer le PDF directement) :
        # c'est là que vit le bouton "Partager sur LinkedIn" bien visible (garde-fou explicite de
        # la Phase 3) — le téléchargement du PDF reste possible depuis cette même page.
        return redirect(url_for("certificates.verify", token=certificate.token))

    @bp.route("/certificate/<token>")
    def verify(token):
        # PUBLIC — aucune vérification de session ici. Ne jamais passer `certificate.email` au
        # template (voir certificate_verify.html) : c'est le seul champ que cette page ne doit
        # jamais révéler.
        certificate = get_certificate_by_token(token)
        if not certificate:
            abort(404)
        return render_template(
            "certificate_verify.html",
            certificate=certificate,
            linkedin_url=_linkedin_add_to_profile_url(certificate),
        )

    @bp.route("/certificate/<token>/pdf")
    def download(token):
        # PUBLIC également — permet de retélécharger le PDF depuis la page de vérification
        # (utile si l'apprenant a perdu son fichier), sans exposer davantage que la page elle-même
        # (le PDF ne contient jamais l'email non plus, voir accounts/certificate_pdf.py).
        certificate = get_certificate_by_token(token)
        if not certificate:
            abort(404)
        return _pdf_response(_build_pdf_for(certificate), certificate.course_slug)

    return bp
