"""Marketing KORTEX — configuration partagée par les 5 agents + le planificateur.

Système volontairement AUTONOME : ne dépend d'aucun module de la plateforme LMS (`common/`,
`bloc*/`, `pricing_agent/`, etc.) — seulement des paquets déjà présents dans le venv du dépôt
(`anthropic`, `requests`, `python-dotenv`) + `schedule` (voir marketing/requirements.txt). Toutes
les clés viennent de `os.environ`, jamais en dur — chargées ici une seule fois depuis
`marketing/.env` (voir `marketing/.env.example` pour la liste complète)."""

import json
import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv

MARKETING_DIR = Path(__file__).resolve().parent
ENV_FILE = MARKETING_DIR / ".env"
load_dotenv(ENV_FILE)

GENERATED_IMAGES_DIR = MARKETING_DIR / "generated" / "images"
LOGS_DIR = MARKETING_DIR / "logs"
ANALYTICS_DIR = MARKETING_DIR / "analytics"
STRATEGY_DIR = MARKETING_DIR / "strategy"
for _d in (GENERATED_IMAGES_DIR, LOGS_DIR, ANALYTICS_DIR, STRATEGY_DIR):
    _d.mkdir(parents=True, exist_ok=True)

PUBLICATIONS_LOG_FILE = LOGS_DIR / "publications.json"
SUPERVISOR_LOG_FILE = LOGS_DIR / "supervisor.log"
DAILY_REPORT_FILE = ANALYTICS_DIR / "daily_report.json"
PERFORMANCE_HISTORY_FILE = STRATEGY_DIR / "performance_history.json"

# --- Secrets (jamais loggés, jamais imprimés en clair) -------------------------------------------
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
META_PAGE_ACCESS_TOKEN = os.environ.get("META_PAGE_ACCESS_TOKEN", "")
META_APP_SECRET = os.environ.get("META_APP_SECRET", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
# Authentifie agent3_publisher.py::upload_image_to_kortex auprès de
# bloc4_publication/app.py::upload_marketing_image (POST /api/upload-image) — doit avoir EXACTEMENT
# la même valeur que MARKETING_UPLOAD_TOKEN dans le .env du site KORTEX (pas ce .env-ci : c'est
# l'app Flask qui la vérifie, ce système ne fait qu'envoyer le token dans l'en-tête Authorization).
MARKETING_UPLOAD_TOKEN = os.environ.get("MARKETING_UPLOAD_TOKEN", "")

# --- Identifiants publics (pas des secrets) -------------------------------------------------------
FACEBOOK_PAGE_ID = os.environ.get("FACEBOOK_PAGE_ID", "")
INSTAGRAM_ACCOUNT_ID = os.environ.get("INSTAGRAM_ACCOUNT_ID", "")
META_APP_ID = os.environ.get("META_APP_ID", "")
TELEGRAM_CHANNEL = os.environ.get("TELEGRAM_CHANNEL", "")
KORTEX_SITE_URL = os.environ.get("KORTEX_SITE_URL", "https://cours.aymen-automation.site")

GRAPH_API_VERSION = "v19.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
TELEGRAM_API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}" if TELEGRAM_BOT_TOKEN else ""
TMPFILES_UPLOAD_URL = "https://tmpfiles.org/api/v1/upload"

REQUEST_TIMEOUT_SECONDS = 30

# Variables requises pour un run RÉEL (pas nécessaires en --dry-run tant qu'on ne publie pas
# réellement — voir agent5_supervisor.py::run_dry_run, qui les vérifie explicitement lui-même).
REQUIRED_ENV_VARS = [
    "ANTHROPIC_API_KEY",
    "META_PAGE_ACCESS_TOKEN",
    "META_APP_SECRET",
    "TELEGRAM_BOT_TOKEN",
    "FACEBOOK_PAGE_ID",
    "INSTAGRAM_ACCOUNT_ID",
    "META_APP_ID",
    "TELEGRAM_CHANNEL",
    "MARKETING_UPLOAD_TOKEN",
]


class MarketingAPIError(RuntimeError):
    """Levée quand un appel à une API externe (Anthropic/Meta/Telegram/Pollinations/tmpfiles)
    échoue de façon non récupérable — jamais avalée silencieusement."""


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)


