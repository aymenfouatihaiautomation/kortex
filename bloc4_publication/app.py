"""Bloc 4 — Application Flask du LMS : landing page publique + cours protégé par accès (Bloc 5).

Un seul cours, pas de système multi-cours. Contenu chargé une fois au démarrage (lecture seule,
jamais modifié) ; l'accès aux chapitres est gardé par une session simple (pas de mot de passe :
un token unique par achat, voir `access_store.py`) — ou par un compte (`accounts/`, Phase 1 email
+ mot de passe, Phase 2 Google).
"""

import hmac
import os
import secrets
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.utils import secure_filename

from bloc4_publication.access_store import SLUG_COURS_1, has_access, resolve_token
from bloc4_publication.config import (
    CHAPTER_1_VIDEO_FILE,
    FLASK_SECRET_KEY,
    LEGAL_CONTACT_EMAIL,
    MARKETING_IMAGES_DIR,
    MARKETING_UPLOAD_TOKEN,
)
from bloc4_publication.content_loader import (
    exam_bank_available,
    get_chapter,
    get_course_by_slug,
    lesson_paragraphs,
    load_course,
    load_published_courses,
    render_inline_emphasis,
    resolve_full_course,
)
from bloc4_publication.exercise_correction import (
    ALLOWED_FILE_EXTENSIONS,
    ALLOWED_MEDIA_EXTENSIONS,
    InvalidUploadError,
    MAX_ANSWER_LENGTH,
    MAX_CORRECTIONS_PER_EXERCISE,
    MAX_MEDIA_FILE_SIZE_BYTES,
    MAX_PRACTICAL_SUBMISSION_LENGTH,
    build_practical_reference_text,
    request_correction,
    validate_and_read_upload,
)

