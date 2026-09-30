"""Bloc 6 — Infrastructure partagée entre les chatbots du projet.

Le chatbot général (avant-vente + navigation catalogue, page d'accueil) ET le tuteur par cours
(pages de lecture, réservé aux acheteurs) réutilisent ces mêmes fonctions — validation
d'historique, rate-limiting — sans les dupliquer. Les deux bots ont des plafonds différents (le
tuteur autorise des messages et une conversation plus longs, voir bloc6_chatbot/course_routes.py),
d'où les paramètres optionnels de `validate_chat_history` ci-dessous plutôt que des constantes
figées.

Bots non authentifiés (général) ou réservés aux acheteurs (tuteur) : tous les garde-fous
ci-dessous s'appliquent AVANT tout appel LLM, jamais après. Le serveur est sans état pour la
conversation (l'historique vient du client à chaque appel, voir *_routes.py) — mais la session
Flask (cookie signé, jamais le contenu des messages) sert à limiter le débit par navigateur,
exactement comme `correction_counts` dans bloc4_publication/app.py pour les exercices."""

import time

MAX_MESSAGE_LENGTH = 1000
MAX_MESSAGES_PER_SESSION = 25

RATE_LIMIT_MAX_REQUESTS = 20
RATE_LIMIT_WINDOW_SECONDS = 60.0


class ChatValidationError(ValueError):
    """Levée quand l'historique de conversation envoyé par le client est invalide ou abusif."""


def validate_chat_history(
    raw_messages,
    max_message_length: int = MAX_MESSAGE_LENGTH,
    max_messages_per_session: int = MAX_MESSAGES_PER_SESSION,
) -> list[dict]:
    """Valide et normalise l'historique envoyé par le client à chaque appel.

    `max_message_length`/`max_messages_per_session` sont paramétrables : le chatbot général et le
    tuteur par cours appellent cette même fonction avec des plafonds différents (voir
    bloc6_chatbot/routes.py vs bloc6_chatbot/course_routes.py) — les valeurs par défaut
    correspondent au chatbot général.

    Ne fait confiance à AUCUN champ au-delà de `role`/`content` : un rôle différent de
    "user"/"assistant" est rejeté — ça inclut "system", le canal réservé aux instructions
    d'opérateur (voir le prompt système construit côté serveur), qu'un client ne doit jamais
    pouvoir injecter lui-même dans l'historique envoyé. Exige aussi une alternance stricte
    user/assistant terminée par un message "user" (contrat de l'API Messages), et plafonne la
    longueur de chaque message et le nombre total de messages — un client n'est pas obligé de
    respecter ce qu'il a réellement reçu, donc ces limites sont revérifiées ici, pas seulement
    côté navigateur."""
    if not isinstance(raw_messages, list) or not raw_messages:
        raise ChatValidationError("Historique de conversation vide ou invalide.")
    if len(raw_messages) > max_messages_per_session:
        raise ChatValidationError(f"Conversation trop longue (max {max_messages_per_session} messages).")

    cleaned = []
    for entry in raw_messages:
        if not isinstance(entry, dict):
            raise ChatValidationError("Message mal formé.")
        role = entry.get("role")
        content = entry.get("content")
        if role not in ("user", "assistant"):
            raise ChatValidationError(f"Rôle de message non autorisé : {role!r}.")
        if not isinstance(content, str) or not content.strip():
            raise ChatValidationError("Message vide.")
        if len(content) > max_message_length:
            raise ChatValidationError(f"Message trop long (max {max_message_length} caractères).")
        cleaned.append({"role": role, "content": content})

    if cleaned[-1]["role"] != "user":
        raise ChatValidationError("Le dernier message doit être celui de l'utilisateur.")
    for previous, current in zip(cleaned, cleaned[1:]):
        if previous["role"] == current["role"]:
            raise ChatValidationError("Les rôles doivent alterner entre 'user' et 'assistant'.")

    return cleaned


class RateLimiter:
    """Limiteur de débit en mémoire (fenêtre glissante), par clé arbitraire — typiquement l'IP.

    En mémoire process : suffisant pour un seul dyno Render (pas de Redis partagé nécessaire à ce
    stade), mais réinitialisé à chaque redémarrage/redéploiement — comme `_MOCK_TRANSACTIONS`
    dans bloc5_payment/routes.py."""

    def __init__(
        self,
        max_requests: int = RATE_LIMIT_MAX_REQUESTS,
        window_seconds: float = RATE_LIMIT_WINDOW_SECONDS,
    ):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        window_start = now - self.window_seconds
        hits = [t for t in self._hits.get(key, []) if t >= window_start]
        if len(hits) >= self.max_requests:
            self._hits[key] = hits
            return False
        hits.append(now)
        self._hits[key] = hits
        return True