def extract_json(text: str) -> dict:
    """Extrait et parse le premier objet JSON d'une réponse LLM.
    Robuste aux caractères de contrôle non échappés et aux blocs ```json.
    """
    import re as _re

    # 1. Retire les blocs markdown ```json ... ```
    match = _JSON_FENCE_RE.search(text)
    candidate = match.group(1) if match else text

    # 2. Extrait l'objet JSON brut
    if not match:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise MarketingAPIError(
                f"Aucun objet JSON trouvé dans la réponse : {text[:200]!r}"
            )
        candidate = candidate[start : end + 1]

    # 3. Tente le parsing direct
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # 4. Nettoyage : retire les caractères de contrôle non autorisés dans JSON
    # (U+0000–U+001F sauf \t \n \r qui sont légaux en JSON string)
    cleaned = _re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", candidate)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 5. Dernier recours : réencode les newlines/tabs non échappés dans les strings
    # (cas fréquent : Claude met un \n littéral dans une valeur JSON)
    def _escape_unescaped_control(s: str) -> str:
        """Échappe les newlines/tabs littéraux à l'intérieur des strings JSON."""
        result = []
        in_string = False
        escape_next = False
        for ch in s:
            if escape_next:
                result.append(ch)
                escape_next = False
                continue
            if ch == "\\":
                escape_next = True
                result.append(ch)
                continue
            if ch == '"' and not escape_next:
                in_string = not in_string
                result.append(ch)
                continue
            if in_string and ch in ("\n", "\r", "\t"):
                result.append(repr(ch)[1:-1])  # '\n' → '\\n'
                continue
            result.append(ch)
        return "".join(result)

    try:
        return json.loads(_escape_unescaped_control(cleaned))
    except json.JSONDecodeError as exc:
        raise MarketingAPIError(
            f"JSON invalide après nettoyage : {exc} — extrait : {cleaned[:300]!r}"
        ) from exc


def append_json_list(path: Path, entry: dict, list_key: str) -> None:
    """Ajoute `entry` à la liste `data[list_key]` d'un fichier JSON (le crée avec une liste vide
    si absent) — utilisé pour les logs/historiques qui grossissent au fil des runs
    (publications.json, performance_history.json)."""
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = {list_key: []}
    data.setdefault(list_key, []).append(entry)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def missing_env_vars(required: list[str] | None = None) -> list[str]:
    """Retourne la liste des variables d'environnement requises absentes/vides — jamais les
    valeurs elles-mêmes (pas de fuite de secret dans un log/rapport)."""
    required = required if required is not None else REQUIRED_ENV_VARS
    return [name for name in required if not os.environ.get(name, "").strip()]


ANTHROPIC_MODEL = "claude-sonnet-5"
_MAX_RETRIES = 3
_RETRY_BACKOFF_SECONDS = 2


def call_anthropic(
    messages: list[dict],
    system: str | None = None,
    max_tokens: int = 4096,
    tools: list[dict] | None = None,
) -> str:
    """Appel direct au SDK `anthropic` (système volontairement autonome, pas d'import de
    `common/llm_client.py`). Retente jusqu'à 3x sur timeout/429/5xx (backoff 2s/4s/8s), lève
    `MarketingAPIError` seulement après épuisement des tentatives. Concatène tous les blocs texte
    de la réponse (les blocs `server_tool_use`/`web_search_tool_result` éventuels sont ignorés
    dans le texte retourné, comme dans `common/llm_client.py::call_chat_api`)."""
    import anthropic

    if not ANTHROPIC_API_KEY:
        raise MarketingAPIError("ANTHROPIC_API_KEY manquante dans marketing/.env")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    kwargs = {"model": ANTHROPIC_MODEL, "max_tokens": max_tokens, "messages": messages}
    if system:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = tools

    last_error: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = client.messages.create(**kwargs)
            return "".join(block.text for block in response.content if block.type == "text")
        except (anthropic.APITimeoutError, anthropic.RateLimitError, anthropic.InternalServerError) as exc:
            last_error = exc
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_BACKOFF_SECONDS * attempt)
        except anthropic.APIError as exc:
            raise MarketingAPIError(f"Appel Anthropic échoué : {exc}") from exc

    raise MarketingAPIError(
        f"Appel Anthropic échoué après {_MAX_RETRIES} tentatives : {last_error}"
    ) from last_error


def http_request_with_retry(method: str, url: str, **kwargs) -> "requests.Response":
    """`requests.request` avec retry sur timeout/429/5xx (backoff 2s/4s/8s, 3 tentatives) —
    partagé par agent3_publisher.py (publication) et agent4_analytics.py (lecture des stats),
    pour ne pas dupliquer cette logique dans chaque agent. Lève `MarketingAPIError` seulement
    après épuisement des tentatives ; toute autre erreur HTTP (4xx hors 429) remonte immédiatement
    sans retry, car un retry ne la résoudrait pas."""
    import requests

    kwargs.setdefault("timeout", REQUEST_TIMEOUT_SECONDS)
    last_error: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = requests.request(method, url, **kwargs)
            if response.status_code == 429 or response.status_code >= 500:
                last_error = MarketingAPIError(
                    f"{method} {url} -> HTTP {response.status_code} : {response.text[:300]}"
                )
                if attempt < _MAX_RETRIES:
                    time.sleep(_RETRY_BACKOFF_SECONDS * attempt)
                    continue
                raise last_error
            return response
        except requests.exceptions.Timeout as exc:
            last_error = exc
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_BACKOFF_SECONDS * attempt)

    raise MarketingAPIError(f"{method} {url} a échoué après {_MAX_RETRIES} tentatives : {last_error}")