# Attribut HTML `accept` du champ d'upload — une seule source de vérité (les listes blanches
# réelles de exercise_correction.py), pour que le sélecteur de fichier du navigateur ne masque
# jamais un type par ailleurs accepté côté serveur.
ACCEPTED_UPLOAD_EXTENSIONS = ",".join(sorted(ALLOWED_FILE_EXTENSIONS | set(ALLOWED_MEDIA_EXTENSIONS)))
from common.llm_client import LLMCallError
from pricing_agent.pricing_state import get_current_price_id, get_current_price_usd
from bloc5_payment import config as bloc5_config
from bloc5_payment.config import paddle_overlay_enabled
from bloc5_payment.paddle_client import resolve_price_id
from bloc6_chatbot.routes import create_general_chat_blueprint
from bloc6_chatbot.course_routes import create_course_chat_blueprint
from accounts.certificate_routes import create_certificate_blueprint
from accounts.chapter_completion import (
    count_answered_items,
    is_chapter_marked_complete,
    mark_chapter_complete,
    missing_item_labels,
    record_item_answered,
)
from accounts.chapter_completion import is_course_complete as chapters_fully_complete
from accounts.exam import has_passed_exam
from accounts.exam_routes import create_exam_blueprint
from accounts.progress import record_chapter_visit


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = FLASK_SECRET_KEY

    if os.environ.get("RENDER"):
        # Render est derrière un proxy qui termine le TLS et transmet en HTTP en interne. Sans
        # ceci, `request.scheme` (donc `url_for(..., _external=True)`, utilisé pour construire
        # l'URI de callback Google — voir accounts/routes.py::login_google) vaudrait "http",
        # jamais "https" — ce qui ne correspondrait plus à l'URI https:// déclarée dans Google
        # Cloud Console et lèverait redirect_uri_mismatch. `x_proto=1` fait confiance à UN SEUL
        # hop de X-Forwarded-Proto (celui du proxy Render, jamais un client direct — la variable
        # RENDER n'est positionnée que sur Render même, jamais en local). `x_for=1` corrige aussi
        # `request.remote_addr` (sinon toujours l'IP interne du proxy pour tout le monde), utilisé
        # par le rate-limiting des connexions (accounts/routes.py, bloc6_chatbot/shared.py).
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    app.jinja_env.filters["paragraphs"] = lesson_paragraphs
    app.jinja_env.filters["inline_emphasis"] = render_inline_emphasis
    # Garde-fou upload (défense en profondeur, en plus de la validation applicative dans
    # validate_and_read_upload) : Flask rejette directement (413) tout corps de requête dépassant
    # cette taille, avant même de le lire en mémoire — marge au-delà de MAX_MEDIA_FILE_SIZE_BYTES
    # (la plus grande des deux limites : image/PDF) pour le champ texte + l'overhead multipart.
    app.config["MAX_CONTENT_LENGTH"] = MAX_MEDIA_FILE_SIZE_BYTES + 64 * 1024

    # `course` : le cours 1, EXACTEMENT comme avant le Changement 4 — /chapter/<n>, /video, les
    # routes de correction d'exercices et de progression restent câblées sur cette variable fixe
    # (délibérément INCHANGÉES à cette étape, voir leur note plus bas). `courses` : le catalogue
    # dynamique complet (data/published_courses.json, ou [course] en fallback si ce fichier est
    # absent/vide/invalide — voir content_loader.load_published_courses) — utilisé par le
    # catalogue, la landing par slug, le tableau de bord multi-cours, et les blueprints
    # exam/certificate/chat tuteur (qui font désormais leur propre lookup par slug).
    course = load_course()
    courses = [resolve_full_course(entry) for entry in load_published_courses()]

    from bloc5_payment.routes import bloc5_bp

    from accounts.oauth import init_oauth
    from accounts.routes import accounts_bp

    app.register_blueprint(bloc5_bp)
    app.register_blueprint(create_general_chat_blueprint(courses))
    app.register_blueprint(create_course_chat_blueprint(courses))
    app.register_blueprint(create_certificate_blueprint(courses))
    app.register_blueprint(create_exam_blueprint(courses))
    app.register_blueprint(accounts_bp)
    # Après app.secret_key (Authlib s'appuie sur la session Flask pour le `state` anti-CSRF) —
    # n'enregistre le client Google que si GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET sont définis,
    # voir accounts/oauth.py::google_oauth_enabled.
    init_oauth(app)

    def _has_paid_access() -> bool:
        # Un email en session ne suffit plus à lui seul depuis l'ajout des comptes
        # (accounts/routes.py) : se connecter prouve seulement qu'on connaît le mot de passe d'un
        # compte, pas qu'on a acheté le cours. `has_access` vérifie le VRAI registre d'achat
        # (bloc4_publication/access_store.py), peu importe que l'email en session vienne d'un
        # jeton d'accès (/access/<token>) ou d'une connexion par mot de passe. Scopé par
        # `course["slug"]` (Changement 4, multi-cours) : un achat d'un AUTRE cours ne doit jamais
        # débloquer celui-ci.
        email = session.get("email")
        return bool(email) and has_access(email, course["slug"])

    def _exam_ready(email: str) -> bool:
        # Critère FORT (Phase 1) ET banque disponible (Phase 2 Étape 1, robustesse) — utilisé à la
        # fois par le tableau de bord et par la fin du dernier chapitre pour proposer l'examen.
        return chapters_fully_complete(email, course["slug"], course["chapters"]) and exam_bank_available(
            course["slug"]
        )

    def _certificate_ready(email: str) -> bool:
        # Phase 3 (verrouillé) : complétion FORTE de tous les chapitres ET examen final réussi au
        # moins une fois (>= 70%) — l'ancien critère de simple visite ne délivre plus rien ici.
        return chapters_fully_complete(email, course["slug"], course["chapters"]) and has_passed_exam(
            email, course["slug"]
        )

    def _chapter_progress_summary(chap: dict, email: str) -> dict:
        # Résumé consommé à la fois par le rendu initial de /chapter/<n> (état correct dès le
        # premier chargement, sans aller-retour JS) et par /chapter/<n>/progress (rafraîchi après
        # chaque QCM/question/soumission pratique répondue — voir base_reading.html). `total_items`
        # vient TOUJOURS de la structure réelle du chapitre (jamais codé en dur) : nombre
        # d'exercices de compréhension + 1 exercice pratique, toujours présent (content_loader.py).
        total_items = len(chap["comprehension_exercises"]) + 1
        answered_count = count_answered_items(email, course["slug"], chap["number"])
        return {
            "answered_count": answered_count,
            "total_items": total_items,
            "missing": missing_item_labels(email, course["slug"], chap),
            "ready": answered_count >= total_items,
            "chapter_marked_complete": is_chapter_marked_complete(email, course["slug"], chap["number"]),
        }

    @app.context_processor
    def inject_legal_contact():
        return {"contact_email": LEGAL_CONTACT_EMAIL}

    @app.route("/")
    def home():
        price = f"${get_current_price_usd():.2f}"
        return render_template("home.html", courses=courses, price=price)

    @app.route("/a-propos")
    def about():
        return render_template("about.html")

    @app.route("/cours")
    def catalog():
        return render_template("catalog.html", courses=courses)

    @app.route("/cours/<slug>")
    def course_landing(slug):
        # Catalogue dynamique (Changement 4, Étape C) : cherche dans load_published_courses (via
        # get_course_by_slug), pas seulement le cours 1 câblé en dur — 404 propre si le slug
        # n'existe dans aucun cours publié.
        entry = get_course_by_slug(slug)
        if entry is None:
            abort(404)
        course_for_slug = resolve_full_course(entry)

        if slug == SLUG_COURS_1:
            # Cours 1 : pricing dynamique inchangé (pricing_agent), jamais le prix figé du
            # catalogue — comportement identique à avant ce changement.
            price_usd_value = get_current_price_usd()
            landing_price_id = resolve_price_id(get_current_price_id())
        else:
            price_usd_value = course_for_slug.get("price_usd")
            landing_price_id = course_for_slug.get("paddle_price_id")
        price = f"${price_usd_value:.2f}" if price_usd_value is not None else "Prix à venir"

        email = session.get("email")
        # Overlay Paddle.js (checkout côté client, requis par Paddle Billing) : proposé
        # uniquement si PADDLE_CLIENT_TOKEN est configuré — voir
        # bloc5_payment/config.py::paddle_overlay_enabled et le garde-fou correspondant dans
        # landing.html (formulaire GET vers /checkout/start inchangé sinon, chemin mock/tests).
        return render_template(
            "landing.html",
            course=course_for_slug,
            price=price,
            paddle_overlay_enabled=paddle_overlay_enabled(),
            # Lu via le module (pas une valeur importée à part) pour rester patchable par les
            # tests, même raison que `from accounts import db` + `db.SessionLocal()` dans
            # accounts/service.py — voir accounts/db.py pour l'explication complète.
            paddle_client_token=bloc5_config.PADDLE_CLIENT_TOKEN,
            paddle_price_id=landing_price_id,
            # Un acheteur déjà connecté ne doit pas revoir le formulaire d'achat sur sa propre
            # landing page — scopé par CE slug précis, pas _has_paid_access (câblée sur le cours 1).
            already_purchased=bool(email) and has_access(email, slug),
            # Cible du bouton "Continuer" : /course (hub riche, examen/attestation) pour le cours 1,
            # INCHANGÉ ; contenu directement (/cours/<slug>/chapitre/1) pour tout autre cours — avant
            # ce fix, un acheteur du cours 2 atterrissait sur /course puis devait encore cliquer une
            # carte de chapitre (course_home_readonly.html) pour lire sa première leçon.
            continue_url=url_for("course_home") if slug == SLUG_COURS_1 else url_for("course_chapter", slug=slug, number=1),
        )

    @app.route("/terms")
    def terms():
        return render_template("terms.html")

    @app.route("/privacy")
    def privacy():
        return render_template("privacy.html")

    @app.route("/refunds")
    def refunds():
        return render_template("refunds.html")

    @app.route("/access/<token>")
    def access(token):
        # resolve_token retourne (email, slug) depuis le Changement 4 (multi-cours) — le slug
        # n'est pas encore utilisé ici pour rediriger vers un cours précis (voir ÉTAPE C), mais
        # le déballage doit rester correct dès cette étape.
        result = resolve_token(token)
        if not result:
            abort(404)
        email, _slug = result
        session["email"] = email
        return redirect(url_for("course_home"))

    @app.route("/course")
    def course_home():
        # Multi-cours (Changement 4, Étape C) : 0 cours acheté -> page d'achat du cours 1 (COMPORTEMENT
        # INCHANGÉ, y compris pour un visiteur non connecté) ; 1 seul cours acheté ET c'est le
        # cours 1 -> tableau de bord riche INCHANGÉ (exam_ready/certificate_ready restent une
        # logique propre au cours 1, pas étendue ici) ; 1 seul cours acheté mais PAS le cours 1
        # -> tableau de bord en lecture seule (course_home_readonly.html) — avant ce fix, ceci
        # redirigeait vers la page de VENTE du cours déjà acheté (boucle confuse pour l'acheteur,
        # voir landing.html:62 "Accéder au cours" -> course_home -> ici) ; plusieurs cours achetés
        # -> liste simple (voir my_courses.html).
        email = session.get("email")
        owned = [c for c in courses if email and has_access(email, c["slug"])]

        if not owned:
            return redirect(url_for("course_landing", slug=course["slug"]))

        if len(owned) > 1:
            return render_template("my_courses.html", courses=owned)

        only = owned[0]
        if only["slug"] != course["slug"]:
            entry = get_course_by_slug(only["slug"])
            course_for_slug = resolve_full_course(entry) if entry else only
            return render_template("course_home_readonly.html", course=course_for_slug, email=email)

        exam_ready = _exam_ready(email)
        certificate_ready = _certificate_ready(email)
        return render_template(
            "course_home.html",
            course=course,
            email=email,
            certificate_ready=certificate_ready,
            exam_ready=exam_ready,
        )

    @app.route("/cours/<slug>/chapitre/<int:number>")
    def course_chapter(slug, number):
        # Lecture seule pour tout cours AUTRE que le cours 1 (redirigé ci-dessous vers /chapter/<n>,
        # comportement inchangé). Volontairement SANS les blocs exercices/progression/completion de
        # chapter.html : leur JS (base_reading.html) construit ses URLs par concaténation littérale
        # ("/chapter/" + numéro + ...), câblée sur les routes du cours 1 — les réutiliser ici ferait
        # planter (403, pas d'accès cours 1) ou pire, enregistrer/corriger sous le mauvais cours pour
        # un acheteur possédant aussi le cours 1. Construire ces routes/JS proprement par slug est un
        # chantier séparé, plus large (voir discussion) — cette route couvre seulement la lecture.
        if slug == SLUG_COURS_1:
            return redirect(url_for("chapter", number=number))
        entry = get_course_by_slug(slug)
        if entry is None:
            abort(404)
        email = session.get("email")
        if not (email and has_access(email, slug)):
            return redirect(url_for("course_landing", slug=slug))
        course_for_slug = resolve_full_course(entry)
        chap = get_chapter(course_for_slug, number)
        if not chap:
            abort(404)
        record_chapter_visit(email, slug, number)
        total = len(course_for_slug["chapters"])
        return render_template(
            "chapter_readonly.html",
            course=course_for_slug,
            chapter=chap,
            prev_number=number - 1 if number > 1 else None,
            next_number=number + 1 if number < total else None,
        )

    @app.route("/chapter/<int:number>")
    def chapter(number):
        if not _has_paid_access():
            return redirect(url_for("course_landing", slug=course["slug"]))
        chap = get_chapter(course, number)
        if not chap:
            abort(404)
        # Suivi de progression (accounts/progress.py) — seulement pour un acheteur authentifié,
        # jamais pour un visiteur non payant (déjà exclu par _has_paid_access ci-dessus).
        # Idempotent : revisiter un chapitre déjà enregistré ne crée pas de doublon.
        record_chapter_visit(session["email"], course["slug"], number)
        total = len(course["chapters"])
        return render_template(
            "chapter.html",
            course=course,
            chapter=chap,
            prev_number=number - 1 if number > 1 else None,
            next_number=number + 1 if number < total else None,
            max_corrections=MAX_CORRECTIONS_PER_EXERCISE,
            max_answer_length=MAX_ANSWER_LENGTH,
            max_practical_length=MAX_PRACTICAL_SUBMISSION_LENGTH,
            accepted_upload_extensions=ACCEPTED_UPLOAD_EXTENSIONS,
            email=session.get("email"),
            chapter_progress=_chapter_progress_summary(chap, session["email"]),
            exam_ready=_exam_ready(session["email"]),
        )

    @app.route("/chapter/<int:number>/exercise/<int:exercise_index>/correct", methods=["POST"])
    def correct_exercise_answer(number, exercise_index):
        # Même contrôle d'accès que /chapter/<n> : jamais de correction LLM gratuite pour un
        # visiteur qui n'a pas payé (voir _has_paid_access), sinon c'est un LLM gratuit ouvert à
        # tous ceux qui se contentent de créer un compte.
        if not _has_paid_access():
            return jsonify({"error": "Accès réservé aux personnes ayant acheté le cours."}), 403

        chap = get_chapter(course, number)
        if not chap:
            abort(404)
        exercises = chap["comprehension_exercises"]
        if exercise_index < 0 or exercise_index >= len(exercises):
            abort(404)
        exercise = exercises[exercise_index]
        if exercise.get("type") != "short_answer":
            return jsonify({"error": "Cet exercice n'est pas une question ouverte."}), 400

        payload = request.get_json(silent=True) or {}
        learner_answer = (payload.get("answer") or "").strip()
        if not learner_answer:
            return jsonify({"error": "Réponse vide."}), 400
        if len(learner_answer) > MAX_ANSWER_LENGTH:
            return jsonify({"error": f"Réponse trop longue (max {MAX_ANSWER_LENGTH} caractères)."}), 400

        # Suivi de PARTICIPATION (accounts/chapter_completion.py) : on enregistre le fait d'avoir
        # répondu dès qu'une réponse valide est soumise, AVANT même d'appeler le correcteur — on
        # ne gate jamais sur la justesse de la correction, seulement sur le fait d'avoir répondu.
        # Idempotent, donc sans risque même si le correcteur échoue plus bas (502) ou en cas de
        # nouvelle tentative sur la même question.
        record_item_answered(session["email"], course["slug"], number, "short_answer", exercise_index)

        counts = session.get("correction_counts", {})
        key = f"{number}:{exercise_index}"
        used = counts.get(key, 0)
        if used >= MAX_CORRECTIONS_PER_EXERCISE:
            return (
                jsonify(
                    {
                        "error": f"Nombre maximal de corrections atteint pour cette question ({MAX_CORRECTIONS_PER_EXERCISE}).",
                        "remaining": 0,
                    }
                ),
                429,
            )

        try:
            feedback = request_correction(exercise["question"], exercise["correct_answer"], learner_answer)
        except LLMCallError:
            return (
                jsonify({"error": "Le correcteur est momentanément indisponible. Réessaie dans quelques instants."}),
                502,
            )

        counts[key] = used + 1
        session["correction_counts"] = counts
        session.modified = True

        return jsonify({"feedback": feedback, "remaining": MAX_CORRECTIONS_PER_EXERCISE - counts[key]})

    @app.route("/chapter/<int:number>/practical/correct", methods=["POST"])
    def correct_practical_exercise(number):
        # Même contrôle d'accès que /chapter/<n> et la correction des questions ouvertes : jamais
        # de correction LLM gratuite pour un visiteur qui n'a pas payé.
        if not _has_paid_access():
            return jsonify({"error": "Accès réservé aux personnes ayant acheté le cours."}), 403

        chap = get_chapter(course, number)
        if not chap:
            abort(404)
        practical = chap["practical_exercise"]

        pasted_text = (request.form.get("answer") or "").strip()

        file_text = ""
        attachment = None
        uploaded = request.files.get("file")
        if uploaded and uploaded.filename:
            # Lu en mémoire uniquement, jamais écrit sur disque (pas de .save()) — jeté dès la fin
            # de cette requête. Texte/code -> contenu décodé ; image/PDF -> bloc vision/document
            # encodé en base64, jamais transformé en texte.
            raw_bytes = uploaded.read()
            try:
                result = validate_and_read_upload(uploaded.filename, raw_bytes)
            except InvalidUploadError as exc:
                return jsonify({"error": str(exc)}), 400
            if result["kind"] == "text":
                file_text = result["content"]
            else:
                attachment = {
                    "block_type": result["block_type"],
                    "media_type": result["media_type"],
                    "data": result["data"],
                }

        submission_parts = []
        if pasted_text:
            submission_parts.append(pasted_text)
        if file_text:
            submission_parts.append(f"[Fichier joint : {uploaded.filename}]\n{file_text}")
        submission = "\n\n".join(submission_parts).strip()
        if not submission and attachment is not None:
            submission = f"(Aucun texte — voir le fichier joint : {uploaded.filename}.)"

        if not submission and attachment is None:
            return jsonify({"error": "Réponse vide (aucun texte ni fichier fourni)."}), 400
        if len(submission) > MAX_PRACTICAL_SUBMISSION_LENGTH:
            return (
                jsonify(
                    {
                        "error": f"Réponse trop longue (max {MAX_PRACTICAL_SUBMISSION_LENGTH} caractères, texte + fichier confondus)."
                    }
                ),
                400,
            )

        # Suivi de PARTICIPATION — même logique que pour une question ouverte ci-dessus : la
        # soumission compte comme "répondu" dès qu'elle est valide, indépendamment du résultat du
        # correcteur appelé plus bas.
        record_item_answered(session["email"], course["slug"], number, "practical", 0)

        counts = session.get("correction_counts", {})
        key = f"{number}:practical"
        used = counts.get(key, 0)
        if used >= MAX_CORRECTIONS_PER_EXERCISE:
            return (
                jsonify(
                    {
                        "error": f"Nombre maximal de corrections atteint pour cet exercice ({MAX_CORRECTIONS_PER_EXERCISE}).",
                        "remaining": 0,
                    }
                ),
                429,
            )

        question = f"{practical['title']}\n\n{practical['instructions']}"
        reference = build_practical_reference_text(practical)

        try:
            feedback = request_correction(question, reference, submission, attachment=attachment)
        except LLMCallError:
            return (
                jsonify({"error": "Le correcteur est momentanément indisponible. Réessaie dans quelques instants."}),
                502,
            )

        counts[key] = used + 1
        session["correction_counts"] = counts
        session.modified = True

        return jsonify({"feedback": feedback, "remaining": MAX_CORRECTIONS_PER_EXERCISE - counts[key]})

    @app.route("/chapter/<int:number>/exercise/<int:exercise_index>/answer", methods=["POST"])
    def answer_mcq_exercise(number, exercise_index):
        # Suivi de PARTICIPATION pour un QCM : contrairement à une question ouverte ou un exercice
        # pratique, un QCM est jugé 100% côté client (voir selectMcqOption dans base_reading.html —
        # la bonne réponse est déjà dans le HTML) : aucune route ne recevait la réponse jusqu'ici.
        # Cette route ne juge RIEN — elle enregistre seulement que l'item a été répondu, jamais si
        # l'option choisie était correcte (ça reste entièrement côté client, comme avant).
        if not _has_paid_access():
            return jsonify({"error": "Accès réservé aux personnes ayant acheté le cours."}), 403

        chap = get_chapter(course, number)
        if not chap:
            abort(404)
        exercises = chap["comprehension_exercises"]
        if exercise_index < 0 or exercise_index >= len(exercises):
            abort(404)
        exercise = exercises[exercise_index]
        if not (exercise.get("type") == "mcq" and exercise.get("options")):
            return jsonify({"error": "Cet exercice n'est pas un QCM."}), 400

        record_item_answered(session["email"], course["slug"], number, "mcq", exercise_index)
        return jsonify(_chapter_progress_summary(chap, session["email"]))

    @app.route("/chapter/<int:number>/progress")
    def chapter_progress_status(number):
        # Lu par le JS après chaque réponse (QCM, question ouverte, exercice pratique) pour
        # rafraîchir l'état du bouton « J'ai terminé ce chapitre » sans recharger la page — voir
        # base_reading.html::fetchChapterProgress.
        if not _has_paid_access():
            return jsonify({"error": "Accès réservé aux personnes ayant acheté le cours."}), 403

        chap = get_chapter(course, number)
        if not chap:
            abort(404)
        return jsonify(_chapter_progress_summary(chap, session["email"]))

    @app.route("/chapter/<int:number>/complete", methods=["POST"])
    def complete_chapter(number):
        # Refus SERVEUR, pas seulement un bouton désactivé côté template — même logique que pour
        # l'attestation (accounts/certificate_routes.py) : impossible de marquer un chapitre
        # terminé tant que tous ses items n'ont pas été répondus, même en appelant cette route
        # directement.
        if not _has_paid_access():
            return jsonify({"error": "Accès réservé aux personnes ayant acheté le cours."}), 403

        chap = get_chapter(course, number)
        if not chap:
            abort(404)

        email = session["email"]
        total_items = len(chap["comprehension_exercises"]) + 1
        if count_answered_items(email, course["slug"], number) < total_items:
            return (
                jsonify(
                    {
                        "error": "Réponds à tous les exercices du chapitre avant de le marquer comme terminé.",
                        "missing": missing_item_labels(email, course["slug"], chap),
                    }
                ),
                400,
            )

        mark_chapter_complete(email, course["slug"], number)
        return jsonify(_chapter_progress_summary(chap, email))

    @app.route("/video/chapter_1.mp4")
    def chapter_1_video():
        if not _has_paid_access():
            abort(403)
        return send_from_directory(CHAPTER_1_VIDEO_FILE.parent, CHAPTER_1_VIDEO_FILE.name)

    # --- Système marketing autonome (marketing/, dépôt/processus séparé) : hébergement d'image ---
    # Instagram Graph API exige une URL PUBLIQUE pour publier une image (elle est re-téléchargée
    # côté serveur Meta) ; les visuels de marketing/agent2_content.py sont générés localement
    # (Pillow) sur la machine qui exécute le système marketing, donc sans URL publique propre. Ces
    # 2 routes servent uniquement de pont d'hébergement ; elles ne font partie d'aucun parcours LMS
    # (achat, cours, examen, certificat) et ne sont jamais liées depuis un template.

    MARKETING_ALLOWED_IMAGE_EXTENSIONS = {".png"}

    @app.route("/api/upload-image", methods=["POST"])
    def upload_marketing_image():
        # Comparaison à temps constant (hmac.compare_digest) : une comparaison `==` naïve sur un
        # token secret fuite sa longueur/son préfixe via le temps de réponse (timing attack).
        # MARKETING_UPLOAD_TOKEN vide => refus systématique (fail-closed), jamais un accès ouvert
        # par défaut si la variable d'environnement a été oubliée au déploiement.
        auth_header = request.headers.get("Authorization", "")
        token = auth_header.removeprefix("Bearer ").strip()
        if not MARKETING_UPLOAD_TOKEN or not hmac.compare_digest(token, MARKETING_UPLOAD_TOKEN):
            abort(403)

        uploaded = request.files.get("file")
        if not uploaded or not uploaded.filename:
            return jsonify({"error": "Aucun fichier fourni (champ 'file' attendu)."}), 400

        extension = Path(secure_filename(uploaded.filename)).suffix.lower()
        if extension not in MARKETING_ALLOWED_IMAGE_EXTENSIONS:
            return jsonify({"error": f"Extension non autorisée : {extension or '(aucune)'}"}), 400

        # Nom de fichier final imprévisible et jamais dérivé de l'entrée client : élimine tout
        # risque de traversée de répertoire ou d'écrasement d'un fichier existant, et empêche de
        # deviner l'URL d'une image publiée avant sa publication réelle.
        stored_name = f"{secrets.token_hex(16)}{extension}"
        uploaded.save(MARKETING_IMAGES_DIR / stored_name)

        return jsonify({"url": url_for("marketing_image", filename=stored_name, _external=True)})

    @app.route("/api/images/<filename>")
    def marketing_image(filename):
        # send_from_directory refuse déjà nativement toute tentative de traversée de répertoire
        # (filename contenant "../") — même garantie que /video/chapter_1.mp4 ci-dessus. Public
        # sans authentification par conception : c'est précisément ce qu'Instagram doit pouvoir
        # télécharger pour publier l'image.
        return send_from_directory(MARKETING_IMAGES_DIR, filename)

    return app
