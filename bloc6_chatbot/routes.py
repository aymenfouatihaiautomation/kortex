"""Bloc 6 — Route Flask du chatbot général : POST /api/chat/general.

Bot PUBLIC non authentifié : tous les garde-fous de `bloc6_chatbot.shared` s'appliquent avant tout
appel LLM. Ne touche à AUCUNE route ni logique de bloc5_payment."""

from flask import Blueprint, jsonify, request

from bloc6_chatbot.general_bot import answer_general_chat
from bloc6_chatbot.shared import ChatValidationError, RateLimiter, validate_chat_history
from common.llm_client import CostTracker, LLMCallError

# Un seul limiteur pour tout le process (voir RateLimiter — mémoire process, pas de Redis).
_rate_limiter = RateLimiter()


def create_general_chat_blueprint(courses: list[dict]) -> Blueprint:
    """Fabrique le blueprint du chatbot général, `courses` figé à la création de l'app (même
    liste que le reste du LMS — voir bloc4_publication/app.py)."""
    bloc6_bp = Blueprint("bloc6_chatbot", __name__)

    @bloc6_bp.route("/api/chat/general", methods=["POST"])
    def chat_general():
        if not _rate_limiter.allow(request.remote_addr or "unknown"):
            return jsonify({"error": "Trop de messages envoyés. Réessaie dans une minute."}), 429

        payload = request.get_json(silent=True) or {}
        try:
            messages = validate_chat_history(payload.get("messages"))
        except ChatValidationError as exc:
            return jsonify({"error": str(exc)}), 400

        tracker = CostTracker(label="chat-general")
        try:
            reply = answer_general_chat(messages, courses, tracker=tracker)
        except LLMCallError:
            return (
                jsonify(
                    {"error": "L'assistant est momentanément indisponible. Réessaie dans quelques instants."}
                ),
                502,
            )

        return jsonify({"reply": reply})

    return bloc6_bp
