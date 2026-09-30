"""Bloc 6 — Route Flask du tuteur par cours : POST /api/chat/course/<slug>.

CONTRÔLE D'ACCÈS CRITIQUE : ce tuteur a accès au contenu payant COMPLET du cours <slug> — la
route réutilise EXACTEMENT le même garde-fou que les routes de correction d'exercices
(`bloc4_publication/app.py` : `has_access(session["email"], slug)`), plus une recherche du cours
par `slug` dans le catalogue (Changement 4, multi-cours) pour qu'un acheteur authentifié ne
reçoive jamais le tuteur d'un cours qu'il n'a pas acheté, ni d'un slug inexistant.

Depuis l'ajout des comptes (accounts/routes.py), un email en session ne suffit plus à lui seul :
se connecter prouve seulement qu'on connaît le mot de passe d'un compte, pas qu'on a acheté ce
cours — d'où la vérification `has_access` en plus de la présence de l'email et du slug. Ne touche
à AUCUNE ligne de bloc5_payment."""

from flask import Blueprint, jsonify, request, session

from bloc4_publication.access_store import has_access
from bloc6_chatbot.course_bot import answer_course_chat
from bloc6_chatbot.shared import ChatValidationError, RateLimiter, validate_chat_history
from common.llm_client import CostTracker, LLMCallError

# Plafonds propres au tuteur (plus généreux que le bot général : un apprenant qui étudie pose
# beaucoup de questions, sur des messages parfois longs — extrait de code, question détaillée).
COURSE_CHAT_MAX_MESSAGE_LENGTH = 2000
COURSE_CHAT_MAX_MESSAGES_PER_SESSION = 40

_rate_limiter = RateLimiter()


def create_course_chat_blueprint(courses: list[dict]) -> Blueprint:
    """Fabrique le blueprint du tuteur pour `courses` (le catalogue complet — voir
    bloc4_publication/app.py). Un seul blueprint pour TOUS les cours (Flask refuse deux
    blueprints de même nom) : le cours est recherché par `slug` À CHAQUE REQUÊTE (voir
    `_find_course`), pas figé à l'enregistrement — nécessaire dès qu'un second cours existe."""
    bp = Blueprint("bloc6_course_chatbot", __name__)

    def _find_course(slug: str) -> dict | None:
        return next((c for c in courses if c["slug"] == slug), None)

    @bp.route("/api/chat/course/<slug>", methods=["POST"])
    def chat_course(slug):
        if not _rate_limiter.allow(request.remote_addr or "unknown"):
            return jsonify({"error": "Trop de messages envoyés. Réessaie dans une minute."}), 429

        # Accès réservé aux acheteurs de CE cours précisément : un slug qui ne correspond à aucun
        # cours publié, ou un compte connecté qui n'a rien acheté (has_access) ne doit jamais lire
        # le contenu payant gratuitement.
        course = _find_course(slug)
        email = session.get("email")
        if not email or course is None or not has_access(email, slug):
            return jsonify({"error": "Accès réservé aux personnes ayant acheté ce cours."}), 403

        payload = request.get_json(silent=True) or {}
        try:
            messages = validate_chat_history(
                payload.get("messages"),
                max_message_length=COURSE_CHAT_MAX_MESSAGE_LENGTH,
                max_messages_per_session=COURSE_CHAT_MAX_MESSAGES_PER_SESSION,
            )
        except ChatValidationError as exc:
            return jsonify({"error": str(exc)}), 400

        tracker = CostTracker(label="chat-course")
        try:
            reply = answer_course_chat(messages, course, tracker=tracker)
        except LLMCallError:
            return (
                jsonify(
                    {"error": "Le tuteur est momentanément indisponible. Réessaie dans quelques instants."}
                ),
                502,
            )

        return jsonify({"reply": reply})

    return bp
